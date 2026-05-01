from flask import Flask, request, jsonify, Response
import yt_dlp
import subprocess
import urllib.parse
import requests
import logging
import threading
import socket
import os as _os

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Track proses mpv yang sedang berjalan
local_player_process = None
local_player_lock = threading.Lock()

app = Flask(__name__)
lyric_cache = {}

MPV_IPC_SOCKET = _os.path.join(_os.path.expanduser("~"), "anggira", ".mpv-ipc.sock")
_playback_volume = 100
_playback_volume_lock = threading.Lock()

def get_audio_info(song, artist=""):
    raw_query = f"{song} {artist}".strip() if artist else song
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'jsruntimes': ['node'],
        'default_search': 'auto',
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if song.startswith("http://") or song.startswith("https://"):
            log.info(f"Fetching audio info from URL: {song}")
            info = ydl.extract_info(song, download=False)
            if isinstance(info, dict) and info.get('entries'):
                info = info['entries'][0]
        else:
            log.info(f"Searching YouTube for: {raw_query}")
            info = ydl.extract_info(f"ytsearch:{raw_query}", download=False)
            if isinstance(info, dict) and info.get('entries'):
                info = info['entries'][0]

        if not isinstance(info, dict) or 'url' not in info:
            raise ValueError(f"No audio URL found for {song}")

        log.info(f"Found: {info.get('title')} ({info.get('duration')}s)")
        return {
            "url": info['url'],
            "title": info.get('title', song),
            "artist": info.get('uploader', artist),
        }

def fetch_lyrics(song, artist=""):
    try:
        params = {"track_name": song, "artist_name": artist}
        resp = requests.get("https://lrclib.net/api/search", 
                           params=params, timeout=5)
        if resp.status_code == 200:
            results = resp.json()
            for r in results:
                if r.get("syncedLyrics"):
                    log.info(f"Found synced lyrics for: {song}")
                    return r["syncedLyrics"]
            if results:
                return results[0].get("plainLyrics", "")
    except Exception as e:
        log.warning(f"Lyric fetch failed: {e}")
    return ""

@app.route("/stream_pcm")
def stream_pcm():
    song = request.args.get("song", "").strip()
    artist = request.args.get("artist", "").strip()
    
    # Log all headers from ESP32 for debugging
    log.info(f"=== /stream_pcm request ===")
    log.info(f"Song: '{song}', Artist: '{artist}'")
    log.info(f"Client IP: {request.remote_addr}")
    for k, v in request.headers:
        if k.startswith("X-"):
            log.info(f"  {k}: {v}")

    if not song:
        return jsonify({"error": "Missing song parameter"}), 400

    try:
        _full_stop_playback()
        info = get_audio_info(song, artist)
        base_url = "http://192.168.1.3:8080"
        encoded_url = urllib.parse.quote(info["url"])

        lyrics = fetch_lyrics(song, artist)
        lyric_url = ""
        if lyrics:
            cache_key = f"{song}_{artist}"
            lyric_cache[cache_key] = lyrics
            lyric_url = (f"{base_url}/lyrics"
                        f"?song={urllib.parse.quote(song)}"
                        f"&artist={urllib.parse.quote(artist)}")

        response_data = {
            "title": info["title"],
            "artist": info["artist"],
            "audio_url": f"{base_url}/play?url={encoded_url}",
            "lyric_url": lyric_url
        }
        log.info(f"Returning: title='{info['title']}', lyric={'yes' if lyric_url else 'no'}")
        return jsonify(response_data)

    except Exception as e:
        log.error(f"stream_pcm error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/lyrics")
def lyrics():
    song = request.args.get("song", "")
    artist = request.args.get("artist", "")
    key = f"{song}_{artist}"
    content = lyric_cache.get(key, "")
    log.info(f"Lyrics requested for '{song}': {'found' if content else 'not found'}")
    return Response(content, content_type="text/plain; charset=utf-8")

@app.route("/play")
def play():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "Missing url"}), 400
    
    log.info(f"Streaming audio to {request.remote_addr}")

    def generate():
        command = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1", 
            "-reconnect_delay_max", "5",
            "-i", url,
            "-f", "mp3",
            "-acodec", "libmp3lame",
            "-ab", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-vn",
            "-"
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        try:
            total = 0
            while True:
                data = process.stdout.read(4096)
                if not data:
                    break
                total += len(data)
                yield data
            log.info(f"Stream complete: {total} bytes sent")
        finally:
            process.kill()

    return Response(generate(), content_type="audio/mpeg")

