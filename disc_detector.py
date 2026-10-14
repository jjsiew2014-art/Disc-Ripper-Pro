"""
disc_detector.py - Optical Drive & Filesystem Disc Type Detection
Part of Disc Ripper Pro v2.0.0

Provides robust inspection of optical discs and browsed folders, accurately
distinguishing between VCD, DVD-Video, Empty Drive, Blu-ray, Audio CD,
Data Discs, and Unreadable media.
"""

import os
import sys
import ctypes
import string
from pathlib import Path
from typing import Optional, List, Tuple


class DiscCheckResult:
    """
    Encapsulates optical disc inspection results with dual tuple / bool support
    for backward compatibility with existing codebase.
    """
    def __init__(self, is_valid: bool, disc_type: str, details: str = "", is_vcd: bool = False, is_dvd: bool = False):
        self.is_valid = bool(is_valid)
        self.disc_type = str(disc_type)
        self.details = str(details)
        self.is_vcd = bool(is_vcd)
        self.is_dvd = bool(is_dvd)

    @property
    def is_supported(self) -> bool:
        return self.is_vcd or self.is_dvd

    def __bool__(self):
        return self.is_valid

    def __iter__(self):
        # Backwards compatible: returns (is_vcd_or_valid, disc_type)
        return iter((self.is_valid, self.disc_type))

    def __getitem__(self, index):
        return (self.is_valid, self.disc_type)[index]

    def __repr__(self):
        return (f"DiscCheckResult(is_valid={self.is_valid}, disc_type={self.disc_type!r}, "
                f"is_vcd={self.is_vcd}, is_dvd={self.is_dvd}, details={self.details!r})")


def suppress_windows_error_dialogs():
    """Context manager to suppress Windows system 'No disc in drive' popups."""
    class ErrorModeGuard:
        def __enter__(self):
            self.prev = None
            if sys.platform == "win32":
                try:
                    # SEM_FAILCRITICALERRORS = 0x0001, SEM_NOOPENFILEERRORBOX = 0x8000
                    self.prev = ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x8000)
                except Exception:
                    pass
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if sys.platform == "win32" and self.prev is not None:
                try:
                    ctypes.windll.kernel32.SetErrorMode(self.prev)
                except Exception:
                    pass

    return ErrorModeGuard()


def get_optical_drives() -> List[str]:
    """Return list of optical drive roots on Windows, e.g. ['D:\\', 'E:\\']."""
    drives = []
    if sys.platform != "win32":
        return drives

    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
                if dtype == 5:  # DRIVE_CDROM = 5
                    drives.append(drive)
            bitmask >>= 1
    except Exception:
        pass
    return drives


def is_drive_ready(drive_path: str) -> bool:
    """Check if drive is ready to read without causing blocking modal prompts."""
    if not drive_path:
        return False
    with suppress_windows_error_dialogs():
        try:
            p = Path(drive_path)
            return p.exists() and p.is_dir()
        except Exception:
            return False


