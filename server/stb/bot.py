import asyncio
"""
Xiaozhi Wake Bot — Telegram Bot untuk STB Android (Termux)
===========================================================
ESP32 MAC  : 3c:dc:75:6b:f9:ec
Wake Word  : Hi, ESP (model wn9_hiesp)

Cara pakai:
    python ~/xiaozhi-bot/bot.py

Dependensi:
    pip install python-telegram-bot

Env variables (.bashrc):
    export TELEGRAM_BOT_TOKEN="token_xiaozhi_bot"
    export ESP32_IP="192.168.1.222"
    export ESP32_PORT="80"
    export TELEGRAM_ALLOWED_USER_ID="8407417185"
"""

import json
import logging
import os
import random
import time
import urllib.request
import urllib.error
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# ─────────────────────────────────────────────────────────────
#  CONFIG — semua dari env variable, tidak ada hardcode
# ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

# IP & Port ESP32 dari env, fallback ke default
ESP32_IP   = os.environ.get('ESP32_IP', '192.168.1.222')
ESP32_PORT = int(os.environ.get('ESP32_PORT', '80'))

WAKE_URL   = f"http://{ESP32_IP}:{ESP32_PORT}/wake"
STATUS_URL = f"http://{ESP32_IP}:{ESP32_PORT}/status"
SAY_URL      = f"http://{ESP32_IP}:{ESP32_PORT}/say"
RESPONSE_URL = f"http://{ESP32_IP}:{ESP32_PORT}/response"
STT_URL      = f"http://{ESP32_IP}:{ESP32_PORT}/stt"
WAKE_WORD  = os.environ.get('WAKE_WORD', 'Hi ESP')

# Path config dashboard — dibaca setiap cek chime agar perubahan langsung berlaku
HOME        = os.path.expanduser("~")
CONFIG_FILE = os.path.join(HOME, "anggira", "dashboard_config.json")

DEFAULT_CHIME = {
    "chime_enabled": True,
    "chime_text":    "jam berapa sekarang dan kapan hujan di cebongan salatiga",
    "chime_hours":   list(range(6, 22)),
    "quotes_enabled": True,
    "quotes_hours":  list(range(6, 22)),
}

def load_chime_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                c = json.load(f)
            for k, v in DEFAULT_CHIME.items():
                c.setdefault(k, v)
            return c
        except Exception as e:
            logger_chime.warning("Gagal baca config: %s", e)
    return DEFAULT_CHIME.copy()

# Whitelist dari env — format: "123456789,987654321"
_allowed_str = os.environ.get('TELEGRAM_ALLOWED_USER_ID', '')
ALLOWED_CHAT_IDS: list[int] = (
    [int(x.strip()) for x in _allowed_str.split(',') if x.strip()]
    if _allowed_str else []
)
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger       = logging.getLogger("WakeBot")
logger_chime = logging.getLogger("Chime")


# ── HTTP ke ESP32 ─────────────────────────────────────────────

def send_wake_http() -> bool:
    """Kirim POST ke ESP32 HTTP wake server."""
    try:
        payload = json.dumps({"wake_word": WAKE_WORD}).encode()
        req = urllib.request.Request(
            WAKE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read().decode())
            logger.info("ESP32 response: %s", resp)
            return resp.get("status") == "ok"
    except urllib.error.URLError as e:
        logger.error("Gagal connect ke ESP32: %s", e.reason)
        return False
    except Exception as e:
        logger.error("Error kirim wake: %s", e)
        return False

def send_say_http(text: str) -> bool:
    """Kirim teks perintah ke Xiaozhi AI via /say endpoint."""
    try:
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            SAY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read().decode())
            logger.info("ESP32 /say response: %s", resp)
            return resp.get("status") == "ok"
    except urllib.error.URLError as e:
        logger.error("Gagal connect ke ESP32 /say: %s", e.reason)
        return False
    except Exception as e:
        logger.error("Error kirim say: %s", e)
        return False




async def poll_response(timeout: int = 20, interval: float = 0.8) -> str:
    """
    Poll /response ESP32 secara async — tidak memblokir event loop.
    Kumpulkan semua kalimat TTS hingga idle IDLE_AFTER detik tanpa kalimat baru.
    """
    import time as _time
    IDLE_AFTER = 3.0
    collected  = []
    last_new   = None
    deadline   = _time.monotonic() + timeout
    loop       = asyncio.get_running_loop()

    while _time.monotonic() < deadline:
        try:
            # HTTP request di executor agar tidak block event loop
            def _fetch():
                with urllib.request.urlopen(RESPONSE_URL, timeout=4) as r:
                    return json.loads(r.read().decode())

            data = await loop.run_in_executor(None, _fetch)

            if data.get("new") and data.get("text"):
                txt = data["text"].strip()
                if txt and txt not in collected:
                    collected.append(txt)
                    last_new = _time.monotonic()
                    logger.info("poll[%d]: %s", len(collected), txt[:60])
            else:
                if collected and last_new and (_time.monotonic() - last_new) >= IDLE_AFTER:
                    break

        except Exception as e:
            logger.warning("poll_response error: %s", e)

        await asyncio.sleep(interval)

    return " ".join(collected) if collected else ""

