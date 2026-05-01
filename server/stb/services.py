import asyncio
import json
import urllib.request
import urllib.error
import urllib.parse
import re
import os
import subprocess
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ================= CONFIG =================
MCP_ENDPOINT = os.environ.get('MCP_ENDPOINT', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_STB_TOKEN = os.environ.get('TELEGRAM_STB_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_TOKEN_FILE = os.environ.get('GOOGLE_TOKEN_FILE', 'google_token.json')

ESP32_URL = f"http://{os.environ.get('ESP32_SENSOR_IP', '192.168.1.222')}"
MUSIC_SERVER = "http://192.168.1.3:8080"
DEFAULT_CITY = "Salatiga"

SYSTEM_PROMPT = """Kamu adalah Anggira, asisten AI pribadi yang ramah.

Kamu punya 2 cara memutar lagu:
- play_song → putar lagu lewat speaker ESP32
- play_song_stb → putar lagu lewat speaker STB/TV di ruangan

Kamu juga bisa memutar internet radio:
- play_radio → putar radio lewat speaker ESP32
- play_radio_stb → putar radio lewat speaker STB/TV di ruangan
- stop_radio → hentikan radio di ESP32
- stop_radio_stb → hentikan radio di STB/TV
- list_radio → tampilkan daftar stasiun radio yang tersedia

Gunakan play_radio_stb / stop_radio_stb jika user menyebut: STB, TV, ruangan, speaker besar.
Gunakan play_radio / stop_radio jika user tidak menyebut tempat.

Kamu juga bisa memutar playlist musik di STB/TV:
- play_playlist → putar playlist berdasarkan nama (contoh: santai, pagi, rohani). Opsional: shuffle=true untuk acak.
- playlist_next → skip ke lagu berikutnya dalam playlist
- playlist_stop → hentikan playlist yang sedang berjalan
- playlist_status → cek lagu yang sedang diputar di playlist
- list_playlists → tampilkan semua nama playlist yang tersedia

Gunakan play_playlist jika user menyebut: playlist, putar semua, lagu-lagu, koleksi, atau menyebut nama playlist.
Jika user tidak tahu nama playlist, gunakan list_playlists dulu.

Jawab singkat, jelas, bahasa Indonesia natural."""

executor = ThreadPoolExecutor(max_workers=4)

# ================= OPENROUTER =================
def _openrouter_chat(messages):
    url = "https://openrouter.ai/api/v1/chat/completions"
    data = json.dumps({
        "model": "minimax/minimax-m2.5:free",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "temperature": 0.7,
        "max_tokens": 300
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        result = json.loads(r.read().decode())
        return result['choices'][0]['message']['content']

async def ai_chat(messages):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _openrouter_chat, messages)

# ================= MUSIC =================
def play_song_http(song, artist=""):
    try:
        url = f"{MUSIC_SERVER}/stream_pcm?song={urllib.parse.quote(song)}&artist={urllib.parse.quote(artist)}"
        return urllib.request.urlopen(url).read().decode()
    except Exception as e:
        return f"Music error: {e}"

async def play_song(song, artist=""):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, play_song_http, song, artist)

# ================= MUSIC STB =================
def play_song_stb_http(song, artist=""):
    try:
        url = f"{MUSIC_SERVER}/play_local?song={urllib.parse.quote(song)}&artist={urllib.parse.quote(artist)}"
        result = urllib.request.urlopen(url, timeout=30).read().decode()
        data = json.loads(result)
        title = data.get("title", song)
        return f"▶ Memutar '{title}' di speaker STB"
    except Exception as e:
        return f"STB Music error: {e}"

def stop_song_stb_http():
    try:
        url = f"{MUSIC_SERVER}/stop_local"
        result = urllib.request.urlopen(url, timeout=5).read().decode()
        data = json.loads(result)
        if data.get("status") == "stopped":
            return "⏹ Musik di STB dihentikan"
        return "Tidak ada musik yang sedang diputar di STB"
    except Exception as e:
        return f"Stop STB error: {e}"

async def play_song_stb(song, artist=""):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, play_song_stb_http, song, artist)

async def stop_song_stb():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, stop_song_stb_http)

# ================= INTERNET RADIO =================
RADIO_STATIONS = {
    "prambors":     {"name": "Prambors FM Jakarta",    "url": "https://s1.cloudmu.id/listen/prambors/stream"},
    "hardrock":     {"name": "Hard Rock FM Jakarta",   "url": "https://stream.zeno.fm/btdooo7j1ydvv"},
    "delta":        {"name": "Delta FM Jakarta",       "url": "https://s1.cloudmu.id/listen/delta_fm/stream"},
    "traxfm":       {"name": "Trax FM Jakarta",        "url": "https://stream.radiojar.com/rrqf78p3bnzuv"},
    "female":       {"name": "Female Radio Jakarta",   "url": "http://103.24.105.90:9300/fjkt"},
    "rripro1jkt":   {"name": "RRI Pro 1 Jakarta",      "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro1.mp3"},
    "rripro2jkt":   {"name": "RRI Pro 2 Jakarta",      "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro2.mp3"},
    "rripro1smg":   {"name": "RRI Pro 1 Semarang",     "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro1.mp3"},
    "rripro2smg":   {"name": "RRI Pro 2 Semarang",     "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro2.mp3"},
    "idolafm":      {"name": "Idola FM Semarang",      "url": "https://stream.cradio.co.id/idolafm"},
    "gajahmada":    {"name": "Gajah Mada FM Semarang", "url": "https://server.radioimeldafm.co.id:8040/gajahmadafm"},
    "swarasmg":     {"name": "Swara Semarang FM",      "url": "https://server.radioimeldafm.co.id/radio/8010/swarasemarang"},
    "upradio":      {"name": "UP Radio Semarang",      "url": "https://stream.tujuhcahaya.com/listen/radio_upradio_semarang/radio.mp3"},
    "salatiga":     {"name": "Radio Salatiga",         "url": "https://icecast.salatiga.go.id:8443/stream.ogg"},
    "bbc":          {"name": "BBC World Service",      "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service"},
    "jazz24":       {"name": "Jazz24",                 "url": "https://live.wostreaming.net/direct/ppm-jazz24aac-ibc1"},
}

