"""Pure-Python MP4 muxer: merge an MV's video and audio fragmented streams into
one MP4 file for MV remuxing.

Both input streams are already-decrypted fragmented MP4s (init + moof/mdat
fragments). The merged output keeps every fragment's moof/tfdt/trun intact
(only the traf ``tfhd.track_ID`` is renumbered) and interleaves fragments by
decode time, so no re-encoding is needed.

Two entry points:
- :func:`mux_mv` - in-memory (small MVs).
- :func:`mux_mv_streamed` - low-memory mode: fragments live in a
  :class:`FragmentStore` on disk and the output is written incrementally.
"""

import struct

from applemusicdecrypt.mp4 import (parse_init, _box_header, _iter_children, patch_moof_track_id,
                     parse_fragment_timing, patch_tkhd_track_id, patch_trex_track_id,
                     patch_mvhd_duration, read_mvhd_timescale_duration, read_trak_timescale)


class FragmentStore:
    """Disk-backed store of renumbered, decrypted MV fragments.

    ``add(kind, fragment_bytes, time_sec, timescale)`` appends the fragment
    to a temp file and records decode info. :meth:`iter_sorted` yields the
    fragments in decode-time order (kind 0 = video first on ties).

    After all fragments are added, call :meth:`normalize_timestamps` to
    rewrite every tfdt so each stream starts at 0 (Apple MV fragments
    typically begin ~10s in, which confuses players like VLC).
    """

    def __init__(self, temp_path: str):
        self._path = temp_path
        self._f = open(temp_path, "w+b")
        self._entries = []  # (time_sec, kind, offset, length, timescale)

    def add(self, kind: int, fragment_bytes: bytes, time_sec: float,
            timescale: int = 90000):
        off = self._f.tell()
        self._f.write(fragment_bytes)
        self._entries.append((time_sec, kind, off, len(fragment_bytes),
                              timescale))

    def iter_sorted(self):
        for time_sec, kind, off, ln, _ts in sorted(
                self._entries, key=lambda e: (e[0], e[1])):
            self._f.seek(off)
            yield time_sec, kind, self._f.read(ln)

    def normalize_timestamps(self) -> None:
        """Rewrite each stored fragment's tfdt so every stream starts at 0."""
        from applemusicdecrypt.mp4 import parse_fragment_timing, patch_tfdt_delta

        # Find the minimum tfdt per stream kind.
        mins: dict[int, int | None] = {0: None, 1: None}
        for _t, kind, off, ln, _ts in self._entries:
            self._f.seek(off)
            _, tfdt = parse_fragment_timing(self._f.read(ln))
            if tfdt is not None:
                cur = mins.get(kind)
                if cur is None or tfdt < cur:
                    mins[kind] = tfdt

        # Rewrite every fragment with its stream's delta, recomputing time_sec.
        new_entries = []
        for time_sec, kind, off, ln, ts in self._entries:
            self._f.seek(off)
            data = self._f.read(ln)
            base = mins.get(kind)
            if base:
                data = patch_tfdt_delta(data, base)
                ln = len(data)
                _, tfdt = parse_fragment_timing(data)
                if tfdt is not None:
                    time_sec = tfdt / ts
                self._f.seek(off)
                self._f.write(data)
            new_entries.append((time_sec, kind, off, ln, ts))
        self._entries = new_entries

    def close(self):
        self._f.flush()
        self._f.close()

    def __del__(self):
        try:
            self._f.close()
        except Exception:
            pass


def _top_boxes(data: bytes) -> list[tuple[bytes, int, int]]:
    out = []
    pos = 0
    while pos + 8 <= len(data):
        btype, size, header_size, _ = _box_header(data, pos, len(data))
        if size < 8 or pos + size > len(data):
            break
        out.append((btype, pos, size))
        pos += size
    return out


