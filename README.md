# 🏠 Anggira — IOT Home System with Xiaozhi AI Music, News & Calendar

Sistem smart home berbasis **ESP32** yang dikendalikan oleh asisten AI **Anggira** via suara (Xiaozhi), Telegram, dan web dashboard.

---

## 🗂️ Struktur Repository

```
anggira-iot/
├── firmware/
│   ├── esp32-s3-xiaozhi/        # ESP32-S3 — Xiaozhi AI Voice Assistant (modifikasi)
│   └── esp32-c3-sensor/         # ESP32-C3 Mini — Sensor Rumah + Kontrol Lampu Servo
└── server/
    └── stb/                     # Server di STB Android (Termux)
        ├── anggira.py           # Core: MCP server + Telegram bot + semua tools
        ├── bot.py               # Telegram bot untuk wake/kontrol ESP32 Xiaozhi
        ├── stream_server.py     # Music streaming server (YouTube → MP3)
        ├── dashboard.py         # Web dashboard log monitor (port 8088)
        ├── google_auth.py       # Setup OAuth2 Google Calendar (jalankan sekali)
        └── launcher.sh          # Auto-launcher semua service dengan restart otomatis
```

---

## 🔧 Komponen Hardware

| Perangkat | Chip | Fungsi |
|---|---|---|
| ESP32-S3 | ESP32-S3 | Xiaozhi AI voice assistant (wake word, TTS, musik) |
| ESP32-C3 Mini | ESP32-C3 | Sensor suhu/kelembaban/tekanan + kontrol lampu servo |
| STB Android | — | Server utama (Termux): AI, Telegram bot, music streaming |

---

## ✨ Fitur Utama

- 🎵 **Music Streaming** — minta lagu via suara/Telegram, stream dari YouTube ke speaker ESP32 atau STB
- 📰 **Berita** — headline berita Indonesia terkini
- 🌤️ **Cuaca** — cuaca real-time kota Salatiga (OpenWeatherMap)
- 📅 **Google Calendar** — lihat & tambah jadwal via suara
- 💡 **Kontrol Lampu** — ON/OFF + jadwal otomatis via servo motor
- 🌡️ **Sensor Rumah** — suhu, kelembaban, tekanan udara (AHT20 + BMP280)
- 📱 **Telegram Bot** — kontrol semua fitur dari HP
- 🖥️ **Web Dashboard** — monitor log semua service
- 💬 **Quotes Per Jam** — quotes motivasi Bahasa Indonesia yang muncul setiap jam +1 menit
- 🕐 **Chime Per Jam** — pengumuman otomatis setiap jam dengan teks kustom
- 🎵 **Playlist Management** — kelola playlist musik via dashboard

---

## 🚀 Quick Start

### 1. STB Server (Termux)

```bash
# Install dependencies
pip install python-telegram-bot websockets flask yt-dlp requests

# Set environment variables di ~/.bashrc
export TELEGRAM_BOT_TOKEN="token_xiaozhi_bot"
export TELEGRAM_STB_TOKEN="token_anggira_bot"
export OPENROUTER_API_KEY="key_kamu"
export OPENWEATHER_API_KEY="key_kamu"
export GOOGLE_CLIENT_ID="client_id"
export GOOGLE_CLIENT_SECRET="client_secret"
export ESP32_SENSOR_IP="192.168.1.222"
export TELEGRAM_ALLOWED_USER_ID="user_id_kamu"
export MCP_ENDPOINT="ws://localhost:port/mcp"

source ~/.bashrc

# (Pertama kali) Setup Google Calendar
python ~/anggira/google_auth.py

# Jalankan semua service
bash ~/anggira/launcher.sh
```

### 2. Firmware ESP32-C3 Sensor

Lihat [`firmware/esp32-c3-sensor/README.md`](firmware/esp32-c3-sensor/README.md)

### 3. Firmware ESP32-S3 Xiaozhi

Lihat [`firmware/esp32-s3-xiaozhi/README.md`](firmware/esp32-s3-xiaozhi/README.md)

---

## 🌐 Endpoints STB Server

| Service | Port | URL |
|---|---|---|
| Music Server | 8080 | `http://STB_IP:8080` |
| Web Dashboard | 8088 | `http://STB_IP:8088` |

---

## 🖥️ Web Dashboard Features

Dashboard web tersedia di `http://STB_IP:8088` dengan fitur:

### 📋 Logs
- Monitor live logs dari semua service (anggira.py, stream_server.py, bot.py)
- Auto-refresh setiap 2 detik
- Clear logs per service

### 🕐 Chime
- Aktifkan/nonaktifkan chime per jam
- Set teks perintah yang diucapkan setiap jam
- Pilih jam aktif (06:00-21:00 default)

### 💬 Quotes
- Kelola daftar quotes motivasi Bahasa Indonesia
- Tambah/hapus quotes custom
- Set jam aktif untuk quotes
- Reset ke daftar default (25 quotes)
- Quotes muncul setiap jam +1 menit

### 🔑 Tokens
- Kelola API keys dan tokens (Telegram, OpenRouter, OpenWeather, Google)
- Simpan langsung ke ~/.bashrc

### 🎵 Playlist
- Kelola playlist musik
- Tambah/edit/hapus playlist
- Test play langsung dari dashboard

### 📡 ESP32 Control
- Kirim perintah langsung ke Xiaozhi
- Aksi cepat (Test Chime, Lampu ON/OFF, Sensor, Cuaca)
- Cek status ESP32 real-time

## 📡 Endpoints ESP32-C3

| Endpoint | Fungsi |
|---|---|
| `/` | Web dashboard ESP32 |
| `/data` | JSON sensor data |
| `/sensor_rumah` | Data sensor untuk Anggira |
| `/on` `/off` | Kontrol lampu |
| `/jadwal` | Lihat jadwal lampu |
| `/set?on=HH:MM&off=HH:MM` | Set jadwal lampu |

---

## 🔗 Referensi

- Firmware ESP32-S3 dimodifikasi dari: [xiaozhi-esp32-music](https://github.com/Maggotxy/xiaozhi-esp32-music)
- Xiaozhi ESP32 original: [xinnan-tech/xiaozhi-esp32](https://github.com/xinnan-tech/xiaozhi-esp32)

---

## 📄 Lisensi

MIT License — bebas digunakan dan dimodifikasi.