def _get_radio_station(name_or_key):
    key = name_or_key.lower().strip()
    if key in RADIO_STATIONS:
        return RADIO_STATIONS[key]
    for k, v in RADIO_STATIONS.items():
        if key in v["name"].lower() or key in k:
            return v
    return None

def list_radio_stations():
    lines = ["📻 Stasiun radio tersedia:"]
    for key, info in RADIO_STATIONS.items():
        lines.append(f"• {info['name']} (kata kunci: {key})")
    return "\n".join(lines)

def play_radio_http(station_name):
    try:
        station = _get_radio_station(station_name)
        if not station:
            return f"❌ Stasiun '{station_name}' tidak ditemukan"
        url = f"{MUSIC_SERVER}/stream_radio?url={urllib.parse.quote(station['url'])}&name={urllib.parse.quote(station['name'])}"
        urllib.request.urlopen(url, timeout=15).read().decode()
        return f"📻 Memutar {station['name']} di speaker ESP32"
    except Exception as e:
        return f"Radio error: {e}"

def stop_radio_http():
    try:
        urllib.request.urlopen(f"{MUSIC_SERVER}/stop_stream", timeout=5).read().decode()
        return "⏹ Radio di ESP32 dihentikan"
    except Exception as e:
        return f"Stop radio error: {e}"

def play_radio_stb_http(station_name):
    try:
        station = _get_radio_station(station_name)
        if not station:
            return f"❌ Stasiun '{station_name}' tidak ditemukan"
        url = f"{MUSIC_SERVER}/play_radio?url={urllib.parse.quote(station['url'])}&name={urllib.parse.quote(station['name'])}"
        urllib.request.urlopen(url, timeout=15).read().decode()
        return f"📻 Memutar {station['name']} di speaker STB/TV"
    except Exception as e:
        return f"Radio STB error: {e}"

def stop_radio_stb_http():
    try:
        urllib.request.urlopen(f"{MUSIC_SERVER}/stop_radio", timeout=5).read().decode()
        return "⏹ Radio di STB/TV dihentikan"
    except Exception as e:
        return f"Stop radio STB error: {e}"

async def play_radio(station_name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, play_radio_http, station_name)

async def stop_radio():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, stop_radio_http)

async def play_radio_stb(station_name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, play_radio_stb_http, station_name)

async def stop_radio_stb():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, stop_radio_stb_http)

async def get_radio_list():
    return list_radio_stations()

# ================= PLAYLIST STB =================

def _call_music_server(path: str) -> str:
    """Panggil endpoint stream_server.py dan kembalikan respons teks."""
    try:
        url = f"{MUSIC_SERVER}{path}"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
        if "error" in data:
            return f"Error: {data['error']}"
        if data.get("status") == "playing" and data.get("playlist"):
            first = data.get("first", "")
            return (
                f"▶ Memutar playlist '{data['playlist']}' "
                f"({data['total']} lagu"
                + (f", shuffle" if data.get("shuffle") else "")
                + f"). Lagu pertama: {first}"
            )
        if data.get("status") == "stopped":
            return "⏹ Playlist dihentikan"
        if data.get("status") == "skipped":
            return "⏭ Lanjut ke lagu berikutnya"
        if data.get("status") == "not_playing":
            return "Tidak ada playlist yang sedang diputar"
        # playlist_status response
        if "playing" in data and "playlist" in data:
            if not data["playing"]:
                return "Tidak ada playlist aktif"
            return (
                f"▶ Playlist: {data['playlist']} | "
                f"Lagu {data['current_index']}/{data['total']}: "
                f"{data['current_song']}"
                + (f" — {data['current_artist']}" if data.get("current_artist") else "")
            )
        # list_playlists response — dict of playlist names
        if isinstance(data, dict):
            names = list(data.keys())
            if not names:
                return "Belum ada playlist. Buat dulu di dashboard."
            return "🎵 Playlist tersedia: " + ", ".join(names)
        return json.dumps(data, ensure_ascii=False)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", str(e))
        except Exception:
            err = str(e)
        return f"Playlist error: {err}"
    except Exception as e:
        return f"Playlist error: {e}"


def play_playlist_stb_http(name: str, shuffle: bool = False) -> str:
    shuf = "true" if shuffle else "false"
    return _call_music_server(
        f"/play_playlist?name={urllib.parse.quote(name)}&shuffle={shuf}"
    )

def playlist_next_http() -> str:
    return _call_music_server("/playlist_next")

def playlist_stop_http() -> str:
    return _call_music_server("/playlist_stop")

def playlist_status_http() -> str:
    return _call_music_server("/playlist_status")

def list_playlists_http() -> str:
    return _call_music_server("/api/playlists")


async def play_playlist_stb(name: str, shuffle: bool = False):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, play_playlist_stb_http, name, shuffle)

async def playlist_next():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, playlist_next_http)

async def playlist_stop():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, playlist_stop_http)

async def playlist_status():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, playlist_status_http)

async def list_playlists():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, list_playlists_http)

