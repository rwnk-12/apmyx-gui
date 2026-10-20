from typing import Any, Dict, List

from backend.router.common import DEFAULTS as WRAPPER_DEFAULTS
from backend.shared.folders import default_folders
from backend.shared.settings import APPLE_MUSIC_DECRYPT_DEFAULTS, INTEGER_RANGES


DEFAULTS: Dict[str, Any] = {
    **WRAPPER_DEFAULTS,
    **APPLE_MUSIC_DECRYPT_DEFAULTS,
    'tag-options': {
        **{key: True for key in (
            'write-title', 'write-artist', 'write-album', 'write-album-artist',
            'write-composer', 'write-genre', 'write-date', 'write-copyright',
            'write-publisher', 'write-isrc', 'write-upc', 'write-disc-track',
            'write-cover', 'write-lyrics', 'write-rating', 'write-apple-ids',
        )},
    },
    'media-user-token': "", 'authorization-token': '', 'language': '',
    'lrc-type': 'lyrics', 'lrc-format': 'lrc', 'embed-lrc': True,
    'save-lrc-file': True, 'save-artist-cover': False, 'save-animated-artwork': False,
    'emby-animated-artwork': False, 'embed-cover': True, 'cover-size': '5000x5000',
    'cover-format': 'jpg', **default_folders(),
    'max-memory-limit': 256, 'decrypt-m3u8-port': '127.0.0.1:10020',
    'get-m3u8-port': '127.0.0.1:20020', 'get-m3u8-from-device': True,
    'get-m3u8-mode': 'hires', 'aac-type': 'aac-lc', 'alac-max': 192000,
    'atmos-max': 2768, 'limit-max': 200, 'check-updates': True, 'album-folder-format': '{AlbumName}',
    'playlist-folder-format': '{PlaylistName}', 'song-file-format': '{DiscNumber}-{SongNumber} {SongName}',
    'artist-folder-format': '{UrlArtistName}', 'explicit-choice': '[E]',
    'clean-choice': '[C]', 'apple-master-choice': '[M]',
    'use-songinfo-for-playlist': True, 'dl-albumcover-for-playlist': True,
    'use-song-metadata-for-playlist-numbering': False,
    'mv-audio-type': 'atmos', 'mv-max': 2160, 'storefront': '', 'preferred-quality': 'ALAC',
    'mv-file-format': '{ArtistName} - {VideoName}'
}


PARTIAL_RESET_KEYS: List[str] = [
    *APPLE_MUSIC_DECRYPT_DEFAULTS, 'tag-options',
    'get-m3u8-from-device', 'get-m3u8-mode', 'aac-type', 'alac-max', 'atmos-max',
    'lrc-type', 'lrc-format', 'embed-lrc', 'save-lrc-file', 'save-artist-cover',
    'save-animated-artwork', 'emby-animated-artwork', 'embed-cover', 'cover-size',
    'cover-format', 'album-folder-format', 'playlist-folder-format', 'song-file-format',
    'artist-folder-format', 'explicit-choice', 'clean-choice', 'apple-master-choice',
    'use-songinfo-for-playlist', 'dl-albumcover-for-playlist',
    'use-song-metadata-for-playlist-numbering',
    'mv-audio-type', 'mv-max', 'mv-file-format'
]


CATEGORIES = {
    "Wrapper": ["wrapper", "applemusicdecrypt-url", "applemusicdecrypt-api-key", "applemusicdecrypt-storefront", "wrapper-v2-url", "wrapper-v2-decrypt-host", "wrapper-v2-decrypt-port"],
    "General": [
        'storefront', 'media-user-token', 'authorization-token', 'language',
        'alac-save-folder', 'atmos-save-folder', 'aac-save-folder', 'mv-save-folder'
    ],
    "Naming Formats": [
        'song-file-format', 'playlist-song-file-format', 'mv-file-format', 'album-folder-format', 'playlist-folder-format',
        'artist-folder-format', 'explicit-choice', 'clean-choice', 'apple-master-choice'
    ],
    "Playlist Settings": [
        'use-songinfo-for-playlist', 'dl-albumcover-for-playlist',
        'use-song-metadata-for-playlist-numbering'
    ],
    "Artwork": [
        'cover-size', 'cover-format', 'embed-cover', 'save-cover-file', 'save-artist-cover',
        'save-animated-artwork', 'emby-animated-artwork'
    ],
    "Lyrics": [
        'lrc-type', 'lyrics-mode', 'lrc-format', 'embed-lrc', 'save-lrc-file',
        'lyrics-translation', 'lyrics-pronunciation'
    ],
    "Metadata Tagging": ['tag-options.' + key for key in DEFAULTS['tag-options']],
    "Audio Quality": [
        'aac-type', 'alac-max', 'amd-max-bit-depth', 'get-m3u8-mode', 'atmos-max'
    ],
    "Music Video Settings": [
        'mv-audio-type', 'mv-max', 'amd-mv-segment-concurrency', 'amd-mv-segment-retries'
    ],
    "Advanced": [
        'limit-max', 'amd-download-timeout', 'amd-download-retries', 'amd-retry-wait',
        'amd-decrypt-batch-size', 'amd-stream-decrypt', 'amd-low-memory',
        'amd-resume-download', 'amd-alac-fix', 'amd-verify-integrity',
        'max-memory-limit', 'decrypt-m3u8-port', 'get-m3u8-port', 'get-m3u8-from-device',
        'check-updates'
    ]
}


