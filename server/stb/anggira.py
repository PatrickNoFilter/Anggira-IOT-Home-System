import asyncio
import websockets
import json
import urllib.request
import urllib.error
from datetime import datetime
import threading

# Import dari services.py
from services import (
    executor, _openrouter_chat,
    play_song, play_song_stb, stop_song_stb,
    play_song_stb_http, stop_song_stb_http,
    play_radio, play_radio_stb, stop_radio, stop_radio_stb,
    play_radio_stb_http, stop_radio_stb_http, list_radio_stations,
    lamp_on, lamp_off, get_sensor_rumah, get_schedule, set_schedule,
    get_weather, get_weather_detail, get_news, get_time,
    get_calendar, add_calendar_event,
    wikipedia, kurs, saham, indeks_saham, kalkulator,
    web_search, world_time, crypto,
    tts_stb, TELEGRAM_STB_TOKEN, DEFAULT_CITY, MCP_ENDPOINT,
    get_vatican_news,
    get_news_topik,
    set_reminder_v2, get_alarms, cancel_alarm,
    start_scheduler,
    play_playlist_stb, play_playlist_stb_http,
    playlist_next, playlist_next_http,
    playlist_stop, playlist_stop_http,
    playlist_status, playlist_status_http,
    list_playlists, list_playlists_http,
)

# ================= TELEGRAM BOT =================
stb_conversations = {}

def telegram_send(token, chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode())
            return result.get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