# ================= ESP32 =================
def esp32_get(path):
    try:
        url = f"{ESP32_URL}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URLError: {e.reason}"
    except Exception as e:
        return f"ESP32 error: {str(e)}"

async def lamp_on():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, esp32_get, "/on")

async def lamp_off():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, esp32_get, "/off")

# ================= SENSOR =================
def esp32_sensor():
    try:
        return urllib.request.urlopen(f"{ESP32_URL}/sensor_rumah").read().decode()
    except Exception as e:
        return f"Sensor error: {e}"

async def get_sensor_rumah():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, esp32_sensor)

# ================= JADWAL =================
def esp32_get_schedule():
    try:
        return urllib.request.urlopen(f"{ESP32_URL}/jadwal").read().decode()
    except Exception as e:
        return f"Jadwal error: {e}"

def esp32_set_schedule(on, off):
    try:
        return urllib.request.urlopen(f"{ESP32_URL}/set?on={on}&off={off}").read().decode()
    except Exception as e:
        return f"Set jadwal error: {e}"

async def get_schedule():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, esp32_get_schedule)

async def set_schedule(on, off):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, esp32_set_schedule, on, off)

# ================= WEATHER =================
async def get_weather(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city},ID&appid={OPENWEATHER_API_KEY}&units=metric&lang=id"
        with urllib.request.urlopen(url) as r:
            d = json.loads(r.read().decode())
        return f"{city}: {d['main']['temp']}°C, {d['weather'][0]['description']}"
    except Exception as e:
        return f"Cuaca error: {e}"

# ================= NEWS =================
async def get_news():
    try:
        xml = urllib.request.urlopen("https://news.google.com/rss?hl=id-ID&gl=ID&ceid=ID:id").read().decode()
        items = re.findall(r"<title>(.*?)</title>", xml)[1:6]
        return "Berita:\n" + "\n".join(items)
    except Exception as e:
        return f"News error: {e}"

# ================= GOOGLE CALENDAR =================
def _load_google_token():
    if not os.path.exists(GOOGLE_TOKEN_FILE):
        return None
    with open(GOOGLE_TOKEN_FILE, 'r') as f:
        return json.load(f)

def _save_google_token(token_data):
    with open(GOOGLE_TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)

def _refresh_google_token(token_data):
    if not token_data.get('refresh_token'):
        raise Exception("Tidak ada refresh_token. Jalankan google_auth.py dulu.")

    data = urllib.parse.urlencode({
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': token_data['refresh_token'],
        'grant_type': 'refresh_token'
    }).encode()

    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=10) as r:
        new_token = json.loads(r.read().decode())

    token_data['access_token'] = new_token['access_token']
    token_data['expires_in'] = new_token.get('expires_in', 3600)
    token_data['token_expiry'] = (datetime.now(timezone.utc) + timedelta(seconds=new_token.get('expires_in', 3600))).isoformat()
    if 'refresh_token' in new_token:
        token_data['refresh_token'] = new_token['refresh_token']

    _save_google_token(token_data)
    return token_data

def _get_valid_access_token():
    token_data = _load_google_token()
    if not token_data:
        raise Exception("Belum ada token Google. Jalankan: python google_auth.py")
    expiry_str = token_data.get('token_expiry')
    if expiry_str:
        expiry = datetime.fromisoformat(expiry_str)
        now = datetime.now(timezone.utc)
        if expiry <= now + timedelta(seconds=60):
            token_data = _refresh_google_token(token_data)
    return token_data['access_token']

def _calendar_request(method, url, body=None):
    access_token = _get_valid_access_token()
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def _get_calendar_events(days_ahead=7, max_results=10):
    try:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()
        url = (f"https://www.googleapis.com/calendar/v3/calendars/primary/events"
               f"?timeMin={urllib.parse.quote(time_min)}"
               f"&timeMax={urllib.parse.quote(time_max)}"
               f"&maxResults={max_results}"
               "&singleEvents=true&orderBy=startTime")
        result = _calendar_request('GET', url)
        items = result.get('items', [])
        if not items:
            return f"Tidak ada jadwal dalam {days_ahead} hari ke depan."
        lines = [f"📅 Jadwal {days_ahead} hari ke depan ({len(items)} event):"]
        for event in items:
            summary = event.get('summary', '(tanpa judul)')
            start = event.get('start', {})
            if 'dateTime' in start:
                dt = datetime.fromisoformat(start['dateTime'])
                dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
                waktu = dt_wib.strftime("%d %b %Y, %H:%M WIB")
            elif 'date' in start:
                waktu = start['date'] + " (seharian)"
            else:
                waktu = "waktu tidak diketahui"
            location = event.get('location', '')
            loc_str = f" 📍{location}" if location else ""
            lines.append(f"• {waktu}: {summary}{loc_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Google Calendar error: {e}"

def _add_calendar_event(summary, start_datetime, end_datetime=None, description="", location=""):
    try:
        start_dt = datetime.fromisoformat(start_datetime)
        if not end_datetime:
            end_dt = start_dt + timedelta(hours=1)
            end_datetime = end_dt.isoformat()
        body = {
            "summary": summary, "description": description, "location": location,
            "start": {"dateTime": start_datetime, "timeZone": "Asia/Jakarta"},
            "end": {"dateTime": end_datetime, "timeZone": "Asia/Jakarta"}
        }
        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        result = _calendar_request('POST', url, body)
        event_link = result.get('htmlLink', '')
        return f"✅ Event '{summary}' berhasil ditambahkan!\nLink: {event_link}"
    except Exception as e:
        return f"Gagal tambah event: {e}"

async def get_calendar(days_ahead=7):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _get_calendar_events, days_ahead)

