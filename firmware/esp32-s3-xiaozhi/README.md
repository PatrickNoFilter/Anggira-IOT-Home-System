# 🤖 Firmware ESP32-S3 — Xiaozhi AI Voice Assistant (Modifikasi)

Firmware ESP32-S3 yang dimodifikasi dari [xiaozhi-esp32-music](https://github.com/Maggotxy/xiaozhi-esp32-music) dengan penambahan fitur music streaming dari STB server.

---

## 🔗 Base Project

Fork & modifikasi dari:
- **Maggotxy/xiaozhi-esp32-music**: https://github.com/Maggotxy/xiaozhi-esp32-music
- **xinnan-tech/xiaozhi-esp32**: https://github.com/xinnan-tech/xiaozhi-esp32

---

## 🎯 Fitur Modifikasi

- Wake word: **"Hi, ESP"** (model `wn9_hiesp`)
- Integrasi dengan `stream_server.py` di STB untuk memutar musik dari YouTube
- HTTP endpoint `/wake`, `/say`, `/status` untuk kontrol via Telegram bot
- MAC Address: `3c:dc:75:6b:f9:ec`

---

## 📦 Setup

1. Clone base project dari link di atas
2. Ikuti setup guide resmi Xiaozhi ESP32
3. Konfigurasi WiFi dan alamat MCP server (STB IP)

### Konfigurasi penting:
- **WiFi**: sesuaikan SSID dan password
- **MCP Endpoint**: arahkan ke `ws://STB_IP:PORT/mcp`
- **Static IP ESP32-S3**: `192.168.1.X` (sesuaikan)

---

## 🔗 Integrasi dengan STB Server

ESP32-S3 berkomunikasi dengan STB via:
1. **WebSocket MCP** — untuk tool calls (putar lagu, cuaca, berita, dll)
2. **HTTP `/stream_pcm`** — minta URL audio dari `stream_server.py`
3. **HTTP `/play`** — stream audio MP3 dari YouTube