CATEGORY_ORDER: list[str] = [
    "General",
    "Naming Formats",
    "Audio Quality",
    "Artwork",
    "Lyrics",
    "Metadata Tagging",
    "Playlist Settings",
    "Music Video Settings",
    "Advanced",
]


OPTIONS = {
    'aac-type': ['AAC-LC', 'AAC', 'AAC-Binaural', 'AAC-Downmix'],
    'cover-format': ['jpg', 'png', 'original'],
    'alac-max': ['192000', '96000', '48000', '44100'],
    'atmos-max': ['2768', '2448'],
    'lrc-type': ['lyrics', 'syllable-lyrics'],
    'lyrics-mode': ['synced', 'unsynced'],
    'lrc-format': ['LRC', 'TTML'],
    'amd-max-bit-depth': ['24', '16'],
    'mv-audio-type': ['Atmos', 'AC3', 'AAC'],
    'mv-max': ['2160', '1080', '720', '480']
}


PLACEHOLDERS = {
    'album-folder-format': ['{AlbumId}', '{AlbumName}', '{ArtistName}', '{ReleaseDate}', '{ReleaseYear}', '{UPC}', '{Copyright}', '{Quality}', '{Codec}', '{Tag}', '{RecordLabel}'],
    'playlist-folder-format': ['{PlaylistId}', '{PlaylistName}', '{ArtistName}', '{Quality}', '{Codec}', '{Tag}'],
    'song-file-format': ['{SongId}', '{SongNumber}', '{SongName}', '{DiscNumber}', '{TrackNumber}', '{Quality}', '{Codec}', '{Tag}', '{ArtistName}'],
    'artist-folder-format': ['{ArtistId}', '{ArtistName}', '{UrlArtistName}'],
    'mv-file-format': ['{VideoName}', '{ArtistName}', '{VideoID}', '{ReleaseDate}', '{ReleaseYear}']
}