async def add_calendar_event(summary, start_datetime, end_datetime=None, description="", location=""):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _add_calendar_event, summary, start_datetime, end_datetime, description, location)

# ================= TTS =================
def tts_stb(text):
    try:
        clean = re.sub(r'[^\w\s,.!?%°\-]', '', text).strip()
        if not clean:
            return
        subprocess.Popen(["termux-tts-speak", "-l", "id", "-p", "1.2", "-r", "1.0", clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"TTS error: {e}")

# ================= WAKTU =================
async def get_time():
    return datetime.now().strftime("%H:%M")

# ================= WIKIPEDIA =================
def _wikipedia(query, lang="id"):
    """Cari ringkasan artikel Wikipedia. Coba bahasa Indonesia dulu, fallback Inggris."""
    try:
        for lng in ([lang] if lang == "en" else [lang, "en"]):
            # Cari judul
            search_url = (
                f"https://{lng}.wikipedia.org/w/api.php"
                f"?action=query&list=search&srsearch={urllib.parse.quote(query)}"
                f"&format=json&srlimit=1&utf8=1"
            )
            req = urllib.request.Request(search_url, headers={"User-Agent": "AnggiraBot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            hits = data.get("query", {}).get("search", [])
            if not hits:
                continue
            title = hits[0]["title"]
            # Ambil ringkasan
            extract_url = (
                f"https://{lng}.wikipedia.org/w/api.php"
                f"?action=query&prop=extracts&exintro&explaintext&exsectionformat=plain"
                f"&titles={urllib.parse.quote(title)}&format=json&utf8=1"
            )
            req2 = urllib.request.Request(extract_url, headers={"User-Agent": "AnggiraBot/1.0"})
            with urllib.request.urlopen(req2, timeout=8) as r:
                sdata = json.loads(r.read().decode())
            pages = sdata.get("query", {}).get("pages", {})
            extract = next(iter(pages.values())).get("extract", "").strip()
            extract = re.sub(r'\n+', ' ', extract)
            if len(extract) > 600:
                extract = extract[:600].rsplit(' ', 1)[0] + "..."
            if extract:
                return f"📖 {title}:\n{extract}"
        return f"Tidak ditemukan info tentang '{query}' di Wikipedia."
    except Exception as e:
        return f"Wikipedia error: {e}"

async def wikipedia(query, lang="id"):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _wikipedia, query, lang)

# ================= KURS MATA UANG =================
def _kurs(from_cur, to_cur, amount=1.0):
    """Kurs mata uang realtime via open.er-api.com (gratis, tanpa key)."""
    try:
        from_c = from_cur.upper().strip()
        to_c   = to_cur.upper().strip()
        url = f"https://open.er-api.com/v6/latest/{from_c}"
        req = urllib.request.Request(url, headers={"User-Agent": "AnggiraBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        if data.get("result") != "success":
            return f"Gagal ambil kurs {from_c}: {data.get('error-type','unknown')}"
        rates  = data.get("rates", {})
        update = data.get("time_last_update_utc", "")
        if to_c not in rates:
            # Tampilkan beberapa kurs populer jika to_c tidak dikenali
            popular = ["USD","EUR","SGD","MYR","JPY","GBP","AUD","IDR"]
            lines = [f"Kurs {from_c} (update: {update[:16]})"]
            for c in popular:
                if c in rates and c != from_c:
                    lines.append(f"  {c}: {rates[c]:,.4f}")
            return "\n".join(lines)
        rate  = rates[to_c]
        total = rate * float(amount)
        return (
            f"💱 Kurs {from_c} → {to_c}\n"
            f"1 {from_c} = {rate:,.4f} {to_c}\n"
            f"{amount:g} {from_c} = {total:,.2f} {to_c}\n"
            f"Update: {update[:16]}"
        )
    except Exception as e:
        return f"Kurs error: {e}"

async def kurs(from_cur, to_cur, amount=1.0):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _kurs, from_cur, to_cur, amount)

# ================= INDEKS SAHAM =================
def _stock(symbol):
    """
    Ambil harga saham/indeks via Yahoo Finance (tanpa API key).
    Symbol: IHSG=^JKSE, S&P500=^GSPC, NASDAQ=^IXIC, Dow=^DJI, Nikkei=^N225
    Saham: BBCA.JK, TLKM.JK, AAPL, GOOGL, dst
    """
    try:
        sym = symbol.upper().strip()
        # Yahoo Finance v8 JSON endpoint
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
            f"?interval=1d&range=1d"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())

        meta = data["chart"]["result"][0]["meta"]
        name      = meta.get("longName") or meta.get("shortName") or sym
        price     = meta.get("regularMarketPrice", 0)
        prev      = meta.get("chartPreviousClose") or meta.get("previousClose") or price
        currency  = meta.get("currency", "")
        exchange  = meta.get("exchangeName", "")
        change    = price - prev
        pct       = (change / prev * 100) if prev else 0
        arrow     = "▲" if change >= 0 else "▼"
        sign      = "+" if change >= 0 else ""

        return (
            f"📈 {name} ({sym})\n"
            f"Harga: {price:,.2f} {currency}\n"
            f"{arrow} {sign}{change:,.2f} ({sign}{pct:.2f}%)\n"
            f"Bursa: {exchange}"
        )
    except Exception as e:
        return f"Saham error ({symbol}): {e}"

# Alias untuk indeks populer
def _indeks_saham(nama):
    """Ambil indeks saham berdasarkan nama populer (IHSG, S&P500, Nasdaq, dll)."""
    mapping = {
        "ihsg":    "^JKSE",
        "jkse":    "^JKSE",
        "sp500":   "^GSPC",
        "s&p500":  "^GSPC",
        "s&p":     "^GSPC",
        "nasdaq":  "^IXIC",
        "dow":     "^DJI",
        "djia":    "^DJI",
        "nikkei":  "^N225",
        "hangseng":"^HSI",
        "hsi":     "^HSI",
        "sti":     "^STI",
        "asx":     "^AXJO",
        "ftse":    "^FTSE",
        "dax":     "^GDAXI",
        "cac":     "^FCHI",
    }
    key = nama.lower().strip().replace(" ", "")
    sym = mapping.get(key, nama)  # fallback: pakai nama apa adanya sebagai symbol
    return _stock(sym)

async def saham(symbol):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _stock, symbol)

async def indeks_saham(nama):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _indeks_saham, nama)

