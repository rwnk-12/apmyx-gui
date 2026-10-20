# apmyx

A GUI-based Apple Music downloader for Atmos, Lossless, and AAC formats (needs to be built from source for MacOS, Linux).

**Get the latest Windows app from [releases](https://github.com/rwnk-12/apmyx-gui/releases)**. Please refer to the [Installation](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#installation) section before starting the GUI to avoid any errors.

## About

Easily download playlists, songs, albums, and artist discographies up to Lossless 24-bit/192kHz, and music videos up to 4K.

- **ALAC, Atmos, AAC, and music videos** download through **Wrapper Lite**, the default wrapper. One launcher installs it, no WSL or Docker needed. Setup guide for [Windows](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#wrapper-installation-windows) / [MacOS](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#wrapper-installation-macos) / [Linux](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#wrapper-installation-linux).
- **Wrapper v2 and Legacy Wrapper** are also supported if you run them yourself. See [Other Wrappers](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#other-wrappers).
- A [media user token](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#getting-your-media-user-token) is optional. It is used as a lyrics fallback, and by the Legacy Wrapper for AAC LC and music videos.

> apmyx is not affiliated with Apple Inc. It is built on publicly available open-source projects.

## Features

**Easy Search** - search songs and artists directly in the app.

<img width="1919" height="1021" alt="v1-main" src="https://github.com/user-attachments/assets/40cfb001-301a-412c-b3dd-c74ee0d7d099" />

**Quality Selection** - check available audio qualities before downloading.

<img width="1918" height="1021" alt="quality" src="https://github.com/user-attachments/assets/49b57177-2e3c-403a-80fa-4b97734a84f6" />

**Artist Discography** - download a full discography with one click.

<img width="1917" height="955" alt="artist_page" src="https://github.com/user-attachments/assets/ee4fad29-8d22-4777-aafc-8a5b464a30ef" />

**Lyrics Sync** - sync your music library with lyrics in LRC or TTML, with line or word timing and optional translation and pronunciation lines.

<img width="1912" height="984" alt="lyrics" src="https://github.com/user-attachments/assets/e00c230e-d2e3-46f3-8a39-743ce4f79a9e" />

**Selective Downloads** - pick specific tracks, albums, or music videos.

<img width="1919" height="946" alt="select" src="https://github.com/user-attachments/assets/87877732-7952-4e59-8ca4-a4121c91cf51" />

**Wrapper Status** - the badge at the top shows which wrapper is connected. Start or stop Wrapper Lite from **Settings -> Wrapper**.

## Requirements

- An **active Apple Music subscription**
- [FFmpeg](https://www.ffmpeg.org/download.html) - required for animated artwork and the ALAC integrity check
- [mp4box](https://gpac.io/downloads/gpac-nightly-builds/) and [mp4decrypt](https://www.bento4.com/downloads/) - only needed for the Legacy Wrapper and some Wrapper v2 downloads

Make sure these tools are added to your system PATH. Restart your computer after doing so.

## Getting Your Media User Token

### Method 1: Developer Tools

1. Open [music.apple.com](https://music.apple.com) and log in.
2. Open DevTools (`Ctrl+Shift+I` / `Cmd+Option+I`).
3. Go to **Application -> Storage -> Cookies -> https://music.apple.com**.
4. Find `media-user-token` and copy its value.

### Method 2: Cookie Export Extension

Install [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome) or [Export Cookies](https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/) (Firefox), export cookies from `music.apple.com`, and copy the value next to `media-user-token`.

> **Note:** Paste the token exactly as-is with no leading or trailing spaces. Extra spaces will cause errors. You can also set it manually in `config.yaml`.

## Installation

1. Download the latest release from [Releases](https://github.com/rwnk-12/apmyx-gui/releases) and extract it.
2. Install and sign in to Wrapper Lite once. See [Wrapper Installation (Windows)](https://github.com/rwnk-12/apmyx-gui?tab=readme-ov-file#wrapper-installation-windows).
3. Run `apmyx.exe`. Wrapper Lite is selected by default at `http://127.0.0.1:12340`.
4. Search for music or paste an Apple Music link, pick the quality, and download.

## Wrapper Installation (Windows)

Works on Windows 10 and 11 (x64). Nothing else needs to be installed.

1. Run `setup-wrapper-lite-qemu.cmd` from the apmyx folder.
2. Enter your Apple ID email, password, and the verification code when prompted.
3. Wait for `Wrapper Lite QEMU is ready at http://127.0.0.1:12340`. You can close the window, the wrapper keeps running in the background.

After a restart, start it again with **Start Wrapper Lite** in **Settings -> Wrapper**, or run:

```bat
setup-wrapper-lite-qemu.cmd -Action Start
```

The launcher also supports `-Action Stop`, `-Action Login`, and `-Action Status`. Turning on **Windows Hypervisor Platform** in Windows Features makes it faster, but it is not required. If it fails to start, add `-Acceleration tcg`.

## Wrapper Installation (MacOS)

Works on Apple Silicon Macs. Intel Macs are not supported, use a hosted wrapper instead.

### Step 1: Install QEMU
```bash
brew install qemu
```

### Step 2: Install and Sign In
Enter your Apple ID email, password, and the verification code when prompted.
```bash
./setup-wrapper-lite-qemu.sh
```

### Step 3: Start apmyx
```bash
git clone https://github.com/rwnk-12/apmyx-gui.git
cd apmyx-gui
pip install -r requirements.txt
python scripts/build_backends.py
python src/main.py
```

After a restart, start the wrapper with **Start Wrapper Lite** in **Settings -> Wrapper**, or run `./setup-wrapper-lite-qemu.sh --action start`.

## Wrapper Installation (Linux)

Works on x86-64 and ARM64. Needs Python 3.8 or newer.

```bash
./setup-wrapper-lite-qemu.sh
```

Enter your Apple ID email, password, and the verification code when prompted. The wrapper uses KVM when `/dev/kvm` is available. The launcher also supports `--action start`, `stop`, `login`, and `status`.

---

> To sign in again, run the launcher with `-Action Login` (Windows) or `--action login` (MacOS, Linux). Your Apple ID and password are never saved, only the wrapper session is.

---

## Other Wrappers

Choose your wrapper in **Settings -> Wrapper**.

| Wrapper | Setup | Default endpoints |
| --- | --- | --- |
| Wrapper Lite (default) | `setup-wrapper-lite-qemu.cmd` / `.sh` | `http://127.0.0.1:12340` |
| Wrapper v2 | Run [wrapper-v2](https://github.com/glomatico/wrapper-v2) yourself | `http://127.0.0.1:80`, TCP `127.0.0.1:10020` |
| Legacy Wrapper | Run [wrapper](https://github.com/zhaarey/wrapper) yourself | Decrypt `127.0.0.1:10020`, M3U8 `127.0.0.1:20020` |

For a hosted wrapper, select Wrapper Lite and enter its HTTPS URL and **Wrapper API Key** in settings. Local wrappers need neither.

## Building from Source

**Prerequisites:** Python 3.12, Go 1.23.1+, Rust, FFmpeg.

```bash
git clone https://github.com/rwnk-12/apmyx-gui.git
cd apmyx-gui

# Set up Python environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# .\venv\Scripts\activate       # Windows
pip install -r requirements.txt

# Build the backends
python scripts/build_backends.py

# Run the app
python src/main.py
```

Use `python scripts/build_backends.py --bundle` to build the standalone backend bridge.

## Support

For issues or questions, [open an issue on GitHub](https://github.com/rwnk-12/apmyx-gui/issues).

## Credits & References

- [WorldObservationLog/AppleMusicDecrypt](https://github.com/WorldObservationLog/AppleMusicDecrypt)
- [WorldObservationLog/Wrapper](https://github.com/WorldObservationLog/wrapper)
- [glomatico/gamdl](https://github.com/glomatico/gamdl)
- [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2)
- [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)
- [zhaarey/wrapper](https://github.com/zhaarey/wrapper)
- [itouakirai/go-mp4tag](https://github.com/itouakirai/go-mp4tag)
- [itouakirai/apple-music-jshook-script](https://github.com/itouakirai/apple-music-jshook-script)
