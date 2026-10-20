"""Fragmented MV to progressive MP4, following zhaarey/apple-music-downloader
(internal/media/defrag/defrag.go and internal/media/mv/mux.go @ 4741380).

Each source trun becomes one output chunk. Sample durations, sizes, sync
flags and composition offsets are copied as-is (ctts version 1); edit lists
are kept, with a single zero-duration placeholder completed from the media
duration. Chunks are written track by track into mdat boxes below 2 GiB.
"""

import os
import struct

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"mvex", b"moof", b"traf"}
REBUILT = {b"stts", b"ctts", b"stsc", b"stsz", b"stss", b"stco", b"co64"}
MDAT_HEADER = 8
MAX_MDAT_PAYLOAD = (1 << 31) - 1 - MDAT_HEADER
STCO_LIMIT = 0xFFFFFFFF - (64 << 20)
FTYP = struct.pack(">I4s4sI4s4s", 24, b"ftyp", b"isom", 0x200, b"isom", b"iso4")


class ProgressiveError(ValueError):
    pass


def _tree(data: bytes) -> list:
    nodes, pos = [], 0
    while pos + 8 <= len(data):
        size, btype = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = len(data) - pos
        body = data[pos + header:pos + size]
        nodes.append([btype, _tree(body) if btype in CONTAINERS else body])
        pos += size
    return nodes


def _encode(nodes: list) -> bytes:
    out = bytearray()
    for btype, body in nodes:
        payload = _encode(body) if isinstance(body, list) else body
        if len(payload) + 8 > 0xFFFFFFFF:
            out += struct.pack(">I4sQ", 1, btype, len(payload) + 16) + payload
        else:
            out += struct.pack(">I4s", len(payload) + 8, btype) + payload
    return bytes(out)


def _box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, btype) + payload


def _child(nodes: list, btype: bytes):
    return next((node for node in nodes if node[0] == btype), None)


def _track_id(tkhd: bytes) -> int:
    return struct.unpack(">I", tkhd[20:24] if tkhd[0] else tkhd[12:16])[0]


def _timescale(full: bytes) -> int:
    return struct.unpack(">I", full[20:24] if full[0] else full[12:16])[0]


def _set_header_duration(full: bytes, duration: int) -> bytes:
    """mdhd/mvhd duration, upgrading to version 1 when it needs 64 bits."""
    if not full[0] and duration > 0xFFFFFFFF:
        creation, modification, timescale = struct.unpack(">III", full[4:16])
        full = b"\x01" + full[1:4] + struct.pack(">QQIQ", creation, modification, timescale, 0) + full[20:]
    out = bytearray(full)
    if out[0]:
        struct.pack_into(">Q", out, 24, duration)
    else:
        struct.pack_into(">I", out, 16, duration)
    return bytes(out)


def _set_tkhd_duration(tkhd: bytes, duration: int) -> bytes:
    if not tkhd[0] and duration > 0xFFFFFFFF:
        creation, modification, track_id, reserved = struct.unpack(">IIII", tkhd[4:20])
        tkhd = b"\x01" + tkhd[1:4] + struct.pack(">QQIIQ", creation, modification, track_id, reserved, 0) + tkhd[24:]
    out = bytearray(tkhd)
    if out[0]:
        struct.pack_into(">Q", out, 28, duration)
    else:
        struct.pack_into(">I", out, 20, duration)
    return bytes(out)


def _scale(value: int, source: int, target: int) -> int:
    if not source or not target:
        raise ProgressiveError("zero timescale")
    if value == 0 or source == target:
        return value
    quotient, remainder = divmod(value, source)
    return quotient * target + remainder * target // source


def _read_header(f, end: int):
    start = f.tell()
    head = f.read(8)
    if len(head) < 8:
        return None
    size, btype = struct.unpack(">I4s", head)
    header = 8
    if size == 1:
        size = struct.unpack(">Q", f.read(8))[0]
        header = 16
    elif size == 0:
        size = end - start
    return btype, start, header, size


def _trex_defaults(mvex) -> dict:
    defaults = {}
    for btype, body in mvex[1] if mvex else []:
        if btype == b"trex":
            track_id, description, duration, size, flags = struct.unpack(">IIIII", body[4:24])
            defaults[track_id] = (description, duration, size, flags)
    return defaults