# ================= KALKULATOR =================
def _kalkulator(expr):
    """Evaluasi ekspresi matematika dengan aman (sin, cos, sqrt, log, pow, dll)."""
    import math
    try:
        # Normalisasi
        expr = expr.replace("^", "**").replace(",", ".").replace("×", "*").replace("÷", "/")
        # Whitelist karakter
        allowed = set("0123456789+-*/().eE_ ")
        math_funcs = {"sin","cos","tan","asin","acos","atan","sqrt","log","log10",
                      "log2","exp","abs","ceil","floor","round","pi","e","inf","pow","factorial"}
        # Cek apakah ada nama fungsi
        cleaned = re.sub(r'[a-zA-Z_]+', '', expr)
        if not all(c in allowed for c in cleaned):
            return "Ekspresi tidak valid. Contoh: 2^10, sqrt(144), sin(pi/2), log(100)"
        safe_globals = {"__builtins__": {}}
        safe_locals  = {k: getattr(math, k) for k in dir(math) if k in math_funcs}
        safe_locals["pi"]  = math.pi
        safe_locals["e"]   = math.e
        result = eval(expr, safe_globals, safe_locals)  # noqa: S307
        if isinstance(result, float) and result == int(result):
            return f"🧮 {expr} = {int(result)}"
        return f"🧮 {expr} = {result:g}"
    except ZeroDivisionError:
        return "Error: pembagian dengan nol"
    except Exception as e:
        return f"Kalkulator error: {e}"

async def kalkulator(expr):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _kalkulator, expr)

# ================= WEB SEARCH =================
def _web_search(query):
    """Cari info via DuckDuckGo Instant Answer API (tanpa key)."""
    try:
        url = (
            f"https://api.duckduckgo.com/"
            f"?q={urllib.parse.quote(query)}&format=json&no_redirect=1&no_html=1&skip_disambig=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AnggiraBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())

        abstract = data.get("AbstractText", "").strip()
        if abstract:
            source = data.get("AbstractSource", "")
            url_link = data.get("AbstractURL", "")
            result = abstract[:500]
            if len(abstract) > 500:
                result = abstract[:500].rsplit(' ', 1)[0] + "..."
            footer = f"\n📎 {source}" if source else ""
            return f"🔍 {result}{footer}"

        # Fallback ke related topics
        topics = data.get("RelatedTopics", [])
        snippets = []
        for t in topics[:4]:
            if isinstance(t, dict) and t.get("Text"):
                snippets.append(t["Text"][:150])
        if snippets:
            return "🔍 " + "\n\n".join(snippets)

        # Fallback ke Answer
        answer = data.get("Answer", "").strip()
        if answer:
            return f"🔍 {answer}"

        return f"Tidak ditemukan hasil untuk: '{query}'. Coba kata kunci lain."
    except Exception as e:
        return f"Web search error: {e}"

async def web_search(query):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _web_search, query)

