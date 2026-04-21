import asyncio
import websockets
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
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')       # Bot untuk ESP32/Xiaozhi
TELEGRAM_STB_TOKEN = os.environ.get('TELEGRAM_STB_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')  # Bot STB = Anggira bot
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')

# Google Calendar - simpan token OAuth2 di file ini atau env
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_TOKEN_FILE = os.environ.get('GOOGLE_TOKEN_FILE', 'google_token.json')

ESP32_URL = f"http://{os.environ.get('ESP32_SENSOR_IP', '192.168.1.222')}"  # C3 Mini sensor+lampu
MUSIC_SERVER = "http://192.168.1.3:8080"
DEFAULT_CITY = "Salatiga"

SYSTEM_PROMPT = """Kamu adalah Anggira, asisten AI pribadi yang ramah.

Kamu punya 2 cara memutar lagu:
- play_song → putar lagu lewat speaker ESP32 (speaker kecil di perangkat ini)
- play_song_stb → putar lagu lewat speaker STB/TV di ruangan (lebih keras, kualitas lebih baik)

Kamu juga bisa memutar internet radio:
- play_radio → putar radio lewat speaker ESP32 (speaker kecil)
- play_radio_stb → putar radio lewat speaker STB/TV di ruangan
- stop_radio → hentikan radio di ESP32
- stop_radio_stb → hentikan radio di STB/TV
- list_radio → tampilkan daftar stasiun radio yang tersedia

Gunakan play_radio_stb / stop_radio_stb jika user menyebut: STB, TV, ruangan, speaker besar, speaker TV, di sana.
Gunakan play_radio / stop_radio jika user tidak menyebut tempat, atau menyebut: sini, di sini, speaker ini.
Gunakan play_song_stb jika user minta lagu tertentu di STB/TV.
Gunakan stop_song_stb jika user minta stop/hentikan musik di STB/TV.

Jawab singkat, jelas, bahasa Indonesia natural."""

executor = ThreadPoolExecutor(max_workers=4)

# ================= OPENROUTER =================
def _openrouter_chat(messages):
    """Kirim pesan ke OpenRouter API (model minimax gratis)."""
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
# Daftar stasiun radio — tambah/ubah sesuai kebutuhan
RADIO_STATIONS = {
    # === Jakarta ===
    "prambors":     {"name": "Prambors FM Jakarta",    "url": "https://s1.cloudmu.id/listen/prambors/stream"},
    "hardrock":     {"name": "Hard Rock FM Jakarta",   "url": "https://stream.zeno.fm/btdooo7j1ydvv"},
    "delta":        {"name": "Delta FM Jakarta",       "url": "https://s1.cloudmu.id/listen/delta_fm/stream"},
    "traxfm":       {"name": "Trax FM Jakarta",        "url": "https://stream.radiojar.com/rrqf78p3bnzuv"},
    "female":       {"name": "Female Radio Jakarta",   "url": "http://103.24.105.90:9300/fjkt"},
    "rripro1jkt":   {"name": "RRI Pro 1 Jakarta",      "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro1.mp3"},
    "rripro2jkt":   {"name": "RRI Pro 2 Jakarta",      "url": "https://stream-node1.rri.co.id/streaming/25/9025/rrijakartapro2.mp3"},
    # === Semarang ===
    "rripro1smg":   {"name": "RRI Pro 1 Semarang",     "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro1.mp3"},
    "rripro2smg":   {"name": "RRI Pro 2 Semarang",     "url": "https://stream-node0.rri.co.id/streaming/16/9016/rrisemarangpro2.mp3"},
    "idolafm":      {"name": "Idola FM Semarang",      "url": "https://stream.cradio.co.id/idolafm"},
    "gajahmada":    {"name": "Gajah Mada FM Semarang", "url": "https://server.radioimeldafm.co.id:8040/gajahmadafm"},
    "swarasmg":     {"name": "Swara Semarang FM",      "url": "https://server.radioimeldafm.co.id/radio/8010/swarasemarang"},
    "upradio":      {"name": "UP Radio Semarang",      "url": "https://stream.tujuhcahaya.com/listen/radio_upradio_semarang/radio.mp3"},
    # === Salatiga ===
    "salatiga":     {"name": "Radio Salatiga",         "url": "https://icecast.salatiga.go.id:8443/stream.ogg"},
    # === Internasional ===
    "bbc":          {"name": "BBC World Service",      "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service"},
    "jazz24":       {"name": "Jazz24",                 "url": "https://live.wostreaming.net/direct/ppm-jazz24aac-ibc1"},
}