def _parse_traf(traf: list, moof_start: int, trex: tuple):
    tfhd = _child(traf, b"tfhd")
    if tfhd is None:
        raise ProgressiveError("traf has no tfhd")
    body = tfhd[1]
    flags = int.from_bytes(body[1:4], "big")
    track_id = struct.unpack(">I", body[4:8])[0]
    pos = 8
    base = moof_start
    if flags & 0x1:
        base = struct.unpack(">Q", body[pos:pos + 8])[0]
        pos += 8
    description = trex[0]
    if flags & 0x2:
        description = struct.unpack(">I", body[pos:pos + 4])[0]
        pos += 4
    default_duration = trex[1]
    if flags & 0x8:
        default_duration = struct.unpack(">I", body[pos:pos + 4])[0]
        pos += 4
    default_size = trex[2]
    if flags & 0x10:
        default_size = struct.unpack(">I", body[pos:pos + 4])[0]
        pos += 4
    default_flags = trex[3]
    if flags & 0x20:
        default_flags = struct.unpack(">I", body[pos:pos + 4])[0]
    runs = []
    for btype, trun in traf:
        if btype != b"trun":
            continue
        version, tflags = trun[0], int.from_bytes(trun[1:4], "big")
        count = struct.unpack(">I", trun[4:8])[0]
        pos = 8
        offset = base
        if tflags & 0x1:
            offset = base + struct.unpack(">i", trun[pos:pos + 4])[0]
            pos += 4
        first_flags = None
        if tflags & 0x4:
            first_flags = struct.unpack(">I", trun[pos:pos + 4])[0]
            pos += 4
        samples = []
        for index in range(count):
            duration, size, sample_flags, cto = default_duration, default_size, None, 0
            if tflags & 0x100:
                duration = struct.unpack(">I", trun[pos:pos + 4])[0]
                pos += 4
            if tflags & 0x200:
                size = struct.unpack(">I", trun[pos:pos + 4])[0]
                pos += 4
            if tflags & 0x400:
                sample_flags = struct.unpack(">I", trun[pos:pos + 4])[0]
                pos += 4
            if tflags & 0x800:
                cto = struct.unpack(">i", trun[pos:pos + 4])[0]
                pos += 4
            if sample_flags is None:
                sample_flags = first_flags if index == 0 and first_flags is not None else default_flags
            if not size:
                raise ProgressiveError(f"track {track_id} sample {index + 1} has zero size")
            samples.append((duration, size, sample_flags, cto))
        if offset < 0:
            raise ProgressiveError(f"calculated negative media data offset {offset}")
        runs.append((offset, samples))
    groups = None
    sbgp = _child(traf, b"sbgp")
    if sbgp is not None:
        body = sbgp[1]
        grouping = body[4:8]
        if grouping not in (b"roll", b"prol"):
            pos = 8
            parameter = None
            if body[0] == 1:
                parameter = struct.unpack(">I", body[pos:pos + 4])[0]
                pos += 4
            elif body[0] > 1:
                raise ProgressiveError(f"sbgp {grouping!r} has unsupported version {body[0]}")
            count = struct.unpack(">I", body[pos:pos + 4])[0]
            pos += 4
            entries = []
            for _ in range(count):
                samples, index = struct.unpack(">II", body[pos:pos + 8])
                pos += 8
                if not samples:
                    raise ProgressiveError(f"sbgp {grouping!r} has a zero sample count")
                if index >= 65536:
                    raise ProgressiveError(f"sbgp {grouping!r} uses fragment-local sgpd entry {index - 65536}")
                entries.append((samples, index))
            groups = (grouping, body[0], body[1:4], parameter, entries)
    return track_id, description, runs, groups


def _sgpd_entries(body: bytes) -> tuple[bytes, int]:
    version = body[0]
    pos = 8 + (4 if version == 1 else 0) + (4 if version >= 2 else 0)
    return body[4:8], struct.unpack(">I", body[pos:pos + 4])[0]


def _runs(values: list) -> list:
    runs = []
    for value in values:
        if runs and runs[-1][1] == value:
            runs[-1][0] += 1
        else:
            runs.append([1, value])
    return runs


