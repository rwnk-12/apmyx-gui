APPLE_MUSIC_DECRYPT_DEFAULTS = {
    "amd-max-bit-depth": 24,
    "amd-download-timeout": 60,
    "amd-download-retries": 8,
    "amd-retry-wait": 30,
    "amd-decrypt-batch-size": 256,
    "amd-stream-decrypt": True,
    "amd-low-memory": False,
    "amd-resume-download": True,
    "amd-alac-fix": True,
    "amd-verify-integrity": False,
    "amd-mv-segment-concurrency": 4,
    "amd-mv-segment-retries": 3,
    "playlist-song-file-format": "{SongNumber}. {ArtistName} - {SongName}",
    "lyrics-mode": "synced",
    "lyrics-translation": True,
    "lyrics-pronunciation": True,
    "save-cover-file": True,
}

INTEGER_RANGES = {
    "amd-max-bit-depth": (16, 24),
    "amd-download-timeout": (0, 3600),
    "amd-download-retries": (1, 20),
    "amd-retry-wait": (1, 300),
    "amd-decrypt-batch-size": (1, 4096),
    "amd-mv-segment-concurrency": (1, 32),
    "amd-mv-segment-retries": (1, 20),
}