# ================= WAKTU DUNIA =================
def _world_time(tz_name):
    """Waktu saat ini di timezone tertentu via worldtimeapi.org."""
    try:
        # Alias nama kota populer → timezone IANA
        alias = {
            "jakarta":     "Asia/Jakarta",
            "tokyo":       "Asia/Tokyo",
            "london":      "Europe/London",
            "new york":    "America/New_York",
            "paris":       "Europe/Paris",
            "sydney":      "Australia/Sydney",
            "dubai":       "Asia/Dubai",
            "singapore":   "Asia/Singapore",
            "beijing":     "Asia/Shanghai",
            "moscow":      "Europe/Moscow",
            "los angeles": "America/Los_Angeles",
            "la":          "America/Los_Angeles",
            "mekah":       "Asia/Riyadh",
            "mekkah":      "Asia/Riyadh",
        }
        tz = alias.get(tz_name.lower().strip(), tz_name)
        url = f"https://worldtimeapi.org/api/timezone/{urllib.parse.quote(tz)}"
        req = urllib.request.Request(url, headers={"User-Agent": "AnggiraBot/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        dt_str   = data.get("datetime", "")
        timezone_name = data.get("timezone", tz)
        dt       = datetime.fromisoformat(dt_str)
        day_names = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
        day      = day_names[dt.weekday()]
        return (
            f"🕐 {timezone_name}\n"
            f"{day}, {dt.strftime('%d %B %Y %H:%M:%S')}"
        )
    except Exception as e:
        return f"World time error: {e}"

async def world_time(tz_name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _world_time, tz_name)

# ================= CUACA DETAIL =================
async def get_weather_detail(city):
    """Cuaca lengkap: suhu, kelembaban, angin, tekanan."""
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={city},ID&appid={OPENWEATHER_API_KEY}&units=metric&lang=id"
        )
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.loads(r.read().decode())
        main = d["main"]
        wind = d.get("wind", {})
        desc = d["weather"][0]["description"].capitalize()
        sunrise = datetime.fromtimestamp(d["sys"]["sunrise"], tz=timezone.utc).astimezone(timezone(timedelta(hours=7))).strftime("%H:%M")
        sunset  = datetime.fromtimestamp(d["sys"]["sunset"],  tz=timezone.utc).astimezone(timezone(timedelta(hours=7))).strftime("%H:%M")
        return (
            f"🌤 Cuaca {city}\n"
            f"{desc}\n"
            f"🌡 Suhu: {main['temp']}°C (terasa {main['feels_like']}°C)\n"
            f"💧 Kelembaban: {main['humidity']}%\n"
            f"💨 Angin: {wind.get('speed',0)} m/s\n"
            f"🔵 Tekanan: {main['pressure']} hPa\n"
            f"🌅 Matahari terbit: {sunrise} | terbenam: {sunset} WIB"
        )
    except Exception as e:
        return f"Cuaca detail error: {e}"

# ================= HARGA CRYPTO =================
def _crypto(symbol):
    """Harga crypto via CoinGecko (gratis, tanpa key)."""
    try:
        # Map simbol populer → CoinGecko ID
        mapping = {
            "btc": "bitcoin", "bitcoin": "bitcoin",
            "eth": "ethereum", "ethereum": "ethereum",
            "bnb": "binancecoin",
            "sol": "solana", "solana": "solana",
            "xrp": "ripple", "ripple": "ripple",
            "doge": "dogecoin", "dogecoin": "dogecoin",
            "ada": "cardano", "cardano": "cardano",
            "dot": "polkadot",
            "usdt": "tether",
            "usdc": "usd-coin",
        }
        key = symbol.lower().strip()
        coin_id = mapping.get(key, key)
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={urllib.parse.quote(coin_id)}&vs_currencies=usd,idr"
            f"&include_24hr_change=true&include_last_updated_at=true"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AnggiraBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        if coin_id not in data:
            return f"Crypto '{symbol}' tidak ditemukan. Coba: BTC, ETH, BNB, SOL, XRP, DOGE"
        info    = data[coin_id]
        usd     = info.get("usd", 0)
        idr     = info.get("idr", 0)
        chg24   = info.get("usd_24h_change", 0)
        arrow   = "▲" if chg24 >= 0 else "▼"
        sign    = "+" if chg24 >= 0 else ""
        return (
            f"₿ {symbol.upper()} ({coin_id})\n"
            f"USD: ${usd:,.2f}\n"
            f"IDR: Rp {idr:,.0f}\n"
            f"{arrow} 24h: {sign}{chg24:.2f}%"
        )
    except Exception as e:
        return f"Crypto error: {e}"

async def crypto(symbol):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _crypto, symbol)

# ================= TIMER / PENGINGAT =================
# (diganti oleh set_reminder_v2 di bagian ALARM & SCHEDULER)

# ================= VATICAN NEWS =================

def _translate_mymemory(text, src="en", tgt="id"):
    """Terjemahkan teks via MyMemory API (gratis, tanpa key, limit 500 karakter/request)."""
    try:
        if not text or not text.strip():
            return text
        text = text[:450]
        url = (
            "https://api.mymemory.translated.net/get"
            f"?q={urllib.parse.quote(text)}&langpair={src}|{tgt}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AnggiraBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        result = data.get("responseData", {}).get("translatedText", "")
        if result and result.lower() != text.lower():
            return result
        return text
    except Exception:
        return text


def _get_vatican_news(lang="id", translate=False, limit=5):
    """
    Ambil berita Vatican via Google News RSS (filter keyword Vatican/Vatikan).
    lang      : "id" (Indonesia) atau "en" (Inggris)
    translate : terjemahkan ke Indonesia jika lang="en"
    limit     : jumlah berita 1-10 (default 5)
    """
    try:
        # Google News RSS — sama reliabelnya dengan fungsi news() yang sudah jalan
        if lang == "en":
            url = "https://news.google.com/rss/search?q=vatican+pope&hl=en&gl=US&ceid=US:en"
        else:
            url = "https://news.google.com/rss/search?q=vatikan+paus&hl=id&gl=ID&ceid=ID:id"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read().decode("utf-8", errors="ignore")

        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        if not items:
            return "Tidak ada berita Vatican saat ini."

        results = []
        for item in items[:limit]:
            # Judul
            title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""

            # Sumber berita (misal: Vatican News - CNN)
            source_m = re.search(r"<source[^>]*>(.*?)</source>", item, re.DOTALL)
            source = source_m.group(1).strip() if source_m else ""

            # Tanggal
            date_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
            date = ""
            if date_m:
                try:
                    from email.utils import parsedate
                    import time as _time
                    t = parsedate(date_m.group(1).strip())
                    if t:
                        date = _time.strftime("%d %b", t)
                except Exception:
                    pass

            if not title:
                continue

            if translate and lang == "en":
                title = _translate_mymemory(title, src="en", tgt="id")

            line = f"• [{date}] {title}" if date else f"• {title}"
            if source:
                line += f"\n  — {source}"
            results.append(line)

        if not results:
            return "Tidak ada berita Vatican yang ditemukan."

        label = "🇮🇩" if lang == "id" else ("🌐 diterjemahkan" if translate else "🌐 Inggris")
        header = f"✝️ Berita Vatican {label} — {len(results)} terbaru:\n\n"
        return header + "\n\n".join(results)

    except Exception as e:
        return f"Vatican News error: {e}"

async def get_vatican_news(lang="id", translate=False, limit=5):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _get_vatican_news, lang, translate, limit)