def _tables(track: dict, stsd: list, sgpds: list, offsets: list, wide: bool) -> list:
    samples = track["samples"]
    tables = [stsd]
    stts = _runs([duration for duration, _, _, _ in samples])
    tables.append([b"stts", struct.pack(">II", 0, len(stts)) + b"".join(struct.pack(">II", c, v) for c, v in stts)])
    ctts = [cto for _, _, _, cto in samples]
    if any(ctts):
        runs = _runs(ctts)
        tables.append([b"ctts", struct.pack(">II", 0x01000000, len(runs)) + b"".join(struct.pack(">Ii", c, v) for c, v in runs)])
    stsc, previous = [], None
    for number, (_, count, description) in enumerate(track["chunks"], 1):
        if (count, description) != previous:
            stsc.append((number, count, description))
            previous = count, description
    tables.append([b"stsc", struct.pack(">II", 0, len(stsc)) + b"".join(struct.pack(">III", *entry) for entry in stsc)])
    sizes = [size for _, size, _, _ in samples]
    if len(set(sizes)) == 1:
        tables.append([b"stsz", struct.pack(">III", 0, sizes[0], len(sizes))])
    else:
        tables.append([b"stsz", struct.pack(">III", 0, 0, len(sizes)) + b"".join(struct.pack(">I", s) for s in sizes)])
    sync = [index + 1 for index, (_, _, flags, _) in enumerate(samples) if not (flags >> 16) & 1]
    if len(sync) != len(samples):
        tables.append([b"stss", struct.pack(">II", 0, len(sync)) + b"".join(struct.pack(">I", n) for n in sync)])
    if wide:
        tables.append([b"co64", struct.pack(">II", 0, len(offsets)) + b"".join(struct.pack(">Q", o) for o in offsets)])
    else:
        tables.append([b"stco", struct.pack(">II", 0, len(offsets)) + b"".join(struct.pack(">I", o) for o in offsets)])
    counts = {}
    for node in sgpds:
        grouping, entries = _sgpd_entries(node[1])
        if grouping in counts:
            raise ProgressiveError(f"multiple sgpd boxes for grouping type {grouping!r}")
        counts[grouping] = entries
        tables.append(node)
    sbgps = {}
    for grouping, version, flags, parameter, samples_in_run, index in track["groups"]:
        if index and (grouping not in counts or index > counts[grouping]):
            raise ProgressiveError(f"sample group {grouping!r} references a missing sgpd entry")
        entry = sbgps.setdefault(grouping, [version, flags, parameter, []])
        if entry[:3] != [version, flags, parameter]:
            raise ProgressiveError(f"sample group {grouping!r} has inconsistent sbgp versions or flags")
        if entry[3] and entry[3][-1][1] == index:
            entry[3][-1][0] += samples_in_run
        else:
            entry[3].append([samples_in_run, index])
    for grouping, (version, flags, parameter, entries) in sbgps.items():
        body = bytes([version]) + flags + grouping
        if version == 1:
            body += struct.pack(">I", parameter)
        body += struct.pack(">I", len(entries)) + b"".join(struct.pack(">II", c, i) for c, i in entries)
        tables.append([b"sbgp", body])
    return tables


def _track_duration(trak: list, movie_scale: int, media_scale: int, media_duration: int) -> int:
    edts = _child(trak, b"edts")
    if edts is None:
        return _scale(media_duration, media_scale, movie_scale)
    total, zero = 0, []
    for node in edts[1]:
        if node[0] != b"elst":
            continue
        body = bytearray(node[1])
        version = body[0]
        count = struct.unpack(">I", body[4:8])[0]
        step = 20 if version == 1 else 12
        for index in range(count):
            pos = 8 + index * step
            duration = struct.unpack(">Q" if version == 1 else ">I", body[pos:pos + (8 if version == 1 else 4)])[0]
            if duration == 0:
                zero.append((node, pos, version))
            else:
                total += duration
    if total:
        return total
    if len(zero) != 1:
        raise ProgressiveError(f"edit list has {len(zero)} zero-duration entries; cannot determine presentation duration")
    node, pos, version = zero[0]
    if version == 1:
        media_time = struct.unpack(">q", node[1][pos + 8:pos + 16])[0]
        rate = struct.unpack(">hh", node[1][pos + 16:pos + 20])
    else:
        media_time = struct.unpack(">i", node[1][pos + 4:pos + 8])[0]
        rate = struct.unpack(">hh", node[1][pos + 8:pos + 12])
    if media_time < 0 or rate != (1, 0):
        raise ProgressiveError("zero-duration edit list placeholder is not a forward media edit")
    if media_time > media_duration:
        raise ProgressiveError(f"edit list media time {media_time} exceeds media duration {media_duration}")
    segment = _scale(media_duration - media_time, media_scale, movie_scale)
    if not segment:
        raise ProgressiveError("edit list presentation duration rounds to zero")
    body = bytearray(node[1])
    if version == 1:
        struct.pack_into(">Q", body, pos, segment)
    else:
        if segment > 0xFFFFFFFF:
            raise ProgressiveError("edit list duration needs a version 1 elst")
        struct.pack_into(">I", body, pos, segment)
    node[1] = bytes(body)
    return segment