@app.route("/play_local")
def play_local():
    """
    Putar lagu langsung di speaker STB menggunakan mpv.
    Otomatis stop lagu sebelumnya jika ada yang sedang main.
    """
    global local_player_process

    song = request.args.get("song", "").strip()
    artist = request.args.get("artist", "").strip()

    if not song:
        return jsonify({"error": "Missing song parameter"}), 400

    log.info(f"=== /play_local request: song='{song}', artist='{artist}' ===")

    try:
        # Cari audio URL dulu
        info = get_audio_info(song, artist)
        audio_url = info["url"]
        title = info["title"]

        _full_stop_playback()
        log.info(f"Playing locally: {title}")
        log.info(f"Audio URL: {audio_url[:80]}...")

        # Simpan ke cache lirik juga
        lyrics = fetch_lyrics(song, artist)
        if lyrics:
            cache_key = f"{song}_{artist}"
            lyric_cache[cache_key] = lyrics

        # Stop proses sebelumnya jika masih jalan
        with local_player_lock:
            if local_player_process and local_player_process.poll() is None:
                log.info("Stopping previous local playback")
                local_player_process.terminate()
                try:
                    local_player_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    local_player_process.kill()

            # Jalankan mpv untuk play audio di STB
            # --no-video   : audio only
            # --volume=100 : volume penuh
            # --really-quiet: suppress output
            local_player_process = _start_mpv(audio_url)
            log.info(f"mpv started with PID: {local_player_process.pid}")

        return jsonify({
            "status": "playing",
            "song": song,
            "title": title,
            "artist": info["artist"],
            "pid": local_player_process.pid
        })

    except FileNotFoundError:
        # mpv tidak terinstall, coba fallback ke ffplay
        log.warning("mpv not found, trying ffplay...")
        try:
            with local_player_lock:
                if local_player_process and local_player_process.poll() is None:
                    local_player_process.terminate()

                cmd = [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-volume", "100",
                    audio_url
                ]
                local_player_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            return jsonify({"status": "playing", "song": song, "player": "ffplay"})
        except Exception as e:
            log.error(f"ffplay also failed: {e}")
            return jsonify({"error": "mpv dan ffplay tidak ditemukan. Install dengan: apt install mpv"}), 500

    except Exception as e:
        log.error(f"play_local error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/stop_local", methods=["GET", "POST"])
def stop_local():
    """Stop pemutaran apapun di STB."""
    _full_stop_playback()
    return jsonify({"status": "stopped"})



@app.route("/stream_radio")
def stream_radio():
    """
    Putar internet radio via speaker ESP32.
    URL stream radio langsung di-pipe FFmpeg → streaming ke ESP32.
    """
    radio_url = request.args.get("url", "").strip()
    name = request.args.get("name", "Radio").strip()

    if not radio_url:
        return jsonify({"error": "Missing url parameter"}), 400

    log.info(f"=== /stream_radio: name='{name}' url='{radio_url}' ===")
    log.info(f"Client IP: {request.remote_addr}")

    def generate():
        command = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", radio_url,
            "-f", "mp3",
            "-acodec", "libmp3lame",
            "-ab", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-vn",
            "-"
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        try:
            total = 0
            while True:
                data = process.stdout.read(4096)
                if not data:
                    break
                total += len(data)
                yield data
            log.info(f"Radio stream ended: {total} bytes sent")
        finally:
            process.kill()

    return Response(generate(), content_type="audio/mpeg")


@app.route("/play_radio")
def play_radio():
    """
    Putar internet radio langsung di speaker STB menggunakan mpv.
    Otomatis stop pemutaran sebelumnya (musik atau radio).
    """
    global local_player_process

    radio_url = request.args.get("url", "").strip()
    name = request.args.get("name", "Radio").strip()

    if not radio_url:
        return jsonify({"error": "Missing url parameter"}), 400

    log.info(f"=== /play_radio: name='{name}' ===")

    try:
        _full_stop_playback()
        with local_player_lock:
            if local_player_process and local_player_process.poll() is None:
                log.info("Stopping previous playback before radio")
                local_player_process.terminate()
                try:
                    local_player_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    local_player_process.kill()

            local_player_process = _start_mpv(radio_url)
            log.info(f"Radio mpv PID: {local_player_process.pid}")

        return jsonify({
            "status": "playing",
            "name": name,
            "url": radio_url,
            "pid": local_player_process.pid
        })

    except FileNotFoundError:
        log.warning("mpv not found, trying ffplay...")
        try:
            with local_player_lock:
                if local_player_process and local_player_process.poll() is None:
                    local_player_process.terminate()
                cmd = ["ffplay", "-nodisp", "-autoexit", "-volume", "100", radio_url]
                local_player_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            return jsonify({"status": "playing", "name": name, "player": "ffplay"})
        except Exception as e:
            return jsonify({"error": "mpv dan ffplay tidak ditemukan"}), 500

    except Exception as e:
        log.error(f"play_radio error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/stop_radio", methods=["GET", "POST"])
def stop_radio():
    """Stop radio di STB."""
    _full_stop_playback()
    return jsonify({"status": "stopped"})



# ================= PLAYLIST =================
import json as _json
import os as _os

PLAYLIST_FILE = _os.path.join(_os.path.expanduser("~"), "anggira", "playlists.json")

_playlist_state = {
    "current_playlist": None,   # nama playlist aktif
    "queue":            [],     # list of {"song": ..., "artist": ...}
    "index":            0,      # index lagu sekarang
    "playing":          False,
    "generation":       0,
}
_playlist_lock = threading.RLock()

def _load_playlists() -> dict:
    if _os.path.exists(PLAYLIST_FILE):
        try:
            with open(PLAYLIST_FILE) as f:
                return _json.load(f)
        except Exception:
            pass
    return {}

def _save_playlists(data: dict):
    _os.makedirs(_os.path.dirname(PLAYLIST_FILE), exist_ok=True)
    with open(PLAYLIST_FILE, "w") as f:
        _json.dump(data, f, indent=2, ensure_ascii=False)

def _clamp_volume(value):
    try:
        return max(0, min(130, int(value)))
    except Exception:
        return 100

def _remove_mpv_socket():
    try:
        _os.unlink(MPV_IPC_SOCKET)
    except FileNotFoundError:
        pass
    except OSError:
        pass

def _build_mpv_command(url: str):
    with _playback_volume_lock:
        volume = _playback_volume
    return [
        "mpv",
        "--no-video",
        "--audio-device=opensles",
        f"--volume={volume}",
        "--really-quiet",
        f"--input-ipc-server={MPV_IPC_SOCKET}",
        url,
    ]

