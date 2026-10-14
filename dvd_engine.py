"""
dvd_engine.py - DVD-Video Detection, Parsing, and Extraction Backend
Part of Disc Ripper Pro v2.0.0

Provides robust, Windows-compatible inspection of DVD-Video (VIDEO_TS) structures,
parsing of IFO tables (VMGI and VTSI), chapter and stream discovery,
and generation of safe FFmpeg / HandBrake commands for DVD ripping.
"""

import os
import sys
import shutil
import struct
import json
import subprocess
import tempfile
import time
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


def get_subprocess_kwargs(extra_flags: int = 0) -> Dict[str, Any]:
    """
    Returns platform-specific kwargs to completely suppress console window creation
    and hide child process windows on Windows from a GUI / portable application.
    """
    kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if extra_flags:
            creation_flags |= extra_flags
        kwargs["creationflags"] = creation_flags

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return kwargs


# ─────────────────────────────────────────────
#  ISO 639-1 Language Mapping
# ─────────────────────────────────────────────
ISO_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "eng": "English",
    "zh": "Chinese",
    "zho": "Chinese",
    "chi": "Chinese",
    "yue": "Cantonese",
    "es": "Spanish",
    "spa": "Spanish",
    "fr": "French",
    "fra": "French",
    "fre": "French",
    "de": "German",
    "deu": "German",
    "ger": "German",
    "ja": "Japanese",
    "jpn": "Japanese",
    "ko": "Korean",
    "kor": "Korean",
    "it": "Italian",
    "ita": "Italian",
    "pt": "Portuguese",
    "por": "Portuguese",
    "ru": "Russian",
    "rus": "Russian",
    "nl": "Dutch",
    "nld": "Dutch",
    "dut": "Dutch",
    "hi": "Hindi",
    "hin": "Hindi",
    "ar": "Arabic",
    "ara": "Arabic",
    "th": "Thai",
    "tha": "Thai",
    "vi": "Vietnamese",
    "vie": "Vietnamese",
    "ms": "Malay",
    "msa": "Malay",
    "may": "Malay",
    "id": "Indonesian",
    "ind": "Indonesian",
    "tl": "Tagalog",
    "tgl": "Tagalog",
    "pl": "Polish",
    "pol": "Polish",
    "sv": "Swedish",
    "swe": "Swedish",
    "da": "Danish",
    "dan": "Danish",
    "no": "Norwegian",
    "nor": "Norwegian",
    "fi": "Finnish",
    "fin": "Finnish",
    "el": "Greek",
    "ell": "Greek",
    "gre": "Greek",
    "tr": "Turkish",
    "tur": "Turkish",
    "cs": "Czech",
    "ces": "Czech",
    "cze": "Czech",
    "hu": "Hungarian",
    "hun": "Hungarian",
    "ro": "Romanian",
    "ron": "Romanian",
    "rum": "Romanian",
    "und": "Undetermined",
}


def get_language_name(code: str) -> str:
    """Return friendly language name for a 2 or 3-letter language code."""
    if not code:
        return ""
    clean = code.strip().lower()
    return ISO_LANGUAGES.get(clean, clean.upper() if len(clean) <= 3 else clean)


def bcd_to_int(b: int) -> int:
    """Decode an 8-bit Binary Coded Decimal value to an integer with validity check."""
    hi = (b >> 4) & 0x0F
    lo = b & 0x0F
    if hi > 9 or lo > 9:
        return 0
    return hi * 10 + lo


# ─────────────────────────────────────────────
#  DVD Title Data Model
# ─────────────────────────────────────────────
def sanitize_filename(name: str, fallback: str = "Title") -> str:
    """Sanitize string for Windows filename safety."""
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')
    return cleaned if cleaned else fallback


@dataclass
class DVDAudioTrack:
    track_id: str                      # Stable identifier: e.g. "T01_A01"
    title_number: int                  # Title association, e.g. 1
    track_number: int                  # 1-based track number for display and HandBrakeCLI: 1, 2, ...
    stream_index: int                  # 0-based relative audio stream index for FFmpeg: 0, 1, ...
    codec: str = "AC-3"                # Codec: "AC-3", "DTS", "LPCM", "MPEG Audio", "AAC", etc.
    channels: str = "Stereo"           # Channel layout: "Stereo", "5.1", "Mono", etc.
    channel_count: int = 2             # 2, 6, 1, etc.
    lang_code: str = "und"             # "en", "zh", "und", etc.
    lang_name: str = "Unknown Language"# "English", "Chinese", "Unknown Language", etc.
    sample_rate: int = 48000           # Sample rate in Hz
    bitrate: int = 0                   # Bitrate in bps
    hb_track_index: int = 1            # HandBrakeCLI track number (1-based)
    ffmpeg_stream_index: int = 0       # FFmpeg audio stream index (0-based)
    source_id: str = ""                # Source stream ID e.g. "0x80"

    def display_label(self) -> str:
        """
        Generate human-readable label matching requirement:
        e.g. 'Track 1 — Chinese — AC-3 — Stereo'
             'Track 2 — English — AC-3 — 5.1'
             'Track 3 — Unknown Language — LPCM — Stereo'
        """
        parts = [f"Track {self.track_number}"]
        if self.lang_name and self.lang_name.lower() not in ("undetermined", "unknown", "und"):
            parts.append(self.lang_name)
        else:
            parts.append("Unknown Language")
        if self.codec:
            parts.append(self.codec)
        if self.channels:
            parts.append(self.channels)
        return " — ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "title_number": self.title_number,
            "track_number": self.track_number,
            "stream_index": self.stream_index,
            "codec": self.codec,
            "format": self.codec,
            "channels": self.channels,
            "channel_count": self.channel_count,
            "lang": self.lang_code,
            "lang_code": self.lang_code,
            "lang_name": self.lang_name,
            "sample_rate": self.sample_rate,
            "bitrate": self.bitrate,
            "hb_track_index": self.hb_track_index,
            "ffmpeg_stream_index": self.ffmpeg_stream_index,
            "source_id": self.source_id,
            "display_label": self.display_label(),
        }


def normalize_audio_track(
    title_number: int,
    track_number: int,
    stream_index: int,
    raw_codec: str,
    raw_channels: Any,
    raw_lang: str,
    raw_lang_name: Optional[str] = None,
    sample_rate: int = 48000,
    bitrate: int = 0,
    hb_track_index: Optional[int] = None,
    ffmpeg_stream_index: Optional[int] = None,
    source_id: str = "",
) -> DVDAudioTrack:
    # 1. Codec
    c = str(raw_codec or "").strip()
    c_lower = c.lower()
    if "ac3" in c_lower or "ac-3" in c_lower or "a52" in c_lower:
        codec = "AC-3"
    elif "dts" in c_lower:
        codec = "DTS"
    elif "lpcm" in c_lower or "pcm" in c_lower:
        codec = "LPCM"
    elif "mp2" in c_lower or "mp3" in c_lower or "mpeg" in c_lower:
        codec = "MPEG Audio"
    elif "aac" in c_lower:
        codec = "AAC"
    elif c:
        codec = c.upper()
    else:
        codec = "AC-3"

    # 2. Channels
    ch_raw = str(raw_channels or "").strip()
    ch_lower = ch_raw.lower()
    if ch_raw in ("6", "5.1") or "5.1" in ch_raw or "6 ch" in ch_lower or "6ch" in ch_lower:
        channels = "5.1"
        ch_count = 6
    elif ch_raw in ("1", "1.0") or "mono" in ch_lower or "1 ch" in ch_lower or "1ch" in ch_lower:
        channels = "Mono"
        ch_count = 1
    elif ch_raw in ("2", "2.0") or "stereo" in ch_lower or "2 ch" in ch_lower or "2ch" in ch_lower:
        channels = "Stereo"
        ch_count = 2
    elif ch_raw in ("3", "3.0") or "3 ch" in ch_lower:
        channels = "3.0"
        ch_count = 3
    elif ch_raw in ("4", "4.0") or "4 ch" in ch_lower:
        channels = "4.0"
        ch_count = 4
    elif ch_raw in ("5", "5.0") or "5 ch" in ch_lower:
        channels = "5.0"
        ch_count = 5
    elif ch_raw.isdigit():
        ch_count = int(ch_raw)
        channels = f"{ch_count}.0"
    else:
        channels = "Stereo"
        ch_count = 2

    # 3. Language
    l_code = (raw_lang or "").strip().lower()
    if l_code in ("\x00\x00", "00", "--", "und", "unknown", "undetermined", ""):
        l_code = "und"
    
    l_name = raw_lang_name.strip() if raw_lang_name else ""
    if not l_name or l_name.lower() in ("undetermined", "unknown", "und") or len(l_name) <= 3:
        lookup_name = get_language_name(l_name) if (l_name and len(l_name) <= 3 and l_name.lower() not in ("und", "unknown")) else ""
        if lookup_name and len(lookup_name) > 3 and lookup_name.lower() not in ("undetermined", "unknown", "und"):
            l_name = lookup_name
        else:
            lookup = get_language_name(l_code)
            if lookup and len(lookup) > 3 and lookup.lower() not in ("undetermined", "unknown", "und"):
                l_name = lookup
            elif l_name and l_name.lower() not in ("undetermined", "unknown", "und"):
                pass
            else:
                l_name = "Unknown Language"

    hb_idx = int(hb_track_index) if hb_track_index is not None else int(track_number)
    ff_idx = int(ffmpeg_stream_index) if ffmpeg_stream_index is not None else int(stream_index)
    track_id = f"T{title_number:02d}_A{track_number:02d}"

    return DVDAudioTrack(
        track_id=track_id,
        title_number=title_number,
        track_number=track_number,
        stream_index=stream_index,
        codec=codec,
        channels=channels,
        channel_count=ch_count,
        lang_code=l_code,
        lang_name=l_name,
        sample_rate=int(sample_rate or 48000),
        bitrate=int(bitrate or 0),
        hb_track_index=hb_idx,
        ffmpeg_stream_index=ff_idx,
        source_id=str(source_id or "")
    )


@dataclass
class DVDChapter:
    chapter_number: int
    start_time: float      # in seconds, e.g. 0.0
    end_time: float        # in seconds, e.g. 345.5
    duration: float = 0.0  # end_time - start_time
    title_number: int = 1
    name: str = ""

    def __post_init__(self):
        if self.duration <= 0.0 and self.end_time > self.start_time:
            self.duration = self.end_time - self.start_time
        if not self.name:
            self.name = f"Chapter {self.chapter_number:02d}"

    def format_time(self, t: float) -> str:
        s = int(round(max(0.0, t)))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "duration": round(self.duration, 3),
            "start_str": self.format_time(self.start_time),
            "end_str": self.format_time(self.end_time),
            "duration_str": self.format_time(self.duration),
            "title_number": self.title_number,
            "name": self.name,
        }


@dataclass
class DVDTitle:
    title_number: int
    vts_number: int
    ttn: int = 1
    duration: float = 0.0
    chapter_count: int = 1
    chapters: List[float] = field(default_factory=list)
    chapters_data: List[DVDChapter] = field(default_factory=list)
    video_codec: str = "MPEG-2"
    resolution: str = "720×480"
    width: int = 720
    height: int = 480
    aspect_ratio: str = "4:3"
    fps: str = "29.97 fps"
    system: str = "NTSC"
    bitrate: str = "~5000 kbps"
    audio_streams: List[Dict[str, Any]] = field(default_factory=list)
    audio_tracks: List[DVDAudioTrack] = field(default_factory=list)
    subtitle_streams: List[Dict[str, Any]] = field(default_factory=list)
    vob_files: List[str] = field(default_factory=list)
    size_mb: float = 0.0
    is_main_feature: bool = False
    name: str = ""
    custom_stem: str = ""

    def format_duration(self) -> str:
        s = int(round(self.duration))
        if s <= 0:
            return "--:--"
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def audio_summary(self) -> str:
        if self.audio_tracks:
            return ", ".join(a.display_label() for a in self.audio_tracks)
        if not self.audio_streams:
            return "No audio"
        items = []
        for a in self.audio_streams:
            lang = a.get("lang_name") or a.get("lang") or ""
            fmt = a.get("format", "AC3")
            ch = a.get("channels", "")
            part = fmt
            if ch:
                part += f" {ch}"
            if lang and lang.lower() != "undetermined":
                part += f" ({lang})"
            items.append(part)
        return ", ".join(items)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching the application's video item model."""
        display_name = self.name or f"Title {self.title_number:02d}"
        if self.is_main_feature and "Main Feature" not in display_name:
            display_name += " (Main Feature)"

        primary_path = self.vob_files[0] if self.vob_files else ""
        c_dicts = [c.to_dict() if isinstance(c, DVDChapter) else c for c in self.chapters_data]
        chap_starts = [c["start_time"] for c in c_dicts] if c_dicts else self.chapters
        a_dicts = [a.to_dict() if isinstance(a, DVDAudioTrack) else a for a in self.audio_tracks]

        return {
            "path": primary_path,
            "filename": display_name,
            "title_number": self.title_number,
            "vts_number": self.vts_number,
            "ttn": self.ttn,
            "duration": round(self.duration, 2),
            "size_mb": round(self.size_mb, 1),
            "width": self.width,
            "height": self.height,
            "codec": self.video_codec,
            "fps": self.fps,
            "bitrate": self.bitrate,
            "aspect_ratio": self.aspect_ratio,
            "chapter_count": len(c_dicts) if c_dicts else self.chapter_count,
            "chapters": chap_starts,
            "chapters_data": c_dicts,
            "audio_streams": self.audio_streams,
            "audio_tracks": a_dicts,
            "audio_summary": self.audio_summary(),
            "subtitle_streams": self.subtitle_streams,
            "vob_files": self.vob_files,
            "is_main_feature": self.is_main_feature,
            "disc_type": "DVD",
            "custom_stem": self.custom_stem or f"Title_{self.title_number:02d}",
        }


