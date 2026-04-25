import http.server
import json
import os
import subprocess
from urllib.parse import urlparse, parse_qs

# ── Path ──────────────────────────────────────────────────────
HOME        = os.path.expanduser("~")
ANGGIRA_DIR = os.path.join(HOME, "anggira")
ANGGIRA_LOG = os.path.join(HOME, "anggira.log")
STREAM_LOG  = os.path.join(HOME, "stream_server.log")
BOT_LOG     = os.path.join(HOME, "bot.log")
BASHRC      = os.path.join(HOME, ".bashrc")
CONFIG_FILE = os.path.join(ANGGIRA_DIR, "dashboard_config.json")

# ── Config keys yang bisa diedit ─────────────────────────────
ENV_KEYS = [
    ("MCP_ENDPOINT",              "MCP Endpoint",              "text",     "wss://api.xiaozhi.me/mcp/?token=..."),
    ("TELEGRAM_BOT_TOKEN",        "Telegram Bot Token (Xiaozhi)", "password", ""),
    ("TELEGRAM_STB_TOKEN",        "Telegram STB Token (Anggira)", "password", ""),
    ("TELEGRAM_ALLOWED_USER_ID",  "Telegram Allowed User ID",  "text",     ""),
    ("OPENROUTER_API_KEY",        "OpenRouter API Key",        "password", ""),
    ("OPENWEATHER_API_KEY",       "OpenWeather API Key",       "password", ""),
    ("ESP32_SENSOR_IP",           "ESP32 Sensor IP (C3)",      "text",     "192.168.1.222"),
    ("ESP32_IP",                  "ESP32 Xiaozhi IP (S3)",     "text",     "192.168.1.222"),
    ("ESP32_PORT",                "ESP32 Xiaozhi Port",        "text",     "8080"),
    ("GOOGLE_CLIENT_ID",          "Google Client ID",          "password", ""),
    ("GOOGLE_CLIENT_SECRET",      "Google Client Secret",      "password", ""),
]

# ── Default dashboard config ──────────────────────────────────
DEFAULT_CONFIG = {
    "chime_enabled": True,
    "chime_text": "jam berapa sekarang dan kapan hujan di cebongan salatiga",
    "chime_hours": list(range(6, 22)),   # jam 06:00–21:00
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                c = json.load(f)
            # merge dengan default agar key baru selalu ada
            for k, v in DEFAULT_CONFIG.items():
                c.setdefault(k, v)
            return c
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(data: dict):
    os.makedirs(ANGGIRA_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def read_env(key: str) -> str:
    """Baca nilai env dari .bashrc."""
    try:
        with open(BASHRC) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"export {key}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return val
    except Exception:
        pass
    return os.environ.get(key, "")

def write_env(key: str, value: str):
    """Tulis / update nilai env di .bashrc."""
    try:
        with open(BASHRC) as f:
            lines = f.readlines()
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith(f"export {key}="):
                new_lines.append(f'export {key}="{value}"\n')
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f'export {key}="{value}"\n')
        with open(BASHRC, "w") as f:
            f.writelines(new_lines)
        os.environ[key] = value
        return True
    except Exception as e:
        return False

def read_log(path, lines=150):
    if os.path.exists(path):
        with open(path) as f:
            return "".join(f.readlines()[-lines:])
    return "(kosong)"

# ── HTML ──────────────────────────────────────────────────────
def build_html():
    cfg     = load_config()
    env_rows = ""
    for key, label, itype, placeholder in ENV_KEYS:
        val = read_env(key)
        display = val if itype != "password" else ("*" * min(len(val), 12) if val else "")
        env_rows += f"""
        <div class="field">
            <label>{label}</label>
            <div class="input-row">
                <input type="{itype}" id="env_{key}" name="{key}"
                       value="{val}" placeholder="{placeholder}"
                       autocomplete="off" spellcheck="false">
                <button class="save-btn" onclick="saveEnv('{key}')">Simpan</button>
            </div>
            <span class="status" id="st_{key}"></span>
        </div>"""

    chime_hours_val = json.dumps(cfg.get("chime_hours", DEFAULT_CONFIG["chime_hours"]))
    hour_checkboxes = ""
    for h in range(0, 24):
        checked = "checked" if h in cfg.get("chime_hours", DEFAULT_CONFIG["chime_hours"]) else ""
        hour_checkboxes += f'<label class="hour-cb"><input type="checkbox" value="{h}" {checked}><span>{h:02d}</span></label>'

    chime_enabled_checked = "checked" if cfg.get("chime_enabled", True) else ""
    chime_text_val = cfg.get("chime_text", DEFAULT_CONFIG["chime_text"])

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Anggira Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap');

*{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#060a10;
  --surface:#0d1520;
  --border:#1a2d4a;
  --accent:#00c8ff;
  --accent2:#ff6b35;
  --green:#00ff88;
  --text:#c8d8e8;
  --dim:#4a6280;
}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;min-height:100vh}}