def _mpv_ipc_command(command):
    payload = _json.dumps({"command": command}) + "\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        sock.connect(MPV_IPC_SOCKET)
        sock.sendall(payload.encode("utf-8"))
        data = sock.recv(4096).decode("utf-8", "ignore").strip()
    if not data:
        return None
    first = data.splitlines()[0]
    return _json.loads(first)

def _set_mpv_volume(value):
    try:
        return _mpv_ipc_command(["set_property", "volume", int(value)])
    except Exception as e:
        log.info(f"MPV volume apply skipped: {e}")
        return None

def _get_mpv_volume():
    try:
        resp = _mpv_ipc_command(["get_property", "volume"])
        if isinstance(resp, dict) and resp.get("error") in (None, "success"):
            return resp.get("data")
    except Exception:
        pass
    return None

def _start_mpv(url: str):
    _remove_mpv_socket()
    return subprocess.Popen(
        _build_mpv_command(url),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def _stop_current_player():
    global local_player_process
    with local_player_lock:
        proc = local_player_process
        local_player_process = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

def _invalidate_playlist_generation():
    with _playlist_lock:
        _playlist_state["generation"] += 1

def _full_stop_playback():
    _invalidate_playlist_generation()
    with _playlist_lock:
        _playlist_state["playing"] = False
        _playlist_state["queue"] = []
        _playlist_state["index"] = 0
        _playlist_state["current_playlist"] = None
    _stop_current_player()

def _play_next_in_playlist():
    """Putar lagu berikutnya di queue. Dipanggil oleh thread monitor."""
    global local_player_process
    with _playlist_lock:
        state = _playlist_state
        if not state["playing"] or state["index"] >= len(state["queue"]):
            state["playing"] = False
            log.info("Playlist selesai")
            return
        track = state["queue"][state["index"]]
        state["index"] += 1

    song   = track.get("song", "")
    artist = track.get("artist", "")
    log.info(f"Playlist: [{state['index']}/{len(state['queue'])}] {song} - {artist}")

    try:
        info = get_audio_info(song, artist)

        with local_player_lock:
            if local_player_process and local_player_process.poll() is None:
                local_player_process.terminate()
                try: local_player_process.wait(timeout=3)
                except subprocess.TimeoutExpired: local_player_process.kill()
            local_player_process = _start_mpv(info["url"])

        with _playlist_lock:
            playlist_generation = _playlist_state["generation"]

        # Monitor selesai lalu lanjut lagu berikutnya
        def _monitor(proc, generation):
            proc.wait()
            # Hanya lanjut jika playback ini masih generasi playlist aktif.
            with _playlist_lock:
                should_continue = (
                    _playlist_state["playing"]
                    and _playlist_state["generation"] == generation
                )
            if should_continue:
                _play_next_in_playlist()
        threading.Thread(target=_monitor, args=(local_player_process, playlist_generation), daemon=True).start()

    except Exception as e:
        log.error(f"Playlist play error: {e}")
        # Skip ke lagu berikutnya
        _play_next_in_playlist()


@app.route("/play_playlist")
def play_playlist():
    """Mulai putar playlist berdasarkan nama. ?name=santai&shuffle=true"""
    name    = request.args.get("name", "").strip().lower()
    shuffle = request.args.get("shuffle", "false").lower() == "true"

    playlists = _load_playlists()
    # Case-insensitive match
    key = next((k for k in playlists if k.lower() == name), None)
    if not key:
        available = ", ".join(playlists.keys()) or "kosong"
        return jsonify({"error": f"Playlist '{name}' tidak ada. Tersedia: {available}"}), 404

    tracks = playlists[key].get("tracks", [])
    if not tracks:
        return jsonify({"error": "Playlist kosong"}), 400

    if shuffle:
        import random
        tracks = tracks.copy()
        random.shuffle(tracks)

    _full_stop_playback()
    with _playlist_lock:
        _playlist_state["current_playlist"] = key
        _playlist_state["queue"]            = tracks
        _playlist_state["index"]            = 0
        _playlist_state["playing"]          = True

    log.info(f"Memulai playlist '{key}' ({len(tracks)} lagu, shuffle={shuffle})")
    _play_next_in_playlist()

    return jsonify({
        "status":   "playing",
        "playlist": key,
        "total":    len(tracks),
        "shuffle":  shuffle,
        "first":    tracks[0].get("song", "") if tracks else ""
    })


@app.route("/playlist_next")
def playlist_next():
    """Skip ke lagu berikutnya."""
    with _playlist_lock:
        if not _playlist_state["playing"]:
            return jsonify({"status": "not_playing"})
        _playlist_state["generation"] += 1

    def _advance():
        _stop_current_player()
        _play_next_in_playlist()

    threading.Thread(target=_advance, daemon=True).start()
    return jsonify({"status": "skipped"})


@app.route("/playlist_prev")
def playlist_prev():
    """Kembali ke lagu sebelumnya di playlist."""
    with _playlist_lock:
        if not _playlist_state["playing"]:
            return jsonify({"status": "not_playing"})
        _playlist_state["generation"] += 1
        _playlist_state["index"] = max(0, _playlist_state["index"] - 2)

    def _go_previous():
        _stop_current_player()
        _play_next_in_playlist()

    threading.Thread(target=_go_previous, daemon=True).start()
    return jsonify({"status": "previous"})


@app.route("/playlist_stop")
def playlist_stop():
    """Stop playlist."""
    _full_stop_playback()
    return jsonify({"status": "stopped"})


@app.route("/stop_all", methods=["GET", "POST"])
def stop_all():
    """Stop semua playback dan playlist."""
    _full_stop_playback()
    return jsonify({"status": "stopped"})


@app.route("/stb_volume", methods=["GET", "POST"])
def stb_volume():
    """Atur volume playback MPV yang sedang aktif."""
    global _playback_volume
    payload = request.get_json(silent=True) or {}
    action = (request.args.get("action") or payload.get("action") or request.args.get("cmd") or "get").lower()
    level = request.args.get("level", payload.get("level"))
    step = request.args.get("step", payload.get("step", 10))

    with _playback_volume_lock:
        current = _playback_volume

    if action == "get":
        actual = _get_mpv_volume()
        if actual is not None:
            with _playback_volume_lock:
                _playback_volume = _clamp_volume(actual)
                current = _playback_volume
        return jsonify({"status": "ok", "volume": current})

    if action == "mute":
        new_volume = 0
    elif action == "up":
        new_volume = _clamp_volume(current + int(step))
    elif action == "down":
        new_volume = _clamp_volume(current - int(step))
    elif action == "set":
        if level is None:
            return jsonify({"error": "Missing level"}), 400
        new_volume = _clamp_volume(level)
    else:
        return jsonify({"error": f"Unknown action '{action}'"}), 400

    with _playback_volume_lock:
        _playback_volume = new_volume

    applied = _set_mpv_volume(new_volume)
    return jsonify({"status": "ok", "volume": new_volume, "applied": bool(applied)})


@app.route("/playlist_status")
def playlist_status():
    """Status playlist saat ini."""
    with _playlist_lock:
        state = _playlist_state
        idx   = state["index"]
        queue = state["queue"]
        current = queue[idx - 1] if idx > 0 and queue else {}
        return jsonify({
            "playing":          state["playing"],
            "playlist":         state["current_playlist"],
            "current_index":    idx,
            "total":            len(queue),
            "current_song":     current.get("song", ""),
            "current_artist":   current.get("artist", ""),
        })


@app.route("/api/playlists", methods=["GET"])
def api_get_playlists():
    return jsonify(_load_playlists())


@app.route("/api/playlists", methods=["POST"])
def api_save_playlists():
    data = request.get_json()
    _save_playlists(data)
    return jsonify({"ok": True})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "server": "anggira-music"})


