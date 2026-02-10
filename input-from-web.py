#!/usr/bin/env python3
"""input-from-web: Type on your phone, inject into focused desktop app."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys

from flask import Flask, request, abort
import qrcode

app = Flask(__name__)
TOKEN = secrets.token_urlsafe(32)
USE_TOKEN = True
METHOD = "type"
PROFILE = {}

CONFIG_PATH = os.path.expanduser("~/.input-from-web-conf.json")

DEFAULT_CONFIG = {
    "_comment": [
        "input-from-web configuration file.",
        "",
        "default_profile: which profile to use when --profile is not specified.",
        "",
        "profiles.<name>.method:",
        "  'type'      - ydotool type, simulates keystrokes (default).",
        "  'clipboard' - wl-copy only, you paste manually.",
        "  Can be overridden with --method on the command line.",
        "",
        "profiles.<name>.port:",
        "  TCP port to listen on (default: 5123).",
        "  Can be overridden with --port on the command line.",
        "",
        "profiles.<name>.use_security_token:",
        "  true  - require a secret token in the URL (default, recommended).",
        "  false - no token, anyone on the network can send input.",
        "          WARNING: only disable on a trusted private network!",
        "",
        "profiles.<name>.voice_send:",
        "  enabled       - true/false to toggle voice command detection.",
        "  delay_seconds - seconds to wait after last edit before auto-triggering.",
        "  send_words    - words that trigger auto-send when typed last (case insensitive).",
        "  clear_words   - words that trigger auto-clear when typed last (case insensitive).",
        "",
        "profiles.<name>.substitutions:",
        "  Keys are phrases to match (case insensitive), values are replacements.",
        "  Applied automatically as you type. Useful for voice dictation.",
        "  Example: {\"full stop\": \".\", \"new line\": \"\\n\"}",
    ],
    "default_profile": "default",
    "profiles": {
        "default": {
            "method": "type",
            "port": 5123,
            "use_security_token": True,
            "voice_send": {
                "enabled": True,
                "delay_seconds": 1.5,
                "send_words": ["send"],
                "clear_words": ["clear"],
            },
            "substitutions": {
                "full stop": ".",
                "question mark": "?",
                "exclamation mark": "!",
                "comma": ",",
                "colon": ":",
                "semicolon": ";",
                "quote": "\"",
                "new line": "\n",
                "new paragraph": "\n\n",
            },
        }
    },
}


def load_or_create_config(profile_name=None):
    """Load config from disk, creating default if missing. Return the active profile."""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"  Created default config: {CONFIG_PATH}")
        config = DEFAULT_CONFIG
    else:
        with open(CONFIG_PATH) as f:
            config = json.load(f)

    if profile_name is None:
        profile_name = config.get("default_profile", "default")

    profiles = config.get("profiles", {})
    if profile_name not in profiles:
        print(f"Error: profile '{profile_name}' not found in {CONFIG_PATH}", file=sys.stderr)
        print(f"Available profiles: {', '.join(profiles.keys())}", file=sys.stderr)
        sys.exit(1)

    print(f"  Profile: {profile_name}")
    return profiles[profile_name]


HTML_TEMPLATE = r"""\
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
.btn-row{display:flex;gap:8px;flex-shrink:0}
#btn{flex:1;padding:16px;font-size:1.2rem;font-weight:bold;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer}
#btn:active{background:#1d4ed8}
#btn:disabled{background:#555}
#clear-btn{width:56px;padding:16px;font-size:1.2rem;font-weight:bold;background:#dc2626;color:#fff;border:none;border-radius:8px;cursor:pointer;flex-shrink:0}
#clear-btn:active{background:#b91c1c}
textarea{flex:1;width:100%;padding:12px;font-size:1rem;background:#262626;color:#fff;border:1px solid #444;border-radius:8px;resize:none}
textarea:focus{outline:none;border-color:#2563eb}
.status{text-align:center;font-size:0.85rem;color:#888;min-height:1.2em;flex-shrink:0}
</style>
</head>
<body>
<div class="container">
<div class="btn-row">
  <button id="btn">SEND</button>
  <button id="clear-btn">X</button>
</div>
<textarea id="txt" placeholder="Type here..." autofocus></textarea>
<div class="status" id="status"></div>
</div>
<script>
const CONFIG = __CONFIG__;
const token = new URLSearchParams(location.search).get("token");

const txt = document.getElementById("txt");
const btn = document.getElementById("btn");
const clearBtn = document.getElementById("clear-btn");
const statusEl = document.getElementById("status");

btn.addEventListener("click", doSend);
clearBtn.addEventListener("click", clearText);

/* --- Substitutions --- */
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const subEntries = Object.entries(CONFIG.substitutions || {})
  .sort((a, b) => b[0].length - a[0].length);

function applySubstitutions() {
  let text = txt.value;
  let changed = false;
  for (const [phrase, replacement] of subEntries) {
    const re = new RegExp("(^|\\s)" + escapeRegex(phrase) + "(?=\\s|$)", "gi");
    if (re.test(text)) {
      text = text.replace(re, function(m, before) { return before + replacement; });
      changed = true;
    }
  }
  if (changed) {
    const pos = txt.selectionStart;
    const diff = txt.value.length - text.length;
    txt.value = text;
    txt.selectionStart = txt.selectionEnd = Math.max(0, pos - diff);
  }
}

/* --- Voice send --- */
let voiceTimer = null;

function checkVoiceCommand() {
  const vs = CONFIG.voice_send;
  if (!vs || !vs.enabled) return;
  if (voiceTimer) { clearTimeout(voiceTimer); voiceTimer = null; }

  const text = txt.value.trimEnd();
  if (!text) return;

  const words = text.split(/\s+/);
  const lastWord = words[words.length - 1].toLowerCase();

  const sendWords = (vs.send_words || []).map(w => w.toLowerCase());
  const clearWords = (vs.clear_words || []).map(w => w.toLowerCase());

  let action = null;
  if (sendWords.includes(lastWord)) action = "send";
  else if (clearWords.includes(lastWord)) action = "clear";

  if (action) {
    const delay = (vs.delay_seconds || 1.5) * 1000;
    voiceTimer = setTimeout(() => {
      voiceTimer = null;
      const re = new RegExp("\\s*" + escapeRegex(lastWord) + "\\s*$", "i");
      txt.value = txt.value.replace(re, "");
      if (action === "send") doSend();
      else clearText();
    }, delay);
  }
}

txt.addEventListener("input", () => {
  applySubstitutions();
  checkVoiceCommand();
});

/* --- Actions --- */
function clearText() {
  txt.value = "";
  txt.focus();
  showStatus("");
}

async function doSend() {
  const text = txt.value;
  if (!text) return;
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const res = await fetch("/send?token=" + encodeURIComponent(token), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: text})
    });
    if (res.ok) {
      txt.value = "";
      showStatus("Sent!");
      txt.focus();
    } else {
      showStatus("Error: " + res.status);
    }
  } catch(e) {
    showStatus("Network error");
  }
  btn.disabled = false;
  btn.textContent = "SEND";
}

