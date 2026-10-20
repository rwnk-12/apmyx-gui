import logging
from xml.etree import ElementTree


def convert_time_to_lrc(time_str):
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            minutes, seconds = int(parts[0]), float(parts[1])
        else:
            minutes, seconds = int(float(time_str) // 60), float(time_str) % 60
        return f"[{minutes:02d}:{seconds:05.2f}]"
    except (ValueError, IndexError) as e:
        logging.warning(f"Could not convert time '{time_str}': {e}")
        return None


def time_to_seconds(time_str):
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        return float(time_str)
    except:
        return 0


def get_lyrics_from_ttml(lyrics_ttml: str, lrc_format: str):
    try:
        if lrc_format == "ttml":
            return lyrics_ttml
        root = ElementTree.fromstring(lyrics_ttml)
        all_lines = []
        body = root.find("{http://www.w3.org/ns/ttml}body")
        if body is not None:
            for div in body.findall("{http://www.w3.org/ns/ttml}div"):
                for p in div.findall("{http://www.w3.org/ns/ttml}p"):
                    begin, text = p.attrib.get("begin"), "".join(p.itertext()).strip()
                    if begin and text:
                        if lrc_time := convert_time_to_lrc(begin):
                            all_lines.append((begin, lrc_time, text))

        if not all_lines:
            raise ValueError("No lyrics lines found in TTML")
        all_lines.sort(key=lambda x: time_to_seconds(x[0]))
        return "\n".join([f"{lrc_time}{text}" for _, lrc_time, text in all_lines])
    except Exception as e:
        logging.error(f"Failed to convert TTML to LRC: {e}")
        return None