def _read_tkhd_track_id(trak: bytes) -> int:
    try:
        _, tsize, theader, _ = _box_header(trak, 0, len(trak))
    except Exception:
        return 0
    for child in _iter_children(trak, theader, tsize):
        if child.type == b"tkhd":
            vaf = struct.unpack(">I", trak[child.payload_start:child.payload_start + 4])[0]
            version = vaf >> 24
            off = child.start + 8 + 4 + (8 if version == 1 else 4) * 2
            return struct.unpack(">I", trak[off:off + 4])[0]
    return 0


def _split_moov(moov: bytes):
    mvhd = None
    traks = []
    mvex = None
    rest = []
    try:
        _, msize, mheader, _ = _box_header(moov, 0, len(moov))
    except Exception:
        return None, [], None, []
    for child in _iter_children(moov, mheader, msize):
        raw = bytes(moov[child.start:child.end])
        if child.type == b"mvhd":
            mvhd = raw
        elif child.type == b"trak":
            traks.append(raw)
        elif child.type == b"mvex":
            mvex = raw
        else:
            rest.append(raw)
    return mvhd, traks, mvex, rest


def _box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), btype) + payload


def _handler_type(trak: bytes) -> bytes:
    try:
        _, tsize, theader, _ = _box_header(trak, 0, len(trak))
        for child in _iter_children(trak, theader, tsize):
            if child.type == b"mdia":
                for sub in _iter_children(trak, child.payload_start, child.end):
                    if sub.type == b"hdlr":
                        return bytes(trak[sub.payload_start + 8:sub.payload_start + 12])
    except Exception:
        pass
    return b""


def patch_track_ids(box: bytes, mapping: dict[int, int], container: bytes, child: bytes) -> bytes:
    """Rewrite the track ID of every ``container/child`` (moof/traf/tfhd or
    mvex/trex) through *mapping* in one pass, so renumbered IDs never collide."""
    out = bytearray(box)
    try:
        _, size, header_size, _ = _box_header(box, 0, len(box))
    except Exception:
        return box
    if container == b"mvex":
        for item in _iter_children(box, header_size, size):
            if item.type == child:
                old = struct.unpack(">I", box[item.payload_start + 4:item.payload_start + 8])[0]
                if old in mapping:
                    struct.pack_into(">I", out, item.payload_start + 4, mapping[old])
        return bytes(out)
    for traf in _iter_children(box, header_size, size):
        if traf.type != b"traf":
            continue
        for item in _iter_children(box, traf.payload_start, traf.end):
            if item.type == child:
                old = struct.unpack(">I", box[item.payload_start + 4:item.payload_start + 8])[0]
                if old in mapping:
                    struct.pack_into(">I", out, item.payload_start + 4, mapping[old])
    return bytes(out)


