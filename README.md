It's just an updated fork I created, a derivative of @rwnk-12 original code; all credit belongs to him for creating it from scratch.
# apmyx

A GUI-based Apple Music downloader for Atmos, Lossless, and AAC formats (needs to be built from source for MacOS, Linux).

**Get the latest Windows app from [releases](https://github.com/fabriguzden/apmyx-gui-Fixed/releases)**. Please refer to the [Installation](https://github.com/fabriguzden/apmyx-gui-Fixed?tab=readme-ov-file#installation) section before starting the GUI to avoid any errors.

## About

Easily download playlists, songs, albums, and artist discographies up to Lossless 24-bit/192kHz, and music videos up to 4K.

- **Music videos, lyrics, AAC LC 256** only need a [token](https://github.com/fabriguzden/apmyx-gui-Fixed/blob/master/README.md#getting-your-media-user-token), no wrapper required.
- **ALAC, Atmos, AAC Binaural, Downmix** require the wrapper. Setup guide for [MacOS](https://github.com/fabriguzden/apmyx-gui-Fixed?tab=readme-ov-file#wrapper-installation-macos) / [Windows](https://github.com/fabriguzden/apmyx-gui-Fixed?tab=readme-ov-file#wrapper-installation-windows). ([Additional MacOS guide](https://gist.github.com/mattneub/cd1d7890a5cc26e7e8053f019cb9cd54))

## Features

**Easy Search** - search songs and artists directly in the app.

<img width="1919" height="1021" alt="v1-main" src="https://github.com/user-attachments/assets/40cfb001-301a-412c-b3dd-c74ee0d7d099" />

**Quality Selection** - check available audio qualities before downloading.

<img width="1918" height="1021" alt="quality" src="https://github.com/user-attachments/assets/49b57177-2e3c-403a-80fa-4b97734a84f6" />

**Artist Discography** - download a full discography with one click.

<img width="1917" height="955" alt="artist_page" src="https://github.com/user-attachments/assets/ee4fad29-8d22-4777-aafc-8a5b464a30ef" />

**Lyrics Sync** - sync your music library with lyrics.

<img width="1912" height="984" alt="lyrics" src="https://github.com/user-attachments/assets/e00c230e-d2e3-46f3-8a39-743ce4f79a9e" />

**Selective Downloads** - pick specific tracks, albums, or music videos.

<img width="1919" height="946" alt="select" src="https://github.com/user-attachments/assets/87877732-7952-4e59-8ca4-a4121c91cf51" />

## Requirements

- An **active Apple Music subscription**
- [mp4box](https://gpac.io/downloads/gpac-nightly-builds/) - required for music video muxing and song/video tagging
- [mp4decrypt](https://www.bento4.com/downloads/) - required for music video downloads
- [FFmpeg](https://www.ffmpeg.org/download.html) - required for animated artwork

Make sure all three tools are added to your system PATH. Restart your computer after doing so.

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

1. Download the latest release from [Releases](https://github.com/fabriguzden/apmyx-gui-Fixed/releases) and extract it.
2. Run `apmyx.exe`.
3. Enter your [media user token](https://github.com/fabriguzden/apmyx-gui-Fixed?tab=readme-ov-file#getting-your-media-user-token) in settings.

## Wrapper Installation (Windows)

Only needed for **ALAC, Atmos, AAC Binaural, AAC Downmix**.

1. Download and extract [AMDL WSL1 ALL IN ONE.zip](https://github.com/itouakirai/apple-music-jshook-script/releases/download/wsa/AMDL-WSL1.ALL.IN.ONE.zip).
2. Run `0-1 Install WSL1(need to reboot later).bat` and restart your computer.
3. Run `0-2 Install Ubuntu-AMDL(only once).bat`.
4. Open `1. Run decryptor (!!!need to replace username and password in this file).bat` in Notepad, replace `username:password` with your Apple Music credentials (enclose in quotes, e.g. `"email@example.com:password"`), save, and run it.
5. Wait for `response type 6 and listening status` and keep this window open while using apmyx.

Then download and run `apmyx.exe` from [releases](https://github.com/fabriguzden/apmyx-gui-Fixed/releases), or run from source:

```bash
git clone https://github.com/fabriguzden/apmyx-gui-Fixed.git
cd apmyx-gui-Fixed
pip install -r requirements.txt
cd src
python main.py
```

## Wrapper Installation (MacOS)

Only needed for **ALAC, Atmos, AAC Binaural, AAC Downmix**.

### Step 1: Install Dependencies
```bash
brew install go gpac git docker
```

### Step 2: Login
Replace `username:password` with your Apple Music credentials (username = email).
```bash
docker run -v ./rootfs/data:/app/rootfs/data -e args="-L username:password -F" --rm ghcr.io/itouakirai/wrapper:x86
```
If 2FA is enabled, enter the verification code when prompted. A response of `type 6` means login was successful.

### Step 3: Start the Wrapper
Keep this window open while using apmyx.
```bash
docker run -v ./rootfs/data:/app/rootfs/data -p 10020:10020 -p 20020:20020 -e args="-M 20020 -H 0.0.0.0" --rm ghcr.io/itouakirai/wrapper:x86
```

### Step 4: Start apmyx
```bash
git clone https://github.com/fabriguzden/apmyx-gui-Fixed.git
cd apmyx-gui-Fixed
pip install -r requirements.txt
cd src
python main.py
```

---

> Wrapper steps 1-3 are based on the guide by [itouakirai](https://github.com/itouakirai/docs). For wrapper issues, [open an issue here](https://github.com/itouakirai/docs/issues/new?title=Issue%20on%20docs&body=Path:%20/amdl/quickstart/macos). For another detailed MacOS guide, see [this gist](https://gist.github.com/mattneub/cd1d7890a5cc26e7e8053f019cb9cd54).

---

## Building from Source

**Prerequisites:** Go 1.18+, Python 3.9+, FFmpeg, mp4box, mp4decrypt.

```bash
git clone https://github.com/fabriguzden/apmyx-gui-Fixed.git
cd apmyx-gui-Fixed/scripts

# Build Go backend
chmod +x build_go.sh
./build_go.sh

# Set up Python environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# .\venv\Scripts\activate       # Windows
pip install -r requirements.txt

# Run the app
cd src
python main.py
```

## Support

For issues or questions, [open an issue on GitHub](https://github.com/fabriguzden/apmyx-gui-Fixed/issues).

## Credits & References

- [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)
- [zhaarey/wrapper](https://github.com/zhaarey/wrapper)
- [itouakirai/apple-music-jshook-script](https://github.com/itouakirai/apple-music-jshook-script)
- [WorldObservationLog/Wrapper](https://github.com/WorldObservationLog/wrapper)