def telegram_edit(token, chat_id, message_id, text):
    try:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        data = json.dumps({"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram edit error: {e}")

def telegram_typing(token, chat_id):
    try:
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        data = json.dumps({"chat_id": chat_id, "action": "typing"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def telegram_get_updates(token, offset=0):
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=30&offset={offset}"
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"Telegram polling error: {e}")
        return {"ok": False, "result": []}

def _handle_stb_message(chat_id, user_text):
    thinking_frames = ["⏳ Berpikir", "⏳ Berpikir.", "⏳ Berpikir..", "⏳ Berpikir..."]
    msg_id = telegram_send(TELEGRAM_STB_TOKEN, chat_id, thinking_frames[0])
    stop_thinking = threading.Event()

    def animate_thinking():
        i = 1
        while not stop_thinking.is_set():
            stop_thinking.wait(0.8)
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
        error_msg = f"❌ <b>Gagal terhubung ke AI</b>\n\nError: <code>{str(e)[:200]}</code>\n\nCoba lagi."
        if msg_id:
            telegram_edit(TELEGRAM_STB_TOKEN, chat_id, msg_id, error_msg)
        else:
            telegram_send(TELEGRAM_STB_TOKEN, chat_id, error_msg)
        return None

async def handle_telegram_stb():
    if not TELEGRAM_STB_TOKEN:
        print("TELEGRAM_STB_TOKEN tidak diset")
        return
    print("Telegram STB bot aktif...")
    offset = 0
    loop = asyncio.get_event_loop()
    while True:
        try:
            result = await loop.run_in_executor(executor, telegram_get_updates, TELEGRAM_STB_TOKEN, offset)
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
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, "Halo! Saya Anggira. Kirim pesan dan saya akan menjawab lewat speaker TV")
                        tts_stb("Halo! Saya siap membantu.")
                        continue
                    if text in ["/stop", "/stopm"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_song_stb_http())
                        tts_stb("Musik dihentikan.")
                        continue
                    if text in ["/stopradio", "/stopr"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_radio_stb_http())
                        tts_stb("Radio dihentikan.")
                        continue
                    if text.startswith("/radio "):
                        station = text[7:].strip()
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, play_radio_stb_http(station))
                        tts_stb(f"Memutar radio {station}")
                        continue
                    if text == "/radiolist":
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, list_radio_stations())
                        continue
                    if text.startswith("/playlist "):
                        parts = text[10:].strip().split()
                        pname = parts[0] if parts else ""
                        shuf = len(parts) > 1 and parts[1].lower() in ("shuffle", "acak")
                        msg = play_playlist_stb_http(pname, shuf)
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, msg)
                        continue
                    if text in ["/playlistnext", "/pnext"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, playlist_next_http())
                        continue
                    if text in ["/playliststop", "/pstop"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, playlist_stop_http())
                        tts_stb("Playlist dihentikan.")
                        continue
                    if text in ["/playliststatus", "/pstatus"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, playlist_status_http())
                        continue
                    if text in ["/playlists", "/listplaylist"]:
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, list_playlists_http())
                        continue

                    # ── Keyword detection (bahasa natural) ──────────
                    tl = text.lower()

                    # Stop musik
                    if any(k in tl for k in ["stop musik", "hentikan musik", "matikan musik", "stop lagu", "hentikan lagu"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_song_stb_http())
                        tts_stb("Musik dihentikan.")
                        continue

                    # Stop radio
                    if any(k in tl for k in ["stop radio", "hentikan radio", "matikan radio", "radio stop", "radio off"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, stop_radio_stb_http())
                        tts_stb("Radio dihentikan.")
                        continue

                    # Stop playlist
                    if any(k in tl for k in ["stop playlist", "hentikan playlist", "matikan playlist"]):
                        msg = playlist_stop_http()
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, msg)
                        tts_stb("Playlist dihentikan.")
                        continue

                    # Skip lagu
                    if any(k in tl for k in ["skip", "lagu berikutnya", "next lagu", "lanjut lagu"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, playlist_next_http())
                        continue

                    # Status playlist
                    if any(k in tl for k in ["status playlist", "lagu apa", "sedang diputar", "playlist status"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, playlist_status_http())
                        continue

                    # List playlist
                    if any(k in tl for k in ["daftar playlist", "list playlist", "playlist apa saja", "ada playlist apa"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, list_playlists_http())
                        continue

                    # List radio
                    if any(k in tl for k in ["daftar radio", "list radio", "radio apa saja", "ada radio apa"]):
                        telegram_send(TELEGRAM_STB_TOKEN, chat_id, list_radio_stations())
                        continue

                    # Putar radio STB
                    for rk in ["putar radio ", "play radio ", "radio "]:
                        if rk in tl:
                            idx = tl.index(rk) + len(rk)
                            station = text[idx:].strip().split()[0] if text[idx:].strip() else ""
                            if station:
                                msg = play_radio_stb_http(station)
                                telegram_send(TELEGRAM_STB_TOKEN, chat_id, msg)
                                tts_stb(msg)
                            break
                    else:
                        # Putar playlist STB
                        matched_pl = None
                        for pk in ["putar playlist ", "play playlist ", "playlist "]:
                            if pk in tl:
                                matched_pl = pk
                                break
                        if matched_pl:
                            idx = tl.index(matched_pl) + len(matched_pl)
                            parts2 = text[idx:].strip().split()
                            pname2 = parts2[0] if parts2 else ""
                            shuf2  = len(parts2) > 1 and parts2[1].lower() in ("shuffle", "acak")
                            if pname2:
                                msg = play_playlist_stb_http(pname2, shuf2)
                                telegram_send(TELEGRAM_STB_TOKEN, chat_id, msg)
                                tts_stb(msg)
                        else:
                            # Putar lagu STB
                            matched_play = None
                            for sk in ["putar ", "play ", "mainkan ", "nyalakan lagu "]:
                                if tl.startswith(sk) or (" " + sk) in tl:
                                    matched_play = sk
                                    break
                            if matched_play and "radio" not in tl and "playlist" not in tl:
                                idx = tl.find(matched_play) + len(matched_play)
                                query = text[idx:].strip()
                                if query:
                                    msg = play_song_stb_http(query)
                                    telegram_send(TELEGRAM_STB_TOKEN, chat_id, msg)
                                    tts_stb(msg)
                            else:
                                # Fallback ke AI
                                await loop.run_in_executor(executor, telegram_typing, TELEGRAM_STB_TOKEN, chat_id)
                                await loop.run_in_executor(executor, _handle_stb_message, chat_id, text)
                        continue

                    continue
        except urllib.error.HTTPError as e:
            if e.code == 409:
                await asyncio.sleep(10)
            elif e.code == 429:
                await asyncio.sleep(30)
            else:
                await asyncio.sleep(5)
        except Exception as e:
            print(f"Telegram loop error: {e}")
            await asyncio.sleep(5)

# ================= STREAM SERVER HELPER =================
async def _call_stream_server(path: str) -> str:
    import urllib.request as _ur
    try:
        url = f"http://127.0.0.1:8080{path}"
        def _fetch():
            with _ur.urlopen(url, timeout=10) as r:
                return r.read().decode()
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(executor, _fetch)
        d = json.loads(data)
        if "error" in d:
            return f"Error: {d['error']}"
        if d.get("status") == "playing" and d.get("playlist"):
            return f"Memutar playlist {d['playlist']} ({d['total']} lagu)"
        if d.get("status") == "stopped":
            return "Playlist dihentikan"
        if d.get("status") == "skipped":
            return "Lanjut ke lagu berikutnya"
        if isinstance(d, dict) and not any(k in d for k in ["status","error","playing"]):
            names = list(d.keys())
            if not names:
                return "Belum ada playlist. Buat dulu di dashboard."
            return "Playlist tersedia: " + ", ".join(names)
        return json.dumps(d)
    except Exception as e:
        return f"Stream server error: {e}"


# ================= MCP SERVER =================
async def handle_mcp():
    if not MCP_ENDPOINT:
        print("MCP_ENDPOINT tidak diset")
        return

    retry_delay = 3   # detik awal sebelum reconnect
    max_delay   = 60  # maksimum delay

    while True:
        try:
            print(f"MCP: mencoba connect ke {MCP_ENDPOINT}...")
            async with websockets.connect(
                MCP_ENDPOINT,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                additional_headers={
                    "User-Agent": "AnggiraHome/1.0",
                }
            ) as ws:
                print("MCP: terhubung ✓")
                retry_delay = 3  # reset setelah connect berhasil

                # Kirim initialize request ke server (client-initiated handshake)
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "anggira", "version": "1.0"}
                    }
                }))
                print("MCP: initialize dikirim, menunggu respons...")

                async for message in ws:
                    try:
                        data = json.loads(message)
                        method = data.get("method", "")
                        msg_id = data.get("id")

                        # Log semua pesan masuk untuk debug
                        print(f"MCP ← {method or "response"} id={msg_id}")

                        # Respons dari server atas initialize yang kita kirim (id=1)
                        if "result" in data and not method and msg_id == 1:
                            print(f"MCP: initialize OK — {data.get("result", {})}")
                            await ws.send(json.dumps({
                                "jsonrpc": "2.0",
                                "method": "notifications/initialized",
                                "params": {}
                            }))
                            print("MCP: siap menerima perintah ✓")
                            continue

                        if method == "initialize":
                            await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05"}}))

                        # Abaikan notifications dari server
                        elif method and method.startswith("notifications/"):
                            pass

                        elif method == "tools/list":
                            await ws.send(json.dumps({
                                "jsonrpc": "2.0", "id": msg_id,
                                "result": {
                                    "tools": [
                                        {"name": "lamp_on"}, {"name": "lamp_off"}, {"name": "news"}, {"name": "weather"}, {"name": "time"},
                                        {"name": "sensor_rumah"}, {"name": "get_schedule"}, {"name": "set_schedule"},
                                        {"name": "play_song", "description": "Putar lagu via speaker ESP32", "inputSchema": {"type": "object", "properties": {"song": {"type": "string"}, "artist": {"type": "string"}}, "required": ["song"]}},
                                        {"name": "play_song_stb", "description": "Putar lagu di STB/TV", "inputSchema": {"type": "object", "properties": {"song": {"type": "string"}, "artist": {"type": "string"}}, "required": ["song"]}},
                                        {"name": "stop_song_stb", "description": "Hentikan musik STB", "inputSchema": {"type": "object", "properties": {}}},
                                        {"name": "play_radio", "description": "Putar radio via ESP32", "inputSchema": {"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]}},
                                        {"name": "play_radio_stb", "description": "Putar radio di STB/TV", "inputSchema": {"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]}},
                                        {"name": "stop_radio", "description": "Hentikan radio ESP32", "inputSchema": {"type": "object", "properties": {}}},
                                        {"name": "stop_radio_stb", "description": "Hentikan radio STB", "inputSchema": {"type": "object", "properties": {}}},
                                        {"name": "list_radio", "description": "Daftar radio", "inputSchema": {"type": "object", "properties": {}}},
                                        {"name": "get_calendar", "description": "Lihat jadwal", "inputSchema": {"type": "object", "properties": {"days_ahead": {"type": "integer"}}}},
                                        {"name": "wikipedia", "description": "Cari informasi dari Wikipedia. Gunakan untuk pertanyaan faktual, sejarah, tokoh, sains, geografi, dll.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Topik yang dicari"}, "lang": {"type": "string", "description": "Bahasa: id atau en (default: id)"}}, "required": ["query"]}},
                                        {"name": "web_search", "description": "Cari informasi terkini di internet. Gunakan untuk berita terbaru atau info yang tidak ada di Wikipedia.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
                                        {"name": "kurs", "description": "Cek kurs/nilai tukar mata uang realtime. Contoh: USD ke IDR, EUR ke IDR.", "inputSchema": {"type": "object", "properties": {"from_currency": {"type": "string", "description": "Mata uang asal (USD, EUR, SGD, JPY, dll)"}, "to_currency": {"type": "string", "description": "Mata uang tujuan (IDR, USD, dll)"}, "amount": {"type": "string", "description": "Jumlah (default: 1)"}}, "required": ["from_currency", "to_currency"]}},
                                        {"name": "saham", "description": "Cek harga saham atau indeks pasar. Gunakan simbol: ^JKSE (IHSG), ^GSPC (S&P500), ^IXIC (Nasdaq), BBCA.JK, TLKM.JK, AAPL, GOOGL, dll.", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "description": "Simbol saham atau indeks"}}, "required": ["symbol"]}},
                                        {"name": "indeks_saham", "description": "Cek indeks pasar saham dengan nama populer: IHSG, S&P500, Nasdaq, Dow, Nikkei, HangSeng, dll.", "inputSchema": {"type": "object", "properties": {"nama": {"type": "string", "description": "Nama indeks: IHSG, S&P500, Nasdaq, Dow, Nikkei, HangSeng, FTSE, DAX, dll."}}, "required": ["nama"]}},
                                        {"name": "crypto", "description": "Cek harga mata uang kripto dalam USD dan IDR. Contoh: BTC, ETH, BNB, SOL, XRP, DOGE.", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "description": "Simbol kripto: BTC, ETH, BNB, SOL, XRP, DOGE, ADA, dll."}}, "required": ["symbol"]}},
                                        {"name": "kalkulator", "description": "Hitung ekspresi matematika. Mendukung +, -, *, /, ^, sin, cos, tan, sqrt, log, log10, exp, factorial, pi, e.", "inputSchema": {"type": "object", "properties": {"expression": {"type": "string", "description": "Ekspresi: 2^10, sqrt(144), sin(pi/2), log(100), 5!"}}, "required": ["expression"]}},
                                        {"name": "world_time", "description": "Cek waktu saat ini di kota atau negara lain.", "inputSchema": {"type": "object", "properties": {"timezone": {"type": "string", "description": "Nama kota (Tokyo, London, New York, Dubai, Singapore, Mekah) atau timezone IANA (Asia/Tokyo, Europe/London)"}}, "required": ["timezone"]}},
                                        {"name": "cuaca_detail", "description": "Cuaca lengkap suatu kota: suhu, kelembaban, angin, tekanan, waktu matahari terbit/terbenam.", "inputSchema": {"type": "object", "properties": {"city": {"type": "string", "description": "Nama kota"}}, "required": ["city"]}},
                                        
                                        {"name": "add_calendar_event", "description": "Tambah event", "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}, "start_datetime": {"type": "string"}, "end_datetime": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["summary", "start_datetime"]}},
                                        {"name": "vatican_news", "description": "Berita terbaru dari Vatican News. Gunakan untuk berita Paus, Gereja Katolik, dan Vatikan. Parameter lang: id (Indonesia, default) atau en (Inggris). Parameter translate: true untuk terjemahkan berita Inggris ke Indonesia. Parameter limit: jumlah berita 1-10 (default 5).", "inputSchema": {"type": "object", "properties": {"lang": {"type": "string", "description": "Bahasa feed: id atau en (default: id)"}, "translate": {"type": "boolean", "description": "Terjemahkan ke Indonesia (hanya berlaku jika lang=en)"}, "limit": {"type": "integer", "description": "Jumlah berita (1-10, default 5)"}}, "required": []}},
                                        {"name": "berita_topik", "description": "Cari berita terbaru berdasarkan topik bebas via Google News. Gunakan untuk: berita ekonomi, harga minyak, teknologi, olahraga, politik, hiburan, atau topik apapun yang diminta user. Parameter topik: kata kunci berita (contoh: harga minyak dunia, AI teknologi, ekonomi Indonesia). Parameter lang: id (default) atau en. Parameter limit: jumlah berita 1-10 (default 5).", "inputSchema": {"type": "object", "properties": {"topik": {"type": "string", "description": "Topik atau kata kunci berita"}, "lang": {"type": "string", "description": "Bahasa: id atau en"}, "limit": {"type": "integer", "description": "Jumlah berita (1-10)"}}, "required": ["topik"]}},
                            {"name": "pengingat_v2", "description": "Setel pengingat dengan timer nyata — ESP32 akan dibangunkan otomatis dan mengucapkan pesan saat waktunya tiba. Opsional: tambahkan ke Google Calendar. Gunakan ini untuk semua permintaan pengingat/alarm.", "inputSchema": {"type": "object", "properties": {"menit": {"type": "string", "description": "Jumlah menit hingga alarm berbunyi (1-1440)"}, "pesan": {"type": "string", "description": "Pesan pengingat yang akan diucapkan"}, "tambah_kalender": {"type": "boolean", "description": "Tambahkan ke Google Calendar (default: false)"}}, "required": ["menit", "pesan"]}},
                            {"name": "lihat_pengingat", "description": "Tampilkan semua pengingat/alarm yang sedang aktif.", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "play_playlist", "description": "Putar playlist musik berdasarkan nama pendek. Contoh: santai, pagi, rohani.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "shuffle": {"type": "boolean"}}, "required": ["name"]}},
                            {"name": "playlist_next", "description": "Skip ke lagu berikutnya.", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "playlist_stop", "description": "Stop playlist.", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "playlist_status", "description": "Cek lagu yang sedang diputar di playlist.", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "list_playlists", "description": "Tampilkan semua nama playlist tersedia.", "inputSchema": {"type": "object", "properties": {}}},
                            {"name": "batal_pengingat", "description": "Batalkan pengingat berdasarkan kata kunci dalam pesan.", "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string", "description": "Kata kunci dari pesan pengingat yang akan dibatalkan"}}, "required": ["keyword"]}}
                                    ]
                                }
                            }))

                        elif method == "tools/call":
                            tool = data["params"]["name"]
                            args = data["params"].get("arguments", {})

                            if tool == "lamp_on": result = await lamp_on()
                            elif tool == "lamp_off": result = await lamp_off()
                            elif tool == "news": result = await get_news()
                            elif tool == "weather": result = await get_weather(DEFAULT_CITY)
                            elif tool == "time": result = await get_time()
                            elif tool == "sensor_rumah": result = await get_sensor_rumah()
                            elif tool == "get_schedule": result = await get_schedule()
                            elif tool == "set_schedule": result = await set_schedule(args.get("on", "18:00"), args.get("off", "06:00"))
                            elif tool == "play_song": result = await play_song(args.get("song", ""), args.get("artist", ""))
                            elif tool == "play_song_stb": result = await play_song_stb(args.get("song", ""), args.get("artist", ""))
                            elif tool == "stop_song_stb": result = await stop_song_stb()
                            elif tool == "play_radio": result = await play_radio(args.get("station", ""))
                            elif tool == "play_radio_stb": result = await play_radio_stb(args.get("station", ""))
                            elif tool == "stop_radio": result = await stop_radio()
                            elif tool == "stop_radio_stb": result = await stop_radio_stb()
                            elif tool == "list_radio": result = await get_radio_list()
                            elif tool == "get_calendar": result = await get_calendar(int(args.get("days_ahead", 7)))
                            elif tool == "add_calendar_event": result = await add_calendar_event(args.get("summary", ""), args.get("start_datetime", ""), args.get("end_datetime"), args.get("description", ""), args.get("location", ""))
                            elif tool == "wikipedia": result = await wikipedia(args.get("query", ""), args.get("lang", "id"))
                            elif tool == "web_search": result = await web_search(args.get("query", ""))
                            elif tool == "kurs": result = await kurs(args.get("from_currency", "USD"), args.get("to_currency", "IDR"), float(args.get("amount", 1)))
                            elif tool == "saham": result = await saham(args.get("symbol", ""))
                            elif tool == "indeks_saham": result = await indeks_saham(args.get("nama", ""))
                            elif tool == "crypto": result = await crypto(args.get("symbol", "BTC"))
                            elif tool == "kalkulator": result = await kalkulator(args.get("expression", ""))
                            elif tool == "world_time": result = await world_time(args.get("timezone", "Asia/Jakarta"))
                            elif tool == "cuaca_detail": result = await get_weather_detail(args.get("city", DEFAULT_CITY))
                            elif tool == "vatican_news": result = await get_vatican_news(args.get("lang", "id"), args.get("translate", False), int(args.get("limit", 5)))
                            elif tool == "berita_topik": result = await get_news_topik(args.get("topik", ""), args.get("lang", "id"), int(args.get("limit", 5)))
                            elif tool == "pengingat_v2": result = await set_reminder_v2(args.get("menit", 5), args.get("pesan", "Pengingat"), args.get("tambah_kalender", False))
                            elif tool == "lihat_pengingat": result = await get_alarms()
                            elif tool == "batal_pengingat": result = await cancel_alarm(args.get("keyword", ""))
                            elif tool == "play_playlist":
                                name = args.get("name", "")
                                shuf = args.get("shuffle", False)
                                result = await play_playlist_stb(name, shuf)
                            elif tool == "playlist_next":
                                result = await playlist_next()
                            elif tool == "playlist_stop":
                                result = await playlist_stop()
                            elif tool == "playlist_status":
                                result = await playlist_status()
                            elif tool == "list_playlists":
                                result = await list_playlists()
                            else: result = "Tool tidak dikenal"

                            await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(result)}]}}))

                    except Exception as e:
                        print(f"MCP: error proses pesan: {e}")

        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError, ConnectionRefusedError) as e:
            print(f"MCP: koneksi terputus ({e}), reconnect dalam {retry_delay}s...")
        except Exception as e:
            print(f"MCP: error tak terduga ({e}), reconnect dalam {retry_delay}s...")

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_delay)  # exponential backoff

# ================= MAIN =================
async def main():
    print("Anggira IOT Home System")
    start_scheduler()
    await asyncio.gather(handle_mcp(), handle_telegram_stb())

if __name__ == "__main__":
    asyncio.run(main())