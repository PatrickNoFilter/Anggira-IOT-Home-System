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