# ─────────────────────────────────────────────
#  IFO Binary Parsers
# ─────────────────────────────────────────────
def find_video_ts_dir(base_path: str) -> Optional[Path]:
    """
    Locates the VIDEO_TS directory within base_path.
    Supports:
    - Root of drive/folder containing VIDEO_TS/
    - Browsed folder that is itself VIDEO_TS
    - Case-insensitive search for VIDEO_TS
    """
    if not base_path:
        return None
    try:
        p = Path(base_path)
        if not p.exists() or not p.is_dir():
            return None

        # Check if p itself is VIDEO_TS
        if p.name.upper() == "VIDEO_TS":
            return p

        # Check direct child VIDEO_TS
        child = p / "VIDEO_TS"
        if child.is_dir():
            return child

        # Case-insensitive child search
        for item in p.iterdir():
            if item.is_dir() and item.name.upper() == "VIDEO_TS":
                return item

        # Check if root contains VIDEO_TS.IFO directly
        if (p / "VIDEO_TS.IFO").is_file() or (p / "video_ts.ifo").is_file():
            return p
    except Exception:
        pass
    return None


def parse_vmgi(ifo_path: str) -> Optional[List[Dict[str, Any]]]:
    """
    Parses Video Manager Information (VIDEO_TS.IFO).
    Extracts the Title Search Pointer Table (TT_SRPT).
    Returns a list of logical title metadata dictionaries or None if unparseable.
    """
    try:
        with open(ifo_path, "rb") as f:
            data = f.read()

        if len(data) < 2048:
            return None

        sig = data[0:12]
        if not sig.startswith(b"DVDVIDEO-VMG"):
            return None

        # Sector 0x00C4: VMG_TT_SRPT start sector
        tt_srpt_sector = struct.unpack_from(">I", data, 0x00C4)[0]
        tt_srpt_offset = tt_srpt_sector * 2048
        if tt_srpt_offset + 8 > len(data):
            return None

        num_titles = struct.unpack_from(">H", data, tt_srpt_offset)[0]
        if num_titles <= 0 or num_titles > 99:
            return None

        titles = []
        for i in range(num_titles):
            entry_offset = tt_srpt_offset + 8 + i * 12
            if entry_offset + 12 > len(data):
                break

            playback_type = data[entry_offset]
            num_angles = max(1, int(data[entry_offset + 1]))
            num_chapters = struct.unpack_from(">H", data, entry_offset + 2)[0]
            vts_num = int(data[entry_offset + 6])
            ttn = int(data[entry_offset + 7])
            vts_sector = struct.unpack_from(">I", data, entry_offset + 8)[0]

            titles.append({
                "title_number": i + 1,
                "vts_number": vts_num,
                "ttn": ttn,
                "chapter_count": max(1, num_chapters),
                "angle_count": num_angles,
                "vts_sector": vts_sector,
            })
        return titles
    except Exception:
        return None


def parse_vtsi(ifo_path: str) -> Optional[Dict[str, Any]]:
    """
    Parses Video Title Set Information (VTS_xx_0.IFO).
    Extracts video attributes, audio stream attributes, subpicture attributes,
    and PGC durations from VTS_PGCIT.
    """
    try:
        with open(ifo_path, "rb") as f:
            data = f.read()

        if len(data) < 2048:
            return None

        sig = data[0:12]
        if not sig.startswith(b"DVDVIDEO-VTS"):
            return None

        # Video attributes at 0x0100 (2 bytes)
        v_attr = struct.unpack_from(">H", data, 0x0100)[0]
        comp_bit = (v_attr >> 14) & 0x03
        video_codec = "MPEG-2" if comp_bit == 1 else ("MPEG-1" if comp_bit == 0 else "MPEG-2")

        tv_sys = (v_attr >> 12) & 0x03
        system_str = "PAL" if tv_sys == 1 else "NTSC"
        fps_val = 25.0 if tv_sys == 1 else 29.97
        fps_str = "25 fps" if tv_sys == 1 else "29.97 fps"

        ar_bit = (v_attr >> 10) & 0x03
        aspect_ratio = "16:9" if ar_bit == 3 else "4:3"

        res_bit = (v_attr >> 3) & 0x07
        if tv_sys == 1:
            res_map = {0: (720, 576), 1: (704, 576), 2: (352, 576), 3: (352, 288)}
        else:
            res_map = {0: (720, 480), 1: (704, 480), 2: (352, 480), 3: (352, 240)}
        width, height = res_map.get(res_bit, (720, 576 if tv_sys == 1 else 480))
        res_str = f"{width}×{height}"

        # Audio streams at 0x0102 (count) + 0x0104 (8 entries of 8 bytes)
        num_audio = struct.unpack_from(">H", data, 0x0102)[0]
        audio_streams = []
        for a in range(min(num_audio, 8)):
            a_off = 0x0104 + a * 8
            if a_off + 8 > len(data):
                break
            a_byte0 = data[a_off]
            fmt_bits = (a_byte0 >> 5) & 0x07
            fmt_map = {0: "AC3", 2: "MPEG", 3: "MPEG-2", 4: "LPCM", 6: "DTS"}
            a_fmt = fmt_map.get(fmt_bits, "AC3")

            ch_bits = a_byte0 & 0x07
            ch_map = {0: "1.0", 1: "2.0", 2: "3.0", 3: "4.0", 4: "5.0", 5: "5.1"}
            a_ch = ch_map.get(ch_bits, "2.0")

            lang_bytes = data[a_off + 2:a_off + 4]
            try:
                lang_code = lang_bytes.decode("ascii", errors="ignore").strip().lower()
            except Exception:
                lang_code = ""
            lang_code = lang_code if (lang_code and lang_code != "\x00\x00") else "und"

            audio_streams.append({
                "index": a,
                "format": a_fmt,
                "channels": a_ch,
                "lang": lang_code,
                "lang_name": get_language_name(lang_code),
            })

        # Subtitle streams at 0x0154 (count) + 0x0156 (32 entries of 6 bytes)
        num_sub = struct.unpack_from(">H", data, 0x0154)[0]
        sub_streams = []
        for s in range(min(num_sub, 32)):
            s_off = 0x0156 + s * 6
            if s_off + 6 > len(data):
                break
            lang_bytes = data[s_off + 2:s_off + 4]
            try:
                lang_code = lang_bytes.decode("ascii", errors="ignore").strip().lower()
            except Exception:
                lang_code = ""
            lang_code = lang_code if (lang_code and lang_code != "\x00\x00") else "und"

            sub_streams.append({
                "index": s,
                "lang": lang_code,
                "lang_name": get_language_name(lang_code),
            })

        # 1. Part-of-Title (Chapter) Search Pointer Table (VTS_PTT_SRPT) at 0x00C8
        vts_ptt_map: Dict[int, List[Tuple[int, int]]] = {}
        if 0x00C8 + 4 <= len(data):
            ptt_sector = struct.unpack_from(">I", data, 0x00C8)[0]
            ptt_offset = ptt_sector * 2048
            if ptt_sector > 0 and ptt_offset + 8 <= len(data):
                num_titles_vts = struct.unpack_from(">H", data, ptt_offset)[0]
                end_byte = struct.unpack_from(">I", data, ptt_offset + 4)[0]
                # In VTS_PTT_SRPT:
                # Byte 0..1: nr_of_srpts (number of Title Search Pointers)
                # Byte 2..3: reserved
                # Byte 4..7: end_byte (last byte offset of table relative to ptt_offset)
                # Byte 8..: array of 4-byte offsets to each Title's PTT table relative to ptt_offset
                if 1 <= num_titles_vts <= 99 and end_byte > 8:
                    for t_idx in range(1, num_titles_vts + 1):
                        off_entry = ptt_offset + 8 + (t_idx - 1) * 4
                        if off_entry + 4 <= len(data) and off_entry + 4 <= ptt_offset + end_byte + 1:
                            t_sub_off = struct.unpack_from(">I", data, off_entry)[0]
                            t_abs = ptt_offset + t_sub_off
                            # Determine length of this title's PTT table
                            if t_idx < num_titles_vts:
                                next_off = ptt_offset + 8 + t_idx * 4
                                if next_off + 4 <= len(data):
                                    next_sub_off = struct.unpack_from(">I", data, next_off)[0]
                                    t_len = next_sub_off - t_sub_off
                                else:
                                    t_len = (end_byte + 1) - t_sub_off
                            else:
                                t_len = (end_byte + 1) - t_sub_off

                            num_ptts = max(0, t_len // 4)
                            if 1 <= num_ptts <= 99 and t_abs + num_ptts * 4 <= len(data):
                                ptts = []
                                for p_idx in range(num_ptts):
                                    p_entry = t_abs + p_idx * 4
                                    pgcn = struct.unpack_from(">H", data, p_entry)[0]
                                    pgn = struct.unpack_from(">H", data, p_entry + 2)[0]
                                    # In DVD-Video, valid PGCN and PGN are >= 1
                                    if pgcn == 0 or pgn == 0:
                                        # End of valid entries (reached padding)
                                        break
                                    ptts.append((pgcn, pgn))
                                if ptts:
                                    vts_ptt_map[t_idx] = ptts

        # 2. Program Chain Information Table (VTS_PGCIT) at 0x00CC
        pgc_durations: List[float] = []
        pgc_chapters: List[List[float]] = []
        pgc_programs: Dict[int, List[Dict[str, float]]] = {}

        if 0x00CC + 4 <= len(data):
            pgcit_sector = struct.unpack_from(">I", data, 0x00CC)[0]
            pgcit_offset = pgcit_sector * 2048
            if pgcit_sector > 0 and pgcit_offset + 8 <= len(data):
                num_pgcs = struct.unpack_from(">H", data, pgcit_offset)[0]
                for p in range(min(num_pgcs, 999)):
                    pgc_idx = p + 1
                    sp_off = pgcit_offset + 8 + p * 8
                    if sp_off + 8 > len(data):
                        break
                    pgc_rel = struct.unpack_from(">I", data, sp_off + 4)[0]
                    pgc_abs = pgcit_offset + pgc_rel
                    if pgc_abs + 8 <= len(data):
                        num_programs = int(data[pgc_abs + 2])
                        num_cells = int(data[pgc_abs + 3])

                        # Playback time (BCD): HH:MM:SS:FF
                        b_h = data[pgc_abs + 4]
                        b_m = data[pgc_abs + 5]
                        b_s = data[pgc_abs + 6]
                        b_f = data[pgc_abs + 7]

                        hours = bcd_to_int(b_h)
                        mins = bcd_to_int(b_m)
                        secs = bcd_to_int(b_s)
                        frames = bcd_to_int(b_f & 0x3F)

                        dur = hours * 3600 + mins * 60 + secs + (frames / fps_val)
                        pgc_durations.append(dur)

                        # Offsets in PGC:
                        # 0x00E4: command_tbl_offset (uint16)
                        # 0x00E6: program_map_offset (uint16)
                        # 0x00E8: cell_playback_offset (uint16)
                        # 0x00EA: cell_position_offset (uint16)
                        program_map_offset = struct.unpack_from(">H", data, pgc_abs + 0x00E6)[0] if pgc_abs + 0x00E8 <= len(data) else 0
                        cell_playback_offset = struct.unpack_from(">H", data, pgc_abs + 0x00E8)[0] if pgc_abs + 0x00EA <= len(data) else 0

                        # Cell Playback Information Table
                        cell_durations: List[float] = []
                        if cell_playback_offset > 0 and num_cells > 0:
                            cpbit_abs = pgc_abs + cell_playback_offset
                            for c in range(min(num_cells, 255)):
                                c_entry = cpbit_abs + c * 24
                                if c_entry + 8 <= len(data):
                                    ch_h = bcd_to_int(data[c_entry + 4])
                                    ch_m = bcd_to_int(data[c_entry + 5])
                                    ch_s = bcd_to_int(data[c_entry + 6])
                                    ch_f = bcd_to_int(data[c_entry + 7] & 0x3F)
                                    c_dur = ch_h * 3600 + ch_m * 60 + ch_s + (ch_f / fps_val)
                                    cell_durations.append(c_dur)
                        pgc_chapters.append(cell_durations)

                        # Calculate cumulative cell start offsets
                        cell_starts = [0.0]
                        for c_d in cell_durations:
                            cell_starts.append(cell_starts[-1] + c_d)

                        # Parse PGC_PGMAP (Program map table)
                        entry_cells = []
                        if program_map_offset > 0 and num_programs > 0:
                            pgmap_abs = pgc_abs + program_map_offset
                            if pgmap_abs + num_programs <= len(data):
                                entry_cells = [int(data[pgmap_abs + k]) for k in range(num_programs)]

                        if not entry_cells and num_programs > 0:
                            if num_programs == num_cells:
                                entry_cells = list(range(1, num_cells + 1))
                            elif num_cells >= num_programs:
                                entry_cells = list(range(1, num_programs + 1))
                            else:
                                entry_cells = [1] * num_programs

                        # Map each program to (start_time, end_time, duration)
                        programs_list = []
                        for prg_i in range(1, num_programs + 1):
                            if prg_i - 1 < len(entry_cells):
                                c_num = entry_cells[prg_i - 1]
                                c_idx = max(0, min(c_num - 1, len(cell_starts) - 1))
                                st = cell_starts[c_idx]
                            else:
                                st = 0.0

                            if prg_i < num_programs and prg_i < len(entry_cells):
                                next_c_num = entry_cells[prg_i]
                                next_c_idx = max(0, min(next_c_num - 1, len(cell_starts) - 1))
                                et = cell_starts[next_c_idx]
                            else:
                                et = max(st, dur if dur > 0 else (cell_starts[-1] if len(cell_starts) > 1 else st))

                            p_dur = max(0.0, et - st)
                            programs_list.append({
                                "pgn": prg_i,
                                "start_time": st,
                                "end_time": et,
                                "duration": p_dur
                            })
                        pgc_programs[pgc_idx] = programs_list

        return {
            "video_codec": video_codec,
            "system": system_str,
            "fps_str": fps_str,
            "fps_val": fps_val,
            "aspect_ratio": aspect_ratio,
            "resolution": res_str,
            "width": width,
            "height": height,
            "audio_streams": audio_streams,
            "subtitle_streams": sub_streams,
            "pgc_durations": pgc_durations,
            "pgc_chapters": pgc_chapters,
            "vts_ptt_map": vts_ptt_map,
            "pgc_programs": pgc_programs,
        }
    except Exception:
        return None


def validate_chapters(chapters: List[DVDChapter], total_duration: float = 0.0) -> bool:
    """
    Validates a list of DVDChapter objects to detect corrupt, dummy, or synthetic anomalies:
    - Must not be empty.
    - If single chapter: start_time >= 0, duration > 0 (or end_time > start_time).
    - If multiple chapters:
      * Start times must be strictly monotonically increasing.
      * Start times must NOT all be identical (e.g. all 0.0).
      * Durations must NOT all be identical if equal to or near total duration.
      * No chapter should have negative duration.
      * End time must be > start time.
    """
    if not chapters:
        return False
    if len(chapters) == 1:
        c = chapters[0]
        return c.start_time >= 0.0 and (c.duration > 0.0 or c.end_time > c.start_time)

    # 1. Monotonic start times: each chapter start time must strictly increase
    for i in range(1, len(chapters)):
        if chapters[i].start_time <= chapters[i - 1].start_time:
            return False

    # 2. Check for identical durations matching total title duration
    first_dur = chapters[0].duration
    all_same_dur = all(abs(c.duration - first_dur) < 0.001 for c in chapters)
    if all_same_dur and first_dur > 0:
        if total_duration > 0 and first_dur >= (total_duration * 0.8):
            return False
        if len(chapters) >= 10:
            return False

    # 3. Check for identical (start_time, end_time) ranges across all chapters
    first_range = (round(chapters[0].start_time, 2), round(chapters[0].end_time, 2))
    if all((round(c.start_time, 2), round(c.end_time, 2)) == first_range for c in chapters):
        return False

    # 4. Check negative durations or end <= start
    for c in chapters:
        if c.duration <= 0.0 or c.end_time <= c.start_time:
            return False

    return True


def probe_chapters_from_ffprobe(ffprobe_path: str, dvd_source: str, title_num: int = 1) -> List[DVDChapter]:
    """Probe chapters of a DVD title using ffprobe dvdvideo demuxer if available."""
    try:
        dvd_dir = find_video_ts_dir(dvd_source)
        target_path = str(dvd_dir.parent if dvd_dir and dvd_dir.name.upper() == "VIDEO_TS" else dvd_source)
        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_chapters",
            "-f", "dvdvideo",
            "-title", str(title_num),
            target_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, **get_subprocess_kwargs())
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            raw_chaps = data.get("chapters", [])
            chaps: List[DVDChapter] = []
            for idx, c in enumerate(raw_chaps, start=1):
                st = float(c.get("start_time", 0.0))
                et = float(c.get("end_time", 0.0))
                dur = max(0.0, et - st)
                name = c.get("tags", {}).get("title") or f"Chapter {idx:02d}"
                chaps.append(DVDChapter(
                    chapter_number=idx,
                    start_time=st,
                    end_time=et,
                    duration=dur,
                    title_number=title_num,
                    name=name
                ))
            if chaps and validate_chapters(chaps):
                return chaps
    except Exception:
        pass
    return []