function showStatus(msg) {
  statusEl.textContent = msg;
  if (msg) setTimeout(() => { statusEl.textContent = ""; }, 2000);
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
    """Inject text using the chosen method."""
    if METHOD == "type":
        subprocess.run(
            ["ydotool", "type", "--key-delay", "0", "--", text],
            check=True,
            timeout=30,
        )
    else:
        subprocess.run(
            ["wl-copy", "-o", "--", text],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )


def check_token():
    if USE_TOKEN and request.args.get("token") != TOKEN:
        abort(403)


@app.route("/")
def index():
    check_token()
    profile_json = json.dumps(PROFILE, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__CONFIG__", profile_json)


@app.route("/send", methods=["POST"])
def send():
    check_token()
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
    global METHOD, USE_TOKEN, PROFILE
    parser = argparse.ArgumentParser(description="Type on your phone, paste on your desktop.")
    parser.add_argument("--method", choices=["clipboard", "type"], default=None,
                        help="Override profile method. type: ydotool type. clipboard: wl-copy only.")
    parser.add_argument("--port", type=int, default=None,
                        help="Override profile port (default: 5123)")
    parser.add_argument("--profile", default=None,
                        help="Config profile name (default: from config file)")
    args = parser.parse_args()

    PROFILE = load_or_create_config(args.profile)

    # CLI flags override profile, profile overrides built-in defaults
    METHOD = args.method or PROFILE.get("method", "type")
    USE_TOKEN = PROFILE.get("use_security_token", True)

    if not USE_TOKEN:
        print("\n\033[1;97;41m  WARNING: security token is DISABLED  \033[0m")
        print("\033[1;31m  Anyone on your network can send keystrokes to this machine!\033[0m")
        print("\033[1;31m  Only run this way on a trusted private network.\033[0m\n")

    host = get_lan_ip()
    port = args.port or PROFILE.get("port", 5123)

    if USE_TOKEN:
        url = f"http://{host}:{port}/?token={TOKEN}"
    else:
        url = f"http://{host}:{port}/"

    print(f"\n  URL: {url}\n")

    qr = qrcode.QRCode(box_size=1, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print()

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
