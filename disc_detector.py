"""
disc_detector.py - Optical Drive & Filesystem Disc Type Detection
Part of Disc Ripper Pro v2.0.4

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
from ctypes import wintypes


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


def flush_optical_drive_cache(path_or_drive: str) -> bool:
    """
    Force Windows kernel and filesystem drivers (CDFS / UDF) to dismount,
    flush volume and directory caches, and re-query hardware media state
    for the optical drive.
    """
    if sys.platform != "win32" or not path_or_drive:
        return False

    drive_letter = None
    p_str = str(path_or_drive).strip()
    if len(p_str) >= 2 and p_str[1] == ':':
        drive_letter = p_str[0].upper()
    elif len(p_str) == 1 and p_str.isalpha():
        drive_letter = p_str.upper()

    if not drive_letter or not drive_letter.isalpha():
        return False

    drive_volume_path = f"\\\\.\\{drive_letter}:"
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    FSCTL_UNLOCK_VOLUME = 0x0009001C
    IOCTL_STORAGE_CHECK_VERIFY = 0x002D4800
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    flushed = False
    with suppress_windows_error_dialogs():
        try:
            # First attempt with READ | WRITE; fallback to READ
            handle = ctypes.windll.kernel32.CreateFileW(
                drive_volume_path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None
            )
            if handle == INVALID_HANDLE_VALUE:
                handle = ctypes.windll.kernel32.CreateFileW(
                    drive_volume_path,
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None
                )

            if handle != INVALID_HANDLE_VALUE:
                bytes_returned = wintypes.DWORD(0)
                try:
                    # 1. Lock volume
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_LOCK_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    # 2. Force dismount volume (drops stale CDFS/UDF cache)
                    dismount_res = ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_DISMOUNT_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    # 3. Request storage stack to poll hardware media state
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, IOCTL_STORAGE_CHECK_VERIFY,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    if dismount_res:
                        flushed = True
                finally:
                    # 4. Unlock volume and close handle
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_UNLOCK_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass

        # Also signal Windows Shell to invalidate cached directory entries for this drive
        try:
            SHCNE_UPDATEDIR = 0x00001000
            SHCNF_PATHW = 0x0005
            SHCNF_FLUSH = 0x1000
            drive_root = f"{drive_letter}:\\"
            ctypes.windll.shell32.SHChangeNotify(
                SHCNE_UPDATEDIR, SHCNF_PATHW | SHCNF_FLUSH, drive_root, None
            )
        except Exception:
            pass

    return flushed


def is_drive_ready(drive_path: str) -> bool:
    """Check if drive is ready to read without causing blocking modal prompts."""
    if not drive_path:
        return False
    with suppress_windows_error_dialogs():
        try:
            p = Path(drive_path)
            if p.exists() and p.is_dir():
                return True
        except OSError as e:
            if getattr(e, "winerror", None) == 1110:  # ERROR_MEDIA_CHANGED
                flush_optical_drive_cache(drive_path)
                try:
                    p = Path(drive_path)
                    return p.exists() and p.is_dir()
                except Exception:
                    return False
        except Exception:
            return False
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
            is_drive_root = (
                sys.platform == "win32"
                and len(path_or_drive) <= 3
                and (path_or_drive.endswith(":\\") or path_or_drive.endswith(":"))
            )

            # Check drive existence / readiness
            try:
                if not p.exists() or not p.is_dir():
                    if is_drive_root:
                        return DiscCheckResult(False, "Empty Drive", "Drive is empty or not ready")
                    return DiscCheckResult(False, "Drive Unavailable", f"Path does not exist: {path_or_drive}")
            except OSError as os_err:
                err_code = getattr(os_err, "winerror", None)
                if err_code == 1110 and is_drive_root:  # ERROR_MEDIA_CHANGED
                    flush_optical_drive_cache(path_or_drive)
                    try:
                        if not p.exists() or not p.is_dir():
                            return DiscCheckResult(False, "Empty Drive", "Drive is empty or not ready")
                    except Exception:
                        return DiscCheckResult(False, "Empty Drive", "Optical drive not ready")
                elif err_code in (21, 1112, 1117, 1785, 31, 157) or is_drive_root:
                    return DiscCheckResult(False, "Empty Drive", "Optical drive not ready")
                else:
                    return DiscCheckResult(False, "Drive Unavailable", f"Path access error: {os_err}")

            # Shallow inspection of root directory (with retry if media changed)
            root_entries = None
            try:
                root_entries = list(p.iterdir())
            except (PermissionError, OSError) as os_err:
                err_code = getattr(os_err, "winerror", None)
                if err_code == 1110 and is_drive_root:  # ERROR_MEDIA_CHANGED
                    flush_optical_drive_cache(path_or_drive)
                    try:
                        root_entries = list(p.iterdir())
                    except Exception:
                        root_entries = None

                if root_entries is None:
                    if err_code in (21, 1112, 1117, 1785, 31, 157) or is_drive_root:
                        return DiscCheckResult(False, "Empty Drive", "Optical drive not ready or empty")
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
                ts_entries = {}
                read_ts_failed = False
                try:
                    with os.scandir(dvd_video_ts) as it:
                        for e in it:
                            try:
                                if e.is_file():
                                    ts_entries[e.name.upper()] = e
                            except Exception:
                                pass
                except (PermissionError, OSError):
                    read_ts_failed = True

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
                elif read_ts_failed and is_drive_root:
                    # Stale DVD-Video folder error after disc change - flush optical drive cache
                    flush_optical_drive_cache(path_or_drive)
                    try:
                        refreshed = list(p.iterdir())
                        if refreshed:
                            root_entries = refreshed
                            names_map = {e.name.upper(): e for e in root_entries}
                    except Exception:
                        pass

            # ── 2. Check VCD ───────────────────────────────
            # Standard VCD track folders: MPEGAV, MPEG2
            for vcd_dir in ("MPEGAV", "MPEG2"):
                if vcd_dir in names_map and names_map[vcd_dir].is_dir():
                    has_dat = False
                    try:
                        with os.scandir(names_map[vcd_dir]) as it:
                            has_dat = any(e.name.upper().endswith(".DAT") for e in it if e.is_file())
                    except (PermissionError, OSError):
                        pass
                    if has_dat:
                        return DiscCheckResult(
                            True, "VCD", f"Found DAT video files in {vcd_dir}",
                            is_vcd=True, is_dvd=False
                        )
                    return DiscCheckResult(
                        True, "VCD", f"Found {vcd_dir} directory",
                        is_vcd=True, is_dvd=False
                    )

            # Standard VCD metadata directory (White Book specification)
            if "VCD" in names_map and names_map["VCD"].is_dir():
                sub_names = set()
                try:
                    with os.scandir(names_map["VCD"]) as it:
                        sub_names = {item.name.upper() for item in it if item.is_file()}
                except (PermissionError, OSError):
                    pass
                if any(meta in sub_names for meta in ("INFO.VCD", "ENTRIES.VCD", "LOT.VCD", "PSD.VCD")):
                    return DiscCheckResult(
                        True, "VCD", "Found standard VCD metadata directory",
                        is_vcd=True, is_dvd=False
                    )
                return DiscCheckResult(
                    True, "VCD", "Found VCD directory",
                    is_vcd=True, is_dvd=False
                )

            # Check root DAT files
            for e in root_entries:
                try:
                    if e.is_file() and e.name.upper().endswith(".DAT"):
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
            cda_files = [e for e in root_entries if e.is_file() and e.name.lower().endswith(".cda")]
            if cda_files:
                return DiscCheckResult(False, "Audio CD", f"Found {len(cda_files)} Audio CD track(s)", is_vcd=False, is_dvd=False)

            # General Data Disc
            return DiscCheckResult(False, "Data Disc", "No VCD or DVD-Video structure found", is_vcd=False, is_dvd=False)

        except Exception as exc:
            return DiscCheckResult(False, "Unknown Disc", f"Inspection error: {exc}")