/* Header */
.header{{
  background:linear-gradient(135deg,#060a10 0%,#0d1a2a 100%);
  border-bottom:1px solid var(--border);
  padding:18px 24px;
  display:flex;align-items:center;gap:14px;
  position:sticky;top:0;z-index:100;
  backdrop-filter:blur(10px);
}}
.header-icon{{font-size:28px}}
.header-title{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header-sub{{font-size:11px;color:var(--dim);margin-top:2px}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--green);
  margin-left:auto;box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}

/* Nav tabs */
.nav{{display:flex;background:var(--surface);border-bottom:1px solid var(--border);overflow-x:auto}}
.nav button{{
  padding:12px 20px;background:none;border:none;color:var(--dim);
  font-family:'JetBrains Mono',monospace;font-size:12px;cursor:pointer;
  border-bottom:2px solid transparent;white-space:nowrap;transition:.2s
}}
.nav button.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.nav button:hover:not(.active){{color:var(--text)}}

/* Panels */
.panel{{display:none;padding:20px;max-width:900px;margin:0 auto}}
.panel.active{{display:block}}

/* Section */
.section{{margin-bottom:24px}}
.section-title{{
  font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
  color:var(--accent);text-transform:uppercase;letter-spacing:2px;
  margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)
}}

/* Field */
.field{{margin-bottom:14px}}
.field label{{display:block;font-size:11px;color:var(--dim);margin-bottom:5px;letter-spacing:.5px}}
.input-row{{display:flex;gap:8px}}
input[type=text],input[type=password],textarea{{
  flex:1;background:#0a1520;border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;
  padding:9px 12px;outline:none;transition:.2s
}}
input:focus,textarea:focus{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(0,200,255,.1)}}
textarea{{width:100%;resize:vertical;min-height:70px}}
.save-btn{{
  padding:9px 16px;background:var(--accent);border:none;border-radius:6px;
  color:#000;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;
  cursor:pointer;white-space:nowrap;transition:.2s
}}
.save-btn:hover{{background:#33d4ff}}
.save-btn.danger{{background:var(--accent2)}}
.save-btn.danger:hover{{background:#ff8c5a}}
.status{{font-size:10px;margin-top:4px;display:block;height:14px}}
.status.ok{{color:var(--green)}}
.status.err{{color:#ff4444}}

/* Toggle */
.toggle-row{{display:flex;align-items:center;gap:12px;margin-bottom:14px}}
.toggle{{position:relative;width:44px;height:24px}}
.toggle input{{opacity:0;width:0;height:0}}
.slider{{
  position:absolute;inset:0;background:#1a2d4a;border-radius:24px;
  cursor:pointer;transition:.3s
}}
.slider:before{{
  content:'';position:absolute;width:18px;height:18px;
  left:3px;bottom:3px;background:var(--dim);border-radius:50%;transition:.3s
}}
.toggle input:checked + .slider{{background:var(--accent)}}
.toggle input:checked + .slider:before{{transform:translateX(20px);background:#000}}
.toggle-label{{font-size:12px;color:var(--text)}}

/* Hour grid */
.hour-grid{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}}
.hour-cb{{cursor:pointer}}
.hour-cb input{{display:none}}
.hour-cb span{{
  display:block;width:38px;padding:6px 0;text-align:center;
  background:#0a1520;border:1px solid var(--border);border-radius:5px;
  font-size:11px;transition:.2s
}}
.hour-cb input:checked + span{{
  background:rgba(0,200,255,.15);border-color:var(--accent);color:var(--accent)
}}

/* Log */
pre{{
  background:#070d15;border:1px solid var(--border);border-radius:8px;
  padding:14px;font-size:11px;max-height:320px;overflow:auto;
  white-space:pre-wrap;word-break:break-all;line-height:1.6
}}
.log-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.log-name{{font-size:12px;color:var(--accent)}}
.log-btn{{
  padding:5px 12px;background:var(--surface);border:1px solid var(--border);
  border-radius:5px;color:var(--dim);font-size:11px;cursor:pointer;
  font-family:inherit
}}
.log-btn:hover{{color:var(--text);border-color:var(--accent)}}

/* Alert banner */
.banner{{
  padding:10px 14px;border-radius:7px;font-size:12px;margin-bottom:16px;display:none
}}
.banner.ok{{background:rgba(0,255,136,.1);border:1px solid var(--green);color:var(--green)}}
.banner.err{{background:rgba(255,68,68,.1);border:1px solid #ff4444;color:#ff4444}}
</style>
</head>
<body>

<div class="header">
  <span class="header-icon">🤖</span>
  <div>
    <div class="header-title">Anggira Dashboard</div>
    <div class="header-sub">STB Control Panel · Termux</div>
  </div>
  <div class="dot"></div>
</div>

<div class="nav">
  <button class="active" onclick="tab(this,'logs')">📋 Logs</button>
  <button onclick="tab(this,'chime')">🕐 Chime</button>
  <button onclick="tab(this,'tokens')">🔑 Tokens</button>
  <button onclick="tab(this,'esp32')">📡 ESP32</button>
</div>

<!-- ═══ LOGS ═══ -->
<div id="panel-logs" class="panel active">
  <div class="section">
    <div class="section-title">Live Logs</div>

    <div class="log-header">
      <span class="log-name">🤖 anggira.py</span>
      <button class="log-btn" onclick="clearLog('anggira')">Clear</button>
    </div>
    <pre id="log-anggira">memuat...</pre>

    <div class="log-header" style="margin-top:16px">
      <span class="log-name">🎵 stream_server.py</span>
      <button class="log-btn" onclick="clearLog('stream')">Clear</button>
    </div>
    <pre id="log-stream">memuat...</pre>

    <div class="log-header" style="margin-top:16px">
      <span class="log-name">📱 bot.py</span>
      <button class="log-btn" onclick="clearLog('bot')">Clear</button>
    </div>
    <pre id="log-bot">memuat...</pre>
  </div>
</div>

<!-- ═══ CHIME ═══ -->
<div id="panel-chime" class="panel">
  <div class="section">
    <div class="section-title">Pengaturan Chime Per Jam</div>
    <div id="chime-banner" class="banner"></div>

    <div class="toggle-row">
      <label class="toggle">
        <input type="checkbox" id="chime-enabled" {chime_enabled_checked}>
        <span class="slider"></span>
      </label>
      <span class="toggle-label">Aktifkan chime per jam (ESP32 wake + ucapkan)</span>
    </div>

    <div class="field">
      <label>PERINTAH YANG DIUCAPKAN SETIAP JAM</label>
      <textarea id="chime-text">{chime_text_val}</textarea>
    </div>

    <div class="field">
      <label>JAM AKTIF (centang jam yang ingin dibunyikan)</label>
      <div class="hour-grid" id="hour-grid">
        {hour_checkboxes}
      </div>
    </div>

    <button class="save-btn" onclick="saveChime()">💾 Simpan Pengaturan Chime</button>
  </div>
</div>

<!-- ═══ TOKENS ═══ -->
<div id="panel-tokens" class="panel">
  <div class="section">
    <div class="section-title">API Keys & Tokens</div>
    <div id="token-banner" class="banner"></div>
    <p style="font-size:11px;color:var(--dim);margin-bottom:16px">
      Nilai disimpan ke ~/.bashrc dan langsung aktif. Restart service setelah mengubah token penting.
    </p>
    {env_rows}
  </div>
</div>

<!-- ═══ ESP32 ═══ -->
<div id="panel-esp32" class="panel">
  <div class="section">
    <div class="section-title">ESP32 Xiaozhi Control</div>
    <div id="esp32-banner" class="banner"></div>

    <div class="field">
      <label>KIRIM PERINTAH LANGSUNG KE XIAOZHI</label>
      <div class="input-row">
        <input type="text" id="say-text" placeholder="contoh: nyalakan lampu">
        <button class="save-btn" onclick="sendSay()">Kirim</button>
      </div>
    </div>

    <div class="field">
      <label>AKSI CEPAT</label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px">
        <button class="save-btn" onclick="quickSay('jam berapa sekarang dan kapan hujan di cebongan salatiga')">🕐 Test Chime</button>
        <button class="save-btn" onclick="quickSay('nyalakan lampu')">💡 Lampu ON</button>
        <button class="save-btn" onclick="quickSay('matikan lampu')">🌑 Lampu OFF</button>
        <button class="save-btn" onclick="quickSay('suhu rumah')">🌡️ Sensor</button>
        <button class="save-btn" onclick="quickSay('cuaca hari ini')">🌤️ Cuaca</button>
        <button class="save-btn danger" onclick="wakeESP()">⚡ Wake Only</button>
      </div>
    </div>

    <div class="field" style="margin-top:16px">
      <label>STATUS ESP32</label>
      <pre id="esp32-status" style="max-height:120px">klik refresh untuk cek...</pre>
      <button class="save-btn" style="margin-top:8px" onclick="checkESP32()">🔄 Refresh Status</button>
    </div>
  </div>
</div>

<script>
// ── Tabs ──────────────────────────────────────────────────────
function tab(btn, id) {{
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-'+id).classList.add('active');
}}

// ── Logs ─────────────────────────────────────────────────────
async function loadLog(type) {{
  try {{
    const r = await fetch('/api/log?type='+type);
    const d = await r.json();
    const el = document.getElementById('log-'+type);
    if(el) {{ el.textContent = d.log; el.scrollTop = el.scrollHeight; }}
  }} catch(e) {{}}
}}
async function clearLog(type) {{
  await fetch('/api/clear_log?type='+type, {{method:'POST'}});
  loadLog(type);
}}
setInterval(() => {{ loadLog('anggira'); loadLog('stream'); loadLog('bot'); }}, 2000);
loadLog('anggira'); loadLog('stream'); loadLog('bot');

// ── Chime ─────────────────────────────────────────────────────
async function saveChime() {{
  const enabled = document.getElementById('chime-enabled').checked;
  const text    = document.getElementById('chime-text').value.trim();
  const hours   = [...document.querySelectorAll('#hour-grid input:checked')].map(i => parseInt(i.value));
  const r = await fetch('/api/save_chime', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{chime_enabled: enabled, chime_text: text, chime_hours: hours}})
  }});
  const d = await r.json();
  showBanner('chime-banner', d.ok, d.ok ? '✅ Chime disimpan!' : '❌ ' + d.error);
}}

// ── Tokens ────────────────────────────────────────────────────
async function saveEnv(key) {{
  const val = document.getElementById('env_'+key).value;
  const st  = document.getElementById('st_'+key);
  const r = await fetch('/api/save_env', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{key, value: val}})
  }});
  const d = await r.json();
  st.textContent = d.ok ? '✅ Tersimpan' : '❌ Gagal';
  st.className = 'status ' + (d.ok ? 'ok' : 'err');
  setTimeout(() => {{ st.textContent = ''; st.className = 'status'; }}, 3000);
}}

// ── ESP32 ─────────────────────────────────────────────────────
async function sendSay() {{
  const text = document.getElementById('say-text').value.trim();
  if (!text) return;
  await doSay(text);
  document.getElementById('say-text').value = '';
}}
function quickSay(text) {{ doSay(text); }}
async function doSay(text) {{
  const r = await fetch('/api/esp32_say', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{text}})
  }});
  const d = await r.json();
  showBanner('esp32-banner', d.ok, d.ok ? '✅ Terkirim: ' + text : '❌ ' + d.error);
}}
async function wakeESP() {{
  const r = await fetch('/api/esp32_wake', {{method:'POST'}});
  const d = await r.json();
  showBanner('esp32-banner', d.ok, d.ok ? '✅ ESP32 dibangunkan' : '❌ ' + d.error);
}}
async function checkESP32() {{
  const r = await fetch('/api/esp32_status');
  const d = await r.json();
  document.getElementById('esp32-status').textContent = JSON.stringify(d.status, null, 2);
}}

