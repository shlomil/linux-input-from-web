# input-from-web

Use your phone's voice dictation to type into any app on your Ubuntu/Linux desktop.

## Motivation

Phone keyboards have excellent voice-to-text engines (Google, Apple, Samsung) that
are far better than anything available natively on Linux desktops. This tool bridges
the gap: it runs a tiny web server on your computer, you open it on your phone,
dictate text, and it gets injected into whatever app is focused on your desktop.

No app install needed on the phone — just a browser.

## How it works

```
Phone browser  ──HTTP POST──>  Python (Flask)  ──> ydotool type / wl-copy
                                    │
                              Prints QR code
                              + secret token URL
                              on startup
```

1. The script starts a Flask web server on your LAN IP
2. A URL with a random security token is printed as a QR code in the terminal
3. Scan the QR code with your phone to open the mobile web UI
4. Type or dictate text, tap SEND
5. The text is injected into your focused desktop app

## Components

| Component | Role |
|---|---|
| **Python 3 / Flask** | Lightweight HTTP server serving the mobile UI and receiving text |
| **qrcode** (Python) | Generates a scannable QR code in the terminal at startup |
| **ydotool** | Simulates keystrokes via `/dev/uinput` (works on Wayland + X11) |
| **wl-clipboard** (`wl-copy`) | Copies text to the Wayland clipboard (clipboard method) |
| **ydotoold** | Daemon required by ydotool, needs access to `/dev/uinput` |

## Installation

### From source

```bash
# System dependencies
sudo apt install ydotool wl-clipboard python3.12-venv

# Clone and set up
git clone <repo-url> && cd linux-input-from-web
python3 -m venv venv
venv/bin/pip install flask qrcode

# Run
./run.sh
```

### From .deb package

```bash
sudo apt install ./input-from-web_0.1.0_all.deb
input-from-web
```

### Building the .deb

```bash
sudo apt install debhelper dh-python
dpkg-buildpackage -us -uc -b
# Package is created in the parent directory
```

## Usage

```
./run.sh [OPTIONS]
```

### Command-line flags

| Flag | Description |
|---|---|
| `--method type` | Simulate keystrokes via ydotool (default) |
| `--method clipboard` | Copy to clipboard via wl-copy, you paste manually |
| `--port PORT` | TCP port to listen on (default: 5123) |
| `--profile NAME` | Use a named profile from the config file |

### Examples

```bash
./run.sh                          # defaults (type method, port 5123)
./run.sh --method clipboard       # clipboard only, you paste with Ctrl+Shift+V
./run.sh --port 8080              # listen on port 8080
./run.sh --profile work           # use the "work" profile from config
```

## Configuration

On first run, a config file is created at `~/.input-from-web-conf.json` with
a `default` profile. You can add more profiles and switch between them.

### Profile fields

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | `"type"` or `"clipboard"` | `"type"` | Input injection method. Overridden by `--method` |
| `auto_paste` | boolean | `false` | After clipboard copy, simulate Ctrl+V via ydotool. Only applies to `clipboard` method. Useful for GUI apps, not terminals |
| `port` | integer | `5123` | TCP port. Overridden by `--port` |
| `use_security_token` | boolean | `true` | Require secret token in URL. **Only disable on trusted networks** |
| `voice_send` | object | (see below) | Voice command auto-trigger settings |
| `substitutions` | object | (see below) | Word/phrase replacement map |

### voice_send

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `true` | Enable voice command detection |
| `delay_seconds` | number | `1.5` | Seconds to wait after last edit before triggering |
| `send_words` | string[] | `["send"]` | Words that trigger auto-send when typed last |
| `clear_words` | string[] | `["clear"]` | Words that trigger auto-clear when typed last |

When dictating, say "send" at the end of your text. If no further edits happen for
1.5 seconds, the text (minus the command word) is automatically sent.

### substitutions

Phrases are replaced in real-time as you type. Useful for voice dictation where you
say punctuation names out loud.

Default substitutions:

| Phrase | Replacement |
|---|---|
| `full stop` | `.` |
| `question mark` | `?` |
| `exclamation mark` | `!` |
| `comma` | `,` |
| `colon` | `:` |
| `semicolon` | `;` |
| `quote` | `"` |
| `new line` | newline |
| `new paragraph` | double newline |

### Example config with multiple profiles

```json
{
  "default_profile": "default",
  "profiles": {
    "default": {
      "method": "type",
      "port": 5123,
      "use_security_token": true,
      "voice_send": {
        "enabled": true,
        "delay_seconds": 1.5,
        "send_words": ["send"],
        "clear_words": ["clear"]
      },
      "substitutions": {
        "full stop": ".",
        "question mark": "?"
      }
    },
    "quick": {
      "method": "clipboard",
      "port": 8080,
      "use_security_token": false,
      "voice_send": { "enabled": false },
      "substitutions": {}
    }
  }
}
```

## Security

By default, each session generates a random 32-character token embedded in the URL.
Only someone who scans the QR code or copies the URL from your terminal can access
the page.

Setting `use_security_token` to `false` removes this protection. A red warning is
printed at startup. Only do this on a network you fully trust — anyone on the same
network could send keystrokes to your machine.

## Requirements

- Ubuntu 24.04+ (or any Linux with Wayland)
- Python 3.12+
- ydotool + ydotoold (for keystroke injection)
- wl-clipboard (for clipboard method)
- Phone and computer on the same local network