def _get_radio_station(name_or_key):
    """Cari stasiun radio berdasarkan key atau nama (case-insensitive)."""
    key = name_or_key.lower().strip()
    # Cek key langsung
    if key in RADIO_STATIONS:
        return RADIO_STATIONS[key]
    # Cek partial match pada nama
    for k, v in RADIO_STATIONS.items():
        if key in v["name"].lower() or key in k:
            return v
    return None

def list_radio_stations():
    """Kembalikan daftar stasiun radio yang tersedia."""
    lines = ["📻 Stasiun radio tersedia:"]
    for key, info in RADIO_STATIONS.items():
        lines.append(f"• {info['name']} (kata kunci: {key})")
    return "\n".join(lines)

def play_radio_http(station_name):
    """Putar internet radio via speaker ESP32 (stream PCM ke ESP32)."""
    try:
        station = _get_radio_station(station_name)
        if not station:
            available = ", ".join(RADIO_STATIONS.keys())
            return f"❌ Stasiun '{station_name}' tidak ditemukan. Tersedia: {available}"
        url = f"{MUSIC_SERVER}/stream_radio?url={urllib.parse.quote(station['url'])}&name={urllib.parse.quote(station['name'])}"
        result = urllib.request.urlopen(url, timeout=15).read().decode()
        return f"📻 Memutar {station['name']} di speaker ESP32"
    except Exception as e:
        return f"Radio error: {e}"

def stop_radio_http():
    """Hentikan radio di ESP32 (sama endpoint dengan stop lagu)."""
    try:
        url = f"{MUSIC_SERVER}/stop_stream"
        result = urllib.request.urlopen(url, timeout=5).read().decode()
        return "⏹ Radio di ESP32 dihentikan"
    except Exception as e:
        return f"Stop radio error: {e}"

def play_radio_stb_http(station_name):
    """Putar internet radio langsung di STB/TV."""
    try:
        station = _get_radio_station(station_name)
        if not station:
            available = ", ".join(RADIO_STATIONS.keys())
            return f"❌ Stasiun '{station_name}' tidak ditemukan. Tersedia: {available}"
        url = f"{MUSIC_SERVER}/play_radio?url={urllib.parse.quote(station['url'])}&name={urllib.parse.quote(station['name'])}"
        result = urllib.request.urlopen(url, timeout=15).read().decode()
        return f"📻 Memutar {station['name']} di speaker STB/TV"
    except Exception as e:
        return f"Radio STB error: {e}"

def stop_radio_stb_http():
    """Hentikan radio di STB/TV."""
    try:
        url = f"{MUSIC_SERVER}/stop_radio"
        result = urllib.request.urlopen(url, timeout=5).read().decode()
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
    """Load token OAuth2 dari file."""
    if not os.path.exists(GOOGLE_TOKEN_FILE):
        return None
    with open(GOOGLE_TOKEN_FILE, 'r') as f:
        return json.load(f)

def _save_google_token(token_data):
    """Simpan token OAuth2 ke file."""
    with open(GOOGLE_TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)

