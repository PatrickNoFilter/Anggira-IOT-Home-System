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
    get_weather, get_news, get_time,
    get_calendar, add_calendar_event,
    tts_stb, TELEGRAM_STB_TOKEN, DEFAULT_CITY, MCP_ENDPOINT
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
                    await loop.run_in_executor(executor, telegram_typing, TELEGRAM_STB_TOKEN, chat_id)
                    await loop.run_in_executor(executor, _handle_stb_message, chat_id, text)
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

# ================= MCP SERVER =================
async def handle_mcp():
    if not MCP_ENDPOINT:
        print("MCP_ENDPOINT tidak diset")
        return

    async with websockets.connect(MCP_ENDPOINT) as ws:
        async for message in ws:
            data = json.loads(message)
            method = data.get("method", "")
            msg_id = data.get("id")

            if method == "initialize":
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05"}}))

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
                            {"name": "add_calendar_event", "description": "Tambah event", "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}, "start_datetime": {"type": "string"}, "end_datetime": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["summary", "start_datetime"]}}
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
                else: result = "Tool tidak dikenal"

                await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(result)}]}}))

# ================= MAIN =================
async def main():
    print("Anggira IOT Home System")
    await asyncio.gather(handle_mcp(), handle_telegram_stb())

if __name__ == "__main__":
    asyncio.run(main())