HELP_TEXT = {
    'playlist-song-file-format': {'tip': 'Optional playlist filename format. Leave blank to use Song File Format.'},
    'lyrics-mode': {'tip': 'Synced keeps timing. Unsynced embeds plain text and saves a .txt file.'},
    'amd-max-bit-depth': {'tip': 'Maximum ALAC bit depth. Select 16 for CD-quality depth or 24 for Hi-Res.'},
    'save-cover-file': {'tip': 'Save cover.jpg or cover.png beside the downloaded audio, independently of embedding.'},
    'amd-download-timeout': {'tip': 'Download inactivity timeout in seconds. 0 disables the timeout.'},
    'amd-download-retries': {'tip': 'Maximum attempts for failed network requests.'},
    'amd-retry-wait': {'tip': 'Maximum delay between retry attempts, in seconds.'},
    'amd-decrypt-batch-size': {'tip': 'Samples decrypted per batch. The default is 256.'},
    'amd-stream-decrypt': {'tip': 'Decrypt audio while it downloads.'},
    'amd-low-memory': {'tip': 'Use temporary files to reduce memory use during downloads and video muxing.'},
    'amd-resume-download': {'tip': 'Resume interrupted downloads from the last complete media box during retries.'},
    'amd-alac-fix': {'tip': 'Repair known ALAC packet defects after downloading.'},
    'amd-verify-integrity': {'tip': 'Treat failed integrity checks as download failures.'},
    'mv-audio-type': {'tip': 'Preferred music video audio. If a video lacks it, the best available track is used (Atmos, then AC3, then AAC).'},
    'mv-max': {'tip': 'Preferred maximum video height. If no stream fits, the best available stream is used.'},
    'amd-mv-segment-concurrency': {'tip': 'Video segments downloaded concurrently per stream, from 1 to 32.'},
    'amd-mv-segment-retries': {'tip': 'Maximum attempts for each failed video segment.'},
    'applemusicdecrypt-api-key': {
        'tip': '<b>Not needed for local wrappers.</b> Leave blank unless a hosted service requires a key.'
    },
    'applemusicdecrypt-storefront': {
        'tip': '<b>Not needed for local wrappers.</b> Storefront selection is optional.'
    },
    'storefront': {'tip': 'Region used for catalog searches. Wrapper Lite synchronizes this with an optional Wrapper storefront selection.', 'info_title': 'About Storefront', 'info_body': 'The storefront controls catalog searches and metadata. An optional storefront under Wrapper overrides this while Wrapper Lite is selected. Leaving that selection unset lets downloads use their Apple Music link region. Switching engines restores your original search storefront.'},
    'language': {
        'info_title': "Language Preference",
        'info_body': """This setting requests metadata (like song titles and lyrics) in a specific language.
<br><br>
It is <b>highly recommended</b> to leave this blank if you are unsure what it does. For most users, changing the <b>Storefront</b> is the correct way to get fully localized metadata.
<br><br>
An incorrect or unsupported language code will be ignored. For more information and a list of supported codes, please refer to this <a href="https://gist.github.com/itouakirai/c8ba9df9dc65bd300094103b058731d0" style="color: #fd576b; text-decoration: none;">link here</a>.
"""
    },
    'media-user-token': {
        'tip': "Your personal Apple Music authentication token.",
        'info_title': "Media User Token Guide",
        'info_body': """
            <div style="text-align: left; line-height: 1.5;">
            1. <b>Open</b> music.apple.com and log in.<br>
            2. <b>Open DevTools</b> (Ctrl+Shift+I / Cmd+Option+I).<br>
            3. <b>Go to</b> Application -> Storage -> Cookies -> https://music.apple.com.<br>
            4. <b>Find</b> <code>media-user-token</code> and copy its value.
            </div>
        """
    },
    'authorization-token': {'tip': 'Optional developer token override. Wrapper Lite fetches and refreshes its developer token automatically.'},
    'album-folder-format': {'tip': "Defines the name for the album's subfolder. <b>Leave this blank to NOT create an album subfolder.</b>"},
    'playlist-folder-format': {'tip': "Defines the name for the playlist's subfolder. <b>Leave this blank to NOT create a playlist subfolder.</b>"},
    'song-file-format': {'tip': "Define the file naming for downloaded songs."},
    'mv-file-format': {'tip': 'Standalone video filenames. Videos inside albums or playlists use the song naming formats.'},
    'artist-folder-format': {'tip': "Defines the artist folder structure. <b>Leave this blank to NOT create artist-specific folders.</b> This will also stop playlists from being saved inside a curator folder."},
    'decrypt-m3u8-port': {'tip': "Local port for decryption. <b>Do NOT change this unless you are sure it conflicts with another application.</b>", 'info_title': "Decryption Port", 'info_body': "The backend downloader uses this port for decrypting HLS streams. Change this only if it conflicts with another application on your system."},
    'get-m3u8-port': {'tip': "Local port for fetching manifests. <b>Do NOT change this unless you are sure it conflicts with another application.</b>"},
    'alac-max': {'tip': "Maximum sample rate for ALAC (lossless) downloads."},
    'atmos-max': {'tip': "Maximum bitrate for Dolby Atmos downloads."},
    'explicit-choice': {'tip': "Tag for explicit content. Leave blank to disable."},
    'clean-choice': {'tip': "Tag for clean content. Leave blank to disable."},
    'apple-master-choice': {'tip': "Tag for Apple Digital Masters. Leave blank to disable."},
    'aac-type': {'info_title': "AAC Audio Type", 'info_body': "AAC-LC: Standard, high-quality stereo. Best for most users.\n\nAAC-Binaural: Special mix for Spatial Audio on headphones.\n\nAAC-Downmix: A stereo version derived from a Dolby Atmos mix."},
    'lrc-format': {'tip': 'LRC supports line or word timing. TTML preserves the original timing and structure. Player support for embedded TTML varies.'},
    'use-songinfo-for-playlist': {
        'tip': "Tags songs with their original album/artist info, not playlist details.",
        'info_title': "Use Original Album Tags for Playlist Songs",
        'info_body': "When enabled, songs downloaded from a playlist will be tagged with metadata from their original album (e.g., album name, album artist, release date, copyright). If disabled, they will be tagged with the playlist's name and curator."
    },
    'dl-albumcover-for-playlist': {
        'tip': "Embeds each song's own artwork instead of the playlist's cover.",
        'info_title': "Embed Individual Song Artwork",
        'info_body': "When downloading a playlist, this option fetches and embeds the specific artwork for each individual song. If disabled, the main playlist cover art will be used for all tracks (if cover embedding is on)."
    },
    'use-song-metadata-for-playlist-numbering': {
        'tip': "Uses original disc/track numbers for file naming, not playlist order.",
        'info_title': "Use Original Track Numbering for Playlist Songs",
        'info_body': """When enabled, downloading a playlist will use the song's real disc and track number for the {DiscNumber} and {SongNumber} placeholders in your file name format.<br><br>
                     <b>Example:</b> A song is 20th in a playlist, but it's track 5 on disc 2 of its original album.
                     <ul>
                     <li><b>Disabled (Default):</b> {DiscNumber}-{SongNumber} becomes 1-20</li>
                     <li><b>Enabled:</b> {DiscNumber}-{SongNumber} becomes 2-05</li>
                     </ul>"""
    },
    'get-m3u8-from-device': {
        'info_title': "Get Manifest From Device",
        'info_body': "Enabling this option uses a connected device via the wrapper to fetch audio manifests. This method can provide access to the highest quality <b>Hi-Res Lossless (ALAC)</b> streams, which are often unavailable through the standard web API."
    }
}