def _extract_title_chapters(
    t_num: int,
    ttn: int,
    duration: float,
    chap_count: int,
    vtsi: Optional[Dict[str, Any]],
    source_path: str,
    ffprobe_path: Optional[str]
) -> Tuple[List[float], List[DVDChapter]]:
    chapters_data: List[DVDChapter] = []

    if vtsi:
        vts_ptt_map = vtsi.get("vts_ptt_map", {})
        pgc_programs = vtsi.get("pgc_programs", {})
        pgc_chaps = vtsi.get("pgc_chapters", [])

        # Candidate 1: From VTS_PTT_SRPT
        if ttn in vts_ptt_map and vts_ptt_map[ttn]:
            cand1: List[DVDChapter] = []
            for chap_i, (pgcn, pgn) in enumerate(vts_ptt_map[ttn], start=1):
                progs = pgc_programs.get(pgcn, [])
                matched_prog = next((p for p in progs if p["pgn"] == pgn), None)
                if matched_prog and matched_prog["duration"] > 0:
                    st = float(matched_prog["start_time"])
                    et = float(matched_prog["end_time"])
                    dur = float(matched_prog["duration"])
                    cand1.append(DVDChapter(
                        chapter_number=chap_i,
                        start_time=st,
                        end_time=et,
                        duration=dur,
                        title_number=t_num,
                        name=f"Chapter {chap_i:02d}"
                    ))
            if cand1 and validate_chapters(cand1, duration):
                chapters_data = cand1

        # Candidate 2: From pgc_programs if Candidate 1 failed or wasn't available
        if not chapters_data:
            target_pgcn = 1
            if ttn in vts_ptt_map and vts_ptt_map[ttn]:
                target_pgcn = vts_ptt_map[ttn][0][0]
            elif 0 <= (ttn - 1) < len(vtsi.get("pgc_durations", [])):
                target_pgcn = ttn

            progs = pgc_programs.get(target_pgcn, [])
            if not progs and pgc_programs:
                target_pgcn = max(pgc_programs.keys(), key=lambda k: sum(p["duration"] for p in pgc_programs[k]))
                progs = pgc_programs.get(target_pgcn, [])

            if progs and len(progs) > 1:
                cand2: List[DVDChapter] = []
                for p in progs:
                    if p["duration"] > 0:
                        cand2.append(DVDChapter(
                            chapter_number=int(p["pgn"]),
                            start_time=float(p["start_time"]),
                            end_time=float(p["end_time"]),
                            duration=float(p["duration"]),
                            title_number=t_num,
                            name=f"Chapter {int(p['pgn']):02d}"
                        ))
                if cand2 and validate_chapters(cand2, duration):
                    chapters_data = cand2

        # Candidate 3: From pgc_chapters (cell durations)
        if not chapters_data and pgc_chaps:
            target_pgcn = 1
            if ttn in vts_ptt_map and vts_ptt_map[ttn]:
                target_pgcn = vts_ptt_map[ttn][0][0]
            target_idx = (target_pgcn - 1) if (0 <= target_pgcn - 1 < len(pgc_chaps)) else 0
            c_durs = [d for d in pgc_chaps[target_idx] if d > 0]
            if len(c_durs) > 1:
                cand3: List[DVDChapter] = []
                accum = 0.0
                for c_i, c_dur in enumerate(c_durs, start=1):
                    st = accum
                    et = accum + c_dur
                    accum = et
                    cand3.append(DVDChapter(
                        chapter_number=c_i,
                        start_time=st,
                        end_time=et,
                        duration=c_dur,
                        title_number=t_num,
                        name=f"Chapter {c_i:02d}"
                    ))
                if cand3 and validate_chapters(cand3, duration):
                    chapters_data = cand3

    # Candidate 4: Probe via ffprobe if chapters_data has <= 1 chapter and ffprobe is available
    if len(chapters_data) <= 1 and ffprobe_path:
        probed = probe_chapters_from_ffprobe(ffprobe_path, source_path, t_num)
        if probed and len(probed) > 1 and validate_chapters(probed, duration):
            chapters_data = probed

    # Candidate 5: Single-chapter fallback if still empty or invalid
    if not chapters_data and duration > 0:
        chapters_data.append(DVDChapter(
            chapter_number=1,
            start_time=0.0,
            end_time=duration,
            duration=duration,
            title_number=t_num,
            name="Chapter 01"
        ))

    chapters_list = [c.start_time for c in chapters_data]
    return chapters_list, chapters_data



