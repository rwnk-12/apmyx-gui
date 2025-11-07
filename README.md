# apmyx

A GUI based Apple Music downloader for Atmos, Lossless, and AAC formats (needs to be built from source for MacOS, Linux).
**Get the latest Windows app from [releases](https://github.com/rwnk-12/apmyx-gui/releases)**

## About

Easily download your playlists, songs, albums, artist discographies up to Lossless 24B/192kHz, and music videos up to 4K. For music videos and AAC LC 256, you only need a **[token](https://github.com/rwnk-12/apmyx-gui/blob/master/README.md#getting-your-media-user-token-using-dev-tools)** and do not need to install the **[wrapper](https://github.com/rwnk-12/apmyx-gui/blob/master/README.md#wrapper-installation-windows)**. The **[wrapper](https://github.com/rwnk-12/apmyx-gui/blob/master/README.md#wrapper-installation-windows)** is required for ALAC, Atmos, AAC Binaural, and Downmix formats.

Some browsers may block the download and flag the zip file as harmful due to a false positive. You can also download it from [Telegram](https://t.me/apmyx/10). The file contains no malicious scripts. The warning appears because it is not signed. You can safely ignore it and select "Run Anyway" when opening the .exe file.

## Features

### Easy  Search
<img width="1919" height="1021" alt="v1-main" src="https://github.com/user-attachments/assets/40cfb001-301a-412c-b3dd-c74ee0d7d099" />

Search for your favorite songs and artists directly in the app.

### Quality Selection
<img width="1919" height="978" alt="quality" src="https://github.com/user-attachments/assets/e0afdeb6-9bf7-4dd0-bc61-18114841594b" />

Check available audio qualities directly in the GUI before downloading.

### Artist Discography Download
<img width="1917" height="955" alt="artist_page" src="https://github.com/user-attachments/assets/ee4fad29-8d22-4777-aafc-8a5b464a30ef" />

Download complete artist discographies with one click.

### Sync your Music Library with lyrics
<img width="1912" height="984" alt="lyrics" src="https://github.com/user-attachments/assets/e00c230e-d2e3-46f3-8a39-743ce4f79a9e" />

### Select your tracks, albums, music videos and download them only. 
<img width="1919" height="946" alt="select" src="https://github.com/user-attachments/assets/87877732-7952-4e59-8ca4-a4121c91cf51" />

## Requirements

You need an **active Apple Music subscription** to download music.

### Getting Your Media User Token Using Dev Tools

1. Open the Apple Music website and log in with your subscription account.

2. Open developer tools (usually Ctrl+Shift+I) and navigate to the Application tab. If the tab is not visible, click the ">>" symbol in the dev tools tabs to find it in the dropdown menu.

3. In the Application tab, expand the Storage section and select Cookies, then click on https://music.apple.com.

4. Find the cookie named `media-user-token` and copy its value.


### Getting Your Media User Token using Cookies export. 

You need a **media user token** for downloading AAC LC quality and lyrics.

**For Chrome:**

1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc?pli=1) extension.
2. Open the Apple Music website and log in to your account.
3. Click the extension icon and then the export button to save the cookies.txt file.
4. Open the file and find the line for "media-user-token".
5. Copy the long value from that line.
6. Paste the value into the apmyx settings field.

**For Firefox:**

1. Install the [Export Cookies](https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/) extension.
2. Open the Apple Music website and log in to your account.
3. Click the extension icon and choose to export cookies for music.apple.com.
4. Open the saved file and find the line for "media-user-token".
5. Copy the long value from that line.
6. Paste the value into the apmyx settings field.

**Note**: Don’t include leading or trailing spaces when pasting the token, paste it exactly (for example at end "==", not "== " ). Extra spaces will cause errors. You can also enter the token manually in config.yaml.

**Note:** Without this token, you can only download higher quality formats like ALAC and Atmos (when using the wrapper). AAC LC and lyrics will not be available.

## Installation

### Basic Setup

1. Download the latest release from the Releases page
2. Extract the file using 7-Zip or WinRAR
3. Run the apmyx.exe file
4. Enter your Apple Music credentials

### Required Tools

You need these tools installed on your computer for apmyx to work properly.

#### Installing mp4box (Required for muxing of MV and tagging)

1. Visit [GPAC Downloads](https://gpac.io/downloads/gpac-nightly-builds/)
2. Download the Windows installer
3. Install GPAC to the default location (usually **C:\Program Files\GPAC**)
4. Search for **Edit the system environment variables**
5. Click **Environment Variables**
6. Under **System variables**, select **Path** and click **Edit**
7. Click **New** and add **C:\Program Files\GPAC**
8. Click **OK** on all windows

#### Installing mp4decrypt (Required for Music Video downloads)

1. Visit [Bento4 Downloads](https://www.bento4.com/downloads/)
2. Click **Binaries for Windows 10**
3. Download and extract the zip file
4. Create a folder **C:\bento4**
5. Copy the contents to **C:\bento4**
6. Search for **Edit the system environment variables**
7. Click **Environment Variables**
8. Under **System variables**, select **Path** and click **Edit**
9. Click **New** and add **C:\bento4\bin**
10. Click **OK** on all windows

#### Installing FFmpeg (Required for animated artwork)

1. Visit the [FFmpeg download page](https://www.ffmpeg.org/download.html)
2. Click on the Windows logo
3. Click **Windows builds from gyan.dev**
4. Download **ffmpeg git full.7z** (latest version)
5. Extract the downloaded file using 7-Zip
6. Rename the extracted folder to **ffmpeg**
7. Move the folder to **C:\ffmpeg**
8. Search for **Edit the system environment variables** in Windows search
9. Click **Environment Variables**
10. Under **System variables**, select **Path** and click **Edit**
11. Click **New** and add **C:\ffmpeg\bin**
12. Click **OK** on all windows



**Important:** Restart your computer after adding all tools to PATH.

## Wrapper Installation (Windows)

The wrapper is only needed if you want to download these formats:
* ALAC (Apple Lossless)
* Atmos
* AAC Binaural
* AAC Downmix
### Step 1: Download and Install WSL

Download the required files from the link below:

[Download AMDL WSL1 ALL IN ONE.zip](https://github.com/itouakirai/apple-music-jshook-script/releases/download/wsa/AMDL-WSL1.ALL.IN.ONE.zip)

1. Extract the downloaded zip file
2. Run the batch script named **0-1 Install WSL1(need to reboot later).bat**
3. This will install WSL on your computer
4. **Important:** Restart your computer after installation completes to avoid errors

### Step 2: Install Ubuntu and Dependencies

1. After restarting, run the script named **0-2 Install Ubuntu-AMDL(only once).bat**
2. This will install Ubuntu on WSL
3. It will also install all required dependencies for the wrapper

### Step 3: Configure and Start the Wrapper

1. Open script **1. Run decryptor (!!!need to replace username and password in this file).bat** in a text editor like Notepad
2. Find the text that says "username:password" and replace it with your Apple Music credentials. Make sure to close your credentials in " " like in example.
   * Example: "youremail@example.com:yourpassword"
3. Save the file
4. Run script **1. Run decryptor (!!!need to replace username and password in this file).bat** to start the wrapper
5. Wait until you see "response type 6 and listening status" in the wrapper window
6. Ignore all other scripts in the folder

### Step 4: Start the script

Download the app for windows from releases and extract it and open apmyx.exe 

OR

From the source code:
```bash
git clone https://github.com/rwnk-12/apmyx-gui.git
cd apmyx-gui
pip install -r requirements.txt
cd src
python main.py
```
# Building from Source

For developers, contributors, or users on macOS and Linux, you can run the application directly from the source code.

## Prerequisites

Before you begin, make sure you have the following installed on your system:

- **Go**: Version 1.18 or newer. ([Download here](https://golang.org/dl/))
- **Python**: Version 3.9 or newer. ([Download here](https://www.python.org/downloads/))
- **Required Tools**: FFmpeg, mp4box, and mp4decrypt. Follow the installation steps for your OS in the Required Tools section above.

## Step-by-Step Instructions

### 1. Get the Code

Clone the project repository to your computer.

```bash
git clone https://github.com/rwnk-12/apmyx-gui.git
cd apmyx-gui
cd scripts
```

### 2. Build the Backend

This step compiles the Go program that handles all downloading and processing.

```bash
# For macOS & Linux (make the script executable first)
chmod +x build_go.sh
./build_go.sh

# For Windows (using Git Bash or WSL)
./build_go.sh
```

A `downloader` (or `downloader.exe`) file will be created in the `src/core/` directory.

### 3. Set Up the Python Environment

This creates an isolated environment and installs the Python libraries needed for the GUI.

```bash
# Create a virtual environment
python -m venv venv

# Activate the environment
# On macOS & Linux:
source venv/bin/activate

# On Windows:
.\venv\Scripts\activate

# Install the required libraries
pip install -r requirements.txt
```

### 4. Run the Application

Once the backend is built and the Python environment is set up, you can start the app.

```bash
python main.py
```

The application window should now appear.

## Support
For issues or questions, please open an issue on GitHub.

## References
* [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)
* [zhaarey/wrapper](https://github.com/zhaarey/wrapper)
* [glomatico/gamdl](https://github.com/glomatico/gamdl)
* [itouakirai/apple-music-jshook-script](https://github.com/itouakirai/apple-music-jshook-script)