def defragment(in_path: str, out_path: str) -> int:
    """Rewrite the fragmented MP4 at *in_path* as a progressive MP4."""
    end = os.path.getsize(in_path)
    moov = None
    fragments = []
    with open(in_path, "rb") as f:
        while True:
            header = _read_header(f, end)
            if header is None:
                break
            btype, start, header_size, size = header
            if btype == b"moov":
                f.seek(start + header_size)
                moov = _tree(f.read(size - header_size))
            elif btype == b"moof":
                f.seek(start + header_size)
                fragments.append((start, _tree(f.read(size - header_size))))
            elif btype == b"mdat" and fragments and len(fragments[-1]) == 2:
                fragments[-1] += ((start + header_size, start + size),)
            f.seek(start + size)
    if moov is None or _child(moov, b"mvhd") is None:
        raise ProgressiveError("fragmented MP4 has no initialization moov")
    mvex = _child(moov, b"mvex")
    if mvex is None:
        raise ProgressiveError("input is not a fragmented MP4")
    defaults = _trex_defaults(mvex)
    traks = [node for node in moov if node[0] == b"trak"]
    tracks = {}
    for trak in traks:
        track_id = _track_id(_child(trak[1], b"tkhd")[1])
        if track_id not in defaults:
            raise ProgressiveError(f"track {track_id} has no trex")
        tracks[track_id] = {"samples": [], "chunks": [], "sources": [], "groups": [], "duration": 0}

    for fragment in fragments:
        if len(fragment) != 3:
            raise ProgressiveError("fragment is missing moof or mdat")
        moof_start, moof, (mdat_start, mdat_end) = fragment
        for node in moof:
            if node[0] != b"traf":
                continue
            track_id = struct.unpack(">I", _child(node[1], b"tfhd")[1][4:8])[0]
            if track_id not in tracks:
                raise ProgressiveError(f"traf references unknown track {track_id}")
            track = tracks[track_id]
            _, description, runs, groups = _parse_traf(node[1], moof_start, defaults[track_id])
            if not description:
                raise ProgressiveError(f"track {track_id} has sample description index 0")
            first = len(track["samples"])
            for offset, samples in runs:
                if not samples:
                    continue
                size = sum(sample[1] for sample in samples)
                if offset < mdat_start or offset + size > mdat_end:
                    raise ProgressiveError(f"track {track_id} sample data is outside its mdat box")
                track["samples"].extend(samples)
                track["duration"] += sum(sample[0] for sample in samples)
                track["chunks"].append([size, len(samples), description])
                track["sources"].append((offset, size))
            if groups is not None:
                grouping, version, flags, parameter, entries = groups
                if sum(count for count, _ in entries) != len(track["samples"]) - first:
                    raise ProgressiveError(f"sbgp {grouping!r} does not cover its fragment")
                track["groups"] += [(grouping, version, flags, parameter, count, index) for count, index in entries]

    ranges = sorted(source for track in tracks.values() for source in track["sources"])
    for (a_start, a_size), (b_start, _) in zip(ranges, ranges[1:]):
        if a_start + a_size > b_start:
            raise ProgressiveError("source sample ranges overlap")

    mvhd = _child(moov, b"mvhd")
    movie_scale = _timescale(mvhd[1])
    movie_duration = 0
    stsds, sgpds = {}, {}
    for trak in traks:
        children = trak[1]
        track_id = _track_id(_child(children, b"tkhd")[1])
        track = tracks[track_id]
        if not track["samples"]:
            raise ProgressiveError(f"track {track_id} contains no samples")
        mdia = _child(children, b"mdia")
        mdhd = _child(mdia[1], b"mdhd")
        stbl = _child(_child(mdia[1], b"minf")[1], b"stbl")
        media_scale = _timescale(mdhd[1])
        if not media_scale:
            raise ProgressiveError(f"track {track_id} has zero timescale")
        stsd = _child(stbl[1], b"stsd")
        if stsd is None:
            raise ProgressiveError(f"track {track_id} has no stsd")
        entries = struct.unpack(">I", stsd[1][4:8])[0]
        for chunk in track["chunks"]:
            if chunk[2] > entries:
                if entries != 1:
                    raise ProgressiveError(f"track {track_id} references sample description {chunk[2]}, but stsd has {entries} entries")
                chunk[2] = 1
        kept = []
        for child in stbl[1]:
            if child[0] == b"sgpd":
                kept.append(child)
            elif child[0] not in REBUILT | {b"stsd", b"sbgp"}:
                raise ProgressiveError(f"track {track_id} has unsupported stbl child {child[0]!r}")
        stsds[track_id], sgpds[track_id] = stsd, kept
        mdhd[1] = _set_header_duration(mdhd[1], track["duration"])
        duration = _track_duration(children, movie_scale, media_scale, track["duration"])
        tkhd = _child(children, b"tkhd")
        tkhd[1] = _set_tkhd_duration(tkhd[1], duration)
        movie_duration = max(movie_duration, duration)
    mvhd[1] = _set_header_duration(mvhd[1], movie_duration)
    moov[:] = [node for node in moov if node[0] != b"mvex"]

    mdats, current = [], 0
    for trak in traks:
        for size, _, _ in tracks[_track_id(_child(trak[1], b"tkhd")[1])]["chunks"]:
            if size > MAX_MDAT_PAYLOAD:
                raise ProgressiveError("chunk exceeds the mdat size limit")
            if current and current + size > MAX_MDAT_PAYLOAD:
                mdats.append(current)
                current = 0
            current += size
    mdats.append(current)

    def layout(wide: bool) -> tuple[bytes, int]:
        offsets = {}
        for trak in traks:
            track_id = _track_id(_child(trak[1], b"tkhd")[1])
            stbl = _child(_child(_child(trak[1], b"mdia")[1], b"minf")[1], b"stbl")
            stbl[1] = _tables(tracks[track_id], stsds[track_id], sgpds[track_id], [0] * len(tracks[track_id]["chunks"]), wide)
        position = len(FTYP) + len(_box(b"moov", _encode(moov))) + MDAT_HEADER
        filled, highest = 0, 0
        for trak in traks:
            track_id = _track_id(_child(trak[1], b"tkhd")[1])
            offsets[track_id] = []
            for size, _, _ in tracks[track_id]["chunks"]:
                if filled and filled + size > MAX_MDAT_PAYLOAD:
                    position += MDAT_HEADER
                    filled = 0
                filled += size
                offsets[track_id].append(position)
                highest = max(highest, position)
                position += size
        for trak in traks:
            track_id = _track_id(_child(trak[1], b"tkhd")[1])
            stbl = _child(_child(_child(trak[1], b"mdia")[1], b"minf")[1], b"stbl")
            stbl[1] = _tables(tracks[track_id], stsds[track_id], sgpds[track_id], offsets[track_id], wide)
        return _box(b"moov", _encode(moov)), highest

    new_moov, highest = layout(False)
    if highest > STCO_LIMIT:
        new_moov, _ = layout(True)

    with open(in_path, "rb") as src, open(out_path, "wb") as dst:
        dst.write(FTYP)
        dst.write(new_moov)
        remaining, index = 0, 0
        for trak in traks:
            track = tracks[_track_id(_child(trak[1], b"tkhd")[1])]
            for offset, size in track["sources"]:
                if not remaining:
                    remaining = mdats[index]
                    index += 1
                    dst.write(struct.pack(">I4s", remaining + MDAT_HEADER, b"mdat"))
                src.seek(offset)
                left = size
                while left:
                    block = src.read(min(left, 1 << 20))
                    if not block:
                        raise ProgressiveError("sample data ended early")
                    dst.write(block)
                    left -= len(block)
                remaining -= size
        return dst.tell()