def detect_disc(path_or_drive: str) -> DiscCheckResult:
    """
    Inspect optical drive or directory and determine media type.

    Categories:
    - VCD: Valid Video CD with MPEGAV/MPEG2 and .DAT tracks
    - DVD-Video: Valid DVD-Video volume with VIDEO_TS, IFO/BUP and VOB files
    - Empty Drive: Optical drive has no media inserted
    - Unreadable Disc: Media in drive is unreadable / I/O error
    - Blu-ray: BDMV structure
    - Audio CD: CDA files
    - Data Disc: Files present, but neither VCD nor DVD
    """
    if not path_or_drive:
        return DiscCheckResult(False, "No Disc", "Empty path provided")

    with suppress_windows_error_dialogs():
        try:
            p = Path(path_or_drive)
            if not p.exists() or not p.is_dir():
                # On Windows, if optical drive is empty, exists() or is_dir() returns False or raises
                if sys.platform == "win32" and len(path_or_drive) <= 3 and path_or_drive.endswith(":\\"):
                    return DiscCheckResult(False, "Empty Drive", "Drive is empty or not ready")
                return DiscCheckResult(False, "Drive Unavailable", f"Path does not exist: {path_or_drive}")

            # Shallow inspection of root directory
            try:
                root_entries = list(p.iterdir())
            except (PermissionError, OSError) as os_err:
                # Common on optical drives with no media or unreadable sectors
                err_code = getattr(os_err, "winerror", None)
                if err_code in (21, 1117):  # ERROR_NOT_READY, ERROR_IO_DEVICE
                    return DiscCheckResult(False, "Empty Drive", "Optical drive not ready")
                return DiscCheckResult(False, "Unreadable Disc", f"Read error: {os_err}")

            if not root_entries:
                return DiscCheckResult(False, "Empty Disc", "No files found on drive or folder")

            names_map = {e.name.upper(): e for e in root_entries}

            # ── 1. Check DVD-Video (VIDEO_TS) ──────────────
            dvd_video_ts = None
            if p.name.upper() == "VIDEO_TS":
                dvd_video_ts = p
            elif "VIDEO_TS" in names_map and names_map["VIDEO_TS"].is_dir():
                dvd_video_ts = names_map["VIDEO_TS"]

            if dvd_video_ts:
                try:
                    ts_entries = {e.name.upper(): e for e in dvd_video_ts.iterdir() if e.is_file()}
                    # Check for IFO, BUP, or VOB files
                    has_ifo = any(k.endswith(".IFO") for k in ts_entries)
                    has_bup = any(k.endswith(".BUP") for k in ts_entries)
                    has_vob = any(k.endswith(".VOB") for k in ts_entries)

                    if (has_ifo or has_bup) and has_vob:
                        return DiscCheckResult(
                            True, "DVD-Video", "Valid DVD-Video structure with IFO and VOB files",
                            is_vcd=False, is_dvd=True
                        )
                    elif has_vob:
                        return DiscCheckResult(
                            True, "DVD-Video", "DVD-Video VOB files found",
                            is_vcd=False, is_dvd=True
                        )
                    elif has_ifo or has_bup:
                        return DiscCheckResult(
                            True, "DVD-Video", "DVD-Video structure found",
                            is_vcd=False, is_dvd=True
                        )
                except (PermissionError, OSError):
                    # VIDEO_TS exists but cannot list files
                    return DiscCheckResult(
                        True, "DVD-Video", "DVD-Video folder detected (unreadable sectors)",
                        is_vcd=False, is_dvd=True
                    )

            # ── 2. Check VCD ───────────────────────────────
            # Standard VCD track folders: MPEGAV, MPEG2
            for vcd_dir in ("MPEGAV", "MPEG2"):
                if vcd_dir in names_map and names_map[vcd_dir].is_dir():
                    try:
                        has_dat = any(e.suffix.upper() == ".DAT" for e in names_map[vcd_dir].iterdir() if e.is_file())
                        if has_dat:
                            return DiscCheckResult(
                                True, "VCD", f"Found DAT video files in {vcd_dir}",
                                is_vcd=True, is_dvd=False
                            )
                    except (PermissionError, OSError):
                        pass
                    return DiscCheckResult(
                        True, "VCD", f"Found {vcd_dir} directory",
                        is_vcd=True, is_dvd=False
                    )

            # Standard VCD metadata directory (White Book specification)
            if "VCD" in names_map and names_map["VCD"].is_dir():
                try:
                    sub_names = {item.name.upper() for item in names_map["VCD"].iterdir() if item.is_file()}
                    if any(meta in sub_names for meta in ("INFO.VCD", "ENTRIES.VCD", "LOT.VCD", "PSD.VCD")):
                        return DiscCheckResult(
                            True, "VCD", "Found standard VCD metadata directory",
                            is_vcd=True, is_dvd=False
                        )
                except (PermissionError, OSError):
                    pass
                return DiscCheckResult(
                    True, "VCD", "Found VCD directory",
                    is_vcd=True, is_dvd=False
                )

            # Check root DAT files
            for e in root_entries:
                try:
                    if e.is_file() and e.suffix.upper() == ".DAT":
                        return DiscCheckResult(
                            True, "VCD", f"Found root DAT track: {e.name}",
                            is_vcd=True, is_dvd=False
                        )
                except (PermissionError, OSError):
                    pass

            # ── 3. Check Other Disc Formats ─────────────────
            # Blu-ray (BDMV / CERTIFICATE)
            if "BDMV" in names_map or "CERTIFICATE" in names_map:
                return DiscCheckResult(False, "Blu-ray", "Found Blu-ray structure (BDMV)", is_vcd=False, is_dvd=False)

            # Audio CD (CD-DA tracks mapped as .cda files on Windows)
            cda_files = [e for e in root_entries if e.is_file() and e.suffix.lower() == ".cda"]
            if cda_files:
                return DiscCheckResult(False, "Audio CD", f"Found {len(cda_files)} Audio CD track(s)", is_vcd=False, is_dvd=False)

            # General Data Disc
            return DiscCheckResult(False, "Data Disc", "No VCD or DVD-Video structure found", is_vcd=False, is_dvd=False)

        except Exception as exc:
            return DiscCheckResult(False, "Unknown Disc", f"Inspection error: {exc}")