// ── Helper ────────────────────────────────────────────────────
function showBanner(id, ok, msg) {{
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'banner ' + (ok ? 'ok' : 'err');
  el.style.display = 'block';
  setTimeout(() => {{ el.style.display = 'none'; }}, 4000);
}}
</script>
</body>
</html>"""

# ── HTTP Handler ──────────────────────────────────────────────
LOG_PATHS = {
    "anggira": ANGGIRA_LOG,
    "stream":  STREAM_LOG,
    "bot":     BOT_LOG,
}

class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)

        if path == "/":
            html = build_html().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)

        elif path == "/api/log":
            log_type = qs.get("type", ["anggira"])[0]
            log_path = LOG_PATHS.get(log_type, ANGGIRA_LOG)
            self.send_json({"log": read_log(log_path)})

        elif path == "/api/esp32_status":
            try:
                import urllib.request as ur
                cfg = load_config()
                ip   = read_env("ESP32_IP") or "192.168.1.222"
                port = read_env("ESP32_PORT") or "8080"
                url  = f"http://{ip}:{port}/status"
                with ur.urlopen(url, timeout=4) as r:
                    status = json.loads(r.read().decode())
                self.send_json({"ok": True, "status": status})
            except Exception as e:
                self.send_json({"ok": False, "status": {"error": str(e)}})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/save_chime":
            data = self.read_body()
            try:
                cfg = load_config()
                cfg["chime_enabled"] = bool(data.get("chime_enabled", True))
                cfg["chime_text"]    = str(data.get("chime_text", "")).strip()
                cfg["chime_hours"]   = [int(h) for h in data.get("chime_hours", [])]
                save_config(cfg)
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif path == "/api/save_env":
            data = self.read_body()
            key  = data.get("key", "")
            val  = data.get("value", "")
            if key and key in [k for k, *_ in ENV_KEYS]:
                ok = write_env(key, val)
                self.send_json({"ok": ok})
            else:
                self.send_json({"ok": False, "error": "key tidak valid"})

        elif path == "/api/clear_log":
            qs       = parse_qs(urlparse(self.path).query)
            log_type = qs.get("type", ["anggira"])[0]
            log_path = LOG_PATHS.get(log_type, ANGGIRA_LOG)
            try:
                open(log_path, "w").close()
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif path == "/api/esp32_wake":
            try:
                import urllib.request as ur
                ip   = read_env("ESP32_IP") or "192.168.1.222"
                port = read_env("ESP32_PORT") or "8080"
                payload = json.dumps({"wake_word": "Hi ESP"}).encode()
                req = ur.Request(f"http://{ip}:{port}/wake", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
                ur.urlopen(req, timeout=5)
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif path == "/api/esp32_say":
            data = self.read_body()
            text = data.get("text", "").strip()
            try:
                import urllib.request as ur
                ip   = read_env("ESP32_IP") or "192.168.1.222"
                port = read_env("ESP32_PORT") or "8080"
                # Wake dulu, tunggu 2 detik, baru say
                payload_wake = json.dumps({"wake_word": "Hi ESP"}).encode()
                req_wake = ur.Request(f"http://{ip}:{port}/wake", data=payload_wake,
                                      headers={"Content-Type": "application/json"}, method="POST")
                ur.urlopen(req_wake, timeout=5)
                import time; time.sleep(2)
                payload_say = json.dumps({"text": text}).encode()
                req_say = ur.Request(f"http://{ip}:{port}/say", data=payload_say,
                                     headers={"Content-Type": "application/json"}, method="POST")
                ur.urlopen(req_say, timeout=5)
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()


# ── Run ───────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "8088"))
    print(f"Dashboard jalan di http://0.0.0.0:{port}")
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()