# ================= BERITA TOPIK =================
def _get_news_topik(topik, lang="id", limit=5):
    """
    Cari berita berdasarkan topik bebas via Google News RSS.
    Contoh topik: harga minyak, teknologi AI, ekonomi Indonesia, bola, dll.
    """
    try:
        if lang == "en":
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topik)}&hl=en&gl=US&ceid=US:en"
        else:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topik)}&hl=id&gl=ID&ceid=ID:id"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read().decode("utf-8", errors="ignore")

        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        if not items:
            return f"Tidak ada berita tentang '{topik}' saat ini."

        results = []
        for item in items[:limit]:
            # Judul
            title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""

            # Sumber
            source_m = re.search(r"<source[^>]*>(.*?)</source>", item)
            source = source_m.group(1).strip() if source_m else ""

            # Tanggal
            date_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
            date = ""
            if date_m:
                try:
                    from email.utils import parsedate
                    import time as _time
                    t = parsedate(date_m.group(1).strip())
                    if t:
                        date = _time.strftime("%d %b", t)
                except Exception:
                    pass

            if not title:
                continue

            line = f"• [{date}] {title}" if date else f"• {title}"
            if source:
                line += f"\n  — {source}"
            results.append(line)

        if not results:
            return f"Tidak ada berita tentang '{topik}'."

        header = f"📰 Berita: *{topik}* — {len(results)} terbaru:\n\n"
        return header + "\n\n".join(results)

    except Exception as e:
        return f"Berita topik error: {e}"

async def get_news_topik(topik, lang="id", limit=5):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _get_news_topik, topik, lang, limit)

# ================= ALARM & SCHEDULER =================
import threading
import time as _time
from email.utils import parsedate as _parsedate

# Config ESP32 Xiaozhi
_XIAOZHI_IP   = os.environ.get('ESP32_IP', '192.168.1.222')
_XIAOZHI_PORT = int(os.environ.get('ESP32_PORT', '8080'))
_XIAOZHI_WAKE_URL = f"http://{_XIAOZHI_IP}:{_XIAOZHI_PORT}/wake"
_XIAOZHI_SAY_URL  = f"http://{_XIAOZHI_IP}:{_XIAOZHI_PORT}/say"

# Chat ID untuk notifikasi Telegram
_ALARM_CHAT_ID = os.environ.get('TELEGRAM_ALLOWED_USER_ID', '').split(',')[0].strip()

# Store alarm in-memory
_alarms: dict = {}
_alarm_lock = threading.Lock()
_scheduler_started = False

# ── Helper: kontrol ESP32 ──────────────────────────────────────

def _xiaozhi_wake():
    try:
        payload = json.dumps({"wake_word": "Hi ESP"}).encode()
        req = urllib.request.Request(
            _XIAOZHI_WAKE_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
        _time.sleep(2)
        return True
    except Exception as e:
        print(f"[Scheduler] Wake ESP32 error: {e}")
        return False

def _xiaozhi_say(text: str):
    try:
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            _XIAOZHI_SAY_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Scheduler] Say ESP32 error: {e}")

def _telegram_notify(pesan: str):
    if not _ALARM_CHAT_ID or not TELEGRAM_STB_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_STB_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": _ALARM_CHAT_ID,
            "text": pesan,
            "parse_mode": "Markdown"
        }).encode()
        req = urllib.request.Request(url, data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Scheduler] Telegram notify error: {e}")

def _trigger_alarm(ucapan: str, notif: str):
    """Wake ESP32, ucapkan pesan, dan kirim notif Telegram."""
    print(f"[Scheduler] TRIGGER: {ucapan}")
    _telegram_notify(notif)
    if _xiaozhi_wake():
        _time.sleep(1)
        _xiaozhi_say(ucapan)

def _cuaca_singkat():
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={DEFAULT_CITY},ID&appid={OPENWEATHER_API_KEY}&units=metric&lang=id"
        )
        with urllib.request.urlopen(url, timeout=6) as r:
            d = json.loads(r.read().decode())
        suhu = d['main']['temp']
        desc = d['weather'][0]['description']
        return f"suhu {suhu:.0f} derajat, {desc}"
    except Exception:
        return ""

# ── Scheduler loop ─────────────────────────────────────────────

def _load_dashboard_config():
    """Baca config chime dari dashboard_config.json."""
    cfg_path = os.path.join(os.path.expanduser("~"), "anggira", "dashboard_config.json")
    default = {"chime_enabled": True,
               "chime_text": "jam berapa sekarang dan kapan hujan di cebongan salatiga",
               "chime_hours": list(range(6, 22))}
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f)
            for k, v in default.items():
                cfg.setdefault(k, v)
            return cfg
    except Exception:
        pass
    return default