# ─────────────────────────────────────────────
#  DVD Structure Scanner
# ─────────────────────────────────────────────
def scan_dvd_structure(source_path: str, ffprobe_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Main entry point for DVD-Video scanning.
    1. Locates VIDEO_TS directory.
    2. Identifies logical titles from VIDEO_TS.IFO and VTS_xx_0.IFO.
    3. Maps logical titles to their respective VOB sets (e.g. VTS_01_1.VOB ... VTS_01_N.VOB).
    4. Gathers duration, chapter count, resolution, aspect ratio, audio and subtitle streams.
    5. Flags likely main feature title.
    6. Returns list of title dictionary objects ready for UI display.
    """
    dvd_dir = find_video_ts_dir(source_path)
    if not dvd_dir:
        return []

    # Map all uppercase files in VIDEO_TS
    try:
        entries = list(dvd_dir.iterdir())
    except (PermissionError, OSError):
        return []

    files_map: Dict[str, Path] = {e.name.upper(): e for e in entries if e.is_file()}

    # Group title VOB files by VTS number:
    # Key: int(vts_num), Value: list of paths sorted by segment index
    # Note: VTS_xx_0.VOB is menu domain, title VOBs are VTS_xx_1.VOB to VTS_xx_9.VOB
    vts_vobs: Dict[int, List[Path]] = {}
    for fname, path in files_map.items():
        if fname.startswith("VTS_") and fname.endswith(".VOB"):
            parts = fname.split("_")
            if len(parts) == 3:
                try:
                    vts_num = int(parts[1])
                    seg_num = int(parts[2].split(".")[0])
                    if seg_num >= 1:  # Title domain only
                        vts_vobs.setdefault(vts_num, []).append((seg_num, path))
                except (ValueError, IndexError):
                    pass

    # Sort each VTS VOB list by segment index
    vts_sorted_vobs: Dict[int, List[Path]] = {}
    for vts_num, items in vts_vobs.items():
        items.sort(key=lambda x: x[0])
        vts_sorted_vobs[vts_num] = [p for _, p in items]

    # Attempt primary IFO parsing
    vmg_ifo_path = files_map.get("VIDEO_TS.IFO") or files_map.get("VIDEO_TS.BUP")
    vmg_titles = parse_vmgi(str(vmg_ifo_path)) if vmg_ifo_path else None

    # Cache parsed VTSI data per VTS number
    vtsi_cache: Dict[int, Dict[str, Any]] = {}

    def get_vtsi(vts_n: int) -> Optional[Dict[str, Any]]:
        if vts_n in vtsi_cache:
            return vtsi_cache[vts_n]
        vts_ifo_name = f"VTS_{vts_n:02d}_0.IFO"
        vts_bup_name = f"VTS_{vts_n:02d}_0.BUP"
        vts_path = files_map.get(vts_ifo_name) or files_map.get(vts_bup_name)
        if vts_path:
            vtsi_data = parse_vtsi(str(vts_path))
            if vtsi_data:
                vtsi_cache[vts_n] = vtsi_data
                return vtsi_data
        return None

    titles_list: List[DVDTitle] = []

    if vmg_titles:
        for t_info in vmg_titles:
            t_num = t_info["title_number"]
            vts_num = t_info["vts_number"]
            ttn = t_info["ttn"]
            chap_count = t_info["chapter_count"]

            vtsi = get_vtsi(vts_num)
            vobs = [str(p) for p in vts_sorted_vobs.get(vts_num, [])]

            # Calculate total size of VOBs
            total_size = sum(os.path.getsize(v) for v in vobs if os.path.exists(v))
            size_mb = total_size / (1024 ** 2)

            duration = 0.0
            if vtsi:
                pgc_durs = vtsi.get("pgc_durations", [])
                vts_ptt_map = vtsi.get("vts_ptt_map", {})
                if pgc_durs:
                    # Find PGCN associated with title ttn from VTS_PTT_SRPT
                    if ttn in vts_ptt_map and vts_ptt_map[ttn]:
                        pgcn = vts_ptt_map[ttn][0][0]
                        if 1 <= pgcn <= len(pgc_durs):
                            duration = pgc_durs[pgcn - 1]
                        else:
                            duration = max(pgc_durs)
                    elif 0 <= (ttn - 1) < len(pgc_durs):
                        duration = pgc_durs[ttn - 1]
                    else:
                        duration = max(pgc_durs)

                v_codec = vtsi.get("video_codec", "MPEG-2")
                res = vtsi.get("resolution", "720×480")
                w = vtsi.get("width", 720)
                h = vtsi.get("height", 480)
                ar = vtsi.get("aspect_ratio", "4:3")
                fps = vtsi.get("fps_str", "29.97 fps")
                tv_sys = vtsi.get("system", "NTSC")
                audio_streams = vtsi.get("audio_streams", [])
                sub_streams = vtsi.get("subtitle_streams", [])
            else:
                v_codec = "MPEG-2"
                res = "720×480"
                w, h = 720, 480
                ar = "4:3"
                fps = "29.97 fps"
                tv_sys = "NTSC"
                audio_streams = []
                sub_streams = []

            # Fallback duration if IFO duration was 0: probe via ffprobe if available
            if duration <= 0 and ffprobe_path and vobs:
                probed = probe_vob_duration(ffprobe_path, vobs[0])
                if probed > 0:
                    vob0_size = os.path.getsize(vobs[0])
                    if vob0_size > 0 and total_size > 0:
                        duration = probed * (total_size / vob0_size)
                    else:
                        duration = probed

            chapters_list, chapters_data = _extract_title_chapters(
                t_num, ttn, duration, chap_count, vtsi, source_path, ffprobe_path
            )

            # Ensure title duration matches the total playback span of validated chapters
            if chapters_data and chapters_data[-1].end_time > 0:
                chap_total = chapters_data[-1].end_time
                if duration <= 0 or abs(duration - chap_total) > 1.0:
                    duration = chap_total

            title_audio_tracks = []
            for a_idx, a_st in enumerate(audio_streams):
                a_trk = normalize_audio_track(
                    title_number=t_num,
                    track_number=a_idx + 1,
                    stream_index=a_idx,
                    raw_codec=a_st.get("format", "AC3"),
                    raw_channels=a_st.get("channels", "2.0"),
                    raw_lang=a_st.get("lang", "und"),
                    raw_lang_name=a_st.get("lang_name"),
                    hb_track_index=a_idx + 1,
                    ffmpeg_stream_index=a_idx,
                )
                title_audio_tracks.append(a_trk)

            title_obj = DVDTitle(
                title_number=t_num,
                vts_number=vts_num,
                ttn=ttn,
                duration=duration,
                chapter_count=len(chapters_data) if chapters_data else 1,
                chapters=chapters_list,
                chapters_data=chapters_data,
                video_codec=v_codec,
                resolution=res,
                width=w,
                height=h,
                aspect_ratio=ar,
                fps=fps,
                system=tv_sys,
                audio_streams=audio_streams,
                audio_tracks=title_audio_tracks,
                subtitle_streams=sub_streams,
                vob_files=vobs,
                size_mb=size_mb,
                name=f"Title {t_num:02d}",
            )
            titles_list.append(title_obj)

    # Fallback: If VIDEO_TS.IFO yielded no titles, synthesize from available VTS sets
    if not titles_list and vts_sorted_vobs:
        for t_idx, (vts_num, vob_paths) in enumerate(sorted(vts_sorted_vobs.items()), start=1):
            vtsi = get_vtsi(vts_num)
            vobs = [str(p) for p in vob_paths]
            total_size = sum(os.path.getsize(v) for v in vobs if os.path.exists(v))
            size_mb = total_size / (1024 ** 2)

            duration = 0.0
            chap_count = 1
            if vtsi:
                pgc_durs = vtsi.get("pgc_durations", [])
                if pgc_durs:
                    duration = max(pgc_durs)
                v_codec = vtsi.get("video_codec", "MPEG-2")
                res = vtsi.get("resolution", "720×480")
                w = vtsi.get("width", 720)
                h = vtsi.get("height", 480)
                ar = vtsi.get("aspect_ratio", "4:3")
                fps = vtsi.get("fps_str", "29.97 fps")
                tv_sys = vtsi.get("system", "NTSC")
                audio_streams = vtsi.get("audio_streams", [])
                sub_streams = vtsi.get("subtitle_streams", [])
            else:
                v_codec = "MPEG-2"
                res = "720×480"
                w, h = 720, 480
                ar = "4:3"
                fps = "29.97 fps"
                tv_sys = "NTSC"
                audio_streams = []
                sub_streams = []

            if duration <= 0 and ffprobe_path and vobs:
                probed = probe_vob_duration(ffprobe_path, vobs[0])
                if probed > 0:
                    vob0_size = os.path.getsize(vobs[0])
                    if vob0_size > 0 and total_size > 0:
                        duration = probed * (total_size / vob0_size)
                    else:
                        duration = probed

            chapters_list, chapters_data = _extract_title_chapters(
                t_idx, 1, duration, chap_count, vtsi, source_path, ffprobe_path
            )

            # Ensure title duration matches validated chapters span
            if chapters_data and chapters_data[-1].end_time > 0:
                chap_total = chapters_data[-1].end_time
                if duration <= 0 or abs(duration - chap_total) > 1.0:
                    duration = chap_total

            title_audio_tracks = []
            for a_idx, a_st in enumerate(audio_streams):
                a_trk = normalize_audio_track(
                    title_number=t_idx,
                    track_number=a_idx + 1,
                    stream_index=a_idx,
                    raw_codec=a_st.get("format", "AC3"),
                    raw_channels=a_st.get("channels", "2.0"),
                    raw_lang=a_st.get("lang", "und"),
                    raw_lang_name=a_st.get("lang_name"),
                    hb_track_index=a_idx + 1,
                    ffmpeg_stream_index=a_idx,
                )
                title_audio_tracks.append(a_trk)

            title_obj = DVDTitle(
                title_number=t_idx,
                vts_number=vts_num,
                ttn=1,
                duration=duration,
                chapter_count=len(chapters_data) if chapters_data else 1,
                chapters=chapters_list,
                chapters_data=chapters_data,
                video_codec=v_codec,
                resolution=res,
                width=w,
                height=h,
                aspect_ratio=ar,
                fps=fps,
                system=tv_sys,
                audio_streams=audio_streams,
                audio_tracks=title_audio_tracks,
                subtitle_streams=sub_streams,
                vob_files=vobs,
                size_mb=size_mb,
                name=f"Title {t_idx:02d}",
            )
            titles_list.append(title_obj)

    # Enrich metadata using FFprobe on first title or available titles if streams were empty
    if ffprobe_path and titles_list:
        for title in titles_list:
            if not title.audio_streams and title.vob_files:
                enrich_title_from_ffprobe(ffprobe_path, title)

    # Determine Main Feature:
    # Find the title with the longest duration (provided duration > 10 minutes or longest non-zero)
    if titles_list:
        valid_durs = [t for t in titles_list if t.duration > 0]
        if valid_durs:
            longest = max(valid_durs, key=lambda t: t.duration)
            if longest.duration >= 300:  # At least 5 minutes to be considered main feature
                longest.is_main_feature = True
        elif titles_list:
            # Fallback based on size if duration is zero
            largest = max(titles_list, key=lambda t: t.size_mb)
            if largest.size_mb >= 500:
                largest.is_main_feature = True

    return [t.to_dict() for t in titles_list]


def probe_vob_duration(ffprobe_path: str, vob_path: str) -> float:
    """Use ffprobe to determine duration of a VOB file in seconds."""
    try:
        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            vob_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **get_subprocess_kwargs())
        data = json.loads(res.stdout) if res.stdout else {}
        fmt = data.get("format", {})
        if "duration" in fmt:
            return float(fmt["duration"])
    except Exception:
        pass
    return 0.0


def enrich_title_from_ffprobe(ffprobe_path: str, title: DVDTitle) -> None:
    """Probe the primary VOB file with ffprobe to populate audio, video, and resolution metadata."""
    if not title.vob_files:
        return
    try:
        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            title.vob_files[0]
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **get_subprocess_kwargs())
        data = json.loads(res.stdout) if res.stdout else {}
        streams = data.get("streams", [])
        for st in streams:
            ctype = st.get("codec_type")
            if ctype == "video" and title.width == 720 and title.height == 480:
                w = st.get("width")
                h = st.get("height")
                if w and h:
                    title.width = int(w)
                    title.height = int(h)
                    title.resolution = f"{title.width}×{title.height}"
            elif ctype == "audio":
                acodec = st.get("codec_name", "ac3").upper()
                ch_cnt = st.get("channels", 2)
                ch_desc = "5.1" if ch_cnt == 6 else ("1.0" if ch_cnt == 1 else "2.0")
                tags = st.get("tags", {})
                lang = tags.get("language") or tags.get("LANGUAGE") or "und"
                srate = int(st.get("sample_rate", 48000) or 48000)
                bit_r = int(st.get("bit_rate", 0) or 0)
                a_idx = len(title.audio_streams)
                title.audio_streams.append({
                    "index": a_idx,
                    "format": acodec,
                    "channels": ch_desc,
                    "lang": lang.lower(),
                    "lang_name": get_language_name(lang),
                })
                title.audio_tracks.append(
                    normalize_audio_track(
                        title_number=title.title_number,
                        track_number=a_idx + 1,
                        stream_index=a_idx,
                        raw_codec=acodec,
                        raw_channels=ch_desc,
                        raw_lang=lang,
                        raw_lang_name=get_language_name(lang),
                        sample_rate=srate,
                        bitrate=bit_r,
                        hb_track_index=a_idx + 1,
                        ffmpeg_stream_index=a_idx,
                    )
                )
    except Exception:
        pass


_dvdvideo_probe_cache: Dict[Tuple[str, str, int], Tuple[bool, Optional[str]]] = {}


def clear_dvdvideo_probe_cache() -> None:
    """Clears the cached dvdvideo demuxer probe results."""
    _dvdvideo_probe_cache.clear()


def check_dvdvideo_support(
    ffmpeg_path: str,
    dvd_source: str,
    title_num: int,
    chapter_num: Optional[int] = None
) -> Tuple[bool, Optional[str]]:
    """
    Checks if FFmpeg's 'dvdvideo' demuxer can read the given title/source.
    Results are cached per (ffmpeg_path, dvd_source, title_num) to avoid
    costly, repeated optical disc spin-up delays on every chapter.
    """
    cache_key = (str(ffmpeg_path), str(dvd_source), int(title_num))
    if cache_key in _dvdvideo_probe_cache:
        return _dvdvideo_probe_cache[cache_key]

    dvd_dir = find_video_ts_dir(dvd_source)
    candidates: List[str] = []
    if dvd_dir:
        if dvd_dir.name.upper() == "VIDEO_TS":
            candidates.append(str(dvd_dir.parent))
            candidates.append(str(dvd_dir))
        else:
            candidates.append(str(dvd_dir))
    if dvd_source and str(dvd_source) not in candidates:
        candidates.append(str(dvd_source))

    can_use = False
    target_path = None

    for cand in candidates:
        try:
            test_cmd = [
                ffmpeg_path, "-v", "error",
                "-f", "dvdvideo",
                "-title", str(title_num),
            ]
            if chapter_num is not None:
                test_cmd.extend(["-chapter_start", str(chapter_num), "-chapter_end", str(chapter_num)])
            test_cmd.extend([
                "-i", cand,
                "-t", "0.1",
                "-f", "null", "-"
            ])
            check_res = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5, **get_subprocess_kwargs())
            if check_res.returncode == 0:
                can_use = True
                target_path = cand
                break
        except Exception:
            pass

    _dvdvideo_probe_cache[cache_key] = (can_use, target_path)
    return can_use, target_path


# ─────────────────────────────────────────────
#  DVD Ripping Command Construction
# ─────────────────────────────────────────────
def prepare_dvd_rip_job(
    ffmpeg_path: str,
    dvd_source: str,
    title_dict: Dict[str, Any],
    out_dir: str,
    output_format: str,
    use_1080p: bool = False,
    audio_only: bool = False,
    audio_format: str = "WAV",
    temp_dir: Optional[str] = None,
    audio_track: Optional[Dict[str, Any]] = None,
    custom_output_filename: Optional[str] = None,
    fps_mode: Optional[str] = None
) -> Tuple[List[str], str, Optional[str]]:
    """
    Constructs an FFmpeg command and output path for ripping a single DVD title.
    Returns (cmd_args, output_filepath, temp_concat_file_or_None).

    Supports:
    - MP4: H.264 + AAC
    - MOV: H.264 + AAC
    - MPG: MPEG program stream (lossless copy when compatible or remux)
    - WAV: 16-bit PCM (Audio Only)
    - MP3: LAME MP3 (Audio Only)
    """
    vob_files: List[str] = title_dict.get("vob_files", [])
    title_num = title_dict.get("title_number", 1)
    custom_stem = title_dict.get("custom_stem") or f"Title_{title_num:02d}"

    # Resolve audio track and validate if title has tracks cataloged
    resolved_audio: Optional[Dict[str, Any]] = None
    if audio_track is not None:
        resolved_audio = audio_track
        if title_dict.get("audio_tracks"):
            t_ids = [t.get("track_id") if isinstance(t, dict) else getattr(t, "track_id", "") for t in title_dict["audio_tracks"]]
            t_nums = [t.get("track_number") if isinstance(t, dict) else getattr(t, "track_number", 0) for t in title_dict["audio_tracks"]]
            if audio_track.get("track_id") and audio_track.get("track_id") not in t_ids:
                if audio_track.get("track_number") not in t_nums:
                    raise ValueError(f"Selected audio track '{audio_track.get('track_id') or audio_track.get('track_number')}' not found for Title {title_num}.")
    elif title_dict.get("audio_tracks"):
        first_trk = title_dict["audio_tracks"][0]
        resolved_audio = first_trk.to_dict() if isinstance(first_trk, DVDAudioTrack) else first_trk

    # Determine extension and filenames
    if audio_only:
        ext = ".wav" if audio_format == "WAV" else ".mp3"
    elif output_format == "MPG":
        ext = ".mpg"
    elif output_format == "MOV":
        ext = ".mov"
    else:
        ext = ".mp4"

    if custom_output_filename:
        out_filename = custom_output_filename
    else:
        out_filename = f"{custom_stem}{ext}"
    out_path = os.path.join(out_dir, out_filename)

    # Collision avoidance
    if os.path.exists(out_path):
        stem, e = os.path.splitext(out_path)
        out_path = f"{stem}_{int(time.time())}{e}"

    # Try libdvdread / dvdvideo demuxer test (cached)
    can_use_dvdvideo, target_dvd_path = check_dvdvideo_support(ffmpeg_path, dvd_source, title_num)
    dvd_dir = find_video_ts_dir(dvd_source)

    temp_concat_file = None
    input_args: List[str] = []

    if can_use_dvdvideo and target_dvd_path:
        input_args = [
            "-f", "dvdvideo",
            "-title", str(title_num),
            "-i", target_dvd_path
        ]
    else:
        actual_vobs = vob_files
        if not actual_vobs and dvd_dir:
            vts_num = title_dict.get("vts_number", title_num)
            cand_vobs = sorted([
                str(f.resolve()) for f in dvd_dir.iterdir()
                if f.name.upper().startswith(f"VTS_{vts_num:02d}_") and f.name.upper().endswith(".VOB")
                and not f.name.upper().endswith("_0.VOB")
            ])
            if not cand_vobs:
                cand_vobs = sorted([
                    str(f.resolve()) for f in dvd_dir.iterdir()
                    if f.name.upper().startswith("VTS_") and f.name.upper().endswith(".VOB")
                    and not f.name.upper().endswith("_0.VOB")
                ])
            actual_vobs = cand_vobs

        if actual_vobs:
            t_dir = temp_dir or tempfile.gettempdir()
            temp_concat_file = os.path.join(t_dir, f"dvd_concat_{title_num}_{int(time.time())}.txt")
            with open(temp_concat_file, "w", encoding="utf-8") as f:
                for vob in actual_vobs:
                    p_normalized = str(vob).replace("\\", "/")
                    f.write(f"file '{p_normalized}'\n")

            input_args = [
                "-f", "concat",
                "-safe", "0",
                "-i", temp_concat_file
            ]
        elif dvd_dir:
            input_args = ["-i", str(dvd_dir)]

    # Encoding / Transcoding arguments
    codec_args: List[str] = []

    if audio_only:
        if audio_format == "WAV":
            # Preserve all channels (including 6-channel 5.1 PCM) at DVD sample rate 48000 Hz
            codec_args = ["-vn", "-c:a", "pcm_s16le", "-ar", "48000"]
        else:  # MP3
            # MP3 does not support 6 channels; downmix 5.1 to stereo (-ac 2)
            ch_cnt = int(resolved_audio.get("channel_count", 2)) if resolved_audio else 2
            is_51 = (resolved_audio.get("channels") == "5.1") if resolved_audio else False
            if ch_cnt > 2 or is_51:
                codec_args = ["-vn", "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2"]
            else:
                codec_args = ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif output_format == "MPG":
        # DVD VOB is MPEG-2 program stream: use stream copy for AC-3, MP2, LPCM
        # If audio track is DTS or AAC, transcode to AC-3 384k to avoid corrupted MPEG-PS
        raw_c = str(resolved_audio.get("codec") or "").lower() if resolved_audio else ""
        if "dts" in raw_c or "aac" in raw_c:
            codec_args = ["-c:v", "copy", "-c:a", "ac3", "-b:a", "384k"]
        else:
            codec_args = ["-c:v", "copy", "-c:a", "copy"]
    elif output_format in ("MP4", "MOV"):
        video_filters: List[str] = []
        if use_1080p:
            # Upscale DVD (720x480 / 720x576) to 1440x1080 (4:3) or 1920x1080 (16:9)
            ar = title_dict.get("aspect_ratio", "4:3")
            if ar == "16:9":
                video_filters.append("scale=1920:1080:flags=lanczos")
            else:
                video_filters.append("scale=1440:1080:flags=lanczos")

        filter_args = ["-vf", ",".join(video_filters)] if video_filters else []
        ch_cnt = int(resolved_audio.get("channel_count", 2)) if resolved_audio else 2
        is_51 = (resolved_audio.get("channels") == "5.1") if resolved_audio else False
        a_br = "384k" if (ch_cnt > 2 or is_51) else "192k"
        codec_args = [
            *filter_args,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-af", "aresample=async=1000",
            "-c:a", "aac",
            "-b:a", a_br
        ]

    # Map video stream (if not audio-only) and selected audio stream index
    ff_stream_idx = 0
    if resolved_audio:
        raw_idx = resolved_audio.get("ffmpeg_stream_index")
        if raw_idx is None:
            raw_idx = resolved_audio.get("stream_index", 0)
        ff_stream_idx = int(raw_idx)

    map_args = ["-map", "0:v:0", "-map", f"0:a:{ff_stream_idx}"] if not audio_only else ["-map", f"0:a:{ff_stream_idx}"]

    input_opt_args: List[str] = []
    if audio_only:
        input_opt_args = ["-probesize", "1000000", "-analyzeduration", "1000000"]
    else:
        input_opt_args = ["-analyzeduration", "10000000", "-probesize", "10000000"]

    fps_mode_args: List[str] = []
    if not audio_only:
        if output_format == "MPG":
            fps_mode_args = ["-fps_mode", "passthrough"]
        else:
            mode_val = (fps_mode or "Passthrough").strip().lower()
            if mode_val == "cfr":
                fps_mode_args = ["-fps_mode", "cfr"]
            else:
                fps_mode_args = ["-fps_mode", "passthrough"]

    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        *input_opt_args,
        *input_args,
        *map_args,
        *codec_args,
        *(["-sn", "-dn", "-threads", "0"] if audio_only else []),
        "-avoid_negative_ts", "make_zero",
        *fps_mode_args,
        "-max_muxing_queue_size", "2048",
        "-max_error_rate", "1.0",
        "-y",
        out_path
    ]

    return cmd, out_path, temp_concat_file


def prepare_dvd_chapter_rip_job(
    ffmpeg_path: str,
    dvd_source: str,
    title_dict: Dict[str, Any],
    chapter_dict: Dict[str, Any],
    out_dir: str,
    output_format: str,
    use_1080p: bool = False,
    audio_only: bool = False,
    audio_format: str = "WAV",
    temp_dir: Optional[str] = None,
    audio_track: Optional[Dict[str, Any]] = None,
    custom_output_filename: Optional[str] = None,
    fps_mode: Optional[str] = None
) -> Tuple[List[str], str, Optional[str]]:
    """
    Constructs an FFmpeg command and output path for ripping a single DVD chapter.
    Returns (cmd_args, output_filepath, temp_concat_file_or_None).

    Supports:
    - MP4: H.264 + AAC
    - MOV: H.264 + AAC
    - MPG: MPEG program stream
    - WAV: 16-bit PCM (Audio Only)
    - MP3: LAME MP3 (Audio Only)
    """
    vob_files: List[str] = title_dict.get("vob_files", [])
    title_num = title_dict.get("title_number", 1)
    custom_stem = title_dict.get("custom_stem") or f"Title_{title_num:02d}"
    c_num = int(chapter_dict.get("chapter_number", 1))

    # Resolve audio track and validate against parent title
    resolved_audio: Optional[Dict[str, Any]] = None
    if audio_track is not None:
        resolved_audio = audio_track
        if title_dict.get("audio_tracks"):
            t_ids = [t.get("track_id") if isinstance(t, dict) else getattr(t, "track_id", "") for t in title_dict["audio_tracks"]]
            t_nums = [t.get("track_number") if isinstance(t, dict) else getattr(t, "track_number", 0) for t in title_dict["audio_tracks"]]
            if audio_track.get("track_id") and audio_track.get("track_id") not in t_ids:
                if audio_track.get("track_number") not in t_nums:
                    raise ValueError(f"Selected audio track '{audio_track.get('track_id') or audio_track.get('track_number')}' not found for Title {title_num}.")
    elif title_dict.get("audio_tracks"):
        first_trk = title_dict["audio_tracks"][0]
        resolved_audio = first_trk.to_dict() if isinstance(first_trk, DVDAudioTrack) else first_trk

    # Filename format: <TitleStem> - <ChapterStem>.<ext>
    c_custom = chapter_dict.get("custom_stem") or chapter_dict.get("name") or f"Chapter {c_num:02d}"
    chap_tag = sanitize_filename(c_custom, fallback=f"Chapter_{c_num:02d}")
    out_stem = f"{custom_stem} - {chap_tag}"

    if audio_only:
        ext = ".wav" if audio_format == "WAV" else ".mp3"
    elif output_format == "MPG":
        ext = ".mpg"
    elif output_format == "MOV":
        ext = ".mov"
    else:
        ext = ".mp4"

    if custom_output_filename:
        out_filename = custom_output_filename
    else:
        out_filename = f"{out_stem}{ext}"
    out_path = os.path.join(out_dir, out_filename)

    # Collision avoidance
    if os.path.exists(out_path):
        stem, e = os.path.splitext(out_path)
        out_path = f"{stem}_{int(time.time())}{e}"

    start_time = float(chapter_dict.get("start_time", 0.0))
    duration = float(chapter_dict.get("duration", 0.0))
    end_time = float(chapter_dict.get("end_time", start_time + duration))
    if duration <= 0.0 and end_time > start_time:
        duration = end_time - start_time

    # Check dvdvideo demuxer with chapter support (cached per title/source)
    can_use_dvdvideo, target_dvd_path = check_dvdvideo_support(ffmpeg_path, dvd_source, title_num, chapter_num=c_num)
    dvd_dir = find_video_ts_dir(dvd_source)

    temp_concat_file = None
    input_args: List[str] = []
    seek_args: List[str] = []

    if can_use_dvdvideo and target_dvd_path:
        input_args = [
            "-f", "dvdvideo",
            "-title", str(title_num),
            "-chapter_start", str(c_num),
            "-chapter_end", str(c_num),
            "-i", target_dvd_path
        ]
        if duration > 0:
            seek_args.extend(["-t", f"{duration:.3f}"])
    else:
        actual_vobs = vob_files
        if not actual_vobs and dvd_dir:
            vts_num = title_dict.get("vts_number", title_num)
            cand_vobs = sorted([
                str(f.resolve()) for f in dvd_dir.iterdir()
                if f.name.upper().startswith(f"VTS_{vts_num:02d}_") and f.name.upper().endswith(".VOB")
                and not f.name.upper().endswith("_0.VOB")
            ])
            if not cand_vobs:
                cand_vobs = sorted([
                    str(f.resolve()) for f in dvd_dir.iterdir()
                    if f.name.upper().startswith("VTS_") and f.name.upper().endswith(".VOB")
                    and not f.name.upper().endswith("_0.VOB")
                ])
            actual_vobs = cand_vobs

        if actual_vobs:
            t_dir = temp_dir or tempfile.gettempdir()
            temp_concat_file = os.path.join(t_dir, f"dvd_concat_{title_num}_c{c_num}_{int(time.time())}.txt")
            with open(temp_concat_file, "w", encoding="utf-8") as f:
                for vob in actual_vobs:
                    p_normalized = str(vob).replace("\\", "/")
                    f.write(f"file '{p_normalized}'\n")

            # Fast input-side seeking BEFORE -i
            if start_time > 0:
                input_args.extend(["-ss", f"{start_time:.3f}"])
            input_args.extend([
                "-f", "concat",
                "-safe", "0",
                "-i", temp_concat_file
            ])
            if duration > 0:
                seek_args.extend(["-t", f"{duration:.3f}"])
        elif dvd_dir:
            if start_time > 0:
                input_args.extend(["-ss", f"{start_time:.3f}"])
            input_args.extend(["-i", str(dvd_dir)])
            if duration > 0:
                seek_args.extend(["-t", f"{duration:.3f}"])

    codec_args: List[str] = []

    if audio_only:
        if audio_format == "WAV":
            codec_args = ["-vn", "-c:a", "pcm_s16le", "-ar", "48000"]
        else:
            ch_cnt = int(resolved_audio.get("channel_count", 2)) if resolved_audio else 2
            is_51 = (resolved_audio.get("channels") == "5.1") if resolved_audio else False
            if ch_cnt > 2 or is_51:
                codec_args = ["-vn", "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2"]
            else:
                codec_args = ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif output_format == "MPG":
        raw_c = str(resolved_audio.get("codec") or "").lower() if resolved_audio else ""
        if "dts" in raw_c or "aac" in raw_c:
            codec_args = ["-c:v", "copy", "-c:a", "ac3", "-b:a", "384k"]
        else:
            codec_args = ["-c:v", "copy", "-c:a", "copy"]
    elif output_format in ("MP4", "MOV"):
        video_filters: List[str] = []
        if use_1080p:
            ar = title_dict.get("aspect_ratio", "4:3")
            if ar == "16:9":
                video_filters.append("scale=1920:1080:flags=lanczos")
            else:
                video_filters.append("scale=1440:1080:flags=lanczos")

        filter_args = ["-vf", ",".join(video_filters)] if video_filters else []
        ch_cnt = int(resolved_audio.get("channel_count", 2)) if resolved_audio else 2
        is_51 = (resolved_audio.get("channels") == "5.1") if resolved_audio else False
        a_br = "384k" if (ch_cnt > 2 or is_51) else "192k"
        codec_args = [
            *filter_args,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-af", "aresample=async=1000",
            "-c:a", "aac",
            "-b:a", a_br
        ]

    ff_stream_idx = 0
    if resolved_audio:
        raw_idx = resolved_audio.get("ffmpeg_stream_index")
        if raw_idx is None:
            raw_idx = resolved_audio.get("stream_index", 0)
        ff_stream_idx = int(raw_idx)

    map_args = ["-map", "0:v:0", "-map", f"0:a:{ff_stream_idx}"] if not audio_only else ["-map", f"0:a:{ff_stream_idx}"]

    input_opt_args: List[str] = []
    if audio_only:
        input_opt_args = ["-probesize", "1000000", "-analyzeduration", "1000000"]
    else:
        input_opt_args = ["-analyzeduration", "10000000", "-probesize", "10000000"]

    fps_mode_args: List[str] = []
    if not audio_only:
        if output_format == "MPG":
            fps_mode_args = ["-fps_mode", "passthrough"]
        else:
            mode_val = (fps_mode or "Passthrough").strip().lower()
            if mode_val == "cfr":
                fps_mode_args = ["-fps_mode", "cfr"]
            else:
                fps_mode_args = ["-fps_mode", "passthrough"]

    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        *input_opt_args,
        *input_args,
        *seek_args,
        *map_args,
        *codec_args,
        *(["-sn", "-dn", "-threads", "0"] if audio_only else []),
        "-avoid_negative_ts", "make_zero",
        *fps_mode_args,
        "-max_muxing_queue_size", "2048",
        "-max_error_rate", "1.0",
        "-y",
        out_path
    ]

    return cmd, out_path, temp_concat_file


def prepare_dvd_audio_from_video_job(
    ffmpeg_path: str,
    local_video_path: str,
    title_dict: Dict[str, Any],
    chapter_dict: Optional[Dict[str, Any]],
    out_dir: str,
    audio_format: str = "WAV",
    audio_track: Optional[Dict[str, Any]] = None,
    custom_output_filename: Optional[str] = None
) -> Tuple[List[str], str]:
    """
    Constructs an ultra-fast FFmpeg command to extract the audio track directly from an
    already-ripped local video file (MP4/MOV/MPG) on disk.
    This eliminates redundant optical disc reads and chapter probes during 'Extract Both' mode.
    """
    title_num = title_dict.get("title_number", 1)
    ext = ".wav" if audio_format == "WAV" else ".mp3"

    if chapter_dict is not None:
        c_num = int(chapter_dict.get("chapter_number", 1))
        title_stem = title_dict.get("custom_stem") or f"Title_{title_num:02d}"
        c_custom = chapter_dict.get("custom_stem") or chapter_dict.get("name") or f"Chapter {c_num:02d}"
        c_tag = sanitize_filename(c_custom, fallback=f"Chapter_{c_num:02d}")
        out_stem = f"{title_stem} - {c_tag}"
    else:
        out_stem = title_dict.get("custom_stem") or f"Title_{title_num:02d}"

    if custom_output_filename:
        out_filename = custom_output_filename
    else:
        out_filename = f"{out_stem}{ext}"

    out_path = os.path.join(out_dir, out_filename)
    if os.path.exists(out_path):
        stem, e = os.path.splitext(out_path)
        out_path = f"{stem}_{int(time.time())}{e}"

    if audio_format == "WAV":
        codec_args = ["-vn", "-sn", "-dn", "-c:a", "pcm_s16le", "-ar", "48000"]
    else:  # MP3
        codec_args = ["-vn", "-sn", "-dn", "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2"]

    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-err_detect", "ignore_err",
        "-i", local_video_path,
        "-map", "0:a:0",
        *codec_args,
        "-threads", "0",
        "-y",
        out_path
    ]
    return cmd, out_path


# ─────────────────────────────────────────────
#  HandBrakeCLI Integration
# ─────────────────────────────────────────────
def find_handbrake() -> Optional[str]:
    """
    Locates HandBrakeCLI.exe executable across standard discovery paths:
    1. PyInstaller MEIPASS bundle directory / application root (ffmpeg/bin, handbrake/bin, root)
    2. System PATH
    3. WinGet default locations
    4. Program Files locations
    """
    candidates = []

    # 1. Application directory / bundled locations
    app_dirs = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        app_dirs.append(Path(sys._MEIPASS))
    app_dirs.append(Path(__file__).resolve().parent)
    app_dirs.append(Path(sys.executable).resolve().parent)

    for base in app_dirs:
        candidates.append(base / "ffmpeg" / "bin" / "HandBrakeCLI.exe")
        candidates.append(base / "handbrake" / "bin" / "HandBrakeCLI.exe")
        candidates.append(base / "HandBrakeCLI.exe")

    # 2. System PATH
    which_hb = shutil.which("HandBrakeCLI") or shutil.which("HandBrakeCLI.exe")
    if which_hb:
        candidates.append(Path(which_hb))

    # 3. WinGet default paths
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "HandBrakeCLI.exe")
        candidates.append(Path(local_app_data) / "Programs" / "HandBrake" / "HandBrakeCLI.exe")

    # 4. Program Files
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates.append(Path(prog_files) / "HandBrake" / "HandBrakeCLI.exe")
    candidates.append(Path(prog_files_x86) / "HandBrake" / "HandBrakeCLI.exe")

    for c in candidates:
        try:
            if c.is_file() and os.access(str(c), os.X_OK):
                return str(c.resolve())
        except Exception:
            pass

    return None


def get_handbrake_version(hb_path: Optional[str] = None) -> Optional[str]:
    """
    Queries HandBrakeCLI version (e.g. 'HandBrake 1.11.2').
    Returns formatted version string or None if unexecutable.
    """
    exe = hb_path or find_handbrake()
    if not exe or not os.path.isfile(exe):
        return None
    try:
        res = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            **get_subprocess_kwargs()
        )
        combined = (res.stdout or "") + "\n" + (res.stderr or "")
        m = re.search(r"HandBrake\s+([\d\.]+)", combined, re.IGNORECASE)
        if m:
            return f"HandBrake {m.group(1)}"
        for line in combined.splitlines():
            line_s = line.strip()
            if "handbrake" in line_s.lower():
                return line_s
    except Exception:
        pass
    return None


def parse_handbrake_json_title_set(json_data: Dict[str, Any], source_path: str = "") -> List[DVDTitle]:
    """
    Parses 'JSON Title Set' dictionary from HandBrakeCLI into DVDTitle and DVDChapter dataclasses.
    """
    title_list = json_data.get("TitleList", [])
    if not isinstance(title_list, list) or not title_list:
        return []

    main_feature_idx = json_data.get("MainFeature", 0)
    titles: List[DVDTitle] = []

    # Check if VIDEO_TS directory is present on disk to find VOB files if needed
    dvd_dir = find_video_ts_dir(source_path) if source_path else None
    vob_map: Dict[int, List[str]] = {}
    if dvd_dir:
        try:
            for item in dvd_dir.iterdir():
                if item.name.upper().startswith("VTS_") and item.name.upper().endswith(".VOB"):
                    parts = item.name.upper().split("_")
                    if len(parts) == 3:
                        try:
                            v_num = int(parts[1])
                            seg = int(parts[2].split(".")[0])
                            if seg >= 1:
                                vob_map.setdefault(v_num, []).append(str(item.resolve()))
                        except Exception:
                            pass
            for v_num in vob_map:
                vob_map[v_num].sort()
        except Exception:
            pass

    for idx, t_raw in enumerate(title_list):
        t_num = int(t_raw.get("Index", idx + 1))

        # Duration
        dur_obj = t_raw.get("Duration", {})
        dur_sec = float(
            dur_obj.get("Hours", 0) * 3600 +
            dur_obj.get("Minutes", 0) * 60 +
            dur_obj.get("Seconds", 0)
        )
        ticks = float(dur_obj.get("Ticks", 0))
        if ticks > 0:
            dur_sec += ticks / 90000.0
        dur_sec = round(dur_sec, 2)

        # Geometry
        geom = t_raw.get("Geometry", {})
        width = int(geom.get("Width", 720))
        height = int(geom.get("Height", 480))
        par = geom.get("PAR", {})
        p_num = par.get("Num") or par.get("Numerator") or 1
        p_den = par.get("Den") or par.get("Denominator") or 1
        dar = (width * p_num) / (height * p_den) if height > 0 else 1.33
        ar = "16:9" if dar >= 1.6 else "4:3"

        # Frame rate
        fr_obj = t_raw.get("FrameRate", {})
        f_num = fr_obj.get("Num") or fr_obj.get("Numerator") or 0
        f_den = fr_obj.get("Den") or fr_obj.get("Denominator") or 1
        if f_num > 0 and f_den > 0:
            fps_val = round(f_num / f_den, 2)
            fps_str = f"{fps_val} fps"
        else:
            fps_str = "29.97 fps"

        # Codec
        v_codec_raw = t_raw.get("VideoCodec", "mpeg2")
        v_codec = "MPEG-2" if "mpeg2" in str(v_codec_raw).lower() else str(v_codec_raw).upper()

        # Chapters
        chap_list = t_raw.get("ChapterList", [])
        chapters_data: List[DVDChapter] = []
        chapters_starts: List[float] = []
        cum_time = 0.0

        for c_i, c_raw in enumerate(chap_list, 1):
            c_dur_obj = c_raw.get("Duration", {})
            c_dur = float(
                c_dur_obj.get("Hours", 0) * 3600 +
                c_dur_obj.get("Minutes", 0) * 60 +
                c_dur_obj.get("Seconds", 0)
            )
            c_ticks = float(c_dur_obj.get("Ticks", 0))
            if c_ticks > 0:
                c_dur += c_ticks / 90000.0
            c_dur = round(c_dur, 2)

            start_t = round(cum_time, 2)
            end_t = round(cum_time + c_dur, 2)
            c_name = c_raw.get("Name") or f"Chapter {c_i:02d}"

            chapter_obj = DVDChapter(
                chapter_number=c_i,
                start_time=start_t,
                end_time=end_t,
                duration=c_dur,
                title_number=t_num,
                name=c_name
            )
            chapters_data.append(chapter_obj)
            chapters_starts.append(start_t)
            cum_time = end_t

        if chapters_data and cum_time > 0 and dur_sec <= 0:
            dur_sec = round(cum_time, 2)

        # Audio streams & DVDAudioTrack list
        audio_list = t_raw.get("AudioList", [])
        audio_streams: List[Dict[str, Any]] = []
        audio_tracks: List[DVDAudioTrack] = []
        for a_i, a_raw in enumerate(audio_list):
            desc = a_raw.get("Description", "")
            lang_code = a_raw.get("LanguageCode") or a_raw.get("Language") or "und"
            lang_lookup = get_language_name(str(lang_code))
            raw_l = a_raw.get("Language")
            if lang_lookup and len(lang_lookup) > 3 and lang_lookup.lower() not in ("undetermined", "unknown", "und"):
                lang_name = lang_lookup
            elif raw_l:
                raw_lookup = get_language_name(str(raw_l))
                lang_name = raw_lookup if (raw_lookup and len(raw_lookup) > 3) else raw_l
            else:
                lang_name = "Unknown Language"
            fmt = a_raw.get("Format") or a_raw.get("Codec") or "AC3"
            srate = a_raw.get("SampleRate", 48000)
            bitrate = a_raw.get("BitRate") or a_raw.get("Bitrate") or 0
            ch_desc = "2.0"
            if "5.1" in desc or "6 ch" in desc.lower():
                ch_desc = "5.1"
            elif "mono" in desc.lower() or "1 ch" in desc.lower():
                ch_desc = "1.0"
            elif "stereo" in desc.lower() or "2 ch" in desc.lower():
                ch_desc = "2.0"
            elif a_raw.get("ChannelLayout"):
                ch_desc = str(a_raw.get("ChannelLayout"))

            audio_streams.append({
                "index": a_i,
                "format": fmt,
                "channels": ch_desc,
                "lang": str(lang_code).lower(),
                "lang_name": lang_name,
            })

            trk = normalize_audio_track(
                title_number=t_num,
                track_number=a_i + 1,
                stream_index=a_i,
                raw_codec=fmt,
                raw_channels=ch_desc,
                raw_lang=str(lang_code),
                raw_lang_name=lang_name,
                sample_rate=srate,
                bitrate=bitrate,
                hb_track_index=a_i + 1,
                ffmpeg_stream_index=a_i,
            )
            audio_tracks.append(trk)

        # Subtitle streams
        sub_list = t_raw.get("SubtitleList", [])
        sub_streams: List[Dict[str, Any]] = []
        for s_i, s_raw in enumerate(sub_list):
            lang_code = s_raw.get("LanguageCode", "und")
            sub_streams.append({
                "index": s_i,
                "format": s_raw.get("Format", "VOBSUB"),
                "lang": lang_code.lower(),
                "lang_name": get_language_name(lang_code),
            })

        # Match VOB files by title index if available
        matched_vobs = vob_map.get(t_num, [])
        if not matched_vobs and t_raw.get("Path") and os.path.isfile(t_raw["Path"]):
            matched_vobs = [str(Path(t_raw["Path"]).resolve())]
        if not matched_vobs and len(vob_map) == 1:
            matched_vobs = list(vob_map.values())[0]

        title_obj = DVDTitle(
            title_number=t_num,
            vts_number=t_num,
            ttn=1,
            duration=dur_sec,
            chapter_count=len(chapters_data) if chapters_data else 1,
            chapters=chapters_starts,
            chapters_data=chapters_data,
            video_codec=v_codec,
            resolution=f"{width}×{height}",
            width=width,
            height=height,
            aspect_ratio=ar,
            fps=fps_str,
            system="NTSC" if height == 480 else "PAL",
            audio_streams=audio_streams,
            audio_tracks=audio_tracks,
            subtitle_streams=sub_streams,
            vob_files=matched_vobs,
            size_mb=round(sum(os.path.getsize(f) for f in matched_vobs) / (1024**2), 1) if matched_vobs else 0.0,
            is_main_feature=False,
            name=f"Title {t_num:02d}",
        )
        titles.append(title_obj)

    # Determine main feature
    if titles:
        if main_feature_idx > 0:
            for t in titles:
                if t.title_number == main_feature_idx:
                    t.is_main_feature = True
                    break
        if not any(t.is_main_feature for t in titles):
            valid_durs = [t for t in titles if t.duration > 0]
            if valid_durs:
                longest = max(valid_durs, key=lambda x: x.duration)
                if longest.duration >= 300:
                    longest.is_main_feature = True

    return titles


@dataclass
class DVDSourceInspection:
    source_path: str
    is_accessible: bool = False
    is_drive: bool = False
    is_mounted: bool = False
    has_video_ts: bool = False
    has_video_ts_ifo: bool = False
    ifo_files: List[str] = field(default_factory=list)
    bup_files: List[str] = field(default_factory=list)
    vob_files: List[str] = field(default_factory=list)
    source_type: str = "unknown"  # "dvd_drive", "dvd_folder", "dvd_iso", "inaccessible", "invalid"
    error_message: Optional[str] = None


def inspect_dvd_source(source_path: str) -> DVDSourceInspection:
    """
    Inspects DVD source accessibility, drive mounting status, and VIDEO_TS / IFO / VOB structure.
    Accurately distinguishes physical optical drives from local folders/ISOs.
    Harmless absence of Blu-ray BDMV directory is not treated as a DVD error.
    """
    if not source_path or not isinstance(source_path, str) or not source_path.strip():
        return DVDSourceInspection(
            source_path=str(source_path or ""),
            is_accessible=False,
            source_type="invalid",
            error_message="DVD source path is empty or not specified."
        )

    norm_path = source_path.strip()
    is_drive = False
    if sys.platform == "win32":
        if len(norm_path) <= 3 and norm_path[1:2] == ":":
            is_drive = True
        elif Path(norm_path).anchor == norm_path:
            is_drive = True

    try:
        p = Path(norm_path)
        if not p.exists():
            msg = f"Optical drive '{norm_path}' is empty, unmounted, or not accessible." if is_drive else f"Path '{norm_path}' does not exist."
            return DVDSourceInspection(
                source_path=norm_path,
                is_accessible=False,
                is_drive=is_drive,
                is_mounted=False,
                source_type="inaccessible",
                error_message=msg,
            )
    except Exception as ex:
        return DVDSourceInspection(
            source_path=norm_path,
            is_accessible=False,
            is_drive=is_drive,
            is_mounted=False,
            source_type="inaccessible",
            error_message=f"Cannot access '{norm_path}': {ex}",
        )

    # Check for ISO file
    if p.is_file():
        if norm_path.lower().endswith(".iso"):
            return DVDSourceInspection(
                source_path=norm_path,
                is_accessible=True,
                is_drive=False,
                is_mounted=True,
                source_type="dvd_iso",
            )
        return DVDSourceInspection(
            source_path=norm_path,
            is_accessible=True,
            is_drive=False,
            is_mounted=True,
            source_type="invalid",
            error_message=f"File '{norm_path}' is not a DVD image or folder.",
        )

    # Directory inspection: locate VIDEO_TS
    video_ts_dir = find_video_ts_dir(norm_path)
    if not video_ts_dir or not video_ts_dir.is_dir():
        return DVDSourceInspection(
            source_path=norm_path,
            is_accessible=True,
            is_drive=is_drive,
            is_mounted=True,
            has_video_ts=False,
            source_type="invalid",
            error_message=f"No VIDEO_TS directory or DVD structure found in '{norm_path}'.",
        )

    # Scan inside VIDEO_TS
    ifo_list: List[str] = []
    bup_list: List[str] = []
    vob_list: List[str] = []
    has_vmgi_ifo = False

    try:
        for entry in video_ts_dir.iterdir():
            if entry.is_file():
                en_name = entry.name.upper()
                if en_name.endswith(".IFO"):
                    ifo_list.append(str(entry))
                    if en_name == "VIDEO_TS.IFO":
                        has_vmgi_ifo = True
                elif en_name.endswith(".BUP"):
                    bup_list.append(str(entry))
                elif en_name.endswith(".VOB"):
                    vob_list.append(str(entry))
    except Exception as ex:
        return DVDSourceInspection(
            source_path=norm_path,
            is_accessible=False,
            is_drive=is_drive,
            is_mounted=False,
            source_type="inaccessible",
            error_message=f"Error reading contents of '{video_ts_dir}': {ex}",
        )

    # Verify IFO readability
    if has_vmgi_ifo:
        vmgi_file = video_ts_dir / "VIDEO_TS.IFO"
        try:
            with open(vmgi_file, "rb") as f:
                head = f.read(12)
                if not head.startswith(b"DVDVIDEO-VMG"):
                    pass  # Handled by binary parser
        except Exception as ex:
            return DVDSourceInspection(
                source_path=norm_path,
                is_accessible=True,
                is_drive=is_drive,
                is_mounted=True,
                has_video_ts=True,
                has_video_ts_ifo=True,
                ifo_files=ifo_list,
                bup_files=bup_list,
                vob_files=vob_list,
                source_type="dvd_drive" if is_drive else "dvd_folder",
                error_message=f"VIDEO_TS.IFO is unreadable: {ex}",
            )

    return DVDSourceInspection(
        source_path=norm_path,
        is_accessible=True,
        is_drive=is_drive,
        is_mounted=True,
        has_video_ts=True,
        has_video_ts_ifo=has_vmgi_ifo,
        ifo_files=ifo_list,
        bup_files=bup_list,
        vob_files=vob_list,
        source_type="dvd_drive" if is_drive else "dvd_folder",
    )


@dataclass
class HandBrakeValidationResult:
    success: bool = False
    working_source_path: Optional[str] = None
    titles: List[DVDTitle] = field(default_factory=list)
    title_count: int = 0
    error_category: Optional[str] = None  # "inaccessible_source", "zero_titles_found", "missing_dvd_structure", "handbrake_missing", "scan_failed", "timeout", "exception"
    error_message: Optional[str] = None
    raw_output_tail: List[str] = field(default_factory=list)


_hb_source_validation_cache: Dict[Tuple[str, str], HandBrakeValidationResult] = {}


def clear_handbrake_validation_cache():
    """Clear cached HandBrake source validation results."""
    _hb_source_validation_cache.clear()


def validate_handbrake_source(
    hb_path: str,
    source_path: str,
    min_duration: int = 0,
    timeout: int = 30,
) -> HandBrakeValidationResult:
    """
    Validates HandBrakeCLI against a DVD source by probing candidate paths
    (VIDEO_TS directory vs drive root).
    Caches results per (hb_path, source_path) to prevent repetitive probing.
    """
    cache_key = (
        os.path.abspath(hb_path) if hb_path else "",
        os.path.abspath(source_path) if source_path else ""
    )
    if cache_key in _hb_source_validation_cache:
        return _hb_source_validation_cache[cache_key]

    insp = inspect_dvd_source(source_path)
    if not insp.is_accessible:
        res = HandBrakeValidationResult(
            success=False,
            error_category="inaccessible_source",
            error_message=insp.error_message or f"DVD source '{source_path}' is inaccessible.",
        )
        _hb_source_validation_cache[cache_key] = res
        return res

    if not insp.has_video_ts and insp.source_type != "dvd_iso":
        res = HandBrakeValidationResult(
            success=False,
            error_category="missing_dvd_structure",
            error_message=insp.error_message or f"No DVD VIDEO_TS structure found in '{source_path}'.",
        )
        _hb_source_validation_cache[cache_key] = res
        return res

    if not hb_path or not os.path.isfile(hb_path):
        res = HandBrakeValidationResult(
            success=False,
            error_category="handbrake_missing",
            error_message="HandBrakeCLI executable not found or not specified.",
        )
        return res


    # Candidate source paths: HandBrake on Windows can be picky about VIDEO_TS vs parent drive
    candidates: List[str] = []
    dvd_dir = find_video_ts_dir(source_path)
    if dvd_dir:
        # Candidate 1: Direct VIDEO_TS folder (e.g. E:\VIDEO_TS)
        candidates.append(str(dvd_dir))
        # Candidate 2: Parent folder / drive root (e.g. E:\)
        if dvd_dir.name.upper() == "VIDEO_TS" and dvd_dir.parent:
            candidates.append(str(dvd_dir.parent))
    candidates.append(source_path)

    # Deduplicate while preserving candidate order
    seen = set()
    unique_candidates = []
    for c in candidates:
        cn = os.path.normpath(c)
        if cn not in seen:
            seen.add(cn)
            unique_candidates.append(c)

    last_error_category = "scan_failed"
    last_error_msg = "HandBrakeCLI scan returned no valid titles"
    last_tail: List[str] = []

    for cand in unique_candidates:
        cmd = [
            hb_path,
            "-i", cand,
            "-t", "0",
            "--scan",
            "--json",
            "--min-duration", str(min_duration),
        ]
        try:
            res_proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **get_subprocess_kwargs(),
            )
            combined = (res_proc.stdout or "") + "\n" + (res_proc.stderr or "")

            # Filter harmless BDMV probe messages from diagnostic lines
            clean_lines = [
                line.strip() for line in combined.splitlines()
                if line.strip() and not any(
                    bdmv in line.lower()
                    for bdmv in ("bdmv\\index.bdmv", "bdmv/index.bdmv", "bdmv\\backup", "bdmv/backup")
                )
            ]
            last_tail = clean_lines[-10:] if clean_lines else []

            marker = "JSON Title Set: "
            pos = combined.find(marker)
            if pos != -1:
                json_text = combined[pos + len(marker):].strip()
                brace_start = json_text.find("{")
                if brace_start != -1:
                    raw_json_chunk = json_text[brace_start:]
                    try:
                        decoder = json.JSONDecoder()
                        json_obj, _ = decoder.raw_decode(raw_json_chunk)
                        titles = parse_handbrake_json_title_set(json_obj, source_path=cand)
                        if titles and len(titles) > 0:
                            val_res = HandBrakeValidationResult(
                                success=True,
                                working_source_path=cand,
                                titles=titles,
                                title_count=len(titles),
                                raw_output_tail=last_tail,
                            )
                            _hb_source_validation_cache[cache_key] = val_res
                            return val_res
                    except Exception:
                        pass

            # Classify failure output
            if "found 0 valid title" in combined.lower() or "no title found" in combined.lower():
                last_error_category = "zero_titles_found"
                last_error_msg = f"HandBrakeCLI found 0 valid title(s) on '{cand}'."
            elif res_proc.returncode != 0:
                last_error_category = "scan_failed"
                last_error_msg = f"HandBrakeCLI scan returned exit code {res_proc.returncode} for '{cand}'."

        except subprocess.TimeoutExpired:
            last_error_category = "timeout"
            last_error_msg = f"HandBrakeCLI scan timed out after {timeout}s on '{cand}'."
        except Exception as ex:
            last_error_category = "exception"
            last_error_msg = f"HandBrakeCLI scan error: {ex}"

    # If all candidates fail:
    val_res = HandBrakeValidationResult(
        success=False,
        working_source_path=None,
        titles=[],
        title_count=0,
        error_category=last_error_category,
        error_message=last_error_msg,
        raw_output_tail=last_tail,
    )
    _hb_source_validation_cache[cache_key] = val_res
    return val_res


def resolve_handbrake_job_mapping(
    val_res: HandBrakeValidationResult,
    title_dict: Dict[str, Any],
    chapter_dict: Optional[Dict[str, Any]] = None,
    audio_track: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Validates and maps the application's canonical title, chapter, and audio track identifiers
    to HandBrakeCLI's actual scanned title list and stream indices.
    Returns (success, hb_title_index, hb_chapter_index, hb_audio_index, error_message).
    """
    if not val_res or not val_res.success:
        err = val_res.error_message if val_res else "HandBrake source not validated"
        return False, None, None, None, err

    if not val_res.titles:
        return False, None, None, None, "No titles available in HandBrake scan result"

    t_num = int(title_dict.get("title_number", 1))
    t_dur = float(title_dict.get("duration", 0.0))

    # 1. Title Mapping
    matched_title: Optional[DVDTitle] = None
    for t in val_res.titles:
        if t.title_number == t_num:
            matched_title = t
            break

    if not matched_title:
        return False, None, None, None, f"Title {t_num} not found in HandBrake title list ({val_res.title_count} titles scanned)"

    # Verify duration consistency if title duration is known
    if t_dur > 15.0 and matched_title.duration > 15.0:
        dur_diff = abs(matched_title.duration - t_dur)
        if dur_diff > 30.0 and (dur_diff / t_dur) > 0.3:
            return False, None, None, None, f"Title {t_num} duration mismatch between scanner ({t_dur:.1f}s) and HandBrake ({matched_title.duration:.1f}s)"

    hb_title_idx = matched_title.title_number

    # 2. Chapter Mapping
    hb_chap_idx: Optional[int] = None
    if chapter_dict is not None:
        c_num = int(chapter_dict.get("chapter_number", 1))
        avail_chaps = (
            len(matched_title.chapters_data) if matched_title.chapters_data
            else (len(matched_title.chapters) if matched_title.chapters
            else matched_title.chapter_count)
        )
        if avail_chaps <= 0:
            avail_chaps = 1
        if c_num < 1 or c_num > avail_chaps:
            return False, None, None, None, (
                f"Chapter {c_num} not found in HandBrake Title {hb_title_idx} "
                f"(contains {avail_chaps} chapters)"
            )
        hb_chap_idx = c_num

    # 3. Audio Track Mapping
    hb_audio_idx: int = 1
    if audio_track:
        target_trk_id = audio_track.get("track_id")
        target_trk_num = audio_track.get("track_number")
        target_hb_idx = audio_track.get("hb_track_index")

        matched_trk: Optional[DVDAudioTrack] = None
        for trk in matched_title.audio_tracks:
            if target_trk_id and trk.track_id == target_trk_id:
                matched_trk = trk
                break
            if target_trk_num and trk.track_number == target_trk_num:
                matched_trk = trk
                break

        if matched_trk:
            hb_audio_idx = matched_trk.hb_track_index or matched_trk.track_number
        elif target_hb_idx is not None:
            hb_audio_idx = int(target_hb_idx)
        elif target_trk_num is not None:
            hb_audio_idx = int(target_trk_num)
        else:
            hb_audio_idx = 1
    elif matched_title.audio_tracks:
        hb_audio_idx = matched_title.audio_tracks[0].hb_track_index or 1

    return True, hb_title_idx, hb_chap_idx, hb_audio_idx, None


def scan_dvd_with_handbrake(
    hb_path: str,
    source_path: str,
    min_duration: int = 0,
    timeout: int = 60
) -> Optional[List[DVDTitle]]:
    """
    Executes HandBrakeCLI with --scan --json to discover DVD titles and chapters.
    Uses candidate path probing and returns list of DVDTitle objects or None if scan fails.
    """
    val_res = validate_handbrake_source(hb_path, source_path, min_duration=min_duration, timeout=timeout)
    if val_res.success and val_res.titles:
        return val_res.titles
    return None


def prepare_dvd_handbrake_rip_job(
    handbrake_path: str,
    dvd_source: str,
    title_dict: Dict[str, Any],
    chapter_dict: Optional[Dict[str, Any]],
    out_dir: str,
    use_1080p: bool = False,
    audio_track: Optional[Dict[str, Any]] = None,
    custom_output_filename: Optional[str] = None,
    val_res: Optional[HandBrakeValidationResult] = None,
    fps_mode: Optional[str] = None,
) -> Tuple[List[str], str]:
    """
    Constructs a HandBrakeCLI command and output path for ripping a DVD title or single chapter to MP4.
    Validates and maps title/chapter/audio indices against HandBrake's scanned structure.
    Returns (cmd_args, output_filepath).
    """
    title_num = title_dict.get("title_number", 1)
    title_stem = title_dict.get("custom_stem") or f"Title_{title_num:02d}"

    if chapter_dict is not None:
        c_num = int(chapter_dict.get("chapter_number", 1))
        c_custom = chapter_dict.get("custom_stem") or chapter_dict.get("name") or f"Chapter {c_num:02d}"
        c_tag = sanitize_filename(c_custom, fallback=f"Chapter_{c_num:02d}")
        out_stem = f"{title_stem} - {c_tag}"
    else:
        out_stem = title_stem

    if custom_output_filename:
        out_filename = custom_output_filename
    else:
        out_filename = f"{out_stem}.mp4"
    out_path = os.path.join(out_dir, out_filename)

    # Collision avoidance
    if os.path.exists(out_path):
        stem, e = os.path.splitext(out_path)
        out_path = f"{stem}_{int(time.time())}{e}"

    # Target path and index mapping
    mapped_title_num = title_num
    mapped_chap_num = int(chapter_dict.get("chapter_number", 1)) if chapter_dict else None
    mapped_audio_idx: Optional[int] = None

    if val_res and val_res.success:
        ok, hb_t_idx, hb_c_idx, hb_a_idx, map_err = resolve_handbrake_job_mapping(
            val_res, title_dict, chapter_dict, audio_track
        )
        if not ok:
            raise ValueError(f"HandBrake title/chapter mapping failed: {map_err}")
        mapped_title_num = hb_t_idx
        mapped_chap_num = hb_c_idx
        mapped_audio_idx = hb_a_idx
        target_dvd_path = val_res.working_source_path or dvd_source
    else:
        dvd_dir = find_video_ts_dir(dvd_source)
        # Prefer direct VIDEO_TS folder if present, as tested for HandBrake 1.11.2 on Windows
        target_dvd_path = str(dvd_dir if dvd_dir else dvd_source)

    # Audio bitrate and track resolution
    resolved_audio: Optional[Dict[str, Any]] = None
    if audio_track is not None:
        resolved_audio = audio_track
        if title_dict.get("audio_tracks"):
            t_ids = [t.get("track_id") if isinstance(t, dict) else getattr(t, "track_id", "") for t in title_dict["audio_tracks"]]
            t_nums = [t.get("track_number") if isinstance(t, dict) else getattr(t, "track_number", 0) for t in title_dict["audio_tracks"]]
            if audio_track.get("track_id") and audio_track.get("track_id") not in t_ids:
                if audio_track.get("track_number") not in t_nums:
                    raise ValueError(f"Selected audio track '{audio_track.get('track_id') or audio_track.get('track_number')}' not found for Title {title_num}.")
    elif title_dict.get("audio_tracks"):
        first_trk = title_dict["audio_tracks"][0]
        resolved_audio = first_trk.to_dict() if isinstance(first_trk, DVDAudioTrack) else first_trk

    if resolved_audio:
        ch_cnt = int(resolved_audio.get("channel_count", 2))
        is_51 = (resolved_audio.get("channels") == "5.1" or ch_cnt > 2)
        a_br = "384k" if is_51 else "192k"
        if mapped_audio_idx is None:
            mapped_audio_idx = int(resolved_audio.get("hb_track_index") if resolved_audio.get("hb_track_index") is not None else resolved_audio.get("track_number", 1))
    else:
        a_br = "192k"
        if mapped_audio_idx is None:
            mapped_audio_idx = 1

    cmd = [
        handbrake_path,
        "-i", target_dvd_path,
        "-t", str(mapped_title_num),
    ]

    if chapter_dict is not None and mapped_chap_num is not None:
        cmd.extend(["-c", f"{mapped_chap_num}-{mapped_chap_num}"])

    cmd.extend([
        "-o", out_path,
        "-e", "x264",
        "-q", "20",
        "--encoder-preset", "fast",
        "-a", str(mapped_audio_idx),
        "-E", "aac",
        "-B", a_br,
    ])

    if use_1080p:
        ar = title_dict.get("aspect_ratio", "4:3")
        if ar == "16:9":
            cmd.extend(["-X", "1920", "-Y", "1080", "--maxWidth", "1920", "--maxHeight", "1080"])
        else:
            cmd.extend(["-X", "1440", "-Y", "1080", "--maxWidth", "1440", "--maxHeight", "1080"])

    f_val = (fps_mode or "Passthrough").strip().lower()
    if f_val == "cfr":
        cmd.append("--cfr")
    else:
        cmd.append("--pfr")

    return cmd, out_path


def validate_ripped_media(
    ffprobe_path: Optional[str],
    file_path: str,
    is_audio_only: bool,
    expected_format: str,
    selected_audio_track: Optional[Dict[str, Any]] = None,
    expected_duration: Optional[float] = None,
    ffmpeg_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Inspect the generated output file using ffprobe and ffmpeg.
    Verifies:
    1. File exists and is > 0 bytes.
    2. Contains expected streams:
       - Video output: >= 1 video stream + >= 1 audio stream.
       - Audio-only output: 0 video streams, >= 1 audio stream.
    3. The audio stream matches the requested track characteristics:
       - MP3: <= 2 channels, mp3 codec
       - WAV: PCM codec, preserves 6 channels for 5.1 sources
       - MP4 / MOV: AAC audio
       - MPG: AC-3, MP2, or LPCM audio
    4. Duration matches expected chapter duration within reasonable DVD GOP/padding tolerances.
    5. Media stream decodability check via quick ffmpeg sample decode.
    Returns (is_valid, message).
    """
    if not file_path or not os.path.isfile(file_path):
        return False, f"Validation failed: Output file does not exist: {file_path}"

    try:
        fsize = os.path.getsize(file_path)
    except Exception as e:
        return False, f"Validation failed: Cannot read file size: {e}"

    if fsize == 0:
        return False, f"Validation failed: Output file is empty (0 bytes): {os.path.basename(file_path)}"

    # If ffprobe is missing, run decode check if ffmpeg is available
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            try:
                dec_res = subprocess.run(
                    [ffmpeg_path, "-v", "error", "-nostdin", "-i", file_path, "-t", "0.5", "-f", "null", "-"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    **get_subprocess_kwargs(),
                )
                if dec_res.returncode != 0:
                    return False, f"Validation failed: Output media file failed decode test: {dec_res.stderr.strip()}"
            except Exception as ex:
                return False, f"Validation failed: Output media decodability check error: {ex}"
        return True, "Output file created (ffprobe not found, detailed stream probe skipped)"

    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        file_path,
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            **get_subprocess_kwargs(),
        )
        data = json.loads(res.stdout) if res.stdout else {}
    except Exception as ex:
        if fsize > 1024:
            return True, f"Output file created ({round(fsize / (1024**2), 1)} MB), ffprobe inspection error: {ex}"
        return False, f"Validation failed: ffprobe error: {ex}"

    streams = data.get("streams", [])
    v_streams = [s for s in streams if s.get("codec_type") == "video"]
    # Filter out attached picture video streams (e.g. album art in MP3 / audio)
    v_streams = [s for s in v_streams if s.get("disposition", {}).get("attached_pic", 0) != 1]
    a_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if is_audio_only:
        if not a_streams:
            return False, f"Validation failed: No audio stream found in audio-only file '{os.path.basename(file_path)}'"
        if v_streams:
            return False, f"Validation failed: Unexpected video stream found in audio-only file '{os.path.basename(file_path)}'"
    else:
        if not v_streams:
            return False, f"Validation failed: No video stream found in video file '{os.path.basename(file_path)}'"
        if not a_streams:
            return False, f"Validation failed: No audio stream found in video file '{os.path.basename(file_path)}'"

    if a_streams:
        primary_a = a_streams[0]
        a_codec = (primary_a.get("codec_name") or "").lower()
        a_channels = int(primary_a.get("channels") or 2)
        fmt_upper = (expected_format or "").upper()

        if fmt_upper == "MP3":
            if "mp3" not in a_codec:
                return False, f"Validation failed: Expected MP3 audio codec, got '{a_codec}'"
            if a_channels > 2:
                return False, f"Validation failed: MP3 audio must not exceed 2 channels, got {a_channels}"
        elif fmt_upper == "WAV":
            if "pcm" not in a_codec:
                return False, f"Validation failed: Expected PCM WAV audio codec, got '{a_codec}'"
            if selected_audio_track:
                req_ch = selected_audio_track.get("channel_count")
                if req_ch == 6 and a_channels != 6:
                    return False, f"Validation failed: Expected 6-channel 5.1 WAV, got {a_channels} channels"
        elif fmt_upper in ("MP4", "MOV"):
            if "aac" not in a_codec:
                return False, f"Validation failed: Expected AAC audio codec in {fmt_upper}, got '{a_codec}'"
        elif fmt_upper == "MPG":
            if not any(k in a_codec for k in ("ac3", "mp2", "pcm")):
                return False, f"Validation failed: Incompatible audio codec '{a_codec}' for MPG container"

    # Validate output duration against expected duration if provided
    if expected_duration is not None and expected_duration > 0:
        dur_sec = None
        fmt_dur = data.get("format", {}).get("duration")
        if fmt_dur is not None:
            try:
                dur_sec = float(fmt_dur)
            except (ValueError, TypeError):
                pass
        if dur_sec is None or dur_sec <= 0:
            for st in streams:
                st_dur = st.get("duration")
                if st_dur is not None:
                    try:
                        val = float(st_dur)
                        if val > 0:
                            dur_sec = val
                            break
                    except (ValueError, TypeError):
                        pass

        if dur_sec is not None and dur_sec > 0:
            # Check for severe truncation (less than 50% of expected duration, with at least 1s difference)
            if dur_sec < max(0.5, expected_duration * 0.50) and (expected_duration - dur_sec) > 1.0:
                return False, (
                    f"Validation failed: Output duration ({dur_sec:.1f}s) is significantly shorter "
                    f"than expected ({expected_duration:.1f}s)"
                )
            # Check for title overrun (e.g. HandBrake -c bug ripping to end of title, > 150% + 10s)
            if dur_sec > (expected_duration * 1.50 + 10.0):
                return False, (
                    f"Validation failed: Output duration ({dur_sec:.1f}s) significantly exceeds "
                    f"expected duration ({expected_duration:.1f}s)"
                )

    # Validate decodability if ffmpeg is available
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        try:
            dec_res = subprocess.run(
                [ffmpeg_path, "-v", "error", "-nostdin", "-i", file_path, "-t", "0.5", "-f", "null", "-"],
                capture_output=True,
                text=True,
                timeout=10,
                **get_subprocess_kwargs(),
            )
            if dec_res.returncode != 0:
                err_detail = (dec_res.stderr or "").strip()
                return False, f"Validation failed: Output media file failed decode test: {err_detail}"
        except Exception as ex:
            return False, f"Validation failed: Output media decodability check error: {ex}"

    return True, f"Validation successful: {os.path.basename(file_path)} passed stream, duration, and decode checks."


def scan_dvd_titles(
    source_path: str,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    handbrake_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Primary DVD title/chapter discovery entry point.
    1. Uses HandBrakeCLI if available to scan titles, chapters, audio, and video streams.
    2. Falls back cleanly to binary IFO parsing (scan_dvd_structure) if HandBrakeCLI is absent,
       unexecutable, or fails to parse the disc.
    """
    hb = handbrake_path or find_handbrake()
    if hb:
        try:
            hb_titles = scan_dvd_with_handbrake(hb, source_path)
            if hb_titles:
                return [t.to_dict() for t in hb_titles]
        except Exception:
            pass

    # Fallback to direct IFO parser
    return scan_dvd_structure(source_path, ffprobe_path or ffmpeg_path)



def check_dvd_encryption(video_ts_dir: str) -> Tuple[bool, str]:
    """
    Checks if DVD VIDEO_TS contains encrypted sectors or CSS protection indicators.
    Returns (is_encrypted, reason).
    """
    try:
        p = Path(video_ts_dir)
        ifo_path = p / "VIDEO_TS.IFO"
        if not ifo_path.exists():
            ifo_path = p / "VIDEO_TS.BUP"
        if not ifo_path.exists():
            return False, ""

        with open(ifo_path, "rb") as f:
            header = f.read(2048)

        if len(header) < 0x0100:
            return False, ""

        # Check POS 0x01E4 in VMGI: Static CSS flag byte in standard IFO
        # Additionally inspect VOB sectors for CSS encryption (scrambled title key)
        vobs = list(p.glob("VTS_*_1.VOB"))
        if vobs:
            with open(vobs[0], "rb") as vf:
                vob_head = vf.read(4096)
                # Pack header 0x000001BA
                # PES packet header for video 0x000001E0
                # PES scramble control bits (bits 4-5 of byte 6 of PES packet header)
                pos = vob_head.find(b"\x00\x00\x01\xe0")
                if pos != -1 and pos + 6 < len(vob_head):
                    scramble_bits = (vob_head[pos + 6] >> 4) & 0x03
                    if scramble_bits != 0:
                        return True, "CSS copy protection detected (scrambled PES streams)"

    except Exception:
        pass

    return False, ""


# ─────────────────────────────────────────────
#  DVD Chapter Timeline Generation
# ─────────────────────────────────────────────
def get_chapter_timeline_output_path(media_path: str) -> str:
    """Returns the expected .txt timeline filepath for a given media file."""
    norm_path = os.path.normpath(os.path.abspath(media_path))
    out_dir = os.path.dirname(norm_path)
    base_stem = Path(norm_path).stem
    return os.path.join(out_dir, f"{base_stem}_Chapter_Timeline.txt")


def generate_chapter_timeline_file(
    ffprobe_path: Optional[str],
    media_path: str,
    output_txt_path: Optional[str] = None,
    user_profile: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[str], int]:
    """
    Extracts chapter timeline metadata from a ripped media file using FFprobe,
    and generates a formatted .txt timeline file matching the reference layout.

    Layout structure:
    C:\\Users\\User>ffprobe -v error -show_chapters -show_entries chapter=id,start_time,end_time:chapter_tags=title -of csv=p=0 "FULL_PATH"
    0,0.000000,59.800000,Chapter 1
    1,59.800000,263.880000,Chapter 2

    Returns:
        (success: bool, output_file_path: Optional[str], error_message: Optional[str], chapter_count: int)
    """
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        return False, None, "FFprobe executable not found", 0

    if not media_path or not os.path.isfile(media_path) or os.path.getsize(media_path) == 0:
        return False, None, "Output media file not found or empty", 0

    norm_media_path = os.path.normpath(os.path.abspath(media_path))
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_chapters",
        "-show_entries", "chapter=id,start_time,end_time:chapter_tags=title",
        "-of", "csv=p=0",
        norm_media_path
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **get_subprocess_kwargs()
        )
    except Exception as ex:
        return False, None, f"Failed to execute FFprobe ({ex})", 0

    if res.returncode != 0:
        err_detail = (res.stderr or "").strip() or f"exit code {res.returncode}"
        return False, None, f"Failed to read chapter metadata ({err_detail})", 0

    raw_lines = [l.strip() for l in (res.stdout or "").splitlines() if l.strip()]
    if not raw_lines:
        return False, None, "No chapter metadata found in the output file", 0

    chapters: List[Dict[str, Any]] = []
    for idx, line in enumerate(raw_lines):
        parts = line.split(",", 3)
        if len(parts) < 3:
            continue
        ch_id = parts[0].strip()
        try:
            st_val = float(parts[1].strip())
            et_val = float(parts[2].strip())
        except ValueError:
            continue

        raw_title = parts[3].strip() if len(parts) >= 4 else ""
        if raw_title:
            title = raw_title
        else:
            try:
                ch_num = int(ch_id) + 1
            except ValueError:
                ch_num = idx + 1
            title = f"Chapter {ch_num}"

        chapters.append({
            "id": ch_id,
            "start": st_val,
            "end": et_val,
            "title": title
        })

    if not chapters:
        return False, None, "No chapter metadata found in the output file", 0

    # Ensure chronological order
    chapters.sort(key=lambda c: (c["start"], c["end"]))

    # Construct displayed command with prompt prefix
    user_dir = (user_profile or os.environ.get("USERPROFILE") or os.path.expanduser("~") or r"C:\Users\User").rstrip("\\/")
    header_line = f'{user_dir}>ffprobe -v error -show_chapters -show_entries chapter=id,start_time,end_time:chapter_tags=title -of csv=p=0 "{norm_media_path}"'

    lines = [header_line]
    for c in chapters:
        lines.append(f"{c['id']},{c['start']:.6f},{c['end']:.6f},{c['title']}")

    txt_content = "\r\n".join(lines) + "\r\n"

    target_path = output_txt_path or get_chapter_timeline_output_path(norm_media_path)
    out_dir = os.path.dirname(target_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    temp_target = os.path.join(out_dir, f".{os.path.basename(target_path)}.tmp_{os.getpid()}_{int(time.time()*1000)}")
    try:
        with open(temp_target, "w", encoding="utf-8", newline="") as f:
            f.write(txt_content)
        os.replace(temp_target, target_path)
    except Exception as write_err:
        if os.path.exists(temp_target):
            try:
                os.remove(temp_target)
            except Exception:
                pass
        return False, None, f"Unable to write the TXT file: {write_err}", len(chapters)

    return True, target_path, None, len(chapters)