@app.route("/api/radio_list")
def api_radio_list():
    stations = [
        {"name": "Prambors FM Jakarta",    "key": "prambors",   "url": "https://s1.cloudmu.id/listen/prambors/stream"},
        {"name": "Hard Rock FM Jakarta",   "key": "hardrock",   "url": "https://stream.zeno.fm/btdooo7j1ydvv"},
        {"name": "Delta FM Jakarta",       "key": "delta",      "url": "https://s1.cloudmu.id/listen/delta_fm/stream"},
        {"name": "Trax FM Jakarta",        "key": "traxfm",     "url": "https://stream.radiojar.com/rrqf78p3bnzuv"},
        {"name": "Female Radio Jakarta",   "key": "female",     "url": "http://103.24.105.90:9300/fjkt"},
        {"name": "RRI Pro 1 Jakarta",      "key": "rripro1jkt", "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro1.mp3"},
        {"name": "RRI Pro 2 Jakarta",      "key": "rripro2jkt", "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro2.mp3"},
        {"name": "RRI Pro 1 Semarang",     "key": "rripro1smg", "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro1.mp3"},
        {"name": "RRI Pro 2 Semarang",     "key": "rripro2smg", "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro2.mp3"},
        {"name": "Idola FM Semarang",      "key": "idolafm",    "url": "https://stream.cradio.co.id/idolafm"},
        {"name": "Gajah Mada FM Semarang", "key": "gajahmada",  "url": "https://server.radioimeldafm.co.id:8040/gajahmadafm"},
        {"name": "Swara Semarang FM",      "key": "swarasmg",   "url": "https://server.radioimeldafm.co.id/radio/8010/swarasemarang"},
        {"name": "UP Radio Semarang",      "key": "upradio",    "url": "https://stream.tujuhcahaya.com/listen/radio_upradio_semarang/radio.mp3"},
        {"name": "Radio Salatiga",         "key": "salatiga",   "url": "https://icecast.salatiga.go.id:8443/stream.ogg"},
        {"name": "BBC World Service",      "key": "bbc",        "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service"},
        {"name": "Jazz24",                 "key": "jazz24",     "url": "https://live.wostreaming.net/direct/ppm-jazz24aac-ibc1"},
    ]
    return jsonify(stations)

@app.route("/remote")
def remote_ui():
    html = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#080c14">