def build_container(video_init, audio_init):
    """Build the merged ftyp + moov and return the info needed to place
    fragments: ``(ftyp, moov, video_map, audio_map, v_ts_sec, a_ts_sec)``.

    Track IDs follow zhaarey/apple-music-downloader: the video track is 1,
    the audio track is 2 and any other track in the video stream (captions,
    for example) is kept and renumbered from 3.
    """
    vtop = _top_boxes(video_init.output_init)
    atop = _top_boxes(audio_init.output_init)
    ftyp = bytes(video_init.output_init[0:vtop[0][2]]) if vtop else b""
    vmoov = next((bytes(video_init.output_init[s:s + sz]) for b, s, sz in vtop if b == b"moov"), b"")
    amoov = next((bytes(audio_init.output_init[s:s + sz]) for b, s, sz in atop if b == b"moov"), b"")

    v_mvhd, v_traks, v_mvex, v_rest = _split_moov(vmoov)
    a_mvhd, a_traks, a_mvex, _a_rest = _split_moov(amoov)
    if v_mvhd is None:
        raise ValueError("mux: need a video mvhd")
    video = [trak for trak in v_traks if _handler_type(trak) == b"vide"]
    audio = [trak for trak in a_traks if _handler_type(trak) == b"soun"]
    if len(video) != 1 or len(audio) != 1:
        raise ValueError("mux: expected exactly one video and one audio track")

    video_map, next_id = {}, 3
    for trak in v_traks:
        old = _read_tkhd_track_id(trak)
        if trak is video[0]:
            video_map[old] = 1
        else:
            video_map[old] = next_id
            next_id += 1
    audio_map = {_read_tkhd_track_id(audio[0]): 2}

    traks = [patch_tkhd_track_id(trak, video_map[_read_tkhd_track_id(trak)]) for trak in v_traks]
    traks.append(patch_tkhd_track_id(audio[0], 2))

    trexes = []
    for mvex, mapping in ((v_mvex, video_map), (a_mvex, audio_map)):
        if mvex is None:
            continue
        patched = patch_track_ids(mvex, mapping, b"mvex", b"trex")
        _, msize, mheader, _ = _box_header(patched, 0, len(patched))
        for child in _iter_children(patched, mheader, msize):
            raw = bytes(patched[child.start:child.end])
            if child.type != b"trex" or struct.unpack(">I", raw[12:16])[0] in set(mapping.values()):
                trexes.append(raw)
    mvex = _box(b"mvex", b"".join(trexes)) if trexes else None

    v_ts, v_dur = read_mvhd_timescale_duration(v_mvhd)
    a_ts, a_dur = read_mvhd_timescale_duration(a_mvhd)
    new_dur = v_dur
    if v_ts and a_ts:
        new_dur = max(v_dur, int(a_dur * v_ts / a_ts))
    mvhd = bytearray(patch_mvhd_duration(v_mvhd, new_dur))
    next_offset = len(mvhd) - 4
    if struct.unpack(">I", mvhd[next_offset:])[0] < next_id:
        struct.pack_into(">I", mvhd, next_offset, next_id)

    moov_payload = bytes(mvhd) + b"".join(traks)
    if mvex is not None:
        moov_payload += mvex
    for r in v_rest:
        moov_payload += r
    moov = _box(b"moov", moov_payload)

    v_ts_sec = read_trak_timescale(traks[v_traks.index(video[0])]) or 90000
    a_ts_sec = read_trak_timescale(traks[-1]) or 48000
    return ftyp, moov, video_map, audio_map, v_ts_sec, a_ts_sec


def fragment_entry(fragment_bytes: bytes, mapping: dict[int, int],
                   timescale: int, kind: int):
    """Renumber a fragment's track IDs and return (time_sec, kind, bytes)."""
    _, tfdt = parse_fragment_timing(fragment_bytes)
    frag = patch_track_ids(fragment_bytes, mapping, b"moof", b"tfhd")
    return (tfdt or 0) / timescale, kind, frag


def mux_mv(video_init, audio_init,
           video_frags: list[bytes], audio_frags: list[bytes]) -> bytes:
    """In-memory merge (small MVs): returns the whole muxed MP4 as bytes."""
    ftyp, moov, v_map, a_map, v_ts, a_ts = build_container(video_init, audio_init)
    entries = [fragment_entry(f, v_map, v_ts, 0) for f in video_frags]
    entries += [fragment_entry(f, a_map, a_ts, 1) for f in audio_frags]
    entries.sort(key=lambda e: (e[0], e[1]))
    out = bytearray(ftyp)
    out.extend(moov)
    for _, _, frag in entries:
        out.extend(frag)
    return bytes(out)


def mux_mv_streamed(video_init, audio_init, store: FragmentStore, out_path: str):
    """Low-memory merge: read renumbered fragments from a disk ``store`` and
    write the merged MP4 incrementally to ``out_path``."""
    ftyp, moov, _v_map, _a_map, _v_ts, _a_ts = build_container(video_init, audio_init)
    with open(out_path, "wb") as f:
        f.write(ftyp)
        f.write(moov)
        for _, _, frag in store.iter_sorted():
            f.write(frag)