def _refresh_google_token(token_data):
    """
    Refresh access token menggunakan refresh_token.
    Dipanggil otomatis jika access_token sudah expired.
    """
    if not token_data.get('refresh_token'):
        raise Exception("Tidak ada refresh_token. Jalankan google_auth.py dulu untuk login.")

    data = urllib.parse.urlencode({
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': token_data['refresh_token'],
        'grant_type': 'refresh_token'
    }).encode()

    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    with urllib.request.urlopen(req, timeout=10) as r:
        new_token = json.loads(r.read().decode())

    # Update token data, pertahankan refresh_token lama jika tidak ada yang baru
    token_data['access_token'] = new_token['access_token']
    token_data['expires_in'] = new_token.get('expires_in', 3600)
    token_data['token_expiry'] = (
        datetime.now(timezone.utc) + timedelta(seconds=new_token.get('expires_in', 3600))
    ).isoformat()
    if 'refresh_token' in new_token:
        token_data['refresh_token'] = new_token['refresh_token']

    _save_google_token(token_data)
    return token_data

def _get_valid_access_token():
    """
    Ambil access_token yang masih valid.
    Auto-refresh jika sudah expired.
    """
    token_data = _load_google_token()
    if not token_data:
        raise Exception(
            "Belum ada token Google. "
            "Jalankan: python google_auth.py\n"
            "Lalu ikuti instruksi untuk login."
        )

    # Cek apakah token sudah expired (dengan buffer 60 detik)
    expiry_str = token_data.get('token_expiry')
    if expiry_str:
        expiry = datetime.fromisoformat(expiry_str)
        now = datetime.now(timezone.utc)
        if expiry <= now + timedelta(seconds=60):
            print("Access token expired, refreshing...")
            token_data = _refresh_google_token(token_data)

    return token_data['access_token']

def _calendar_request(method, url, body=None):
    """Helper untuk request ke Google Calendar API."""
    access_token = _get_valid_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def _get_calendar_events(days_ahead=7, max_results=10):
    """
    Ambil event Google Calendar untuk N hari ke depan.
    Returns string hasil yang sudah diformat.
    """
    try:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            f"?timeMin={urllib.parse.quote(time_min)}"
            f"&timeMax={urllib.parse.quote(time_max)}"
            f"&maxResults={max_results}"
            "&singleEvents=true"
            "&orderBy=startTime"
        )

        result = _calendar_request('GET', url)
        items = result.get('items', [])

        if not items:
            return f"Tidak ada jadwal dalam {days_ahead} hari ke depan."

        # Format output
        lines = [f"📅 Jadwal {days_ahead} hari ke depan ({len(items)} event):"]
        for event in items:
            summary = event.get('summary', '(tanpa judul)')

            # Ambil waktu mulai (bisa seharian atau jam tertentu)
            start = event.get('start', {})
            if 'dateTime' in start:
                dt = datetime.fromisoformat(start['dateTime'])
                # Konversi ke WIB (UTC+7)
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
    """
    Tambah event baru ke Google Calendar.
    start_datetime: string ISO8601, misal "2025-04-21T09:00:00+07:00"
    end_datetime: opsional, default 1 jam setelah start
    """
    try:
        # Parse start time
        start_dt = datetime.fromisoformat(start_datetime)

        # Default end time: 1 jam setelah start
        if not end_datetime:
            end_dt = start_dt + timedelta(hours=1)
            end_datetime = end_dt.isoformat()

        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_datetime,
                "timeZone": "Asia/Jakarta"
            },
            "end": {
                "dateTime": end_datetime,
                "timeZone": "Asia/Jakarta"
            }
        }

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        result = _calendar_request('POST', url, body)

        event_link = result.get('htmlLink', '')
        return f"✅ Event '{summary}' berhasil ditambahkan ke Google Calendar!\nLink: {event_link}"

    except Exception as e:
        return f"Gagal tambah event: {e}"

async def get_calendar(days_ahead=7):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _get_calendar_events, days_ahead)

async def add_calendar_event(summary, start_datetime, end_datetime=None, description="", location=""):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor, _add_calendar_event,
        summary, start_datetime, end_datetime, description, location
    )


