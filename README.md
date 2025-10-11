# apmyx

A GUI based Apple Music downloader for Atmos, Lossless, and AAC formats.

## About

Download your playlists, songs, albums, artist discography, and Music Videos with ease.

## Features

### Easy Search
<img width="1919" height="1018" alt="search" src="https://github.com/user-attachments/assets/be03233c-c5e8-4840-8db7-d01aeacf4b21" />

Search for your favorite songs and artists directly in the app.

### Quality Selection
<img width="1919" height="978" alt="quality" src="https://github.com/user-attachments/assets/e0afdeb6-9bf7-4dd0-bc61-18114841594b" />

Check available audio qualities directly in the GUI before downloading.

### Artist Discography Download
<img width="1917" height="955" alt="artist_page" src="https://github.com/user-attachments/assets/ee4fad29-8d22-4777-aafc-8a5b464a30ef" />

Download complete artist discographies with one click.

## Download

Get the latest release from the [Releases](https://github.com/rwnk-12/apmyx-gui/releases) page.

**Note:** Extract the downloaded file using 7-Zip or WinRAR for best compatibility.

## Requirements

You need an **active Apple Music subscription** to download music.

### Getting Your Media User Token

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

**Note:** Without this token, you can only download higher quality formats like ALAC and Atmos (when using the wrapper). AAC LC and lyrics will not be available.

## Installation

### Basic Setup

1. Download the latest release from the Releases page
2. Extract the file using 7-Zip or WinRAR
3. Run the apmyx.exe file
4. Enter your Apple Music credentials

### Required Tools

You need these tools installed on your computer for apmyx to work properly.

#### Installing FFmpeg

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

#### Installing mp4box

1. Visit [GPAC Downloads](https://gpac.io/downloads/gpac-nightly-builds/)
2. Download the Windows installer
3. Install GPAC to the default location (usually **C:\Program Files\GPAC**)
4. Search for **Edit the system environment variables**
5. Click **Environment Variables**
6. Under **System variables**, select **Path** and click **Edit**
7. Click **New** and add **C:\Program Files\GPAC**
8. Click **OK** on all windows

#### Installing mp4decrypt

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

**Important:** Restart your computer after adding all tools to PATH.

## Wrapper Installation

The wrapper is only needed if you want to download these high quality formats:
* ALAC (Apple Lossless)
* Atmos
* AAC Binaural
* AAC Downmix
### Step 1: Download and Install WSL

Download the required files from the link below:

[Download AMDL WSL1 ALL IN ONE.zip](https://github.com/itouakirai/apple-music-jshook-script/releases/download/wsa/AMDL-WSL1.ALL.IN.ONE.zip)

1. Extract the downloaded zip file
2. Run the batch script named **0-1**
3. This will install WSL on your computer
4. **Important:** Restart your computer after installation completes to avoid errors

### Step 2: Install Ubuntu and Dependencies

1. After restarting, run the script named **0-2**
2. This will install Ubuntu on WSL
3. It will also install all required dependencies for the wrapper

### Step 3: Configure and Start the Wrapper

1. Open script **1** in a text editor like Notepad
2. Find the text that says "username:password" and replace it with your Apple Music credentials
   * Example: youremail@example.com:yourpassword
3. Save the file
4. Run script **1. Run Decryptor** to start the wrapper
5. Wait until you see "response type 6" in the wrapper window
6. Ignore all other scripts in the folder

### Step 4: Use apmyx GUI

Once the wrapper shows "response type 6":
1. Start the apmyx GUI application
2. You can now download music in ALAC and Atmos quality
**Note:** Keep the wrapper window open while using apmyx.

## Support
For issues or questions, please open an issue on GitHub.

## References
* [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)
* [zhaarey/wrapper](https://github.com/zhaarey/wrapper)
* [glomatico/gamdl](https://github.com/glomatico/gamdl)
* [itouakirai/apple-music-jshook-script](https://github.com/itouakirai/apple-music-jshook-script)
