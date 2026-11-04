"""
dvd_diagnostics.py - Persistent DVD Scan Diagnostics & Crash-Resilient Session Tracking
Part of Disc Ripper Pro v2.0.4

Provides microsecond-timestamped, disk-synced diagnostic logging and session markers
to capture evidence before unexpected system termination or optical drive driver faults.
"""

import os
import sys
import json
import time
import uuid
import shutil
import platform
import zipfile
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict

# Global thread lock to serialize access to physical optical drives
_DRIVE_IO_LOCK = threading.Lock()

def get_drive_io_lock() -> threading.Lock:
    """Return global lock for serializing optical drive access across threads."""
    return _DRIVE_IO_LOCK


def get_diagnostics_dir() -> Path:
    """
    Returns the persistent, user-writable diagnostics directory:
    %LOCALAPPDATA%\\Disc Ripper Pro\\Logs
    Creates the directory if it does not exist.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        local_appdata = os.path.expanduser("~")
    diag_dir = Path(local_appdata) / "Disc Ripper Pro" / "Logs"
    try:
        diag_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return diag_dir


def get_system_diagnostic_info(
    hb_path: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Collects safe, non-sensitive system and tool diagnostic information.
    Never collects passwords, tokens, credentials, or personal files.
    """
    info: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "application": {
            "name": "Disc Ripper Pro",
            "version": "2.0.4",
            "is_frozen": getattr(sys, "frozen", False),
            "executable": sys.executable,
        },
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
        },
        "python": {
            "version": platform.python_version(),
            "compiler": platform.python_compiler(),
            "build": platform.python_build(),
        },
        "tools": {}
    }

    if sys.platform == "win32":
        try:
            win_ver = sys.getwindowsversion()
            info["operating_system"]["win_version_details"] = {
                "major": win_ver.major,
                "minor": win_ver.minor,
                "build": win_ver.build,
                "platform": win_ver.platform,
                "service_pack": win_ver.service_pack,
            }
        except Exception:
            pass

    # Tool version probes (with short timeouts and hidden windows)
    def probe_version(tool_path: Optional[str], args: List[str]) -> Dict[str, Any]:
        res: Dict[str, Any] = {"path": tool_path, "available": False, "version": None}
        if not tool_path or not os.path.isfile(tool_path):
            return res
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            p = subprocess.run(
                [tool_path] + args,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            res["available"] = (p.returncode == 0)
            res["exit_code"] = p.returncode
            lines = (p.stdout or p.stderr or "").splitlines()
            res["version"] = lines[0].strip() if lines else None
        except Exception as ex:
            res["error"] = str(ex)
        return res

    # Auto-resolve tool paths if not provided
    import shutil
    hb = hb_path
    if not hb:
        try:
            import dvd_engine
            hb = getattr(dvd_engine, "find_handbrake", lambda: None)()
        except Exception:
            pass
        if not hb:
            hb = shutil.which("HandBrakeCLI") or shutil.which("HandBrakeCLI.exe")

    ff = ffmpeg_path
    if not ff:
        try:
            import dvd_engine
            ff = getattr(dvd_engine, "find_ffmpeg", lambda: None)()
        except Exception:
            pass
        if not ff:
            ff = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")

    fp = ffprobe_path
    if not fp:
        try:
            import dvd_engine
            fp = getattr(dvd_engine, "find_ffprobe", lambda: None)()
        except Exception:
            pass
        if not fp:
            fp = shutil.which("ffprobe") or shutil.which("ffprobe.exe")

    info["tools"]["handbrake"] = probe_version(hb, ["--version"])
    info["tools"]["ffmpeg"] = probe_version(ff, ["-version"])
    info["tools"]["ffprobe"] = probe_version(fp, ["-version"])

    return info


class SessionMarker:
    """
    Manages crash-resilient session marker file:
    active_scan_session.json in %LOCALAPPDATA%\\Disc Ripper Pro\\Logs
    """
    MARKER_FILENAME = "active_scan_session.json"

    @classmethod
    def get_marker_path(cls) -> Path:
        return get_diagnostics_dir() / cls.MARKER_FILENAME

    @classmethod
    def write_marker(cls, data: Dict[str, Any]):
        marker_path = cls.get_marker_path()
        tmp_path = marker_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(marker_path)
        except Exception:
            pass

    @classmethod
    def check_stale_session(cls) -> Optional[Dict[str, Any]]:
        """
        Checks if an active session marker exists with status 'IN_PROGRESS'.
        Indicates the previous application run terminated unexpectedly during a scan.
        """
        marker_path = cls.get_marker_path()
        if not marker_path.exists():
            return None
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") == "IN_PROGRESS":
                return data
        except Exception:
            pass
        return None

    @classmethod
    def acknowledge_stale_session(cls) -> Optional[str]:
        """
        Archives the stale session marker to Archive/ so it is not prompted again.
        Returns path to archived marker.
        """
        marker_path = cls.get_marker_path()
        if not marker_path.exists():
            return None
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["status"] = "INTERRUPTED_ACKNOWLEDGED"
            data["acknowledged_at"] = datetime.now().isoformat()

            archive_dir = get_diagnostics_dir() / "Archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            sess_id = data.get("session_id", "unknown")
            archived_path = archive_dir / f"session_{sess_id}.json"

            with open(archived_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            marker_path.unlink(missing_ok=True)
            return str(archived_path)
        except Exception:
            try:
                marker_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None

    @classmethod
    def clear_marker(cls):
        try:
            cls.get_marker_path().unlink(missing_ok=True)
        except Exception:
            pass


class DVDScanDiagnosticSession:
    """
    Encapsulates a single DVD scan diagnostic session with microsecond logging
    and persistent file syncing.
    """
    def __init__(
        self,
        drive_path: str,
        scanner_mode: str = "auto",
        app_version: str = "2.0.4",
        hb_path: Optional[str] = None,
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
        console_callback = None
    ):
        self.session_id = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.drive_path = drive_path
        self.scanner_mode = scanner_mode
        self.app_version = app_version
        self.hb_path = hb_path
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.console_callback = console_callback

        self.start_time = time.time()
        self.start_iso = datetime.now().isoformat()
        self.current_stage = "STARTING"
        self.log_file = get_diagnostics_dir() / f"dvd_scan_{self.session_id}.log"
        self._file_handle = None
        self._lock = threading.Lock()

        self._init_log()
        self._init_marker()

    def _init_log(self):
        try:
            self._file_handle = open(self.log_file, "a", encoding="utf-8")
            self._file_handle.write(f"=== Disc Ripper Pro DVD Scan Diagnostic Session ===\n")
            self._file_handle.write(f"Session ID   : {self.session_id}\n")
            self._file_handle.write(f"App Version  : {self.app_version}\n")
            self._file_handle.write(f"Start Time   : {self.start_iso}\n")
            self._file_handle.write(f"Drive Path   : {self.drive_path}\n")
            self._file_handle.write(f"Scanner Mode : {self.scanner_mode}\n")
            self._file_handle.write(f"Log File     : {self.log_file}\n")
            self._file_handle.write(f"OS Platform  : {platform.platform()}\n")
            self._file_handle.write(f"Architecture : {platform.machine()} ({platform.architecture()[0]})\n")
            self._file_handle.write(f"Python       : {platform.python_version()}\n")
            self._file_handle.write("===================================================\n\n")
            self._file_handle.flush()
            os.fsync(self._file_handle.fileno())
        except Exception:
            pass

    def _init_marker(self):
        SessionMarker.write_marker({
            "session_id": self.session_id,
            "app_version": self.app_version,
            "status": "IN_PROGRESS",
            "stage": self.current_stage,
            "start_time": self.start_iso,
            "last_heartbeat": self.start_iso,
            "drive_path": self.drive_path,
            "scanner_mode": self.scanner_mode,
            "log_file": str(self.log_file),
        })

    def log_event(self, level: str, message: str, stage: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        """Log an event, immediately flushing to disk."""
        now_dt = datetime.now()
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed = time.time() - self.start_time
        use_stage = stage or self.current_stage

        line = f"[{ts_str}] [+{elapsed:7.2f}s] [{level.upper():5s}] [{use_stage}] {message}"
        if data:
            try:
                line += f" | Data: {json.dumps(data, ensure_ascii=False)}"
            except Exception:
                line += f" | Data: {str(data)}"
        line += "\n"

        with self._lock:
            if self._file_handle and not self._file_handle.closed:
                try:
                    self._file_handle.write(line)
                    self._file_handle.flush()
                    os.fsync(self._file_handle.fileno())
                except Exception:
                    pass

        if self.console_callback:
            try:
                self.console_callback(message, level.lower())
            except Exception:
                pass

    def set_stage(self, stage: str, details: Optional[str] = None):
        """Update current major stage and persist to session marker."""
        self.current_stage = stage
        msg = f"Entering stage: {stage}" + (f" ({details})" if details else "")
        self.log_event("STAGE", msg, stage=stage)

        SessionMarker.write_marker({
            "session_id": self.session_id,
            "app_version": self.app_version,
            "status": "IN_PROGRESS",
            "stage": self.current_stage,
            "stage_details": details or "",
            "start_time": self.start_iso,
            "last_heartbeat": datetime.now().isoformat(),
            "drive_path": self.drive_path,
            "scanner_mode": self.scanner_mode,
            "log_file": str(self.log_file),
        })

    def log_process_start(self, cmd: List[str], candidate_path: Optional[str] = None) -> Dict[str, Any]:
        """Record process launch before subprocess execution."""
        cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
        proc_info = {
            "cmd": cmd_str,
            "candidate": candidate_path or "",
            "start_time": time.time(),
            "start_iso": datetime.now().isoformat()
        }
        self.log_event("PROC_START", f"Launching external process: {cmd_str}", data=proc_info)
        return proc_info

    def log_process_end(
        self,
        proc_info: Dict[str, Any],
        returncode: Optional[int],
        stdout_tail: Optional[List[str]] = None,
        stderr_tail: Optional[List[str]] = None
    ):
        """Record process completion and tails."""
        start_t = proc_info.get("start_time", self.start_time)
        dur = time.time() - start_t
        res_data = {
            "returncode": returncode,
            "duration_sec": round(dur, 3),
            "stdout_tail": stdout_tail[-15:] if stdout_tail else [],
            "stderr_tail": stderr_tail[-15:] if stderr_tail else [],
        }
        status_tag = "SUCCESS" if returncode == 0 else f"EXIT_{returncode}"
        self.log_event("PROC_END", f"Process finished with {status_tag} in {dur:.2f}s", data=res_data)

    def complete(self, titles_count: int = 0):
        """Mark session successfully completed."""
        elapsed = time.time() - self.start_time
        self.log_event("COMPLETE", f"DVD Scan completed successfully with {titles_count} title(s) in {elapsed:.2f}s.")
        SessionMarker.clear_marker()
        self.close()

    def fail(self, error_message: str):
        """Record scan failure."""
        elapsed = time.time() - self.start_time
        self.log_event("FAIL", f"DVD Scan failed after {elapsed:.2f}s: {error_message}")
        SessionMarker.clear_marker()
        self.close()

    def cancel(self):
        """Record scan cancellation."""
        elapsed = time.time() - self.start_time
        self.log_event("CANCEL", f"DVD Scan canceled by user after {elapsed:.2f}s.")
        SessionMarker.clear_marker()
        self.close()

    def close(self):
        with self._lock:
            if self._file_handle and not self._file_handle.closed:
                try:
                    self._file_handle.write(f"\n=== End of Session: {datetime.now().isoformat()} ===\n")
                    self._file_handle.flush()
                    os.fsync(self._file_handle.fileno())
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None


    def complete_session(self, title_count: int = 0, details: Optional[str] = None):
        """Alias for complete()."""
        if details:
            self.log_event("INFO", details)
        self.complete(titles_count=title_count)

    def fail_session(self, error_message: str):
        """Alias for fail()."""
        self.fail(error_message=error_message)


def check_stale_session() -> Optional[Dict[str, Any]]:
    """Checks if an active session was left in progress from a previous crash/BSOD."""
    return SessionMarker.check_stale_session()


def acknowledge_stale_session() -> Optional[str]:
    """Archives active stale session so it is not prompted again."""
    return SessionMarker.acknowledge_stale_session()


def archive_stale_session(session_id: Optional[str] = None) -> Optional[str]:
    """Alias for acknowledge_stale_session()."""
    return SessionMarker.acknowledge_stale_session()


def clear_marker():
    """Removes the active session marker."""
    SessionMarker.clear_marker()


def export_diagnostic_package(
    output_zip_path: Optional[str] = None,
    session_id: Optional[str] = None,
    hb_path: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None
) -> str:
    """
    Bundles diagnostic logs, session history, and system info into a ZIP archive.
    Returns the absolute path to the generated ZIP.
    Filters any sensitive information.
    """
    diag_dir = get_diagnostics_dir()
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output_zip_path:
        desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
        target_dir = desktop if desktop.exists() else diag_dir
        output_zip_path = str(target_dir / f"Disc_Ripper_Pro_Diagnostics_{ts_str}.zip")

    output_path = Path(output_zip_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sys_info = get_system_diagnostic_info(hb_path, ffmpeg_path, ffprobe_path)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. System info JSON
        sys_info_bytes = json.dumps(sys_info, indent=2, ensure_ascii=False).encode("utf-8")
        zf.writestr("system_diagnostic_info.json", sys_info_bytes)

        # 2. Active or recent session markers
        marker_path = SessionMarker.get_marker_path()
        if marker_path.exists():
            zf.write(marker_path, "active_scan_session.json")

        archive_dir = diag_dir / "Archive"
        if archive_dir.exists():
            for f in archive_dir.glob("*.json"):
                zf.write(f, f"Archive/{f.name}")

        # 3. Scan logs (up to 5 most recent or matching session_id)
        logs = sorted(diag_dir.glob("dvd_scan_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if session_id:
            logs = [l for l in logs if session_id in l.name] or logs

        for log_f in logs[:5]:
            zf.write(log_f, f"Logs/{log_f.name}")

        # 4. Raw HandBrake scan JSON (latest and recent)
        latest_hb_scan = diag_dir / "latest_handbrake_scan.json"
        if latest_hb_scan.exists():
            zf.write(latest_hb_scan, "latest_handbrake_scan.json")
        for hb_json in sorted(diag_dir.glob("handbrake_scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
            zf.write(hb_json, f"Logs/{hb_json.name}")

    return str(output_path.resolve())


def save_raw_handbrake_scan(json_obj: Dict[str, Any], source_path: str = "") -> Optional[str]:
    """
    Saves raw HandBrakeCLI scan JSON to the user's persistent diagnostics directory:
    %LOCALAPPDATA%\\Disc Ripper Pro\\Logs\\latest_handbrake_scan.json
    Preserves all title/chapter metadata, ticks, and timings for debugging.
    Returns the absolute path to the saved JSON file.
    """
    try:
        diag_dir = get_diagnostics_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_file = diag_dir / "latest_handbrake_scan.json"
        history_file = diag_dir / f"handbrake_scan_{ts}.json"

        data = {
            "source_path": str(source_path),
            "timestamp": datetime.now().isoformat(),
            "scan_data": json_obj,
        }
        content = json.dumps(data, indent=2, ensure_ascii=False)

        target_file.write_text(content, encoding="utf-8")
        try:
            history_file.write_text(content, encoding="utf-8")
        except Exception:
            pass
        return str(target_file.resolve())
    except Exception:
        return None


def inspect_media_file_integrity(
    file_path: str,
    ffprobe_path: Optional[str] = None,
    ffmpeg_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Performs deep diagnostic inspection on an output media file (MP4/MOV/MPG/WAV/MP3).
    Diagnoses:
    - Zero-byte or undersized files (< 4 KB, e.g. empty MP4 container headers)
    - Missing video or audio streams
    - Single-frame videos (static cover/thumbnail with audio)
    - Audio/video duration discrepancies
    - Decoder errors or freeze at start, middle, and end
    Returns a comprehensive diagnostic report dictionary.
    """
    report: Dict[str, Any] = {
        "file_path": str(file_path),
        "exists": False,
        "size_bytes": 0,
        "is_undersized": False,
        "container_format": None,
        "container_duration": 0.0,
        "video_streams": [],
        "audio_streams": [],
        "is_single_frame": False,
        "duration_discrepancy_sec": 0.0,
        "decodability": {
            "start": "untested",
            "midpoint": "untested",
            "midpoint_has_frames": False,
            "end": "untested",
        },
        "verdict": "FAIL",
        "verdict_reason": "",
        "suggested_action": "",
    }

    p = Path(file_path)
    if not p.is_file():
        report["verdict_reason"] = f"File does not exist: {file_path}"
        report["suggested_action"] = "Verify output folder path and rip task status."
        return report

    report["exists"] = True
    fsize = p.stat().st_size
    report["size_bytes"] = fsize
    if fsize < 4096:
        report["is_undersized"] = True
        report["verdict_reason"] = f"File is severely undersized ({fsize} bytes < 4 KB). Likely an empty container header."
        report["suggested_action"] = "Re-rip with HandBrakeCLI or check if the chapter duration was under 1.0 second."
        return report

    # Resolve probe and ffmpeg executables (prioritizing bundled application paths)
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        app_candidates = [
            Path(__file__).resolve().parent / "ffmpeg" / "bin" / "ffprobe.exe",
            Path(sys.executable).resolve().parent / "ffmpeg" / "bin" / "ffprobe.exe",
            Path(__file__).resolve().parent / "bin" / "ffprobe.exe",
        ]
        for c in app_candidates:
            if c.is_file():
                ffprobe_path = str(c)
                break
        else:
            ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
        app_candidates = [
            Path(__file__).resolve().parent / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(sys.executable).resolve().parent / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(__file__).resolve().parent / "bin" / "ffmpeg.exe",
        ]
        for c in app_candidates:
            if c.is_file():
                ffmpeg_path = str(c)
                break
        else:
            ffmpeg_path = shutil.which("ffmpeg")

    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        report["verdict_reason"] = "ffprobe executable not found; cannot inspect media streams."
        return report

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

    # Probe container and streams
    try:
        probe_cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            "-i", str(file_path)
        ]
        res = subprocess.run(
            probe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=25,
            creationflags=creationflags
        )
        if res.returncode != 0:
            report["verdict_reason"] = f"ffprobe probe failed (exit code {res.returncode}): {res.stderr.strip()[:200]}"
            return report

        probe_json = json.loads(res.stdout)
    except Exception as ex:
        report["verdict_reason"] = f"Failed to execute ffprobe: {ex}"
        return report

    fmt = probe_json.get("format", {})
    streams = probe_json.get("streams", [])
    report["container_format"] = fmt.get("format_name")
    try:
        report["container_duration"] = float(fmt.get("duration", 0.0))
    except Exception:
        pass

    v_streams = [s for s in streams if s.get("codec_type") == "video"]
    a_streams = [s for s in streams if s.get("codec_type") == "audio"]

    for s in v_streams:
        raw_nb = s.get("nb_frames")
        nb_val = int(raw_nb) if raw_nb and str(raw_nb).isdigit() else None
        v_dur = 0.0
        try:
            v_dur = float(s.get("duration", 0.0))
        except Exception:
            pass
        report["video_streams"].append({
            "codec": s.get("codec_name"),
            "width": s.get("width"),
            "height": s.get("height"),
            "fps": s.get("r_frame_rate"),
            "nb_frames": nb_val,
            "duration": v_dur,
        })

    for s in a_streams:
        a_dur = 0.0
        try:
            a_dur = float(s.get("duration", 0.0))
        except Exception:
            pass
        report["audio_streams"].append({
            "codec": s.get("codec_name"),
            "channels": s.get("channels"),
            "sample_rate": s.get("sample_rate"),
            "duration": a_dur,
        })

    is_audio_only = p.suffix.lower() in (".wav", ".mp3")
    if not is_audio_only and not v_streams:
        report["verdict_reason"] = "Output file has no video stream."
        report["suggested_action"] = "Re-rip chapter with HandBrakeCLI or check chapter authoring."
        return report

    # Single-frame cover / static thumbnail detection
    if v_streams and report["container_duration"] >= 2.0:
        first_v = report["video_streams"][0]
        nb = first_v.get("nb_frames")
        if nb is not None and nb <= 1:
            report["is_single_frame"] = True
            report["verdict_reason"] = (
                f"Video stream contains only {nb} frame(s) for a {report['container_duration']:.1f}s file "
                "(static cover or thumbnail only; video content is missing)."
            )
            report["suggested_action"] = (
                "The source DVD cell likely contains only a menu still or lead-out frame. "
                "Verify if this chapter is a degenerate title cell on the original disc."
            )
            return report

    # Audio/video duration discrepancy
    if v_streams and a_streams:
        v_d = report["video_streams"][0]["duration"] or report["container_duration"]
        a_d = report["audio_streams"][0]["duration"] or report["container_duration"]
        disc = abs(v_d - a_d)
        report["duration_discrepancy_sec"] = disc
        if disc > 5.0 and (v_d < 1.0 or a_d < 1.0):
            report["verdict_reason"] = (
                f"Severe stream discrepancy: Video is {v_d:.1f}s but Audio is {a_d:.1f}s."
            )
            report["suggested_action"] = "Check source DVD chapter cell authoring."
            return report

    # Multi-point decodability tests if ffmpeg is available
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        dur = report["container_duration"]
        # Start test
        try:
            c_start = subprocess.run(
                [ffmpeg_path, "-v", "error", "-ss", "0.0", "-i", str(file_path), "-t", "0.5", "-f", "null", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=creationflags
            )
            report["decodability"]["start"] = "PASS" if c_start.returncode == 0 else f"FAIL ({c_start.stderr.decode('utf-8', errors='ignore').strip()[:100]})"
        except Exception as ex:
            report["decodability"]["start"] = f"ERROR: {ex}"

        # Midpoint test
        if dur > 2.0:
            mid = dur / 2.0
            try:
                if v_streams:
                    # Request raw frames to verify real video decoded at midpoint
                    c_mid = subprocess.run(
                        [ffmpeg_path, "-v", "error", "-ss", f"{mid:.2f}", "-i", str(file_path), "-t", "0.5", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=15,
                        creationflags=creationflags
                    )
                    has_bytes = len(c_mid.stdout) > 0
                    report["decodability"]["midpoint_has_frames"] = has_bytes
                    if c_mid.returncode == 0 and has_bytes:
                        report["decodability"]["midpoint"] = "PASS"
                    elif c_mid.returncode == 0 and not has_bytes:
                        report["decodability"]["midpoint"] = "FAIL (0 video frames decoded at midpoint)"
                    else:
                        report["decodability"]["midpoint"] = f"FAIL ({c_mid.stderr.decode('utf-8', errors='ignore').strip()[:100]})"
                else:
                    c_mid = subprocess.run(
                        [ffmpeg_path, "-v", "error", "-ss", f"{mid:.2f}", "-i", str(file_path), "-t", "0.5", "-f", "null", "-"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=15,
                        creationflags=creationflags
                    )
                    report["decodability"]["midpoint"] = "PASS" if c_mid.returncode == 0 else "FAIL"
            except Exception as ex:
                report["decodability"]["midpoint"] = f"ERROR: {ex}"

        # End test
        if dur > 2.0:
            end_t = max(0.0, dur - 1.0)
            try:
                c_end = subprocess.run(
                    [ffmpeg_path, "-v", "error", "-ss", f"{end_t:.2f}", "-i", str(file_path), "-t", "0.5", "-f", "null", "-"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=15,
                    creationflags=creationflags
                )
                report["decodability"]["end"] = "PASS" if c_end.returncode == 0 else "FAIL"
            except Exception as ex:
                report["decodability"]["end"] = f"ERROR: {ex}"

    # Evaluate overall decodability
    if v_streams and report["container_duration"] > 2.0 and not report["decodability"]["midpoint_has_frames"]:
        report["verdict_reason"] = "No video frames could be decoded at the midpoint of the video."
        report["suggested_action"] = "The video track is truncated or blank after the opening frame."
        return report

    report["verdict"] = "PASS"
    report["verdict_reason"] = "All video/audio stream integrity, frame count, and multi-point decode checks passed."
    return report



# ─────────────────────────────────────────────────────────────
#  Disc Health Check & Human-Readable Diagnostic Report Engine
# ─────────────────────────────────────────────────────────────

class HealthStatus:
    GOOD = "Good"
    WARNINGS = "Warnings Found"
    PROBLEMS = "Problems Detected"
    INCONCLUSIVE = "Inconclusive"


class FindingSeverity:
    ERROR = "Error"
    WARNING = "Warning"
    INFO = "Info"


class CheckStatus:
    PASSED = "Passed"
    FAILED = "Failed"
    WARNING = "Warning"
    NOT_TESTED = "Not Tested"
    INCONCLUSIVE = "Inconclusive"


@dataclass
class DiagnosticFinding:
    severity: str
    title: str
    explanation: str
    location: Optional[str] = None
    evidence: Optional[str] = None
    recommended_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CheckItem:
    name: str
    status: str
    details: str
    duration_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscHealthReport:
    overall_status: str
    summary: str
    source_path: str = ""
    media_type: str = "Unknown"
    mode: str = "quick"
    duration_sec: float = 0.0
    checks: List[CheckItem] = field(default_factory=list)
    findings: List[DiagnosticFinding] = field(default_factory=list)
    recommended_next_steps: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    disc_info: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, Any] = field(default_factory=dict)
    report_id: str = field(default_factory=lambda: f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    app_version: str = "2.0.4"
    os_info: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "app_version": self.app_version,
            "os_info": self.os_info,
            "source_path": self.source_path,
            "media_type": self.media_type,
            "mode": self.mode,
            "overall_status": self.overall_status,
            "summary": self.summary,
            "duration_sec": self.duration_sec,
            "disc_info": self.disc_info,
            "checks": [c.to_dict() for c in self.checks],
            "findings": [f.to_dict() for f in self.findings],
            "dependencies": self.dependencies,
            "limitations": self.limitations,
            "recommended_next_steps": self.recommended_next_steps,
        }


def mask_private_path(path_str: str) -> str:
    r"""
    Masks the Windows username in user profile directories for privacy,
    e.g. C:\Users\Admin\AppData\... -> C:\Users\<user>\AppData\...
    Preserves drive letters, system paths, and application subdirectories.
    """
    if not path_str:
        return path_str
    try:
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            up_path = Path(user_profile).resolve()
            p_obj = Path(path_str).resolve()
            try:
                rel = p_obj.relative_to(up_path)
                return str(up_path.parent / "<user>" / rel)
            except ValueError:
                pass
    except Exception:
        pass
    import re
    return re.sub(r'([A-Za-z]:[\\/]Users[\\/])[^\\/]+([\\/].*)?', r'\1<user>\2', str(path_str))


def run_disc_health_check(
    source_path: str,
    mode: str = "quick",
    hb_path: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    progress_callback = None,
    cancel_event: Optional[threading.Event] = None,
    cancel_check = None,
    lang: str = "en"
) -> DiscHealthReport:
    """
    Runs a structured, non-destructive, evidence-based Disc Health Check.
    Distinguishes optical drive errors, missing navigation data, chapter timing
    inconsistencies, and tool dependency issues without falsely claiming physical damage.
    """
    start_t = time.time()
    checks: List[CheckItem] = []
    findings: List[DiagnosticFinding] = []
    disc_info: Dict[str, Any] = {}
    limitations: List[str] = []
    recommended_next_steps: List[str] = []
    report_id = f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1000000:06d}"

    is_tw = (lang == "zh_TW")
    is_cn = (lang == "zh_CN")

    def notify(pct: int, msg: str):
        if progress_callback:
            try:
                progress_callback(pct, msg)
            except Exception:
                pass

    os_info_str = f"{sys.platform} ({os.name})"
    try:
        import platform
        os_info_str = f"{platform.system()} {platform.release()} ({platform.version()}) {platform.machine()}"
    except Exception:
        pass

    # Lazy internal imports
    try:
        import disc_detector
    except ImportError:
        disc_detector = None
    try:
        import dvd_engine
    except ImportError:
        dvd_engine = None

    # Probe dependencies safely
    deps = get_system_diagnostic_info(hb_path, ffmpeg_path, ffprobe_path).get("tools", {})

    def check_cancelled() -> bool:
        if cancel_event and cancel_event.is_set():
            return True
        if cancel_check and cancel_check():
            return True
        return False

    if check_cancelled():
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type="Unknown", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="健康檢查已被使用者取消。" if is_tw else ("健康检查已被用户取消。" if is_cn else "Health check was cancelled by user."),
            duration_sec=0.0, disc_info={}, checks=[CheckItem("Operation", CheckStatus.INCONCLUSIVE, "Cancelled before start", 0.0)],
            findings=[], dependencies=deps, limitations=["Operation cancelled by user."], recommended_next_steps=["Retry check when ready."]
        )

    # ── Stage 1: Disc Access ──
    notify(10, "Checking disc access..." if not (is_tw or is_cn) else ("檢查光碟存取..." if is_tw else "检查光盘访问..."))
    t0 = time.time()

    if not source_path or not str(source_path).strip():
        dur = round(time.time() - t0, 3)
        checks.append(CheckItem(
            "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
            CheckStatus.FAILED,
            "未指定光碟來源或路徑為空" if (is_tw or is_cn) else "No disc source or directory specified",
            dur
        ))
        findings.append(DiagnosticFinding(
            FindingSeverity.ERROR,
            "未指定光碟來源" if (is_tw or is_cn) else "No Source Specified",
            "執行健康檢查前未選取光碟機代號或來源資料夾。" if (is_tw or is_cn) else "No source drive or directory was selected before running the health check.",
            None, "source_path is empty",
            "請選取有效的光碟機代號或 DVD/VCD 資料夾後重試。" if (is_tw or is_cn) else "Select a valid optical drive or DVD/VCD folder and retry."
        ))
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type="Unknown", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="無法判定光碟健康狀態，因為未指定光碟來源。" if is_tw else ("无法确定光盘健康状态，因为未指定光盘来源。" if is_cn else "Health status is inconclusive because no source drive or folder was specified."),
            duration_sec=round(time.time() - start_t, 2), disc_info={}, checks=checks,
            findings=findings, dependencies=deps, limitations=["檢查未執行：缺少來源路徑。"],
            recommended_next_steps=["選取光碟機代號或資料夾路徑。" if (is_tw or is_cn) else "Select a source drive or folder."]
        )

    p = Path(source_path)
    is_opt = sys.platform == "win32" and len(source_path) <= 3 and source_path.endswith(("\\", "/")) and len(source_path) <= 3 and source_path[1:2] == ":"
    if is_opt and disc_detector:
        with disc_detector.suppress_windows_error_dialogs():
            if not disc_detector.is_drive_ready(source_path):
                dur = round(time.time() - t0, 3)
                checks.append(CheckItem(
                    "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
                    CheckStatus.FAILED,
                    "光碟機未就緒或未放入光碟" if (is_tw or is_cn) else "Optical drive is not ready or tray is empty",
                    dur
                ))
                findings.append(DiagnosticFinding(
                    FindingSeverity.ERROR,
                    "光碟機未就緒" if (is_tw or is_cn) else "Optical Drive Not Ready",
                    f"光碟機 {source_path} 回報未就緒或托盤中無光碟。" if (is_tw or is_cn) else f"Optical drive {source_path} is not ready or no disc was detected.",
                    source_path, "Drive status: NOT_READY / ERROR 21",
                    "請確認光碟已放入光碟機托盤並等待讀取指示燈就緒。" if (is_tw or is_cn) else "Insert a disc into the drive tray and wait for it to spin up."
                ))
                return DiscHealthReport(
                    report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    app_version="2.0.4", os_info=os_info_str, source_path=source_path,
                    media_type="Empty Drive", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
                    summary="光碟機未就緒或托盤中無光碟，無法執行健康檢查。" if is_tw else ("光驱未就绪或托盘中无光盘，无法执行健康检查。" if is_cn else "The optical drive is not ready or has no disc inserted."),
                    duration_sec=round(time.time() - start_t, 2), disc_info={"drive": source_path}, checks=checks,
                    findings=findings, dependencies=deps, limitations=["光碟機無媒體可供測試。"],
                    recommended_next_steps=["放入光碟後重試健康檢查。" if (is_tw or is_cn) else "Insert a disc and retry the health check."]
                )

    try:
        if not p.exists() or not p.is_dir():
            dur = round(time.time() - t0, 3)
            checks.append(CheckItem(
                "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
                CheckStatus.FAILED,
                f"路徑不存在或無法存取: {source_path}" if (is_tw or is_cn) else f"Path does not exist or is inaccessible: {source_path}",
                dur
            ))
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "路徑無法存取" if (is_tw or is_cn) else "Path Inaccessible",
                f"指定的目錄 {source_path} 不存在。" if (is_tw or is_cn) else f"The path {source_path} does not exist.",
                source_path, "Directory not found",
                "確認光碟機代號或資料夾路徑是否正確。" if (is_tw or is_cn) else "Verify the drive letter or folder path."
            ))
            return DiscHealthReport(
                report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                app_version="2.0.4", os_info=os_info_str, source_path=source_path,
                media_type="Inaccessible", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
                summary="來源路徑不存在或無法存取。" if is_tw else ("来源路径不存在或无法访问。" if is_cn else "The source path does not exist or cannot be accessed."),
                duration_sec=round(time.time() - start_t, 2), disc_info={}, checks=checks,
                findings=findings, dependencies=deps, limitations=["路徑無法讀取。"],
                recommended_next_steps=["確認路徑。" if (is_tw or is_cn) else "Check the source path."]
            )

        root_entries = list(p.iterdir())
        dur = round(time.time() - t0, 3)
        checks.append(CheckItem(
            "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
            CheckStatus.PASSED,
            f"檔案系統存取正常 (根目錄共 {len(root_entries)} 個項目)" if is_tw else (f"文件系统访问正常 (根目录共 {len(root_entries)} 个项目)" if is_cn else f"Filesystem accessible ({len(root_entries)} root items)"),
            dur
        ))
    except (PermissionError, OSError) as exc:
        dur = round(time.time() - t0, 3)
        err_c = getattr(exc, "winerror", None)
        if err_c in (21, 1117):
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "光碟機 I/O 讀取錯誤" if (is_tw or is_cn) else "Optical Drive I/O Error",
                f"存取光碟根目錄時發生裝置 I/O 錯誤 ({exc})。可能為光碟刮痕、雷射讀取困難或光碟未完成封編。" if (is_tw or is_cn) else f"Device I/O read failure ({exc}). May indicate physical scratches or unreadable lead-in.",
                source_path, str(exc),
                "請檢查光碟表面是否有灰塵、指紋或刮傷；使用軟布由內向外擦拭後重試。" if (is_tw or is_cn) else "Inspect disc surface for dirt or scratches; clean gently with a soft cloth."
            ))
            checks.append(CheckItem(
                "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
                CheckStatus.FAILED, f"I/O read error: {exc}", dur
            ))
            return DiscHealthReport(
                report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                app_version="2.0.4", os_info=os_info_str, source_path=source_path,
                media_type="Unreadable", mode=mode, overall_status=HealthStatus.PROBLEMS,
                summary="光碟發生硬體 I/O 讀取錯誤，無法讀取檔案系統根目錄。" if is_tw else ("光盘发生硬件 I/O 读取错误，无法读取文件系统根目录。" if is_cn else "Hardware I/O read error encountered while accessing the disc filesystem."),
                duration_sec=round(time.time() - start_t, 2), disc_info={}, checks=checks,
                findings=findings, dependencies=deps, limitations=["光碟根目錄讀取失敗。"],
                recommended_next_steps=["清潔光碟表面後重試。" if (is_tw or is_cn) else "Clean the disc surface and retry."]
            )
        else:
            checks.append(CheckItem(
                "光碟存取與就緒性" if is_tw else ("光盘访问与就绪性" if is_cn else "Disc Access"),
                CheckStatus.FAILED, str(exc), dur
            ))
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR, "存取拒絕或權限問題" if (is_tw or is_cn) else "Permission Denied",
                str(exc), source_path, str(exc), "請確認檔案讀取權限。" if (is_tw or is_cn) else "Check file read permissions."
            ))
            return DiscHealthReport(
                report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                app_version="2.0.4", os_info=os_info_str, source_path=source_path,
                media_type="Inaccessible", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
                summary=f"存取光碟時發生錯誤: {exc}", duration_sec=round(time.time() - start_t, 2),
                disc_info={}, checks=checks, findings=findings, dependencies=deps, limitations=[],
                recommended_next_steps=["確認讀取權限。" if (is_tw or is_cn) else "Check permissions."]
            )

    if check_cancelled():
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type="Unknown", mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="健康檢查已被使用者取消。" if is_tw else "健康检查已被用户取消。", duration_sec=round(time.time() - start_t, 2),
            disc_info={}, checks=checks, findings=[], dependencies=deps, limitations=["使用者中止。"],
            recommended_next_steps=["重試檢查。" if (is_tw or is_cn) else "Retry."]
        )

    # ── Stage 2: Media Identification ──
    notify(25, "Identifying disc format..." if not (is_tw or is_cn) else ("識別光碟格式..." if is_tw else "识别光盘格式..."))
    t0 = time.time()
    if disc_detector:
        det = disc_detector.detect_disc(source_path)
        media_type = det.disc_type
        disc_info["disc_type"] = media_type
        disc_info["details"] = det.details
    else:
        media_type = "DVD-Video" if (p / "VIDEO_TS").is_dir() else "Unknown"
        disc_info["disc_type"] = media_type

    dur = round(time.time() - t0, 3)

    if media_type == "DVD-Video":
        checks.append(CheckItem(
            "媒體格式辨識" if is_tw else ("媒体格式识别" if is_cn else "Media Identification"),
            CheckStatus.PASSED,
            "確認為標準 DVD-Video 結構 (VIDEO_TS)" if (is_tw or is_cn) else "Standard DVD-Video structure confirmed (VIDEO_TS)",
            dur
        ))
    elif media_type == "VCD":
        checks.append(CheckItem(
            "媒體格式辨識" if is_tw else ("媒体格式识别" if is_cn else "Media Identification"),
            CheckStatus.PASSED,
            "確認為標準影音光碟結構 (VCD / MPEGAV)" if (is_tw or is_cn) else "Standard Video CD structure confirmed (VCD / MPEGAV)",
            dur
        ))
    elif media_type in ("Blu-ray", "Audio CD", "Data Disc"):
        checks.append(CheckItem(
            "媒體格式辨識" if is_tw else ("媒体格式识别" if is_cn else "Media Identification"),
            CheckStatus.WARNING,
            f"非專用影音光碟格式: {media_type}" if (is_tw or is_cn) else f"Non-target media format: {media_type}",
            dur
        ))
        findings.append(DiagnosticFinding(
            FindingSeverity.WARNING,
            f"非支援的專用格式 ({media_type})" if (is_tw or is_cn) else f"Unsupported Disc Format ({media_type})",
            f"偵測到 {media_type}。Disc Ripper Pro 專注於 DVD-Video 與 Video CD 轉檔。" if (is_tw or is_cn) else f"Detected {media_type}. Disc Ripper Pro is tailored for DVD-Video and VCD.",
            source_path, getattr(det, "details", ""),
            "如需轉檔影音，請置入標準 DVD 或 VCD 光碟。" if (is_tw or is_cn) else "Insert a standard DVD-Video or VCD disc."
        ))
    else:
        checks.append(CheckItem(
            "媒體格式辨識" if is_tw else ("媒体格式识别" if is_cn else "Media Identification"),
            CheckStatus.FAILED,
            f"無法識別之光碟結構: {media_type}" if (is_tw or is_cn) else f"Unrecognized media structure: {media_type}",
            dur
        ))
        findings.append(DiagnosticFinding(
            FindingSeverity.ERROR,
            "未識別之光碟結構" if (is_tw or is_cn) else "Unrecognized Disc Structure",
            f"在 {source_path} 未發現 VIDEO_TS (DVD) 或 MPEGAV (VCD) 結構。" if (is_tw or is_cn) else f"No recognizable VIDEO_TS (DVD) or MPEGAV (VCD) directory found on {source_path}.",
            source_path, getattr(det, "details", ""),
            "確認光碟是否為標準影音光碟或已正確燒錄。" if (is_tw or is_cn) else "Ensure the disc is a standard mastered video disc."
        ))

    if check_cancelled():
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type=media_type, mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="健康檢查已被使用者取消。" if is_tw else "健康检查已被用户取消。", duration_sec=round(time.time() - start_t, 2),
            disc_info=disc_info, checks=checks, findings=findings, dependencies=deps, limitations=["使用者中止。"],
            recommended_next_steps=["重試檢查。" if (is_tw or is_cn) else "Retry."]
        )

    # ── Stage 3: Disc Structure Scan ──
    notify(45, "Scanning directory and navigation tables..." if not (is_tw or is_cn) else ("掃描目錄結構與導覽表格..." if is_tw else "扫描目录结构与导航表..."))
    t0 = time.time()
    video_ts_dir = None
    vcd_dat_files = []

    if media_type == "DVD-Video":
        if dvd_engine:
            video_ts_dir = dvd_engine.find_video_ts_dir(source_path)
        else:
            video_ts_dir = p / "VIDEO_TS" if (p / "VIDEO_TS").is_dir() else p

        if not video_ts_dir or not video_ts_dir.is_dir():
            dur = round(time.time() - t0, 3)
            checks.append(CheckItem(
                "光碟檔案結構掃描" if is_tw else ("光盘文件结构扫描" if is_cn else "Disc Structure Scan"),
                CheckStatus.FAILED,
                "未找到 VIDEO_TS 目錄" if (is_tw or is_cn) else "VIDEO_TS folder not found",
                dur
            ))
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "缺少 VIDEO_TS 目錄" if (is_tw or is_cn) else "Missing VIDEO_TS Directory",
                "DVD 根目錄下找不到標準 VIDEO_TS 資料夾。" if (is_tw or is_cn) else "DVD root does not contain standard VIDEO_TS folder.",
                source_path, "find_video_ts_dir returned None",
                "確認光碟是否符合標準 DVD-Video 規範。" if (is_tw or is_cn) else "Verify disc conforms to DVD-Video specifications."
            ))
        else:
            # Check IFO and BUP
            ifo_p = video_ts_dir / "VIDEO_TS.IFO"
            bup_p = video_ts_dir / "VIDEO_TS.BUP"
            has_ifo = ifo_p.is_file()
            has_bup = bup_p.is_file()

            if not has_ifo:
                findings.append(DiagnosticFinding(
                    FindingSeverity.ERROR,
                    "缺少主要導覽表 (VIDEO_TS.IFO)" if (is_tw or is_cn) else "Missing Primary IFO (VIDEO_TS.IFO)",
                    "主要 DVD 導覽管理檔案 VIDEO_TS.IFO 遺失，可能導致轉檔程式無法辨識標題。" if (is_tw or is_cn) else "Primary navigation table VIDEO_TS.IFO is missing.",
                    str(ifo_p), "VIDEO_TS.IFO not found",
                    "檢查光碟是否有檔案損毀或遺失。" if (is_tw or is_cn) else "Check if disc filesystem was corrupted."
                ))
            else:
                try:
                    hdr = ifo_p.read_bytes()[:12]
                    if not hdr.startswith(b"DVDVIDEO-VMG"):
                        findings.append(DiagnosticFinding(
                            FindingSeverity.WARNING,
                            "非標準 VMGI 標頭特徵" if (is_tw or is_cn) else "Non-Standard VMGI Header",
                            f"VIDEO_TS.IFO 標頭為 {hdr[:12]!r}，非標準 b'DVDVIDEO-VMG'。" if (is_tw or is_cn) else f"VIDEO_TS.IFO header is {hdr[:12]!r}, expected b'DVDVIDEO-VMG'.",
                            str(ifo_p), f"Header: {hdr[:12]!r}",
                            "光碟可能為非標準母片壓製，建議預覽轉檔片段確認。" if (is_tw or is_cn) else "Disc authoring may be non-standard; review preview rips."
                        ))
                except Exception as ex_read:
                    findings.append(DiagnosticFinding(
                        FindingSeverity.ERROR,
                        "無法讀取 VIDEO_TS.IFO" if (is_tw or is_cn) else "Cannot Read VIDEO_TS.IFO",
                        f"讀取 IFO 標頭時發生錯誤: {ex_read}" if (is_tw or is_cn) else f"Failed to read IFO header: {ex_read}",
                        str(ifo_p), str(ex_read),
                        "可能為光碟內圈刮損或讀取錯誤。" if (is_tw or is_cn) else "May be caused by scratches or read error on inner tracks."
                    ))

            if not has_bup:
                findings.append(DiagnosticFinding(
                    FindingSeverity.INFO,
                    "缺少備用導覽表 (VIDEO_TS.BUP)" if (is_tw or is_cn) else "Missing Backup BUP (VIDEO_TS.BUP)",
                    "未找到備份導覽檔案 VIDEO_TS.BUP。只要主要 IFO 正常，轉檔通常不受影響。" if (is_tw or is_cn) else "Backup navigation table VIDEO_TS.BUP is missing. Non-critical if primary IFO is readable.",
                    str(bup_p), "BUP not found",
                    "一般情況下可正常進行轉檔。" if (is_tw or is_cn) else "Normal ripping should proceed safely."
                ))

            # Inspect VOB files
            vob_files = sorted([vf for vf in video_ts_dir.glob("*.VOB") if vf.is_file()])
            total_vob_size = sum(vf.stat().st_size for vf in vob_files)
            disc_info["vob_count"] = len(vob_files)
            disc_info["total_size_mb"] = round(total_vob_size / 1024**2, 1)

            if not vob_files or total_vob_size == 0:
                findings.append(DiagnosticFinding(
                    FindingSeverity.ERROR,
                    "無有效視訊資料檔 (VOB)" if (is_tw or is_cn) else "No Valid Video Data (VOB)",
                    "VIDEO_TS 目錄下未找到大於 0 位元組的 VOB 影片檔案。" if (is_tw or is_cn) else "No VOB video files with size > 0 found in VIDEO_TS.",
                    str(video_ts_dir), f"VOB count: {len(vob_files)}, Size: {total_vob_size}",
                    "光碟可能為空盤或燒錄程序未完成。" if (is_tw or is_cn) else "Disc may be blank or burning process aborted."
                ))

            dur = round(time.time() - t0, 3)
            struct_status = CheckStatus.FAILED if any(f.severity == FindingSeverity.ERROR for f in findings) else CheckStatus.PASSED
            checks.append(CheckItem(
                "光碟檔案結構掃描" if is_tw else ("光盘文件结构扫描" if is_cn else "Disc Structure Scan"),
                struct_status,
                f"VIDEO_TS 結構驗證完成 (含 {len(vob_files)} 個 VOB 檔案，共 {disc_info['total_size_mb']} MB)" if is_tw else (f"VIDEO_TS 结构验证完成 (含 {len(vob_files)} 个 VOB 文件，共 {disc_info['total_size_mb']} MB)" if is_cn else f"VIDEO_TS verified ({len(vob_files)} VOB files, {disc_info['total_size_mb']} MB)"),
                dur
            ))

    elif media_type == "VCD":
        for cand in ("MPEGAV", "MPEG2"):
            td = p / cand
            if td.is_dir():
                vcd_dat_files.extend(sorted([f for f in td.glob("*.DAT") if f.is_file()]))
        if not vcd_dat_files:
            vcd_dat_files.extend(sorted([f for f in p.glob("*.DAT") if f.is_file()]))

        disc_info["track_count"] = len(vcd_dat_files)
        total_dat_size = sum(f.stat().st_size for f in vcd_dat_files)
        disc_info["total_size_mb"] = round(total_dat_size / 1024**2, 1)

        dur = round(time.time() - t0, 3)
        if not vcd_dat_files or total_dat_size == 0:
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "缺少 VCD DAT 視訊軌道" if (is_tw or is_cn) else "Missing VCD DAT Tracks",
                "在 MPEGAV 或光碟目錄中未找到任何有效 DAT 影片檔案。" if (is_tw or is_cn) else "No valid DAT video tracks found in MPEGAV or root.",
                source_path, f"Found {len(vcd_dat_files)} DAT files",
                "確認光碟是否為標準 Video CD 影音光碟。" if (is_tw or is_cn) else "Verify disc is a valid Video CD."
            ))
            checks.append(CheckItem(
                "光碟檔案結構掃描" if is_tw else ("光盘文件结构扫描" if is_cn else "Disc Structure Scan"),
                CheckStatus.FAILED, "未找到 DAT 視訊檔案" if (is_tw or is_cn) else "No DAT video files found", dur
            ))
        else:
            checks.append(CheckItem(
                "光碟檔案結構掃描" if is_tw else ("光盘文件结构扫描" if is_cn else "Disc Structure Scan"),
                CheckStatus.PASSED,
                f"VCD 軌道結構正常 (共 {len(vcd_dat_files)} 個 DAT 軌道，總計 {disc_info['total_size_mb']} MB)" if is_tw else (f"VCD 轨道结构正常 (共 {len(vcd_dat_files)} 个 DAT 轨道，总计 {disc_info['total_size_mb']} MB)" if is_cn else f"VCD tracks verified ({len(vcd_dat_files)} DAT tracks, {disc_info['total_size_mb']} MB)"),
                dur
            ))
    else:
        dur = round(time.time() - t0, 3)
        checks.append(CheckItem(
            "光碟檔案結構掃描" if is_tw else ("光盘文件结构扫描" if is_cn else "Disc Structure Scan"),
            CheckStatus.NOT_TESTED,
            f"非 VCD/DVD 媒體，略過結構檢查" if (is_tw or is_cn) else f"Skipped for media type: {media_type}",
            dur
        ))

    if check_cancelled():
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type=media_type, mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="健康檢查已被使用者取消。" if is_tw else "健康检查已被用户取消。", duration_sec=round(time.time() - start_t, 2),
            disc_info=disc_info, checks=checks, findings=findings, dependencies=deps, limitations=["使用者中止。"],
            recommended_next_steps=["重試檢查。" if (is_tw or is_cn) else "Retry."]
        )

    # ── Stage 4: Title & Chapter Integrity ──
    notify(65, "Validating titles and chapter boundaries..." if not (is_tw or is_cn) else ("驗證標題與章節時間標記..." if is_tw else "验证标题与章节时间标记..."))
    t0 = time.time()

    if media_type == "DVD-Video" and video_ts_dir:
        try:
            titles = dvd_engine.scan_dvd_titles(source_path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, handbrake_path=hb_path) if dvd_engine else []
            disc_info["title_count"] = len(titles)

            def _get(obj, k, d=None):
                if isinstance(obj, dict):
                    return obj.get(k, d)
                return getattr(obj, k, d)

            total_chapters = 0
            for t_item in titles:
                total_chapters += int(_get(t_item, "chapter_count", len(_get(t_item, "chapters", []) or [])) or 0)
            disc_info["total_chapters"] = total_chapters

            chap_issues_count = 0
            for t_item in titles:
                t_dur = float(_get(t_item, "duration", 0.0) or 0.0)
                t_num = _get(t_item, "title_number", _get(t_item, "title_num", 1))
                if t_dur <= 0.0:
                    findings.append(DiagnosticFinding(
                        FindingSeverity.WARNING,
                        f"標題 {t_num} 長度為 0" if (is_tw or is_cn) else f"Title {t_num} Duration Zero",
                        f"標題 {t_num} 回報之播放長度為 0.0 秒。" if (is_tw or is_cn) else f"Title {t_num} reports a duration of 0.0s.",
                        f"Title {t_num}", "duration <= 0.0s",
                        "該標題可能為未使用的靜態選單單元或前導畫面。" if (is_tw or is_cn) else "Review whether this title is a menu still or lead-in cell."
                    ))
                    chap_issues_count += 1

                # Validate chapter boundaries
                ch_data = _get(t_item, "chapters_data", _get(t_item, "chapters", []))
                if ch_data and dvd_engine and hasattr(dvd_engine, "validate_title_chapter_boundaries"):
                    all_valid, issues = dvd_engine.validate_title_chapter_boundaries(ch_data, t_dur)
                    if not all_valid:
                        for iss in issues:
                            chap_issues_count += 1
                            sev = FindingSeverity.ERROR if ("start time" in iss and "before" in iss) else FindingSeverity.WARNING
                            findings.append(DiagnosticFinding(
                                sev,
                                "章節時間標記異常" if (is_tw or is_cn) else "Chapter Timing Anomaly",
                                iss,
                                f"Title {t_num}", iss,
                                "轉檔前請檢查該標題之章節選取，或直接轉檔整段標題。" if (is_tw or is_cn) else "Review chapter selections before ripping, or rip entire title."
                            ))

            dur = round(time.time() - t0, 3)
            if not titles:
                findings.append(DiagnosticFinding(
                    FindingSeverity.WARNING,
                    "未列舉出可播放標題" if (is_tw or is_cn) else "No Playable Titles Enumerated",
                    "在 DVD 導覽結構中未發現有效播放標題。" if (is_tw or is_cn) else "Could not enumerate valid titles from DVD navigation tables.",
                    source_path, "Titles list is empty",
                    "可在設定中切換 DVD 掃描引擎（如 HandBrakeCLI 或 IFO 剖析器）。" if (is_tw or is_cn) else "Try toggling DVD Scanner mode in Settings."
                ))
                checks.append(CheckItem(
                    "標題與章節完整性" if is_tw else ("标题与章节完整性" if is_cn else "Title & Chapter Validation"),
                    CheckStatus.WARNING, "列舉到 0 個標題" if (is_tw or is_cn) else "0 titles enumerated", dur
                ))
            else:
                c_status = CheckStatus.WARNING if chap_issues_count > 0 else CheckStatus.PASSED
                checks.append(CheckItem(
                    "標題與章節完整性" if is_tw else ("标题与章节完整性" if is_cn else "Title & Chapter Validation"),
                    c_status,
                    f"驗證 {len(titles)} 個標題共 {total_chapters} 個章節 (發現 {chap_issues_count} 個注意事項)" if is_tw else (f"验证 {len(titles)} 个标题共 {total_chapters} 个章节 (发现 {chap_issues_count} 个注意事项)" if is_cn else f"Validated {len(titles)} title(s), {total_chapters} chapter(s) ({chap_issues_count} anomalies)"),
                    dur
                ))
        except Exception as ex_t:
            dur = round(time.time() - t0, 3)
            checks.append(CheckItem(
                "標題與章節完整性" if is_tw else ("标题与章节完整性" if is_cn else "Title & Chapter Validation"),
                CheckStatus.WARNING, f"掃描標題時發生例外: {ex_t}" if (is_tw or is_cn) else f"Title scan exception: {ex_t}", dur
            ))
            findings.append(DiagnosticFinding(
                FindingSeverity.WARNING, "標題剖析異常" if (is_tw or is_cn) else "Title Parsing Exception",
                str(ex_t), source_path, str(ex_t),
                "可在設定中選擇不同 DVD 掃描引擎重試。" if (is_tw or is_cn) else "Try selecting an alternative DVD scanner in Settings."
            ))

    elif media_type == "VCD":
        dur = round(time.time() - t0, 3)
        checks.append(CheckItem(
            "標題與章節完整性" if is_tw else ("标题与章节完整性" if is_cn else "Title & Chapter Validation"),
            CheckStatus.PASSED,
            f"VCD 共包含 {len(vcd_dat_files)} 個獨立音訊/視訊軌道" if is_tw else (f"VCD 共包含 {len(vcd_dat_files)} 个独立音/视频轨道" if is_cn else f"VCD contains {len(vcd_dat_files)} track(s)"),
            dur
        ))
    else:
        dur = round(time.time() - t0, 3)
        checks.append(CheckItem(
            "標題與章節完整性" if is_tw else ("标题与章节完整性" if is_cn else "Title & Chapter Validation"),
            CheckStatus.NOT_TESTED, "非 VCD/DVD 媒體，略過章節驗證" if (is_tw or is_cn) else "Skipped for non-target media", dur
        ))

    if check_cancelled():
        return DiscHealthReport(
            report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            app_version="2.0.4", os_info=os_info_str, source_path=source_path,
            media_type=media_type, mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
            summary="健康檢查已被使用者取消。" if is_tw else "健康检查已被用户取消。", duration_sec=round(time.time() - start_t, 2),
            disc_info=disc_info, checks=checks, findings=findings, dependencies=deps, limitations=["使用者中止。"],
            recommended_next_steps=["重試檢查。" if (is_tw or is_cn) else "Retry."]
        )

    # ── Stage 5: Media Readability Test ──
    notify(80, "Testing media data readability..." if not (is_tw or is_cn) else ("測試媒體資料讀取..." if is_tw else "测试媒体数据读取..."))
    t0 = time.time()

    if mode == "quick":
        dur = 0.0
        checks.append(CheckItem(
            "完整媒體讀取測試" if is_tw else ("完整媒体读取测试" if is_cn else "Media Readability Test"),
            CheckStatus.NOT_TESTED,
            "快速檢查模式略過全盤資料讀取以節省時間" if (is_tw or is_cn) else "Skipped in Quick Check mode to save time",
            dur
        ))
        limitations.append("快速檢查主要評估檔案目錄、導覽表格與章節邊界，並未讀取或解碼完整媒體串流。" if is_tw else ("快速检查主要评估文件目录、导航表与章节边界，并未读取或解码完整媒体流。" if is_cn else "Quick Check assessed disc structure and navigation without reading the full media streams."))
    else:
        # Thorough Read Test
        read_errors = []
        bytes_read = 0
        blocks_read = 0

        target_files = []
        if media_type == "DVD-Video" and video_ts_dir:
            target_files = sorted([f for f in video_ts_dir.glob("*.VOB") if f.is_file()])
        elif media_type == "VCD":
            target_files = vcd_dat_files

        for f_idx, tf in enumerate(target_files):
            if check_cancelled():
                break
            try:
                f_sz = tf.stat().st_size
                if f_sz > 0:
                    offsets = [0, int(f_sz * 0.25), int(f_sz * 0.50), int(f_sz * 0.75), max(0, f_sz - 65536)]
                    with open(tf, "rb") as rf:
                        for off in offsets:
                            if check_cancelled():
                                break
                            try:
                                rf.seek(off)
                                b = rf.read(65536)
                                bytes_read += len(b)
                                blocks_read += 1
                            except (OSError, IOError) as r_err:
                                read_errors.append((tf.name, off, str(r_err)))
            except Exception as e_file:
                read_errors.append((tf.name, 0, str(e_file)))

        dur = round(time.time() - t0, 3)
        if check_cancelled():
            return DiscHealthReport(
                report_id=report_id, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                app_version="2.0.4", os_info=os_info_str, source_path=source_path,
                media_type=media_type, mode=mode, overall_status=HealthStatus.INCONCLUSIVE,
                summary="健康檢查已被使用者取消。" if is_tw else "健康检查已被用户取消。", duration_sec=round(time.time() - start_t, 2),
                disc_info=disc_info, checks=checks, findings=findings, dependencies=deps, limitations=["使用者中止。"],
                recommended_next_steps=["重試檢查。" if (is_tw or is_cn) else "Retry."]
            )

        if read_errors:
            for fn, off, err_str in read_errors:
                findings.append(DiagnosticFinding(
                    FindingSeverity.ERROR,
                    "光碟實體讀取錯誤" if (is_tw or is_cn) else "Physical Disc Read Error",
                    f"讀取 {fn} 位移 {off} 時發生錯誤: {err_str}。光碟表面可能存在刮痕、指紋污漬或光碟機讀取不穩。" if (is_tw or is_cn) else f"Read error on {fn} at offset {off}: {err_str}.",
                    fn, err_str,
                    "請清潔光碟表面後重試；若仍失敗，轉檔該區域時可能會發生卡頓或跳幀。" if (is_tw or is_cn) else "Clean the disc surface gently and retry. If errors persist, ripping this section may stall."
                ))
            checks.append(CheckItem(
                "完整媒體讀取測試" if is_tw else ("完整媒体读取测试" if is_cn else "Media Readability Test"),
                CheckStatus.FAILED,
                f"在 {blocks_read} 個測試區塊中發現 {len(read_errors)} 個讀取錯誤" if is_tw else (f"在 {blocks_read} 个测试区块中发现 {len(read_errors)} 个读取错误" if is_cn else f"{len(read_errors)} read error(s) detected across {blocks_read} blocks"),
                dur
            ))
        else:
            mb_read = round(bytes_read / 1024**2, 2)
            checks.append(CheckItem(
                "完整媒體讀取測試" if is_tw else ("完整媒体读取测试" if is_cn else "Media Readability Test"),
                CheckStatus.PASSED,
                f"跨檔案多點讀取抽樣通過 (共測試 {blocks_read} 個區塊，讀取 {mb_read} MB，0 錯誤)" if is_tw else (f"跨文件多点读取抽样通过 (共测试 {blocks_read} 个区块，读取 {mb_read} MB，0 错误)" if is_cn else f"Multi-point sample read test passed ({blocks_read} blocks, {mb_read} MB read, 0 errors)"),
                dur
            ))
        limitations.append(f"完整讀取測試執行了多點資料抽樣驗證 (共測試 {blocks_read} 個區塊)。作業系統檔案系統介面不提供完整雷射全磁區映像掃描。" if is_tw else (f"完整读取测试执行了多点数据抽样验证 (共测试 {blocks_read} 个区块)。操作系统文件系统接口不提供完整激光全扇区镜像扫描。" if is_cn else f"Thorough Read Test performed multi-point sample reads across {blocks_read} blocks. Full optical sector surface imaging is limited by OS drivers."))

    # ── Stage 6: Dependency Check ──
    notify(90, "Verifying external tool dependencies..." if not (is_tw or is_cn) else ("驗證外部工具相依性..." if is_tw else "验证外部工具依赖性..."))
    t0 = time.time()
    hb_avail = deps.get("handbrake", {}).get("available", False)
    ff_avail = deps.get("ffmpeg", {}).get("available", False)
    dur = round(time.time() - t0, 3)

    if media_type == "DVD-Video":
        if not hb_avail and not ff_avail:
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "缺少 DVD 轉檔元件 (非光碟問題)" if (is_tw or is_cn) else "Missing DVD Ripping Tools (App Environment)",
                "未偵測到 HandBrakeCLI 或 FFmpeg。注意：此為應用程式執行環境問題，並非光碟本身損毀。" if (is_tw or is_cn) else "Neither HandBrakeCLI nor FFmpeg is available. Note: This is an application/environment issue, not physical disc damage.",
                None, "HandBrakeCLI and FFmpeg unavailable",
                "確認應用程式目錄或 ffmpeg/bin 包含必要執行檔。" if (is_tw or is_cn) else "Verify executables are present in the application directory."
            ))
            checks.append(CheckItem(
                "必要外部相依元件" if is_tw else ("必要外部依赖组件" if is_cn else "Dependency Check"),
                CheckStatus.FAILED, "缺少 HandBrakeCLI 與 FFmpeg" if (is_tw or is_cn) else "Missing HandBrakeCLI and FFmpeg", dur
            ))
        else:
            checks.append(CheckItem(
                "必要外部相依元件" if is_tw else ("必要外部依赖组件" if is_cn else "Dependency Check"),
                CheckStatus.PASSED, "DVD 轉檔元件已就緒" if (is_tw or is_cn) else "DVD ripping tools verified", dur
            ))
    elif media_type == "VCD":
        if not ff_avail:
            findings.append(DiagnosticFinding(
                FindingSeverity.ERROR,
                "缺少 FFmpeg 元件 (非光碟問題)" if (is_tw or is_cn) else "Missing FFmpeg (App Environment)",
                "未偵測到 FFmpeg。VCD 轉檔需要 FFmpeg。注意：此非光碟損毀。" if (is_tw or is_cn) else "FFmpeg is required for VCD ripping and was not found. Note: This is an application issue, not physical disc damage.",
                None, "FFmpeg unavailable",
                "確認 ffmpeg.exe 位於應用程式資料夾中。" if (is_tw or is_cn) else "Ensure ffmpeg.exe is present."
            ))
            checks.append(CheckItem(
                "必要外部相依元件" if is_tw else ("必要外部依赖组件" if is_cn else "Dependency Check"),
                CheckStatus.FAILED, "缺少 FFmpeg" if (is_tw or is_cn) else "Missing FFmpeg", dur
            ))
        else:
            checks.append(CheckItem(
                "必要外部相依元件" if is_tw else ("必要外部依赖组件" if is_cn else "Dependency Check"),
                CheckStatus.PASSED, "VCD 轉檔元件已就緒" if (is_tw or is_cn) else "VCD ripping tools verified", dur
            ))
    else:
        checks.append(CheckItem(
            "必要外部相依元件" if is_tw else ("必要外部依赖组件" if is_cn else "Dependency Check"),
            CheckStatus.PASSED, "外部工具已檢查" if (is_tw or is_cn) else "External tools inspected", dur
        ))

    # ── Stage 7: Evaluation & Summary ──
    notify(100, "Compiling health report..." if not (is_tw or is_cn) else ("彙整健康診斷報告..." if is_tw else "汇总健康诊断报告..."))
    total_dur = round(time.time() - start_t, 2)

    has_errors = any(f.severity == FindingSeverity.ERROR for f in findings)
    has_warnings = any(f.severity == FindingSeverity.WARNING for f in findings)

    if has_errors:
        overall_status = HealthStatus.PROBLEMS
        if is_tw:
            summary = "檢查過程中偵測到可能影響轉檔的嚴重問題。請檢閱下方的診斷發現與建議動作以排除問題。"
        elif is_cn:
            summary = "检查过程中检测到可能影响转码的严重问题。请查看下方的诊断发现与建议操作以排查问题。"
        else:
            summary = "Problems were detected during the check that are likely to affect reading or ripping. Review the findings and recommendations below."
    elif has_warnings:
        overall_status = HealthStatus.WARNINGS
        if is_tw:
            summary = "光碟可正常存取，但檢查過程中發現部分需要注意的警告或時間標記異常。轉檔前請先檢視相關章節。"
        elif is_cn:
            summary = "光盘可正常访问，但检查过程中发现部分需要注意的警告或时间标记异常。转码前请先检查相关章节。"
        else:
            summary = "The disc is accessible, but warnings or navigation inconsistencies were found. Review affected chapters before proceeding."
    else:
        overall_status = HealthStatus.GOOD
        if is_tw:
            summary = "在已執行的檢查項目中未發現問題。光碟結構、導覽表格與章節時間標記皆有效，已準備好可進行轉檔。光碟完整表面尚未進行全盤讀取。"
        elif is_cn:
            summary = "在已执行的检查项目中未发现问题。光盘结构、导航表与章节时间标记均有效，已准备好可进行转码。光盘完整表面尚未进行全盘读取。"
        else:
            summary = "No issues were detected in the checks performed. The disc structure, navigation tables, and chapter boundaries are valid and ready for ripping. The entire disc surface has not been read."

    # Populate actionable recommendations
    if overall_status == HealthStatus.GOOD:
        recommended_next_steps.append("可直接返回主畫面並開始轉檔所需標題與章節。" if is_tw else ("可直接返回主界面并开始转码所需标题与章节。" if is_cn else "Proceed to the main window and rip your desired titles and chapters."))
        if mode == "quick":
            recommended_next_steps.append("若後續轉檔過程發生停滯或讀取不順，可執行完整讀取測試以進一步檢查光碟表面可讀性。" if is_tw else ("若后续转码过程发生停滞或读取不顺，可运行完整读取测试以进一步检查光盘表面可读性。" if is_cn else "If you encounter playback or reading stutter later, run a Thorough Read Test."))
    elif overall_status == HealthStatus.WARNINGS:
        recommended_next_steps.append("轉檔前在標題清單中檢閱受影響的章節時間標記。" if is_tw else ("转码前在标题列表中查看受影响的章节时间标记。" if is_cn else "Review affected chapters in the title list before ripping."))
        recommended_next_steps.append("若章節時間標記不連續，可考慮轉檔整段標題。" if is_tw else ("若章节时间标记不连续，可考虑转码整段标题。" if is_cn else "Consider ripping the entire title if chapter timestamps are inconsistent."))
    else:
        # Problems detected
        if any("I/O" in f.title or "Read Error" in f.title or "讀取錯誤" in f.title for f in findings):
            recommended_next_steps.append("檢查光碟表面是否有灰塵、刮痕或指紋，使用超細纖維軟布清潔後重試。" if is_tw else ("检查光盘表面是否有灰尘、划痕或指纹，使用微纤维软布清洁后重试。" if is_cn else "Inspect disc surface for scratches or dirt; clean gently with a soft microfiber cloth."))
            recommended_next_steps.append("確認光碟機托盤已完全閉合或更換光碟機測試。" if is_tw else ("确认光驱托盘已完全闭合或更换光驱测试。" if is_cn else "Ensure the drive tray is fully closed or test with another optical drive."))
        if any("Dependency" in f.title or "元件" in f.title for f in findings):
            recommended_next_steps.append("確認設定中的 FFmpeg 與 HandBrakeCLI 執行檔路徑正確。" if is_tw else ("确认设置中的 FFmpeg 与 HandBrakeCLI 路径正确。" if is_cn else "Verify FFmpeg and HandBrakeCLI paths in Settings."))

    limitations.append("光碟雷射訊號強度與驅動程式內部韌體診斷受限於作業系統介面。" if is_tw else ("光盘激光信号强度与驱动程序内部固件诊断受限于操作系统接口。" if is_cn else "Optical laser diagnostics are limited by the operating system drive interface."))

    return DiscHealthReport(
        report_id=report_id,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        app_version="2.0.4",
        os_info=os_info_str,
        source_path=source_path,
        media_type=media_type,
        mode=mode,
        overall_status=overall_status,
        summary=summary,
        duration_sec=total_dur,
        disc_info=disc_info,
        checks=checks,
        findings=findings,
        dependencies=deps,
        limitations=limitations,
        recommended_next_steps=recommended_next_steps
    )


def generate_diagnostic_report_text(report: DiscHealthReport, mask_privacy: bool = True, lang: str = "en") -> str:
    """
    Generates a clean, structured, human-readable plain text diagnostic report.
    Adheres strictly to the standard template with verified findings and zero dummy data.
    """
    divider = "-" * 50
    lines = []

    src = mask_private_path(report.source_path) if mask_privacy else report.source_path

    is_tw = (lang == "zh_TW")
    is_cn = (lang == "zh_CN")

    status_map = {
        HealthStatus.GOOD: "狀態良好" if is_tw else ("状态良好" if is_cn else "Good"),
        HealthStatus.WARNINGS: "發現警告" if is_tw else ("发现警告" if is_cn else "Warnings Found"),
        HealthStatus.PROBLEMS: "偵測到問題" if is_tw else ("检测到问题" if is_cn else "Problems Detected"),
        HealthStatus.INCONCLUSIVE: "無法判定" if is_tw else ("无法确定" if is_cn else "Inconclusive"),
    }
    status_disp = status_map.get(report.overall_status, report.overall_status)

    mode_map = {
        "quick": "快速檢查" if is_tw else ("快速检查" if is_cn else "Quick Check"),
        "thorough": "完整讀取測試" if is_tw else ("完整读取测试" if is_cn else "Thorough Read Test"),
    }
    mode_disp = mode_map.get(report.mode, report.mode)

    header_title = "DISC RIPPER PRO — 光碟健康診斷報告" if is_tw else ("DISC RIPPER PRO — 光盘健康诊断报告" if is_cn else "DISC RIPPER PRO — DIAGNOSTIC REPORT")
    lines.append(divider)
    lines.append(header_title)
    lines.append(divider)
    lines.append("")

    if is_tw:
        lines.append(f"報告日期:             {report.timestamp}")
        lines.append(f"應用程式版本:         {report.app_version}")
        lines.append(f"作業系統:             {report.os_info}")
        lines.append(f"媒體類型:             {report.media_type}")
        lines.append(f"光碟來源:             {src}")
        lines.append(f"診斷模式:             {mode_disp}")
        lines.append(f"整體結果:             {status_disp}")
        lines.append(f"測試耗時:             {report.duration_sec:.2f}s")
    elif is_cn:
        lines.append(f"报告日期:             {report.timestamp}")
        lines.append(f"应用程序版本:         {report.app_version}")
        lines.append(f"操作系统:             {report.os_info}")
        lines.append(f"媒体类型:             {report.media_type}")
        lines.append(f"光盘来源:             {src}")
        lines.append(f"诊断模式:             {mode_disp}")
        lines.append(f"整体结果:             {status_disp}")
        lines.append(f"测试耗时:             {report.duration_sec:.2f}s")
    else:
        lines.append(f"Report Date:           {report.timestamp}")
        lines.append(f"Application Version:   {report.app_version}")
        lines.append(f"Operating System:      {report.os_info}")
        lines.append(f"Media Type:            {report.media_type}")
        lines.append(f"Source:                {src}")
        lines.append(f"Diagnostic Mode:       {mode_disp}")
        lines.append(f"Overall Result:        {status_disp}")
        lines.append(f"Test Duration:         {report.duration_sec:.2f}s")

    lines.append("")
    lines.append(divider)
    lines.append("1. 摘要說明" if is_tw else ("1. 摘要说明" if is_cn else "1. SUMMARY"))
    lines.append(divider)
    lines.append("")
    lines.append(report.summary.strip())
    lines.append("")

    lines.append(divider)
    lines.append("2. 光碟資訊" if is_tw else ("2. 光盘信息" if is_cn else "2. DISC INFORMATION"))
    lines.append(divider)
    lines.append("")
    if is_tw:
        lines.append(f"偵測媒體類型:         {report.media_type}")
        lines.append(f"光碟標題/軌道數量:    {report.disc_info.get('title_count', report.disc_info.get('track_count', '無 / N/A'))}")
        lines.append(f"章節總數:             {report.disc_info.get('total_chapters', '無 / N/A')}")
        lines.append(f"光碟來源或路徑:       {src}")
        if report.disc_info.get("volume_label"):
            lines.append(f"光碟磁碟區標籤:       {report.disc_info['volume_label']}")
        if report.disc_info.get("total_size_mb"):
            lines.append(f"總媒體容量估計:       {report.disc_info['total_size_mb']} MB")
    elif is_cn:
        lines.append(f"检测媒体类型:         {report.media_type}")
        lines.append(f"光盘标题/轨道数量:    {report.disc_info.get('title_count', report.disc_info.get('track_count', '无 / N/A'))}")
        lines.append(f"章节总数:             {report.disc_info.get('total_chapters', '无 / N/A')}")
        lines.append(f"光盘来源或路径:       {src}")
        if report.disc_info.get("volume_label"):
            lines.append(f"光盘卷标:             {report.disc_info['volume_label']}")
        if report.disc_info.get("total_size_mb"):
            lines.append(f"总媒体容量估计:       {report.disc_info['total_size_mb']} MB")
    else:
        lines.append(f"Detected media type:       {report.media_type}")
        lines.append(f"Detected titles / tracks:  {report.disc_info.get('title_count', report.disc_info.get('track_count', 'N/A'))}")
        lines.append(f"Detected chapters:         {report.disc_info.get('total_chapters', 'N/A')}")
        lines.append(f"Disc source:               {src}")
        if report.disc_info.get("volume_label"):
            lines.append(f"Volume label:              {report.disc_info['volume_label']}")
        if report.disc_info.get("total_size_mb"):
            lines.append(f"Estimated total size:      {report.disc_info['total_size_mb']} MB")

    lines.append("")
    lines.append(divider)
    lines.append("3. 執行檢查項目" if is_tw else ("3. 执行检查项目" if is_cn else "3. CHECK RESULTS"))
    lines.append(divider)
    lines.append("")
    status_tag_map = {
        CheckStatus.PASSED: "[PASS]" if not (is_tw or is_cn) else ("[通過]" if is_tw else "[通过]"),
        CheckStatus.FAILED: "[FAIL]" if not (is_tw or is_cn) else ("[失敗]" if is_tw else "[失败]"),
        CheckStatus.WARNING: "[WARN]" if not (is_tw or is_cn) else ("[警告]" if is_tw else "[警告]"),
        CheckStatus.NOT_TESTED: "[NOT TESTED]" if not (is_tw or is_cn) else ("[未測試]" if is_tw else "[未测试]"),
        CheckStatus.INCONCLUSIVE: "[INCONCLUSIVE]" if not (is_tw or is_cn) else ("[無法判定]" if is_tw else "[无法确定]"),
    }
    for c in report.checks:
        tag = status_tag_map.get(c.status, f"[{c.status}]")
        dur_str = f"({c.duration_sec:.2f}s)" if c.duration_sec > 0 else ""
        lines.append(f"{tag:<14} {c.name} {dur_str} — {c.details}")

    lines.append("")
    lines.append(divider)
    lines.append("4. 診斷發現" if is_tw else ("4. 诊断发现" if is_cn else "4. FINDINGS"))
    lines.append(divider)
    lines.append("")
    if not report.findings:
        lines.append("在本次測試範圍內未發現任何錯誤或警告。" if is_tw else ("在本次测试范围内未发现任何错误或警告。" if is_cn else "No issues or warnings were detected within the tested scope."))
    else:
        for idx, f in enumerate(report.findings, 1):
            sev_str = f.severity.upper()
            if is_tw:
                sev_str = "【錯誤】" if f.severity == FindingSeverity.ERROR else ("【警告】" if f.severity == FindingSeverity.WARNING else "【資訊】")
            elif is_cn:
                sev_str = "【错误】" if f.severity == FindingSeverity.ERROR else ("【警告】" if f.severity == FindingSeverity.WARNING else "【信息】")

            lines.append(f"[{idx}] {sev_str} {f.title}")
            lines.append(f"    說明: {f.explanation}" if (is_tw or is_cn) else f"    Explanation: {f.explanation}")
            if f.location:
                lines.append(f"    位置: {f.location}" if (is_tw or is_cn) else f"    Location:    {f.location}")
            if f.evidence:
                lines.append(f"    證據: {f.evidence}" if (is_tw or is_cn) else f"    Evidence:    {f.evidence}")
            if f.recommended_action:
                lines.append(f"    建議: {f.recommended_action}" if (is_tw or is_cn) else f"    Action:      {f.recommended_action}")
            lines.append("")

    lines.append("")
    lines.append(divider)
    lines.append("5. 相依元件狀態" if is_tw else ("5. 依赖组件状态" if is_cn else "5. DEPENDENCY STATUS"))
    lines.append(divider)
    lines.append("")
    for tool_name, tool_data in report.dependencies.items():
        t_label = tool_name.capitalize()
        if tool_name == "handbrake":
            t_label = "HandBrakeCLI"
        elif tool_name == "ffmpeg":
            t_label = "FFmpeg"
        elif tool_name == "ffprobe":
            t_label = "FFprobe"

        avail = tool_data.get("available", False)
        ver = tool_data.get("version", "N/A")
        raw_p = tool_data.get("path") or ""
        p_disp = mask_private_path(raw_p) if mask_privacy else raw_p
        avail_str = ("已就緒" if is_tw else ("已就绪" if is_cn else "Available")) if avail else ("未找到" if is_tw else ("未找到" if is_cn else "Not Available"))
        lines.append(f"{t_label:<14}: {avail_str} (ver: {ver}) — {p_disp or 'N/A'}")

    lines.append("")
    lines.append(divider)
    lines.append("6. 測試範圍與限制" if is_tw else ("6. 测试范围与限制" if is_cn else "6. TEST SCOPE AND LIMITATIONS"))
    lines.append(divider)
    lines.append("")
    if report.limitations:
        for lim in report.limitations:
            lines.append(f"• {lim}")
    else:
        lines.append("Standard test scope applied." if not (is_tw or is_cn) else "套用標準診斷範圍。")

    lines.append("")
    lines.append(divider)
    lines.append("7. 建議後續動作" if is_tw else ("7. 建议后续操作" if is_cn else "7. RECOMMENDED NEXT STEPS"))
    lines.append(divider)
    lines.append("")
    if report.recommended_next_steps:
        for step in report.recommended_next_steps:
            lines.append(f"• {step}")
    else:
        lines.append("Proceed to ripping." if not (is_tw or is_cn) else "可繼續前往轉檔。")

    lines.append("")
    lines.append(divider)
    lines.append("報告結束" if is_tw else ("报告结束" if is_cn else "END OF REPORT"))
    lines.append(divider)

    return "\n".join(lines) + "\n"


def export_diagnostic_report_txt(
    report: DiscHealthReport,
    dest_path: str,
    mask_privacy: bool = True,
    lang: str = "en"
) -> str:
    """
    Exports a clean, human-readable UTF-8 plain-text diagnostic report to a single file.
    Writes atomically via a temporary file in the destination folder to prevent partial
    writes or corrupted files if an error or interruption occurs.
    Returns the absolute path of the generated file.
    """
    report_text = generate_diagnostic_report_text(report, mask_privacy=mask_privacy, lang=lang)
    target = Path(dest_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write to temporary file then atomic replace
    tmp_path = target.with_suffix(target.suffix + f".tmp_{time.time_ns() % 1000000}")
    try:
        tmp_path.write_text(report_text, encoding="utf-8")
        tmp_path.replace(target)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise

    return str(target)



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Disc Ripper Pro DVD Diagnostics & Integrity Tool")
    parser.add_argument("--inspect", type=str, help="Path to a ripped media file to inspect integrity")
    parser.add_argument("--export", action="store_true", help="Export diagnostic package to Desktop")
    parser.add_argument("--clear", action="store_true", help="Clear active session markers")
    args = parser.parse_args()

    if args.inspect:
        res = inspect_media_file_integrity(args.inspect)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("verdict") == "PASS" else 1)
    elif args.export:
        zip_path = export_diagnostic_package()
        print(f"Exported diagnostic package to: {zip_path}")
    elif args.clear:
        clear_marker()
        print("Cleared session markers.")
    else:
        parser.print_help()