# ================= TTS STB =================
def tts_stb(text):
    try:
        clean = re.sub(r'[^\w\s,.!?%°\-]', '', text).strip()
        if not clean:
            return
        subprocess.Popen(
            ["termux-tts-speak", "-l", "id", "-p", "1.2", "-r", "1.0", clean],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"TTS error: {e}")

# ================= TELEGRAM STB BOT =================
stb_conversations = {}

def telegram_send(token, chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode())
            return result.get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

def telegram_edit(token, chat_id, message_id, text):
    """Edit pesan yang sudah terkirim — untuk update animasi thinking."""
    try:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        data = json.dumps({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json"
        })
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram edit error: {e}")

def telegram_typing(token, chat_id):
    """Kirim indikator mengetik ke Telegram."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        data = json.dumps({
            "chat_id": chat_id,
            "action": "typing"
        }).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json"
        })
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def telegram_get_updates(token, offset=0):
    try:
        url = (
            f"https://api.telegram.org/bot{token}/getUpdates"
            f"?timeout=30&offset={offset}"
        )
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"Telegram polling error: {e}")
        return {"ok": False, "result": []}

def _handle_stb_message(chat_id, user_text):
    # Animasi thinking — kirim pesan awal
    thinking_frames = ["⏳ Berpikir", "⏳ Berpikir.", "⏳ Berpikir..", "⏳ Berpikir..."]
    msg_id = telegram_send(TELEGRAM_STB_TOKEN, chat_id, thinking_frames[0])

    # Update animasi thinking sambil tunggu AI
    import threading
    stop_thinking = threading.Event()

    def animate_thinking():
        i = 1
        while not stop_thinking.is_set():
            stop_thinking.wait(0.8)
            # Cek lagi setelah wait — jangan edit kalau sudah di-stop
            if stop_thinking.is_set():
                break
            if msg_id:
                telegram_edit(TELEGRAM_STB_TOKEN, chat_id, msg_id, thinking_frames[i % len(thinking_frames)])
            i += 1

    t = threading.Thread(target=animate_thinking, daemon=True)
    t.start()

    try:
        if chat_id not in stb_conversations:
            stb_conversations[chat_id] = []
        history = stb_conversations[chat_id]
        history.append({"role": "user", "content": user_text})
        if len(history) > 10:
            history = history[-10:]
            stb_conversations[chat_id] = history

        ai_response = _openrouter_chat(history)
        history.append({"role": "assistant", "content": ai_response})

        # Stop animasi lalu edit ke respon final
        stop_thinking.set()
        t.join(timeout=1)

        if msg_id:
            telegram_edit(TELEGRAM_STB_TOKEN, chat_id, msg_id, ai_response)
        else:
            telegram_send(TELEGRAM_STB_TOKEN, chat_id, ai_response)

        tts_stb(ai_response)
        return ai_response

    except Exception as e:
        stop_thinking.set()
        t.join(timeout=1)
        error_msg = (
            "❌ <b>Gagal terhubung ke AI</b>\n\n"
            f"Error: <code>{str(e)[:200]}</code>\n\n"
            "Coba lagi beberapa saat."
        )
        if msg_id:
            telegram_edit(TELEGRAM_STB_TOKEN, chat_id, msg_id, error_msg)
        else:
            telegram_send(TELEGRAM_STB_TOKEN, chat_id, error_msg)
        print(f"Handle STB message error: {e}")
        return None

async def handle_telegram_stb():
    if not TELEGRAM_STB_TOKEN:
        print("TELEGRAM_STB_TOKEN tidak diset, Telegram STB bot tidak aktif")
        return
    print("Telegram STB bot aktif, menunggu pesan...")
    offset = 0
    loop = asyncio.get_event_loop()
    while True:
        try:
            result = await loop.run_in_executor(
                executor, telegram_get_updates, TELEGRAM_STB_TOKEN, offset
            )
            if result.get("ok"):
                for update in result.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    chat_id = message.get("chat", {}).get("id")
                    if not text or not chat_id:
                        continue
                    print(f"STB Bot [{chat_id}]: {text}")
                    if text == "/start":
                        telegram_send(
                            TELEGRAM_STB_TOKEN, chat_id,
                            "Halo! Saya Anggira di STB. Kirim pesan dan saya akan menjawab lewat speaker TV"
                        )
                        tts_stb("Halo! Saya siap membantu.")
                        continue
                    if text in ["/stop", "/stopm"]:
                        stop_result = stop_song_stb_http()
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_result)
                        tts_stb("Musik dihentikan.")
                        continue
                    if text in ["/stopradio", "/stopr"]:
                        stop_result = stop_radio_stb_http()
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_result)
                        tts_stb("Radio dihentikan.")
                        continue
                    if text.startswith("/radio "):
                        station = text[7:].strip()
                        radio_result = play_radio_stb_http(station)
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, radio_result)
                        tts_stb(f"Memutar radio {station}")
                        continue
                    if text == "/radiolist":
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, list_radio_stations())
                        continue
                    # Kirim typing indicator dulu
                    await loop.run_in_executor(
                        executor, telegram_typing, TELEGRAM_STB_TOKEN, chat_id
                    )
                    await loop.run_in_executor(
                        executor, _handle_stb_message, chat_id, text
                    )
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f"Telegram 409 Conflict - ada instance lain, tunggu 10 detik...")
                await asyncio.sleep(10)
            elif e.code == 429:
                print(f"Telegram 429 Too Many Requests, tunggu 30 detik...")
                await asyncio.sleep(30)
            else:
                print(f"Telegram HTTP error {e.code}: {e.reason}")
                await asyncio.sleep(5)
        except Exception as e:
            print(f"Telegram STB loop error: {e}")
            await asyncio.sleep(5)

# ================= MCP =================
async def handle_mcp():
    async with websockets.connect(MCP_ENDPOINT) as ws:
        async for message in ws:
            data = json.loads(message)
            method = data.get("method", "")
            msg_id = data.get("id")

            if method == "initialize":
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"protocolVersion": "2024-11-05"}
                }))

            elif method == "tools/list":
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {"name": "lamp_on"},
                            {"name": "lamp_off"},
                            {"name": "news"},
                            {"name": "weather"},
                            {"name": "time"},
                            {"name": "sensor_rumah"},
                            {"name": "get_schedule"},
                            {"name": "set_schedule"},
                            {
                                "name": "play_song",
                                "description": "Putar lagu dari internet via speaker ESP32",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "song": {"type": "string"},
                                        "artist": {"type": "string"}
                                    },
                                    "required": ["song"]
                                }
                            },
                            {
                                "name": "play_song_stb",
                                "description": "Putar lagu langsung di speaker STB/TV ruangan. Gunakan jika user menyebut STB, TV, speaker ruangan, atau speaker besar.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "song": {"type": "string", "description": "Judul lagu"},
                                        "artist": {"type": "string", "description": "Nama artis (opsional)"}
                                    },
                                    "required": ["song"]
                                }
                            },
                            {
                                "name": "stop_song_stb",
                                "description": "Hentikan musik yang sedang diputar di speaker STB/TV",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "play_radio",
                                "description": "Putar internet radio lewat speaker ESP32. Gunakan jika user tidak menyebut STB/TV.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "station": {
                                            "type": "string",
                                            "description": "Nama atau kata kunci stasiun radio, contoh: prambors, hardrock, gen, bbc, jazz24"
                                        }
                                    },
                                    "required": ["station"]
                                }
                            },
                            {
                                "name": "play_radio_stb",
                                "description": "Putar internet radio di speaker STB/TV ruangan. Gunakan jika user menyebut STB, TV, atau speaker ruangan.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "station": {
                                            "type": "string",
                                            "description": "Nama atau kata kunci stasiun radio, contoh: prambors, hardrock, gen, bbc, jazz24"
                                        }
                                    },
                                    "required": ["station"]
                                }
                            },
                            {
                                "name": "stop_radio",
                                "description": "Hentikan radio yang sedang diputar di speaker ESP32",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "stop_radio_stb",
                                "description": "Hentikan radio yang sedang diputar di speaker STB/TV",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "list_radio",
                                "description": "Tampilkan daftar semua stasiun internet radio yang tersedia",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "get_calendar",
                                "description": "Lihat jadwal Google Calendar beberapa hari ke depan",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "days_ahead": {
                                            "type": "integer",
                                            "description": "Berapa hari ke depan yang ingin dilihat (default: 7)"
                                        }
                                    }
                                }
                            },
                            {
                                "name": "add_calendar_event",
                                "description": "Tambah event/jadwal baru ke Google Calendar",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {
                                            "type": "string",
                                            "description": "Nama/judul event"
                                        },
                                        "start_datetime": {
                                            "type": "string",
                                            "description": "Waktu mulai format ISO8601, contoh: 2025-04-21T09:00:00+07:00"
                                        },
                                        "end_datetime": {
                                            "type": "string",
                                            "description": "Waktu selesai format ISO8601 (opsional, default +1 jam)"
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Deskripsi event (opsional)"
                                        },
                                        "location": {
                                            "type": "string",
                                            "description": "Lokasi event (opsional)"
                                        }
                                    },
                                    "required": ["summary", "start_datetime"]
                                }
                            }
                        ]
                    }
                }))

            elif method == "tools/call":
                tool = data["params"]["name"]

                if tool == "lamp_on":
                    result = await lamp_on()
                elif tool == "lamp_off":
                    result = await lamp_off()
                elif tool == "news":
                    result = await get_news()
                elif tool == "weather":
                    result = await get_weather(DEFAULT_CITY)
                elif tool == "time":
                    result = datetime.now().strftime("%H:%M")
                elif tool == "sensor_rumah":
                    result = await get_sensor_rumah()
                elif tool == "get_schedule":
                    result = await get_schedule()
                elif tool == "set_schedule":
                    args = data["params"].get("arguments", {})
                    result = await set_schedule(
                        args.get("on", "18:00"),
                        args.get("off", "06:00")
                    )
                elif tool == "play_song":
                    args = data["params"].get("arguments", {})
                    result = await play_song(
                        args.get("song", ""),
                        args.get("artist", "")
                    )
                elif tool == "play_song_stb":
                    args = data["params"].get("arguments", {})
                    result = await play_song_stb(
                        args.get("song", ""),
                        args.get("artist", "")
                    )
                elif tool == "stop_song_stb":
                    result = await stop_song_stb()
                elif tool == "play_radio":
                    args = data["params"].get("arguments", {})
                    result = await play_radio(args.get("station", ""))
                elif tool == "play_radio_stb":
                    args = data["params"].get("arguments", {})
                    result = await play_radio_stb(args.get("station", ""))
                elif tool == "stop_radio":
                    result = await stop_radio()
                elif tool == "stop_radio_stb":
                    result = await stop_radio_stb()
                elif tool == "list_radio":
                    result = await get_radio_list()
                elif tool == "get_calendar":
                    args = data["params"].get("arguments", {})
                    days = int(args.get("days_ahead", 7))
                    result = await get_calendar(days)
                elif tool == "add_calendar_event":
                    args = data["params"].get("arguments", {})
                    result = await add_calendar_event(
                        summary=args.get("summary", ""),
                        start_datetime=args.get("start_datetime", ""),
                        end_datetime=args.get("end_datetime"),
                        description=args.get("description", ""),
                        location=args.get("location", "")
                    )
                else:
                    result = "Tool tidak dikenal"

                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": str(result)}
                        ]
                    }
                }))

# ================= MAIN =================
async def main():
    print("Anggira FULL + MUSIC + RADIO + SENSOR + JADWAL + GOOGLE CALENDAR + TELEGRAM STB")
    await asyncio.gather(
        handle_mcp(),
        handle_telegram_stb()
    )

if __name__ == "__main__":
    asyncio.run(main())
