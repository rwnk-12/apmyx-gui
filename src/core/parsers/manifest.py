import base64
import json
import re


QUALITY_FIELDS = (
    "codec",
    "bitrate",
    "avgBitrate",
    "sampleRateHz",
    "bitDepth",
    "channels",
)


def merge_quality(track, quality):
    result = dict(track)
    attrs = result["attributes"] = dict(track.get("attributes", {}))
    if "audioTraits" in quality:
        attrs["audioTraits"] = sorted(
            set(attrs.get("audioTraits", [])) | set(quality["audioTraits"])
        )
    attrs.update(
        {key: quality[key] for key in QUALITY_FIELDS if quality.get(key) is not None}
    )
    return result


def parse_qualities_from_manifest(manifest_data: str) -> dict:
    traits = set()
    info = {
        "audioTraits": [],
        "codec": None,
        "bitrate": None,
        "avgBitrate": None,
        "sampleRateHz": None,
        "bitDepth": None,
        "channels": None,
    }

    for line in manifest_data.splitlines():
        if (
            line.startswith("#EXT-X-SESSION-DATA:")
            and "com.apple.hls.audioAssetMetadata" in line
        ):
            try:
                b64 = re.search(r'VALUE="([^"]+)"', line)
                if b64:
                    meta = json.loads(base64.b64decode(b64.group(1)))
                    for asset in meta.values() if isinstance(meta, dict) else []:
                        codec = (
                            asset.get("AUDIO-FORMAT-ID")
                            or asset.get("CODEC")
                            or info["codec"]
                        )
                        if codec:
                            info["codec"] = codec
                        if asset.get("IS-ATMOS") or asset.get("AUDIO-FORMAT-ID") in [
                            "ec+3",
                            "ac-4",
                        ]:
                            traits.add("atmos")
                        if asset.get("IS-SPATIAL"):
                            traits.add("spatial")
                        sr = (
                            asset.get("SAMPLE-RATE-HZ")
                            or asset.get("AUDIO-SAMPLE-RATE-HZ")
                            or asset.get("SAMPLE-RATE")
                            or asset.get("SAMPLE_RATE")
                        )
                        bd = (
                            asset.get("BITS-PER-SAMPLE")
                            or asset.get("BIT-DEPTH")
                            or asset.get("BIT_DEPTH")
                            or asset.get("BITS_PER_SAMPLE")
                        )
                        ch = asset.get("CHANNELS") or asset.get("NUM-CHANNELS")
                        if sr and not info["sampleRateHz"]:
                            info["sampleRateHz"] = int(sr)
                        if bd and not info["bitDepth"]:
                            info["bitDepth"] = int(bd)
                        if ch and not info["channels"]:
                            info["channels"] = int(ch)
            except Exception:
                pass

    stream_re = re.compile(r"#EXT-X-STREAM-INF:([^\r\n]+)")
    for m in stream_re.finditer(manifest_data):
        attrs = m.group(1)
        bw = re.search(r"BANDWIDTH=(\d+)", attrs)
        abw = re.search(r"AVERAGE-BANDWIDTH=(\d+)", attrs)
        codecs = re.search(r'CODECS="([^"]+)"', attrs)
        if bw:
            b = int(bw.group(1))
            if (info["bitrate"] or 0) < b:
                info["bitrate"] = b
        if abw:
            a = int(abw.group(1))
            if (info["avgBitrate"] or 0) < a:
                info["avgBitrate"] = a
        if codecs and not info["codec"]:
            info["codec"] = codecs.group(1)

    if "atmos" in traits:
        traits.add("spatial")
    info["audioTraits"] = list(traits)
    return info
