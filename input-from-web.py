#!/usr/bin/env python3
"""input-from-web: Type on your phone, inject into focused desktop app."""

import argparse
import secrets
import socket
import subprocess
import sys
import time

from flask import Flask, request, abort
import qrcode

app = Flask(__name__)
TOKEN = secrets.token_urlsafe(32)
AUTO_PASTE = True

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Input</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;font-family:system-ui,sans-serif;background:#1a1a1a;color:#fff}
.container{display:flex;flex-direction:column;height:100dvh;padding:8px;gap:8px}
button{width:100%;padding:16px;font-size:1.2rem;font-weight:bold;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;flex-shrink:0}
button:active{background:#1d4ed8}
button:disabled{background:#555}
textarea{flex:1;width:100%;padding:12px;font-size:1rem;background:#262626;color:#fff;border:1px solid #444;border-radius:8px;resize:none}
textarea:focus{outline:none;border-color:#2563eb}
.status{text-align:center;font-size:0.85rem;color:#888;min-height:1.2em;flex-shrink:0}
</style>
</head>
<body>
<div class="container">
<button id="btn" onclick="send()">SEND</button>
<textarea id="txt" placeholder="Type here..." autofocus></textarea>
<div class="status" id="status"></div>
</div>
<script>
const token = new URLSearchParams(location.search).get("token");
async function send() {
  const txt = document.getElementById("txt");
  const btn = document.getElementById("btn");
  const status = document.getElementById("status");
  const text = txt.value;
  if (!text) return;
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const res = await fetch("/send?token=" + encodeURIComponent(token), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text})
    });
    if (res.ok) {
      txt.value = "";
      status.textContent = "Sent!";
      txt.focus();
    } else {
      status.textContent = "Error: " + res.status;
    }
  } catch(e) {
    status.textContent = "Network error";
  }
  btn.disabled = false;
  btn.textContent = "SEND";
  setTimeout(() => status.textContent = "", 2000);
}
</script>
</body>
</html>
"""


def get_lan_ip():
    """Get LAN IP via UDP socket trick (no traffic actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def inject_text(text):
    """Copy text to Wayland clipboard, then optionally simulate Ctrl+V."""
    subprocess.run(
        ["wl-copy", "-o", "--", text],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=5,
    )
    if AUTO_PASTE:
        time.sleep(0.1)
        subprocess.run(
            ["ydotool", "key", "--delay", "100", "ctrl+v"],
            check=True,
            timeout=5,
        )


@app.route("/")
def index():
    if request.args.get("token") != TOKEN:
        abort(403)
    return HTML


@app.route("/send", methods=["POST"])
def send():
    if request.args.get("token") != TOKEN:
        abort(403)
    data = request.get_json(force=True)
    text = data.get("text", "")
    if not text:
        return {"error": "empty"}, 400
    try:
        inject_text(text)
    except subprocess.CalledProcessError as e:
        print(f"Injection failed: {e}", file=sys.stderr)
        return {"error": "injection failed"}, 500
    return {"ok": True}


def main():
    global AUTO_PASTE
    parser = argparse.ArgumentParser(description="Type on your phone, paste on your desktop.")
    parser.add_argument("--no-paste", action="store_true",
                        help="Clipboard only — skip auto Ctrl+V")
    args = parser.parse_args()
    AUTO_PASTE = not args.no_paste

    host = get_lan_ip()
    port = 5123
    url = f"http://{host}:{port}/?token={TOKEN}"

    print(f"\n  URL: {url}\n")

    qr = qrcode.QRCode(box_size=1, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print()

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