def _scheduler_loop():
    print("[Scheduler] Background scheduler started")
    calendar_notified = set()  # set event_id yang sudah dinotifikasi

    while True:
        try:
            now = datetime.now()
            now_wib = datetime.now(timezone(timedelta(hours=7)))

            # ── 1. Alarm in-memory ──────────────────────────────
            with _alarm_lock:
                to_trigger = [
                    (aid, a) for aid, a in _alarms.items()
                    if not a.get("done") and now >= a["waktu"]
                ]
                for aid, _ in to_trigger:
                    _alarms[aid]["done"] = True

            for aid, alarm in to_trigger:
                ucapan = f"Pengingat! {alarm['pesan']}"
                notif  = f"⏰ *Pengingat:* {alarm['pesan']}"
                threading.Thread(
                    target=_trigger_alarm, args=(ucapan, notif), daemon=True
                ).start()

            # ── 2. Alarm Google Calendar (5 menit sebelum event) ─
            try:
                cal_now = now_wib
                cal_end = cal_now + timedelta(minutes=6)
                url = (
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
                    f"?timeMin={urllib.parse.quote(cal_now.isoformat())}"
                    f"&timeMax={urllib.parse.quote(cal_end.isoformat())}"
                    "&maxResults=5&singleEvents=true&orderBy=startTime"
                )
                access_token = _get_valid_access_token()
                req = urllib.request.Request(url, headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                })
                with urllib.request.urlopen(req, timeout=8) as r:
                    events = json.loads(r.read().decode()).get("items", [])

                for ev in events:
                    ev_id = ev.get("id", "")
                    if ev_id in calendar_notified:
                        continue
                    summary = ev.get("summary", "Tanpa judul")
                    start = ev.get("start", {})
                    waktu_str = ""
                    if "dateTime" in start:
                        dt = datetime.fromisoformat(start["dateTime"])
                        dt_wib = dt.astimezone(timezone(timedelta(hours=7)))
                        waktu_str = dt_wib.strftime("%H:%M")
                    calendar_notified.add(ev_id)
                    ucapan = f"Pengingat! Sebentar lagi ada jadwal: {summary}" + (f" jam {waktu_str}" if waktu_str else "")
                    notif  = f"📅 *Jadwal dalam 5 menit:* {summary}" + (f" pukul {waktu_str} WIB" if waktu_str else "")
                    threading.Thread(
                        target=_trigger_alarm, args=(ucapan, notif), daemon=True
                    ).start()
            except Exception as e:
                if "Belum ada token" not in str(e):
                    print(f"[Scheduler] Calendar check error: {e}")

            # ── 3. Chime per jam (handled natively oleh ESP32 S3 via FetchChimeConfig ke dashboard) ──
            # ESP32 S3 sudah fetch config dari /api/chime_config setiap jam dan self-trigger.
            # Tidak perlu duplicate trigger dari sini agar tidak double-chime.

        except Exception as e:
            print(f"[Scheduler] Loop error: {e}")

        _time.sleep(30)  # cek setiap 30 detik

def start_scheduler():
    """Mulai background scheduler — panggil sekali dari anggira.py main()."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()
    print("[Scheduler] Started OK")

# ── Fungsi pengingat baru (replace _set_reminder lama) ─────────

def _set_reminder_v2(menit, pesan, tambah_kalender=False):
    """
    Setel pengingat dengan timer nyata yang akan wake ESP32.
    Opsional: tambahkan ke Google Calendar.
    """
    try:
        m = float(menit)
        if m <= 0 or m > 1440:
            return "Menit harus antara 1 dan 1440 (24 jam)."

        waktu_alarm = datetime.now() + timedelta(minutes=m)
        waktu_wib   = waktu_alarm.strftime("%H:%M")

        with _alarm_lock:
            alarm_id = f"manual_{int(_time.time())}"
            _alarms[alarm_id] = {
                "waktu": waktu_alarm,
                "pesan": pesan,
                "done":  False
            }

        hasil = (
            f"⏰ Pengingat disetel!\n"
            f"Pesan: {pesan}\n"
            f"Waktu: {waktu_wib} WIB ({m:.0f} menit lagi)\n"
            f"ESP32 akan dibangunkan otomatis."
        )

        # Tambah ke Google Calendar jika diminta
        if tambah_kalender:
            try:
                start_iso = waktu_alarm.astimezone(timezone(timedelta(hours=7))).isoformat()
                end_iso   = (waktu_alarm + timedelta(minutes=15)).astimezone(timezone(timedelta(hours=7))).isoformat()
                cal_result = _add_calendar_event(
                    summary=f"⏰ {pesan}",
                    start_datetime=start_iso,
                    end_datetime=end_iso,
                    description="Pengingat otomatis dari Anggira"
                )
                hasil += f"\n✅ Ditambahkan ke Google Calendar"
            except Exception as e:
                hasil += f"\n⚠️ Gagal tambah ke Calendar: {e}"

        return hasil
    except Exception as e:
        return f"Pengingat error: {e}"

async def set_reminder_v2(menit, pesan, tambah_kalender=False):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _set_reminder_v2, menit, pesan, tambah_kalender)

def list_alarms():
    """Tampilkan semua alarm aktif."""
    with _alarm_lock:
        aktif = [(aid, a) for aid, a in _alarms.items() if not a.get("done")]
    if not aktif:
        return "Tidak ada pengingat aktif saat ini."
    lines = ["⏰ *Pengingat aktif:*"]
    for aid, a in aktif:
        sisa = (a["waktu"] - datetime.now()).total_seconds()
        mnt  = int(sisa // 60)
        lines.append(f"• {a['pesan']} — {mnt} menit lagi ({a['waktu'].strftime('%H:%M')})")
    return "\n".join(lines)

async def get_alarms():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, list_alarms)

def cancel_alarm_by_keyword(keyword: str):
    """Batalkan alarm yang pesannya mengandung keyword."""
    with _alarm_lock:
        cancelled = []
        for aid, a in _alarms.items():
            if not a.get("done") and keyword.lower() in a["pesan"].lower():
                a["done"] = True
                cancelled.append(a["pesan"])
    if cancelled:
        return "✅ Dibatalkan:\n" + "\n".join(f"• {p}" for p in cancelled)
    return f"Tidak ada pengingat dengan kata kunci '{keyword}'."

async def cancel_alarm(keyword: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, cancel_alarm_by_keyword, keyword)