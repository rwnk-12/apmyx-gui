from decimal import Decimal, ROUND_HALF_UP
from xml.etree import ElementTree

for prefix, uri in (
    ("", "http://www.w3.org/ns/ttml"),
    ("itunes", "http://music.apple.com/lyric-ttml-internal"),
    ("ttm", "http://www.w3.org/ns/ttml#metadata"),
    ("tts", "http://www.w3.org/ns/ttml#styling"),
    ("ttp", "http://www.w3.org/ns/ttml#parameter"),
):
    ElementTree.register_namespace(prefix, uri)


def seconds(value):
    value = str(value).strip()
    for suffix, multiplier in (
        ("ms", Decimal("0.001")),
        ("s", Decimal(1)),
        ("m", Decimal(60)),
        ("h", Decimal(3600)),
    ):
        if value.endswith(suffix):
            return Decimal(value[: -len(suffix)]) * multiplier
    result = Decimal(0)
    for part in value.split(":"):
        result = result * 60 + Decimal(part)
    return result


def canonical_ttml(root):
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"p", "span"}:
            if node.text and node.text.isspace():
                node.text = None
            for child in node:
                if child.tail and child.tail.isspace():
                    child.tail = None
    return ElementTree.canonicalize(ElementTree.tostring(root, encoding="unicode"))


def lrc_time(value):
    time = seconds(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{int(time // 60):02d}:{time % 60:05.2f}"


def word_text(node):
    result = node.text or ""
    for child in node:
        if child.get("begin"):
            result += "<" + lrc_time(child.get("begin")) + ">"
        result += word_text(child) + (child.tail or "")
    return result


def local(name):
    return name.rsplit("}", 1)[-1]


def attribute(node, name):
    return next((value for key, value in node.attrib.items() if local(key) == name), None)


def extras_for(settings):
    return tuple(
        kind
        for kind, key in (("translation", "lyrics-translation"), ("pronunciation", "lyrics-pronunciation"))
        if settings.get(key, True)
    )


def extra_lines(root, key, stamp, extras):
    meta = next((node for node in root.iter() if local(node.tag) == "iTunesMetadata"), None)
    if not key or not extras or meta is None:
        return []
    lines = []
    for kind, tag in (("translation", "translation"), ("pronunciation", "transliteration")):
        if kind not in extras:
            continue
        for group in (node for node in meta.iter() if local(node.tag) == tag):
            if attribute(group, "for") == key:
                text = "".join(group.itertext()).strip()
                if kind == "translation" and attribute(meta, "type") == "replacement":
                    return [f"[{stamp}]{text}"]
                lines.append(f"[{stamp}]{text}")
                continue
            for item in group:
                if local(item.tag) == "text" and attribute(item, "for") == key:
                    lines.append(f"[{stamp}]{''.join(item.itertext()).strip()}")
    return lines


def render_lyrics(ttml, format="lrc", mode="synced", extras=()):
    root = ElementTree.fromstring(ttml)
    if mode == "unsynced":
        return "\n".join(
            "".join(node.itertext()).strip()
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "p" and "".join(node.itertext()).strip()
        )
    if format == "ttml":
        return canonical_ttml(root)
    lines = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "p":
            continue
        text = "".join(node.itertext()).strip()
        if not text:
            continue
        if node.get("begin"):
            if format == "lrc" and any(child.get("begin") for child in node.iter() if child is not node):
                text = word_text(node).strip()
                if node.get("end"):
                    text += "<" + lrc_time(node.get("end")) + ">"
            lines.append(f"[{lrc_time(node.get('begin'))}]{text}")
            if format == "lrc":
                lines.extend(extra_lines(root, attribute(node, "key"), lrc_time(node.get("begin")), extras))
        else:
            lines.append(text)
    return "\n".join(lines)