<title>Anggira Remote</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Archivo+Black&family=Archivo:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#080c14;--surface:#0e1520;--panel:#131d2e;--border:rgba(0,180,255,0.12);--accent:#00b4ff;--accent2:#ff4f30;--accent3:#00ffa3;--text:#c8dff0;--dim:#4a6880;--r:14px}
*{box-sizing:border-box;margin:0;padding:0}html{height:100%;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:'Archivo',sans-serif;min-height:100%;overflow-x:hidden}
.hdr{position:sticky;top:0;z-index:200;background:rgba(8,12,20,.94);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);padding:14px 18px 12px;display:flex;align-items:center;gap:12px}
.logo{font-family:'Archivo Black',sans-serif;font-size:20px;background:linear-gradient(120deg,var(--accent),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{font-size:10px;color:var(--dim);font-family:'Space Mono',monospace;letter-spacing:1px;margin-top:1px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent3);box-shadow:0 0 8px var(--accent3);animation:blink 2s infinite;margin-left:auto}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.nav{display:flex;overflow-x:auto;background:var(--surface);border-bottom:1px solid var(--border);scrollbar-width:none;position:sticky;top:57px;z-index:100}
.nav::-webkit-scrollbar{display:none}
.nt{padding:12px 16px;background:none;border:none;color:var(--dim);font-family:'Space Mono',monospace;font-size:10px;letter-spacing:.5px;cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;transition:color .2s,border-color .2s}
.nt.a{color:var(--accent);border-bottom-color:var(--accent)}
.pg{padding:16px;display:none}.pg.a{display:block}
.pc{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:16px}
.pa{width:100%;height:140px;background:linear-gradient(135deg,#0a1628,#152040,#0a1628);display:flex;align-items:center;justify-content:center;position:relative}
.vl{width:90px;height:90px;border-radius:50%;background:conic-gradient(#0a1020,#1a2840,#0a1020,#1a2840);border:3px solid rgba(0,180,255,.15);display:flex;align-items:center;justify-content:center}
.vl.sp{animation:sp 4s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.vc{width:24px;height:24px;border-radius:50%;background:var(--panel);border:2px solid rgba(0,180,255,.3)}
.pi{padding:12px 16px 8px}
.pt{font-family:'Archivo Black',sans-serif;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px}
.par{font-size:11px;color:var(--dim);font-family:'Space Mono',monospace}
.ps{font-size:10px;color:var(--accent);font-family:'Space Mono',monospace;margin-top:4px}
.ctrl{display:flex;align-items:center;justify-content:center;gap:10px;padding:10px 16px 10px}.vol{display:flex;align-items:center;gap:10px;padding:0 16px 14px}.vr{flex:1;accent-color:var(--accent);height:4px}.vtx{font-family:'Space Mono',monospace;font-size:11px;color:var(--dim);min-width:34px;text-align:right}
.cb{background:none;border:1px solid var(--border);color:var(--text);border-radius:50%;width:42px;height:42px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;transition:all .15s}
.cb:active{transform:scale(.92)}.cb:hover{border-color:var(--accent);color:var(--accent)}
.cb.pr{width:54px;height:54px;font-size:20px;background:var(--accent);border-color:var(--accent);color:#080c14}
.cb.rd:hover{background:rgba(255,79,48,.1);border-color:var(--accent2);color:var(--accent2)}
.st{font-family:'Space Mono',monospace;font-size:10px;letter-spacing:2px;color:var(--dim);text-transform:uppercase;margin-bottom:10px;margin-top:16px;padding-left:2px}
.st:first-child{margin-top:0}
.sr{display:flex;gap:8px;margin-bottom:10px}
.si{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:11px 14px;color:var(--text);font-family:'Archivo',sans-serif;font-size:13px;outline:none;transition:border-color .2s}
.si:focus{border-color:var(--accent)}.si::placeholder{color:var(--dim)}
.sb{background:var(--accent);border:none;border-radius:10px;padding:0 16px;color:#080c14;font-family:'Archivo Black',sans-serif;font-size:13px;cursor:pointer}
.sb:active{transform:scale(.95)}
.br{display:flex;gap:8px;margin-bottom:10px}
.sv{flex:1;background:none;border:1px solid var(--border);border-radius:8px;padding:10px 6px;color:var(--text);font-size:10px;font-family:'Space Mono',monospace;cursor:pointer;transition:all .15s;text-align:center}
.sv:hover{border-color:var(--accent);color:var(--accent)}.sv:active{transform:scale(.96)}.sv.active{border-color:var(--accent);color:var(--accent);background:rgba(0,180,255,.08)}
.sv.rd:hover{border-color:var(--accent2);color:var(--accent2)}
.qg{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}
.qc{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);padding:13px 8px;cursor:pointer;transition:all .15s;display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center}
.qc:hover{border-color:var(--accent)}.qc:active{transform:scale(.95)}
.qi{font-size:22px}.ql{font-family:'Space Mono',monospace;font-size:9px;color:var(--dim);line-height:1.3}
.plg{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:12px}
.plc{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);padding:12px;transition:border-color .2s}
.plc:hover{border-color:var(--accent)}
.pln{font-family:'Archivo Black',sans-serif;font-size:13px;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.plct{font-family:'Space Mono',monospace;font-size:10px;color:var(--dim);margin-bottom:8px}
.pla{display:flex;gap:5px}
.plb{flex:1;background:none;border:1px solid var(--border);border-radius:6px;padding:6px 2px;color:var(--dim);font-size:10px;cursor:pointer;transition:all .15s;font-family:'Space Mono',monospace}
.plb:hover{border-color:var(--accent);color:var(--accent)}.plb.sh:hover{border-color:var(--accent3);color:var(--accent3)}
.pladd{width:100%;background:none;border:1px dashed var(--border);border-radius:var(--r);padding:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;color:var(--dim);font-size:12px;font-family:'Space Mono',monospace;transition:all .2s}
.pladd:hover{border-color:var(--accent);color:var(--accent)}
.tkl{display:flex;flex-direction:column;gap:6px;margin-top:8px}
.tki{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 13px;display:flex;align-items:center;gap:10px}
.tkn{font-family:'Space Mono',monospace;font-size:10px;color:var(--dim);min-width:16px}
.tki2{flex:1;min-width:0}
.tktt{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tkar{font-size:10px;color:var(--dim);font-family:'Space Mono',monospace}
.tkd{background:none;border:none;color:var(--dim);font-size:16px;cursor:pointer;padding:2px}.tkd:hover{color:var(--accent2)}
.rl{display:flex;flex-direction:column;gap:8px}
.ri{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 14px;display:flex;align-items:center;gap:12px;transition:border-color .2s}
.ri:hover{border-color:var(--accent)}
.rin{flex:1}.rn{font-size:13px;font-weight:500}.rk{font-family:'Space Mono',monospace;font-size:10px;color:var(--dim)}
.rp{background:none;border:1px solid var(--border);border-radius:50%;width:34px;height:34px;color:var(--text);font-size:14px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .15s;flex-shrink:0}
.rp:hover{background:var(--accent);border-color:var(--accent);color:#080c14}
.dvd{height:1px;background:var(--border);margin:14px 0}
.mo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:500;backdrop-filter:blur(8px);align-items:flex-end}
.mo.sh{display:flex}
.md{width:100%;background:var(--surface);border-top:1px solid var(--border);border-radius:20px 20px 0 0;padding:20px 18px 32px;animation:su .25s ease;max-height:80vh;overflow-y:auto}
@keyframes su{from{transform:translateY(100%)}to{transform:translateY(0)}}
.mh{width:36px;height:4px;border-radius:2px;background:var(--border);margin:0 auto 18px}
.mt{font-family:'Archivo Black',sans-serif;font-size:16px;margin-bottom:16px}
.ci{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;color:var(--text);font-family:'Space Mono',monospace;font-size:12px;outline:none;transition:border-color .2s;margin-bottom:8px}
.ci:focus{border-color:var(--accent)}
.cs{width:100%;background:var(--accent);border:none;border-radius:8px;padding:11px;color:#080c14;font-family:'Archivo Black',sans-serif;font-size:13px;cursor:pointer}
.em{text-align:center;padding:28px 16px;color:var(--dim);font-family:'Space Mono',monospace;font-size:11px;line-height:1.8}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(100px);background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:11px 18px;font-family:'Space Mono',monospace;font-size:11px;z-index:999;transition:transform .3s;white-space:nowrap;max-width:90vw;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}
.toast.sh{transform:translateX(-50%) translateY(0)}
.toast.ok{border-color:rgba(0,255,163,.3);color:var(--accent3)}
.toast.er{border-color:rgba(255,79,48,.3);color:var(--accent2)}
</style>
</head>
<body>
<header class="hdr">
  <div><div class="logo">ANGGIRA</div><div class="sub">STB REMOTE</div></div>
  <div class="dot"></div>
</header>
<nav class="nav">
  <button class="nt a" onclick="tab('music',this)">🎵 MUSIK</button>
  <button class="nt" onclick="tab('playlist',this)">📋 PLAYLIST</button>
  <button class="nt" onclick="tab('radio',this)">📻 RADIO</button>
</nav>
<div class="pg a" id="pg-music">
  <div class="pc">
    <div class="pa"><div class="vl" id="vl"><div class="vc"></div></div></div>
    <div class="pi">
      <div class="pt" id="nt">Tidak ada yang diputar</div>
      <div class="par" id="na">—</div>
      <div class="ps" id="ns">IDLE</div>
    </div>
    <div class="ctrl">
      <button class="cb rd" onclick="stopAll()">⏹</button>
      <button class="cb" onclick="skipPrev()">⏮</button>
      <button class="cb" onclick="skipNext()">⏭</button>
      <button class="cb pr" id="ppb" onclick="togglePlay()">▶</button>
    </div>
    <div class="vol">
      <button class="cb" onclick="volumeAdj('down')">−</button>
      <input class="vr" id="vol" type="range" min="0" max="130" value="100" oninput="setVolume(this.value)">
      <button class="cb" onclick="volumeAdj('up')">+</button>
    </div>
  </div>
  <p class="st">CARI & PUTAR</p>
  <div class="sr">
    <input class="si" id="si" placeholder="Nama lagu atau artis..." type="text" onkeydown="if(event.key==='Enter')playSong()">
    <button class="sb" onclick="playSong()">▶</button>
  </div>
  <p class="st">QUICK PLAY</p>
  <div class="qg">
    <div class="qc" onclick="qplay('lofi chill beats')"><div class="qi">🎧</div><div class="ql">Lofi Chill</div></div>
    <div class="qc" onclick="qplay('jazz cafe music')"><div class="qi">☕</div><div class="ql">Jazz Café</div></div>
    <div class="qc" onclick="qplay('instrumental piano relax')"><div class="qi">🎹</div><div class="ql">Piano</div></div>
    <div class="qc" onclick="qplay('dangdut koplo terpopuler')"><div class="qi">🎶</div><div class="ql">Dangdut</div></div>
    <div class="qc" onclick="qplay('rohani kristen terpopuler')"><div class="qi">✝️</div><div class="ql">Rohani</div></div>
    <div class="qc" onclick="qplay('pop indonesia 2024')"><div class="qi">🌟</div><div class="ql">Pop Indo</div></div>
    <div class="qc" onclick="qplay('klasik beethoven mozart')"><div class="qi">🎼</div><div class="ql">Klasik</div></div>
    <div class="qc" onclick="qplay('kpop hits terbaru')"><div class="qi">💫</div><div class="ql">K-Pop</div></div>
    <div class="qc" onclick="qplay('reggae santai indonesia')"><div class="qi">🌴</div><div class="ql">Reggae</div></div>
  </div>
</div>
<div class="pg" id="pg-playlist">
  <p class="st">PLAYLIST TERSIMPAN</p>
  <div class="br" style="margin-bottom:12px">
    <button class="sv" id="pm-order" onclick="setPlayMode('order')">▶ Urut</button>
    <button class="sv" id="pm-shuffle" onclick="setPlayMode('shuffle')">🔀 Acak</button>
  </div>
  <div class="plg" id="plg"><div class="em" style="grid-column:span 2">⏳ Memuat...</div></div>
  <button class="pladd" onclick="om('m-ap')">＋ Buat Playlist Baru</button>
  <div id="pld" style="display:none">
    <div class="dvd"></div>
    <p class="st" id="pldn">PLAYLIST</p>
    <div class="br">
      <button class="sv" onclick="playDetail()">▶ Putar</button>
      <button class="sv rd" onclick="closeDt()">✕ Tutup</button>
    </div>
    <div class="sr">
      <input class="si" id="as" placeholder="Nama lagu..." type="text">
      <button class="sb" onclick="addTrack()">＋</button>
    </div>
    <input class="ci" id="aa" placeholder="Artis (opsional)" type="text">
    <div class="tkl" id="tkl"></div>
  </div>
</div>
<div class="pg" id="pg-radio">
  <p class="st">STASIUN RADIO</p>
  <div class="rl" id="rl"><div class="em">⏳ Memuat stasiun...</div></div>
  <div class="dvd"></div>
  <p class="st">URL CUSTOM</p>
  <div class="sr">
    <input class="si" id="ru" placeholder="URL stream radio..." type="url">
    <button class="sb" onclick="playCustom()">▶</button>
  </div>
  <input class="ci" id="rn" placeholder="Nama stasiun (opsional)" type="text">
  <button class="sv rd" style="width:100%;margin-top:4px" onclick="stopRadio()">⏹ Stop Radio</button>
</div>
<div class="mo" id="m-ap" onclick="if(event.target===this)cm('m-ap')">
  <div class="md">
    <div class="mh"></div>
    <div class="mt">Buat Playlist Baru</div>
    <input class="ci" id="npn" placeholder="Nama playlist..." type="text" onkeydown="if(event.key==='Enter')createPl()">
    <button class="cs" onclick="createPl()">Buat</button>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
let S={playing:false,song:'',artist:'',pls:{},opl:null,playMode:'order'};
let tT;
window.addEventListener('DOMContentLoaded',()=>{loadRadios();loadPls();setInterval(poll,4000);syncVolume();});
function tab(n,b){
  document.querySelectorAll('.pg').forEach(e=>e.classList.remove('a'));
  document.querySelectorAll('.nt').forEach(e=>e.classList.remove('a'));
  document.getElementById('pg-'+n).classList.add('a');b.classList.add('a');
  if(n==='playlist'){loadPls();syncPlayModeUI();}if(n==='radio')loadRadios();
}
async function api(p,o={}){
  try{const r=await fetch(p,{method:o.m||'GET',headers:{'Content-Type':'application/json'},body:o.b?JSON.stringify(o.b):undefined,signal:AbortSignal.timeout(o.t||10000)});return await r.json();}
  catch(e){return{error:e.message};}
}
function setSt(t,a,s){
  document.getElementById('nt').textContent=t||'Tidak ada yang diputar';
  document.getElementById('na').textContent=a||'—';
  document.getElementById('ns').textContent=s||'IDLE';
  const on=!!(s&&s!=='IDLE');
  document.getElementById('vl').className='vl'+(on?' sp':'');
  document.getElementById('ppb').textContent=on?'⏸':'▶';
  S.playing=on;S.song=t;S.artist=a;
}
async function poll(){const d=await api('/playlist_status',{t:3000});if(d&&d.playing)setSt(d.current_song,d.current_artist,'PLAYLIST ['+d.current_index+'/'+d.total+']');}
async function playSong(){const v=document.getElementById('si').value.trim();if(!v){toast('⚠ Masukkan nama lagu','er');return;}await doPlay(v,'');}
async function qplay(q){document.getElementById('si').value=q;await doPlay(q,'');}
async function doPlay(song,artist){
  toast('⏳ Mencari: '+song+'...');setSt(song,artist,'LOADING...');
  const p=song.split(' - ');const s=p[0].trim(),a=artist||(p[1]||'').trim();
  const d=await api('/play_local?song='+encodeURIComponent(s)+'&artist='+encodeURIComponent(a));
  if(d.error||d.status==='error'){toast('❌ '+(d.error||'Gagal'),'er');setSt('','','IDLE');}
  else{setSt(d.title||song,d.artist||a,'▶ PLAYING');toast('✅ '+(d.title||song),'ok');}
}
async function stopAll(){await api('/stop_all');setSt('','','IDLE');toast('⏹ Dihentikan');}
async function stopRadio(){await api('/stop_radio');setSt('','','IDLE');toast('⏹ Radio dihentikan');}
async function skipPrev(){
  toast('⏳ Previous...');
  const d=await api('/playlist_prev',{t:15000});
  if(d.error)toast('❌ '+d.error,'er');else toast('⏮ Previous','ok');
}
async function skipNext(){
  toast('⏳ Skip...');
  const d=await api('/playlist_next',{t:15000});
  if(d.error)toast('❌ '+d.error,'er');else toast('⏭ Skip','ok');
}
async function syncVolume(){
  const d=await api('/stb_volume?action=get',{t:3000});
  if(d&&d.volume!=null){const el=document.getElementById('vol'); if(el) el.value=d.volume;}
}
async function setVolume(v){
  const d=await api('/stb_volume?action=set&level='+encodeURIComponent(v),{t:3000});
  if(d.error)toast('❌ '+d.error,'er');
  else toast('🔊 Volume '+d.volume,'ok');
}
async function volumeAdj(dir){
  const d=await api('/stb_volume?action='+(dir==='up'?'up':'down')+'&step=10',{t:3000});
  if(d.error)toast('❌ '+d.error,'er');
  else{const el=document.getElementById('vol'); if(el&&d.volume!=null) el.value=d.volume; toast('🔊 Volume '+d.volume,'ok');}
}
async function togglePlay(){if(S.playing)await stopAll();else if(S.song)await doPlay(S.song,S.artist);}
async function loadRadios(){
  const el=document.getElementById('rl');
  const d=await api('/api/radio_list',{t:5000});
  if(!d||d.error||!Array.isArray(d)){el.innerHTML='<div class="em">❌ Gagal memuat radio</div>';return;}
  el.innerHTML=d.map(r=>`<div class="ri">
    <div style="font-size:20px;flex-shrink:0">📻</div>
    <div class="rin"><div class="rn">${esc(r.name)}</div><div class="rk">${esc(r.key)}</div></div>
    <button class="rp" onclick="playRadio('${esc(r.url)}','${esc(r.name)}')">▶</button>
  </div>`).join('');
}
async function playRadio(url,name){
  toast('⏳ Memuat: '+name+'...');setSt(name,'Radio','📻 LOADING...');
  const d=await api('/play_radio?url='+encodeURIComponent(url)+'&name='+encodeURIComponent(name));
  if(d.error){toast('❌ '+d.error,'er');setSt('','','IDLE');}
  else{setSt(name,'Radio Streaming','📻 RADIO');toast('✅ '+name,'ok');}
}
async function playCustom(){
  const url=document.getElementById('ru').value.trim();
  const name=document.getElementById('rn').value.trim()||'Radio Custom';
  if(!url){toast('⚠ Masukkan URL','er');return;}
  await playRadio(url,name);
}
async function loadPls(){const d=await api('/api/playlists',{t:5000});if(d&&!d.error)S.pls=d;renderPls();syncPlayModeUI();}
function renderPls(){
  const g=document.getElementById('plg');const ks=Object.keys(S.pls);
  if(!ks.length){g.innerHTML='<div class="em" style="grid-column:span 2">📋 Belum ada playlist</div>';return;}
  g.innerHTML=ks.map(n=>{const c=(S.pls[n].tracks||[]).length;
    return`<div class="plc"><div class="pln">${esc(n)}</div><div class="plct">${c} lagu</div>
    <div class="pla">
      <button class="plb" onclick="openDt('${esc(n)}')">Edit</button>
      <button class="plb" onclick="startPl('${esc(n)}')">▶</button>
    </div></div>`;}).join('');
}
async function startPl(name,mode){
  const playMode=mode||S.playMode||'order';
  toast('⏳ Memuat: '+name+' ('+(playMode==='shuffle'?'acak':'urut')+')...');
  const d=await api('/play_playlist?name='+encodeURIComponent(name)+'&shuffle='+(playMode==='shuffle'));
  if(d.error)toast('❌ '+d.error,'er');
  else{toast('✅ '+name,'ok');setSt(d.first||'...','','PLAYLIST: '+name+' ('+d.total+')');}
}
function openDt(n){S.opl=n;document.getElementById('pldn').textContent=n.toUpperCase();document.getElementById('pld').style.display='block';renderTk(n);}
function closeDt(){S.opl=null;document.getElementById('pld').style.display='none';}
function playDetail(){if(S.opl)startPl(S.opl,S.playMode);} 
function renderTk(n){
  const t=(S.pls[n]||{}).tracks||[];
  document.getElementById('tkl').innerHTML=t.length
    ?t.map((x,i)=>`<div class="tki"><div class="tkn">${i+1}</div><div class="tki2"><div class="tktt">${esc(x.song)}</div><div class="tkar">${esc(x.artist||'—')}</div></div><button class="tkd" onclick="rmTk('${esc(n)}',${i})">✕</button></div>`).join('')
    :'<div class="em">🎵 Playlist kosong</div>';
}
async function addTrack(){
  if(!S.opl)return;const song=document.getElementById('as').value.trim();
  if(!song){toast('⚠ Masukkan nama lagu','er');return;}
  const artist=document.getElementById('aa').value.trim();const n=S.opl;
  if(!S.pls[n])S.pls[n]={tracks:[]};
  S.pls[n].tracks.push({song,artist});await savePls();
  document.getElementById('as').value='';document.getElementById('aa').value='';
  renderTk(n);toast('✅ '+song+' ditambahkan','ok');
}
async function rmTk(n,i){S.pls[n].tracks.splice(i,1);await savePls();renderTk(n);}
async function savePls(){await api('/api/playlists',{m:'POST',b:S.pls});}
function om(id){document.getElementById(id).classList.add('sh');}
function cm(id){document.getElementById(id).classList.remove('sh');}
async function createPl(){
  const n=document.getElementById('npn').value.trim();
  if(!n){toast('⚠ Masukkan nama','er');return;}
  S.pls[n]={tracks:[]};await savePls();cm('m-ap');
  document.getElementById('npn').value='';renderPls();openDt(n);
  toast('✅ Playlist "'+n+'" dibuat','ok');
}
function setPlayMode(mode){S.playMode=mode==='shuffle'?'shuffle':'order';syncPlayModeUI();toast(S.playMode==='shuffle'?'🔀 Playlist acak':'▶ Playlist urut','ok');}
function syncPlayModeUI(){const o=document.getElementById('pm-order');const s=document.getElementById('pm-shuffle');if(o&&s){o.className='sv'+(S.playMode==='order'?' active':'');s.className='sv'+(S.playMode==='shuffle'?' active':'');}}
function toast(msg,type=''){
  const el=document.getElementById('toast');clearTimeout(tT);
  el.textContent=msg;el.className='toast sh'+(type?' '+type:'');
  tT=setTimeout(()=>el.classList.remove('sh'),3000);
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
</body>
</html>"""
    from flask import Response
    return Response(html, content_type="text/html; charset=utf-8")

if __name__ == "__main__":
    log.info("Starting music server on 0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, threaded=True)