HELP_TEXT.update({
    'check-updates': {'tip': 'Check GitHub for a newer apmyx release when the app starts, at most once a day.'},
    'lyrics-translation': {'tip': 'Add translated lines under each LRC line when Apple provides a translation.'},
    'lyrics-pronunciation': {'tip': 'Add romanized pronunciation lines under each LRC line when Apple provides them.'},
    'tag-options.write-title': {'tip': 'Title (©nam).'},
    'tag-options.write-date': {'tip': 'Release date (©day).'},
    'tag-options.write-publisher': {'tip': 'Record label (©pub).'},
    'tag-options.write-upc': {'tip': 'Album UPC (BARCODE).'},
    'tag-options.write-rating': {'tip': 'Explicit or clean rating (rtng).'},
    'tag-options.write-apple-ids': {'tip': 'Apple song, album, and artist IDs (cnID, plID, atID).'},
})

PLACEHOLDERS['playlist-song-file-format'] = PLACEHOLDERS['song-file-format'] + ['{PlaylistName}']

OPTION_LABELS = {
    'lrc-type': {'lyrics': 'Line lyrics', 'syllable-lyrics': 'Syllable / word lyrics'},
    'lyrics-mode': {'synced': 'Synced', 'unsynced': 'Unsynced (plain text)'},
}

LABELS = {
    'check-updates': 'Check for Updates on Startup',
    'applemusicdecrypt-url': 'Wrapper Lite HTTP URL',
    'applemusicdecrypt-api-key': 'Wrapper API Key',
    'applemusicdecrypt-storefront': 'Storefront',
    'use-songinfo-for-playlist': 'Use Original Album Tags',
    'dl-albumcover-for-playlist': 'Embed Individual Song Artwork',
    'use-song-metadata-for-playlist-numbering': 'Use Original Track Numbering',
    'emby-animated-artwork': 'Emby Animated Artwork',
    'mv-save-folder': 'Music Video Save Folder',
    'mv-file-format': 'Music Video File Format',
    'tag-options.write-rating': 'Write Content Rating',
    'tag-options.write-apple-ids': 'Write Apple IDs',
    'lyrics-translation': 'Lyrics Translation Lines',
    'lyrics-pronunciation': 'Lyrics Pronunciation Lines',
    'tag-options.write-isrc': 'Write ISRC', 'tag-options.write-upc': 'Write UPC',
    'tag-options.write-disc-track': 'Write Track / Disc Numbers',
    'lrc-type': 'Lyrics Source', 'lyrics-mode': 'Lyrics Timing',
    'lrc-format': 'Synced Lyrics Format', 'embed-lrc': 'Embed Lyrics',
    'save-lrc-file': 'Save Lyrics File', 'embed-cover': 'Embed Artwork',
    'save-cover-file': 'Save Artwork File',
    'playlist-song-file-format': 'Playlist Song File Format',
    'alac-max': 'Maximum ALAC Sample Rate', 'amd-max-bit-depth': 'Maximum ALAC Bit Depth',
    'amd-download-timeout': 'Download Timeout (seconds)',
    'amd-download-retries': 'Network Attempts',
    'amd-retry-wait': 'Maximum Retry Wait (seconds)',
    'amd-decrypt-batch-size': 'Decrypt Batch Size',
    'amd-stream-decrypt': 'Decrypt While Downloading',
    'amd-low-memory': 'Low Memory Mode',
    'amd-resume-download': 'Resume Interrupted Downloads',
    'amd-alac-fix': 'Repair ALAC Packets',
    'amd-verify-integrity': 'Fail on Integrity Errors',
    'amd-mv-segment-concurrency': 'Parallel Video Segments',
    'amd-mv-segment-retries': 'Video Segment Attempts',
    'mv-max': 'Maximum Video Height', 'mv-audio-type': 'Video Audio Format',
    'limit-max': 'Maximum Filename Length',
}