def check_esp32_status() -> str:
    """Cek status ESP32."""
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
            resp = json.loads(r.read().decode())
            return f"✅ Online — `{resp.get('device', 'xiaozhi')}`"
    except Exception:
        return "❌ Offline / tidak terjangkau"


# ── Telegram Handlers ─────────────────────────────────────────

WAKE_TRIGGERS = {
    "hi, esp", "hi esp", "hiesp",
    "wake esp", "bangunkan esp", "esp bangun",
    "wake", "bangun",
}

def is_allowed(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return chat_id in ALLOWED_CHAT_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info("/start dari chat_id=%d", chat_id)
    await update.message.reply_text(
        "🤖 *Xiaozhi Wake Bot*\n"
        f"ESP32: `{ESP32_IP}:{ESP32_PORT}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *WAKE WORD*\n"
        "`Hi ESP` · `Hi, ESP` · `hiesp`\n"
        "`wake` · `bangun` · `wake esp` · `bangunkan esp`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💬 *BICARA KE XIAOZHI*\n"
        "Setelah Xiaozhi bangun, kirim pesan apapun\n"
        "Contoh: `nyalakan lampu`, `cuaca hari ini`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🏠 *RUMAH PINTAR*\n"
        "`nyalakan lampu` · `matikan lampu`\n"
        "`suhu rumah` — cek suhu & kelembaban\n"
        "`jadwal lampu` — lihat jadwal otomatis\n"
        "`atur jadwal nyala jam 18 mati jam 6`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎵 *MUSIK*\n"
        "`putar [lagu] [artis]` — speaker ESP32\n"
        "`putar [lagu] di TV` — speaker STB/TV\n"
        "`stop musik` — hentikan musik\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📻 *RADIO*\n"
        "`putar radio [stasiun]` — speaker ESP32\n"
        "`putar radio [stasiun] di TV` — speaker STB\n"
        "`stop radio` · `daftar radio`\n"
        "Stasiun: prambors, hardrock, delta, traxfm,\n"
        "female, idolafm, salatiga, bbc, jazz24, dll\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📅 *KALENDER*\n"
        "`jadwal minggu ini` — lihat Google Calendar\n"
        "`tambah jadwal [event] [tanggal] [jam]`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🌐 *INFO & DATA*\n"
        "`cuaca` / `cuaca [kota]`\n"
        "`berita` — 5 berita terkini Indonesia\n"
        "`berita vatikan` — Vatican News (bahasa Indonesia)\n"
        "`berita vatikan inggris` — Vatican News (Inggris)\n"
        "`berita vatikan terjemahan` — Vatican News diterjemahkan\n"
        "`jam sekarang` / `jam di Tokyo`\n"
        "`cari [topik]` — Wikipedia / web search\n"
        "`kurs USD ke IDR` — nilai tukar\n"
        "`harga BTC` / `saham BBCA` / `IHSG`\n"
        "`hitung [ekspresi]` — kalkulator\n"
        "`ingatkan [N] menit [pesan]` — timer\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔧 *PERINTAH BOT*\n"
        "/status — cek koneksi ESP32\n"
        "/help — tampilkan bantuan ini",
        parse_mode="Markdown"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not is_allowed(chat_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return
    status = check_esp32_status()
    await update.message.reply_text(
        f"📊 *Status ESP32*\n\n"
        f"IP: `{ESP32_IP}:{ESP32_PORT}`\n"
        f"Status: {status}",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id  = update.message.chat_id
    text     = update.message.text.strip()
    user     = update.message.from_user
    username = f"@{user.username}" if user and user.username else str(chat_id)

    logger.info("Pesan dari %s (id=%d): %s", username, chat_id, text)

    if not ALLOWED_CHAT_IDS:
        logger.info("💡 Tip: tambahkan %d ke TELEGRAM_ALLOWED_USER_ID di .bashrc", chat_id)

    if not is_allowed(chat_id):
        await update.message.reply_text("⛔ Anda tidak memiliki akses.")
        return

    if text.lower() in WAKE_TRIGGERS:
        await update.message.reply_text("⏳ Membangunkan Xiaozhi...")
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, send_wake_http)
        if success:
            await update.message.reply_text(
                "✅ *Xiaozhi dibangunkan!*\n"
                "💬 Sekarang kirim pesan apapun untuk berbicara ke Xiaozhi.\n"
                "Contoh: `nyalakan lampu`, `cuaca hari ini`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "❌ *Gagal mengirim perintah.*\n\n"
                f"ESP32 tidak merespons di `{WAKE_URL}`\n\n"
                "Pastikan:\n"
                "• ESP32 menyala dan terhubung WiFi\n"
                "• Firmware sudah include `wake_server.h`",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(f"⏳ Mengirim ke Xiaozhi: _{text}_...", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, send_say_http, text)
        if success:
            response = await poll_response()
            if response:
                await update.message.reply_text(
                    f"🤖 *Xiaozhi:*\n{response}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"✅ Perintah terkirim!\n💬 `{text}`\n_(tidak ada respons teks)_",
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(
                "❌ Gagal mengirim perintah.\n"
                "Coba ketik `Hi ESP` dulu untuk membangunkan Xiaozhi.",
                parse_mode="Markdown"
            )


# ── Chime ─────────────────────────────────────────────────────

async def handle_chime():
    """
    Loop async — setiap 30 detik cek waktu.
    Jika menit == 0 dan jam ada di chime_hours → wake + say ke ESP32.
    Config dibaca ulang tiap cek sehingga perubahan dashboard langsung berlaku.
    """
    last_triggered_hour = -1
    logger_chime.info("Chime loop aktif ✓")

    while True:
        try:
            now  = datetime.now()
            hour = now.hour
            mnt  = now.minute

            if mnt == 0 and hour != last_triggered_hour:
                cfg = load_chime_config()

                if cfg.get("chime_enabled") and hour in cfg.get("chime_hours", []):
                    text = cfg.get("chime_text", DEFAULT_CHIME["chime_text"])
                    logger_chime.info("Jam %02d:00 → '%s'", hour, text)

                    # Langsung /say — firmware sudah handle abort+retry sendiri
                    loop = asyncio.get_running_loop()
                    ok_say = await loop.run_in_executor(None, send_say_http, text)
                    logger_chime.info("Say %s", "OK ✓" if ok_say else "GAGAL ✗")
                else:
                    reason = "disabled" if not cfg.get("chime_enabled") else f"jam {hour} tidak aktif"
                    logger_chime.debug("Jam %02d:00 — skip (%s)", hour, reason)

                last_triggered_hour = hour

        except Exception as e:
            logger_chime.error("Chime loop error: %s", e)

        await asyncio.sleep(30)


# ── Quotes ─────────────────────────────────────────────────────

QUOTE_PROMPTS = [
    "kata mutiara hari ini",
    "kutipan alkitab hari ini",
    "kutipan lirik lagu hari ini",
    "kata mandarin dan artinya hari ini",
    "kata korea dan artinya hari ini"
]

logger_quote = logging.getLogger("Quote")

async def handle_quotes():
    """
    Loop async — setiap 30 detik cek waktu.
    Jika menit == 1 dan quotes_enabled dan jam ada di quotes_hours → kirim prompt quote random ke ESP32.
    Config dibaca ulang tiap cek sehingga perubahan dashboard langsung berlaku.
    """
    last_triggered_hour = -1
    logger_quote.info("Quote loop aktif ✓")

    while True:
        try:
            now  = datetime.now()
            hour = now.hour
            mnt  = now.minute

            if mnt == 11 and hour != last_triggered_hour:
                cfg = load_chime_config()

                if cfg.get("quotes_enabled") and hour in cfg.get("quotes_hours", []):
                    # Pilih prompt quote random
                    quote_prompt = random.choice(QUOTE_PROMPTS)
                    logger_quote.info("Jam %02d:01 → '%s'", hour, quote_prompt)

                    loop = asyncio.get_running_loop()
                    ok_say = await loop.run_in_executor(None, send_say_http, quote_prompt)
                    logger_quote.info("Say %s", "OK ✓" if ok_say else "GAGAL ✗")
                else:
                    reason = "disabled" if not cfg.get("quotes_enabled") else f"jam {hour} tidak aktif"
                    logger_quote.debug("Jam %02d:01 — skip (%s)", hour, reason)

                last_triggered_hour = hour

        except Exception as e:
            logger_quote.error("Quote loop error: %s", e)

        await asyncio.sleep(30)


# ── Main ──────────────────────────────────────────────────────

async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN belum diset! Tambahkan ke ~/.bashrc")
        logger.error("   export TELEGRAM_BOT_TOKEN='token_kamu'")
        return

    logger.info("=" * 50)
    logger.info("  Xiaozhi Wake Bot (HTTP mode)")
    logger.info("  ESP32 : http://%s:%d", ESP32_IP, ESP32_PORT)
    logger.info("  Wake  : %s", WAKE_URL)
    logger.info("  Say   : %s", SAY_URL)
    logger.info("  Allowed IDs: %s", ALLOWED_CHAT_IDS if ALLOWED_CHAT_IDS else "semua")
    logger.info("=" * 50)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def run_bot():
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(allowed_updates=["message"])
            logger.info("Bot berjalan. Kirim 'Hi, ESP' dari Telegram.")
            try:
                await asyncio.Event().wait()
            finally:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()

    await asyncio.gather(run_bot(), handle_chime(), handle_quotes())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot dihentikan.")
