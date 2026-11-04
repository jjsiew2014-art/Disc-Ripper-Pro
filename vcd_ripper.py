"""
Disc Ripper Pro - A modern VCD & DVD video extraction tool for Windows
Uses FFmpeg to rip VCD and DVD-Video media with a premium dark UI
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import queue
import collections
import atexit
import os
import sys
import json
import time
import re
import shutil
import ctypes
import string
from pathlib import Path
from datetime import datetime

import dvd_engine
import dvd_diagnostics
import disc_detector
from disc_detector import detect_disc, get_optical_drives, is_drive_ready, DiscCheckResult, flush_optical_drive_cache


# ─────────────────────────────────────────────
#  Constants & Colour Palette
# ─────────────────────────────────────────────
APP_NAME = "Disc Ripper Pro"
APP_VERSION = "2.0.4"
APP_USER_MODEL_ID = "jjsiew.discripperpro.2.0.4"

THEME_DARK = {
    "bg_dark":        "#0D0F14",
    "bg_panel":       "#141720",
    "bg_card":        "#1C2030",
    "bg_hover":       "#242840",
    "accent":         "#6C63FF",
    "accent_hover":   "#8B84FF",
    "accent_dim":     "#3D3880",
    "success":        "#22C55E",
    "warning":        "#F59E0B",
    "error":          "#EF4444",
    "cyan":           "#06B6D4",
    "text_primary":   "#F0F2FF",
    "text_secondary": "#8B93B0",
    "text_muted":     "#7E88A8",
    "border":         "#252A40",
    "border_accent":  "#4A44AA",
    "progress_bg":    "#1C2030",
    "dat_tag":        "#EC4899",
    "mpg_tag":        "#F59E0B",
    "mp4_tag":        "#22C55E",
    "mov_tag":        "#6C63FF",
    "btn_primary_fg": "#F0F2FF",
    "badge_fg":       "#F0F2FF",
    "rename_btn":     "#38BDF8",
    "rename_btn_hover": "#7DD3FC",
}

THEME_LIGHT = {
    "bg_dark":        "#F1F5F9",
    "bg_panel":       "#FFFFFF",
    "bg_card":        "#F8FAFC",
    "bg_hover":       "#E2E8F0",
    "accent":         "#5B50E5",
    "accent_hover":   "#4B40D4",
    "accent_dim":     "#EEF2FF",
    "success":        "#16A34A",
    "warning":        "#D97706",
    "error":          "#DC2626",
    "cyan":           "#0891B2",
    "text_primary":   "#0F172A",
    "text_secondary": "#475569",
    "text_muted":     "#94A3B8",
    "border":         "#E2E8F0",
    "border_accent":  "#A5B4FC",
    "progress_bg":    "#E2E8F0",
    "dat_tag":        "#DB2777",
    "mpg_tag":        "#D97706",
    "mp4_tag":        "#16A34A",
    "mov_tag":        "#5B50E5",
    "btn_primary_fg": "#FFFFFF",
    "badge_fg":       "#4338CA",
    "rename_btn":     "#0284C7",
    "rename_btn_hover": "#0369A1",
}

COLORS = dict(THEME_DARK)

def get_windows_theme():
    """Detects whether Windows system app theme is light or dark using registry."""
    if sys.platform != "win32":
        return "dark"
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if val == 1 else "dark"
    except Exception:
        return "dark"

def set_window_dark_mode(hwnd, dark=True):
    """Sets the Windows DWM immersive dark mode attribute for the window title bar."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1 if dark else 0)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(val),
            ctypes.sizeof(val)
        )
        if res != 0:
            # Fallback for Windows 10 builds before 19041 (1809~1909)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                19,
                ctypes.byref(val),
                ctypes.sizeof(val)
            )
        return True
    except Exception:
        return False

def apply_theme_palette(theme_name):
    palette = THEME_LIGHT if theme_name == "light" else THEME_DARK
    COLORS.update(palette)
    for fmt, key in [("DAT", "dat_tag"), ("MPG", "mpg_tag"), ("MP4", "mp4_tag"), ("MOV", "mov_tag")]:
        if fmt in OUTPUT_FORMATS:
            OUTPUT_FORMATS[fmt]["color"] = COLORS[key]
    if "WAV" in AUDIO_FORMATS:
        AUDIO_FORMATS["WAV"]["color"] = COLORS["success"]
    if "MP3" in AUDIO_FORMATS:
        AUDIO_FORMATS["MP3"]["color"] = COLORS["warning"]

BASE_FONTS = {
    "title":       ("Segoe UI", 26, "bold"),
    "header":      ("Segoe UI", 16, "bold"),
    "heading":     ("Segoe UI", 16, "bold"),
    "subheading":  ("Segoe UI", 13, "bold"),
    "subhead":     ("Segoe UI", 13, "bold"),
    "body":        ("Segoe UI", 12, "normal"),
    "body_bold":   ("Segoe UI", 12, "bold"),
    "small":       ("Segoe UI", 11, "normal"),
    "small_bold":  ("Segoe UI", 11, "bold"),
    "mono":        ("Consolas", 11, "normal"),
    "mono_bold":   ("Consolas", 11, "bold"),
    "badge":       ("Segoe UI", 10, "bold"),
    "tiny":        ("Segoe UI", 10, "normal"),
    "tiny_bold":   ("Segoe UI", 10, "bold"),
    "rename_btn":  ("Segoe UI", 18, "bold"),
    "emoji_32":    ("Segoe UI Emoji", 32, "normal"),
    "emoji_38":    ("Segoe UI Emoji", 38, "normal"),
    "emoji_64":    ("Segoe UI Emoji", 64, "normal"),
}

FONTS = {k: (spec[0], spec[1], spec[2] if len(spec) > 2 else "normal") for k, spec in BASE_FONTS.items()}

def scale_val(val, scale=None):
    if scale is None:
        try:
            scale = i18n.get_scale_factor()
        except Exception:
            scale = 1.0
    return max(1, int(round(val * scale)))

def apply_font_scale(root, scale=1.0):
    import tkinter.font as tkFont
    for k, spec in BASE_FONTS.items():
        fam, size = spec[0], spec[1]
        weight = spec[2] if len(spec) > 2 else "normal"
        scaled_size = max(8, int(round(size * scale)))
        configured = False
        if k in FONTS and isinstance(FONTS[k], tkFont.Font):
            try:
                FONTS[k].configure(size=scaled_size)
                configured = True
            except Exception:
                configured = False
        if not configured:
            try:
                FONTS[k] = tkFont.Font(root, family=fam, size=scaled_size, weight=weight)
            except Exception:
                FONTS[k] = (fam, scaled_size, weight)


VCD_DAT_PATHS = ["MPEGAV", "MPEG2"]   # folders inside VCD that hold .DAT files
VCD_MARKER    = "VCD"                  # label to detect VCD type drives

OUTPUT_FORMATS = {
    "DAT": {
        "ext": ".dat",
        "args": [],
        "desc": "Raw direct copy (VCD only)",
        "color": COLORS["dat_tag"],
    },
    "MPG": {
        "ext": ".mpg",
        "args": ["-c:v", "copy", "-c:a", "copy"],
        "desc": "MPEG-1/2 (native disc stream)",
        "color": COLORS["mpg_tag"],
    },
    "MP4": {
        "ext": ".mp4",
        "args": ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "192k"],
        "desc": "H.264 + AAC (widely compatible)",
        "color": COLORS["mp4_tag"],
    },
    "MOV": {
        "ext": ".mov",
        "args": ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "192k"],
        "desc": "QuickTime / Apple compatible",
        "color": COLORS["mov_tag"],
    },
}

AUDIO_FORMATS = {
    "WAV": {
        "ext": ".wav",
        "args": ["-vn", "-acodec", "pcm_s16le", "-ar", "44100"],
        "desc": "Lossless PCM audio",
        "color": COLORS["success"],
    },
    "MP3": {
        "ext": ".mp3",
        "args": ["-vn", "-acodec", "libmp3lame", "-q:a", "2"],
        "desc": "High quality compressed audio",
        "color": COLORS["warning"],
    },
}


# ─────────────────────────────────────────────
#  I18n System
# ─────────────────────────────────────────────
TRANSLATIONS = {
    "en": {
        "header": {
            "title": "Disc Ripper Pro",
            "console": "📋  Console",
            "clear_all": "🗑  Clear All",
            "clear_all_tip": "Clear loaded video files and progress",
            "about": "⚙  Setting",
            "batch_rename": "✏  Batch Rename",
            "eject_disc": "⏏  Eject Disc",
            "no_disc": "⏺  No disc detected",
            "vcd_on": "💿  VCD on {drive}:",
            "drive_no_vcd": "💿  Drive {drive}: (no VCD)",
        },
        "drive": {
            "detect_vcd": "VCD detected!",
            "detect_dvd": "DVD-Video detected!",
            "detect_disc": "Disc detected!",
            "detecting": "Drive detecting...",
            "detected": "Drive detected",
            "insert_vcd": "Insert a VCD disc\nor click Browse",
            "insert_disc": "Insert a VCD/DVD disc\nor click Browse",
            "folder_selected": "VCD folder selected",
            "drive_label": "Drive  {drive}:",
        },
        "source": {
            "title": "SOURCE",
            "browse": "Browse Folder",
            "scan": "Scan VCD",
        },
        "selection": {
            "title": "SELECTION",
            "all": "All",
            "none": "None",
            "count": "{n} of {total} selected",
            "mode_title": "Complete Title",
            "mode_chapters": "Selected Chapters",
            "count_chapters": "{n} of {total} chapters selected",
        },
        "format": {
            "title": "OUTPUT FORMAT",
            "video_mode": "🎬  Video",
            "audio_mode": "🎵  Audio Only",
            "both_mode": "🎬+🎵  Video and Audio",
            "video_lbl": "Video Format:",
            "dat_desc": "Raw direct copy",
            "mpg_desc": "MPEG-1/2 (native VCD stream)",
            "mp4_desc": "H.264 + AAC (widely compatible)",
            "mov_desc": "QuickTime / Apple compatible",
            "dat_mode_lbl": "DAT Output Mode:",
            "dat_raw": "Raw .dat  (no changes)",
            "dat_mp4": "Rename to .mp4",
            "res_title": "Export Resolution:",
            "res_orig": "Original Quality",
            "res_1080p": "1440×1080  (upscale to 1080p, 4:3)",
            "audio_lbl": "Audio Format:",
            "wav_desc": "Lossless PCM audio",
            "mp3_desc": "High quality compressed audio",
            "audio_track_lbl": "DVD Audio Track:",
            "target_title_lbl": "Target Title:",
            "no_audio_tracks": "No audio tracks available",
        },
        "output": {
            "title": "OUTPUT FOLDER",
            "choose": "Choose Output Folder",
            "auto_open": "Open output folder after ripped",
            "dvd_title_folder": "Create folder with DVD title",
            "dvd_timeline": "Generate Chapter Timeline File (.txt)",
        },
        "rip": {
            "start": "Start Ripping",
            "stop": "Stop Ripping",
        },
        "content": {
            "title": "Video Files",
            "badge": "  {n}  ",
            "badge_empty": "0 tracks detected",
            "empty_title": "No VCD loaded",
            "empty_sub": "Insert a disc or browse to a VCD folder, then click Scan VCD",
            "scan_prog_folder": "Scanning folder: {name}...",
            "scan_prog_read": "Reading metadata ({idx}/{total}): {name}",
            "rip_prog_proc": "Processing {idx}/{total}: {name}",
            "rip_prog_stop": "Stopped: {success}/{total} files saved",
            "rip_prog_done": "Completed: {success}/{total} files ripped",
        },
        "console": {
            "title": "  📋  Console Log",
            "clear": "Clear",
        },
        "about": {
            "title": "Setting",
            "app": "Application",
            "version": "Version",
            "dev": "Developer",
            "cat_appearance": "Appearance & Display",
            "cat_processing": "Processing Settings",
            "cat_diagnostics": "Diagnostics & System Information",
            "ffmpeg": "FFmpeg status",
            "ffmpeg_path": "FFmpeg path",
            "handbrake": "HandBrakeCLI status",
            "handbrake_path": "HandBrakeCLI path",
            "copy_path": "Copy",
            "copied": "Copied!",
            "copy_ffmpeg_tip": "Copy full FFmpeg path to clipboard",
            "copy_hb_tip": "Copy full HandBrakeCLI path to clipboard",
            "ready": "✓  Ready",
            "not_found": "✗  Not Found",
            "license": "MIT License",
            "close": "Close",
        },
        "language": {
            "title": "Language",
            "en": "English",
            "zh": "中文",
        },
        "appearance": {
            "title": "Appearance",
            "system": "System",
            "light": "Light Mode",
            "dark": "Dark Mode",
        },
        "scale": {
            "title": "Scale",
            "100": "100%",
            "125": "125%",
            "150": "150%",
            "100%": "100%",
            "125%": "125%",
            "150%": "150%",
        },
        "priority": {
            "title": "Process Priority",
            "low": "Low",
            "medium": "Medium",
            "high": "High",
        },
        "fps_mode": {
            "title": "FPS Mode",
            "passthrough": "Passthrough",
            "cfr": "CFR",
        },
        "dvd_scanner": {
            "title": "DVD Scanner",
            "auto": "Auto",
            "direct_ifo": "Direct IFO",
            "handbrake": "HandBrake",
            "auto_tip": "Auto: HandBrake scan with Direct IFO fallback",
            "direct_ifo_tip": "Direct IFO (Safe Mode): Bypasses HandBrake and SCSI IOCTLs",
            "handbrake_tip": "HandBrake Only: Uses HandBrakeCLI scanner",
        },
        "notification": {
            "title": "Notification",
            "enabled": "Enabled",
            "disabled": "Disabled",
            "tip": "Show a Windows notification when ripping completes",
            "rip_done": "Ripping Completed",
            "rip_done_with_err": "Ripping Completed with Errors",
            "rip_stopped": "Ripping Stopped",
            "rip_timeout": "Ripping Timed Out",
            "rip_stats": "✓ Succeeded: {success}  |  ✗ Failed: {errors}  (Total: {total})",
        },
        "diagnostics": {
            "title": "Diagnostics & Safety",
            "diag_scan": "Diagnostic Scan",
            "export_zip": "Export Logs (.zip)",
            "stale_detected_title": "Previous DVD Scan Interrupted",
            "stale_detected_body": "A previous DVD scan was interrupted unexpectedly (possibly due to a Windows system crash, restart, or optical drive driver fault).",
            "stale_export_prompt": "Would you like to export the diagnostic log package now to help troubleshoot?",
            "save_dialog_title": "Export Diagnostic Package",
            "export_success_title": "Diagnostics Exported",
            "export_success_msg": "Diagnostic package successfully exported to:\n\n{path}",
            "export_fail_title": "Export Failed",
            "diag_scan_started": "Diagnostic DVD scan started on: {path} (mode: {mode})",
            "diag_scan_done": "Diagnostic DVD scan completed. Diagnostic logs written to disk.",
            "health_check": "Disc Health Check",
            "export_report": "Export Diagnostic Report (.txt)",
            "health_check_tip": "Assess disc readability, structure integrity, and chapter boundaries before ripping",
            "select_mode_title": "Select Diagnostic Mode",
            "mode_quick": "Quick Check (Default)",
            "mode_quick_desc": "Rapidly validates disc structure, navigation tables, and chapter timing (~2-5s)",
            "mode_thorough": "Thorough Read Test (Optional)",
            "mode_thorough_desc": "Performs multi-point data read tests across media files to detect unreadable sectors (~15-45s)",
            "start_check": "Start Health Check",
            "results_title": "Disc Health Check Results",
            "status_good": "Good",
            "status_warnings": "Warnings Found",
            "status_problems": "Problems Detected",
            "status_inconclusive": "Inconclusive",
            "summary": "Summary",
            "checks_performed": "Checks Performed",
            "findings": "Findings",
            "recommended_steps": "Recommended Next Steps",
            "proceed_rip": "Proceed to Ripping",
            "export_txt_btn": "Export Report (.txt)",
            "no_findings": "No issues or warnings were detected within the tested scope.",
            "save_txt_dialog": "Save Diagnostic Report (.txt)",
            "export_txt_success_title": "Report Exported",
            "export_txt_success_msg": "Diagnostic report successfully exported to:\n\n{path}",
            "cancel": "Cancel",
            "close": "Close",
            "running_check": "Running disc diagnostics...",
            "select_disc_folder": "Select DVD/VCD Drive or Folder for Health Check",
            "no_disc_selected": "Please select or insert a disc first.",
            "confirm_rip_warn": "Warnings were detected during the health check:\n\n{warnings}\n\nDo you want to proceed to the ripping screen anyway?",
            "confirm_rip_problems": "Problems were detected that may prevent successful ripping:\n\n{problems}\n\nRipping may fail or produce corrupted files. Do you want to proceed anyway?",
            "confirm_rip_inconclusive": "The disc health check was incomplete or inconclusive.\n\nDo you want to proceed to the ripping screen anyway?",
        },
        "rename": {
            "title": "Rename file",
            "inst": "Output filename (without extension):",
            "apply": "Apply",
            "cancel": "Cancel",
        },
        "batch": {
            "title": "Batch Rename",
            "header": "Batch Rename Files",
            "inst": "Edit output filenames below (without extension):",
            "track": "Track {n}:",
            "apply_all": "Apply All",
            "cancel": "Cancel",
            "no_files_title": "No Files",
            "no_files_msg": "No files to rename. Please scan a VCD first.",
            "seq_enable": "Enable Sequential Numbering",
            "seq_base": "Base Name:",
            "seq_start": "Start Index:",
            "seq_suffix": "Suffix:",
            "seq_preview": "Preview:",
        },
        "messageboxes": {
            "no_source_title": "No source",
            "no_source_msg": "Please insert a VCD/DVD or browse to a disc folder first.",
            "invalid_path_title": "Invalid path",
            "invalid_path_msg": "Path does not exist:\n{path}",
            "no_files_title": "No files found",
            "no_files_msg": "No video files or titles were found.\nMake sure you selected a valid VCD or DVD disc/folder.",
            "ffmpeg_req_title": "FFmpeg not found",
            "ffmpeg_req_msg": "FFmpeg is required for audio extraction and video conversion.\n\nDownload from https://ffmpeg.org/download.html and ensure\nffmpeg.exe is in your PATH or in a 'ffmpeg/bin' folder next to this script.\n\nTip: Select 'DAT' video format to extract raw files without FFmpeg.",
            "no_sel_title": "No selection",
            "no_sel_msg": "No videos selected. Rip all videos?",
            "no_sel_chaps_msg": "No chapters selected. Rip all chapters?",
            "no_vid_title": "No videos",
            "no_vid_msg": "Please scan a VCD or DVD first.",
            "stop_title": "Task Stopped",
            "stop_msg": "Ripping task was stopped by user.\n\n{success} video(s) were saved to:\n{folder}",
            "eject_title": "Eject Disc?",
            "eject_msg": "Successfully ripped {success} file(s)!\n\nWould you like to eject the disc now?",
            "err_title": "Completed with errors",
            "err_msg": "Ripped {success} file(s) successfully.\n{errors} file(s) had errors — check the console log.",
            "no_drive_title": "No Disc Drive",
            "no_drive_msg": "No optical disc drive was detected.",
            "eject_fail_title": "Eject Failed",
            "eject_fail_msg": "Could not eject drive {drive}:\n{err}",
            "ejecting": "Ejecting disc from drive {drive}:...",
            "unsupported_disc_title": "Unsupported Disc Format",
            "unsupported_disc_msg": "The detected optical disc or folder is not a valid VCD or DVD-Video disc. This app supports VCD and DVD-Video media.",
            "timeout_title": "Disc Read Timeout",
            "timeout_msg": "Ripping was stopped due to severely damaged disc sectors or read timeout. Partial video has been saved.",
            "btn_ok": "OK",
            "btn_eject": "Eject Disc",
        },
        "log": {
            "non_vcd_blocked": "Disc detected in drive {drive}, type: {type}, blocking process.",
            "vcd_auto": "VCD disc auto-detected at {drive}",
            "vcd_found": "VCD structure found at {folder}",
            "vcd_not_std": "Selected folder may not be a standard VCD (no .DAT files found). Scanning anyway...",
            "scan_dir": "Scanning {path} …",
            "no_vid": "No video files found in selected path.",
            "found_files": "Found {total} file(s). Reading metadata…",
            "loaded": "Loaded {total} video(s) from VCD. All selected.",
            "out_set": "Output folder set: {folder}",
            "cancel_req": "Cancellation requested by user… Stopping process.",
            "start_ext": "Starting extraction of {total} file(s) → {fmt} format…",
            "start_chaps": "Starting extraction of {total} chapter(s) → {fmt} format…",
            "extracting": "Extracting: {name} → {out}",
            "raw_dat_ok": "✓  Extracted raw DAT → Saved as: {name}  ({size} MB)",
            "copy_err": "Direct copy error: {err}",
            "saved_ok": "✓  Saved: {name}  ({size} MB)",
            "saved_partial": "⚠  Preserved partial video: {name}  ({size} MB)",
            "read_timeout": "Disc read timed out on {name} ({timeout}s without data). Terminating process.",
            "ffmpeg_err": "FFmpeg error processing: {name}",
            "exc": "Exception: {err}",
            "stop_sum": "Extraction stopped by user. {success} file(s) completed.",
            "done_ok": "All {success} file(s) ripped successfully! Output: {folder}",
            "open_err": "Could not open output folder: {err}",
            "done_err": "Completed with {errors} error(s). {success} file(s) saved to {folder}",
            "cleared": "Disc information cleared.",
            "cleared_all": "Cleared video files and progress.",
            "eject_win32": "Disc ejected from drive {drive}: (DeviceIoControl)",
            "eject_win32_fail": "DeviceIoControl eject failed: {err}",
            "eject_ps": "Eject command sent to drive {drive}: (PowerShell)",
            "eject_ps_fail": "PowerShell eject also failed: {err}",
            "batch_renamed": "Batch renamed {total} file(s).",
            "ffmpeg_dl": "FFmpeg not found! Download from https://ffmpeg.org and add to PATH.",
            "ffmpeg_hint": "Or place ffmpeg.exe in a 'ffmpeg/bin' subfolder next to this script.",
            "timeline_done": "Chapter timeline generated: {name}",
            "timeline_no_chapters": "Chapter timeline for {name}: No chapter metadata found in the output file.",
            "timeline_ffprobe_missing": "Chapter timeline generation skipped: FFprobe executable not found.",
            "timeline_failed": "Chapter timeline failed for {name}: {err}",
        }
    },
    "zh_CN": {
        "header": {
            "title": "Disc Ripper Pro",
            "console": "📋  控制台",
            "clear_all": "🗑  清空",
            "clear_all_tip": "清空已加载的影片列表与进度",
            "about": "⚙  设置",
            "batch_rename": "✏  批量重命名",
            "eject_disc": "⏏  弹出光盘",
            "no_disc": "⏺  未检测到光盘",
            "vcd_on": "💿  VCD 位于 {drive}:",
            "drive_no_vcd": "💿  驱动器 {drive}: (无 VCD)",
        },
        "drive": {
            "detect_vcd": "检测到 VCD！",
            "detect_dvd": "检测到 DVD-Video！",
            "detect_disc": "检测到光盘！",
            "detecting": "正在检测驱动器...",
            "detected": "已识别到驱动器",
            "insert_vcd": "插入 VCD 光盘\n或点击浏览",
            "insert_disc": "插入 VCD/DVD 光盘\n或点击浏览",
            "folder_selected": "已选择 VCD 文件夹",
            "drive_label": "驱动器  {drive}:",
        },
        "source": {
            "title": "来源",
            "browse": "浏览文件夹",
            "scan": "扫描 VCD",
        },
        "selection": {
            "title": "选择",
            "all": "全选",
            "none": "取消全选",
            "count": "已选择 {n} / {total}",
            "mode_title": "完整标题",
            "mode_chapters": "选定章节",
            "count_chapters": "已选 {n}/{total} 个章节",
        },
        "format": {
            "title": "输出格式",
            "video_mode": "🎬  视频",
            "audio_mode": "🎵  仅音频",
            "both_mode": "🎬+🎵  视频与音频",
            "video_lbl": "视频格式：",
            "dat_desc": "原始档案",
            "mpg_desc": "MPEG-1/2 (原生 VCD)",
            "mp4_desc": "H.264 + AAC (广泛兼容)",
            "mov_desc": "QuickTime / 苹果兼容",
            "dat_mode_lbl": "DAT 输出模式：",
            "dat_raw": "原始 .dat",
            "dat_mp4": "重命名为 .mp4",
            "res_title": "导出分辨率：",
            "res_orig": "原始画质",
            "res_1080p": "1440×1080 (拉伸至 1080p, 4:3)",
            "audio_lbl": "音频格式：",
            "wav_desc": "无损 PCM 音频",
            "mp3_desc": "高品质压缩音频",
            "audio_track_lbl": "DVD 音轨选择：",
            "target_title_lbl": "目标标题：",
            "no_audio_tracks": "无可用音轨",
        },
        "output": {
            "title": "输出",
            "choose": "选择文件夹",
            "auto_open": "提取完成后打开输出文件夹",
            "dvd_title_folder": "根据 DVD 标题创建文件夹",
            "dvd_timeline": "生成章节时间轴文件 (.txt)",
        },
        "rip": {
            "start": "开始提取",
            "stop": "停止提取",
        },
        "content": {
            "title": "视频文件",
            "badge": "  {n}  ",
            "badge_empty": "检测到 0 个轨道",
            "empty_title": "未加载 VCD",
            "empty_sub": "插入光盘或浏览至 VCD 文件夹，然后点击扫描 VCD",
            "scan_prog_folder": "正在扫描文件夹：{name}...",
            "scan_prog_read": "正在读取元数据 ({idx}/{total})：{name}",
            "rip_prog_proc": "正在处理 ({idx}/{total})：{name}",
            "rip_prog_stop": "已停止：成功保存 {success}/{total} 个文件",
            "rip_prog_done": "已完成：成功提取 {success}/{total} 个文件",
        },
        "console": {
            "title": "  📋  控制台日志",
            "clear": "清除",
        },
        "about": {
            "title": "设置",
            "app": "应用程序",
            "version": "版本",
            "dev": "开发者",
            "cat_appearance": "外观与显示",
            "cat_processing": "处理设置",
            "cat_diagnostics": "诊断与系统信息",
            "ffmpeg": "FFmpeg 状态",
            "ffmpeg_path": "FFmpeg 路径",
            "handbrake": "HandBrakeCLI 状态",
            "handbrake_path": "HandBrakeCLI 路径",
            "copy_path": "复制",
            "copied": "已复制！",
            "copy_ffmpeg_tip": "复制完整 FFmpeg 路径到剪贴板",
            "copy_hb_tip": "复制完整 HandBrakeCLI 路径到剪贴板",
            "ready": "✓  就绪",
            "not_found": "✗  未找到",
            "license": "MIT 许可证",
            "close": "关闭",
        },
        "language": {
            "title": "语言",
            "en": "English",
            "zh": "中文",
        },
        "appearance": {
            "title": "外观",
            "system": "跟随系统",
            "light": "浅色模式",
            "dark": "深色模式",
        },
        "scale": {
            "title": "界面缩放",
            "100": "100%",
            "125": "125%",
            "150": "150%",
            "100%": "100%",
            "125%": "125%",
            "150%": "150%",
        },
        "priority": {
            "title": "进程优先级",
            "low": "低",
            "medium": "中",
            "high": "高",
        },
        "fps_mode": {
            "title": "帧率模式",
            "passthrough": "Passthrough",
            "cfr": "CFR",
        },
        "dvd_scanner": {
            "title": "DVD 扫描引擎",
            "auto": "自动",
            "direct_ifo": "Direct IFO",
            "handbrake": "HandBrake",
            "auto_tip": "自动模式：优先使用 HandBrake 扫描，必要时平滑回退至 Direct IFO",
            "direct_ifo_tip": "直接 IFO 安全模式：完全绕过 HandBrake 及底层 SCSI SPTI 指令",
            "handbrake_tip": "仅 HandBrake 模式：仅使用 HandBrakeCLI 扫描",
        },
        "notification": {
            "title": "系统通知",
            "enabled": "开启",
            "disabled": "关闭",
            "tip": "转换完成后在 Windows 发送系统提示通知",
            "rip_done": "转换完成",
            "rip_done_with_err": "转换完成 (存在失败)",
            "rip_stopped": "转换已停止",
            "rip_timeout": "转换超时",
            "rip_stats": "✓ 成功: {success} 个  |  ✗ 失败: {errors} 个  (共 {total} 个)",
        },
        "diagnostics": {
            "title": "诊断与安全",
            "diag_scan": "诊断模式扫描",
            "export_zip": "导出日志 (.zip)",
            "stale_detected_title": "检测到上次 DVD 扫描异常中断",
            "stale_detected_body": "Disc Ripper Pro 检测到上次 DVD 扫描异常终止（可能由于 Windows 系统重启、蓝屏 BSOD 或光驱驱动崩溃）。",
            "stale_export_prompt": "是否立即导出诊断日志包（ZIP）以便排查问题？",
            "save_dialog_title": "导出诊断日志包",
            "export_success_title": "导出成功",
            "export_success_msg": "诊断日志包已成功导出至：\n\n{path}",
            "export_fail_title": "导出失败",
            "diag_scan_started": "已启动 DVD 诊断扫描：{path}（模式：{mode}）",
            "diag_scan_done": "DVD 诊断扫描已完成，日志已写入磁盘。",
            "health_check": "光碟健康检查",
            "export_report": "导出诊断报告 (.txt)",
            "health_check_tip": "在转码前评估光盘可读性、结构完整性与章节边界",
            "select_mode_title": "选择诊断模式",
            "mode_quick": "快速检查 (默认)",
            "mode_quick_desc": "快速验证光盘结构、导航表与章节时间边界 (~2-5秒)",
            "mode_thorough": "完整读取测试 (可选)",
            "mode_thorough_desc": "跨媒体文件执行多点数据读取测试以检测损坏扇区 (~15-45秒)",
            "start_check": "开始健康检查",
            "results_title": "光盘健康检查结果",
            "status_good": "状态良好",
            "status_warnings": "发现警告",
            "status_problems": "检测到问题",
            "status_inconclusive": "无法确定",
            "summary": "摘要说明",
            "checks_performed": "执行检查项目",
            "findings": "诊断发现",
            "recommended_steps": "建议后续操作",
            "proceed_rip": "继续前往转码",
            "export_txt_btn": "导出报告 (.txt)",
            "no_findings": "在本次测试范围内未发现任何错误或警告。",
            "save_txt_dialog": "保存诊断报告 (.txt)",
            "export_txt_success_title": "报告导出成功",
            "export_txt_success_msg": "诊断报告已成功导出至：\n\n{path}",
            "cancel": "取消",
            "close": "关闭",
            "running_check": "正在执行光盘诊断...",
            "select_disc_folder": "选择健康检查专用的 DVD/VCD 光驱或文件夹",
            "no_disc_selected": "请先放入或选择光盘。",
            "confirm_rip_warn": "健康检查过程中发现警告：\n\n{warnings}\n\n您仍要继续前往转码界面吗？",
            "confirm_rip_problems": "健康检查检测到可能影响转码的严重问题：\n\n{problems}\n\n转码可能失败或产生损坏文件。您确定仍要继续吗？",
            "confirm_rip_inconclusive": "光盘健康检查未完成或无法确定。\n\n您仍要继续前往转码界面吗？",
        },
        "rename": {
            "title": "重命名文件",
            "inst": "输出文件名 (不含扩展名)：",
            "apply": "应用",
            "cancel": "取消",
        },
        "batch": {
            "title": "批量重命名",
            "header": "批量重命名文件",
            "inst": "在下方编辑输出文件名 (不含扩展名)：",
            "track": "轨道 {n}:",
            "apply_all": "全部应用",
            "cancel": "取消",
            "no_files_title": "没有文件",
            "no_files_msg": "没有可以重命名的文件。请先扫描 VCD。",
            "seq_enable": "启用顺序编号",
            "seq_base": "基础名称：",
            "seq_start": "起始序号：",
            "seq_suffix": "后缀：",
            "seq_preview": "预览：",
        },
        "messageboxes": {
            "no_source_title": "没有来源",
            "no_source_msg": "请先插入 VCD/DVD 或浏览至光盘文件夹。",
            "invalid_path_title": "路径无效",
            "invalid_path_msg": "路径不存在：\n{path}",
            "no_files_title": "未找到文件",
            "no_files_msg": "未找到视频文件或影片标题。\n请确保选择了有效的 VCD 或 DVD 光盘/文件夹。",
            "ffmpeg_req_title": "未找到 FFmpeg",
            "ffmpeg_req_msg": "音频提取和视频转换需要 FFmpeg。\n\n请从 https://ffmpeg.org/download.html 下载，并确保\nffmpeg.exe 位于您的 PATH 环境变量中，或者与本脚本同级的 'ffmpeg/bin' 文件夹中。\n\n提示：选择 'DAT' 视频格式可以直接提取原始文件而无需 FFmpeg。",
            "no_sel_title": "未选择",
            "no_sel_msg": "未选择任何视频。要提取所有视频吗？",
            "no_sel_chaps_msg": "未选择任何章节。要提取所有章节吗？",
            "no_vid_title": "没有视频",
            "no_vid_msg": "请先扫描 VCD 或 DVD。",
            "stop_title": "任务已停止",
            "stop_msg": "提取任务已被用户停止。\n\n{success} 个视频已保存至：\n{folder}",
            "eject_title": "弹出光盘？",
            "eject_msg": "已成功提取 {success} 个文件！\n\n您想现在弹出光盘吗？",
            "err_title": "完成但有错误",
            "err_msg": "成功提取了 {success} 个文件。\n{errors} 个文件出现错误 — 请查看控制台日志。",
            "no_drive_title": "没有光盘驱动器",
            "no_drive_msg": "未检测到光盘驱动器。",
            "eject_fail_title": "弹出失败",
            "eject_fail_msg": "无法弹出驱动器 {drive}:\n{err}",
            "ejecting": "正在从驱动器 {drive} 弹出光盘:...",
            "unsupported_disc_title": "不支持的光盘格式",
            "unsupported_disc_msg": "检测到的光盘或文件夹不是有效的 VCD 或 DVD-Video 光盘。本软件支持 VCD 与 DVD-Video 媒体。",
            "timeout_title": "光碟读取超时",
            "timeout_msg": "由于光盘严重划伤或坏道导致读取超时，已停止提取。已为您保留已完成抓取的视频片段。",
            "btn_ok": "确定",
            "btn_eject": "弹出光碟",
        },
        "log": {
            "non_vcd_blocked": "在驱动器 {drive} 检测到光盘，类型: {type}，已拦截处理流程。",
            "vcd_auto": "自动检测到 VCD 光盘于 {drive}",
            "vcd_found": "在 {folder} 找到 VCD 结构",
            "vcd_not_std": "所选文件夹可能不是标准 VCD (未找到 .DAT 文件)。仍将扫描...",
            "scan_dir": "正在扫描 {path} …",
            "no_vid": "在所选路径中未找到视频文件。",
            "found_files": "找到 {total} 个文件。正在读取元数据…",
            "loaded": "已从 VCD 加载 {total} 个视频。已全选。",
            "out_set": "输出文件夹设置为：{folder}",
            "cancel_req": "用户请求取消… 正在停止进程。",
            "start_ext": "开始提取 {total} 个文件 → {fmt} 格式…",
            "start_chaps": "开始提取 {total} 个章节 → {fmt} 格式…",
            "extracting": "正在提取：{name} → {out}",
            "raw_dat_ok": "✓  已提取原始 DAT → 保存为：{name}  ({size} MB)",
            "copy_err": "直接复制错误：{err}",
            "saved_ok": "✓  已保存：{name}  ({size} MB)",
            "saved_partial": "⚠  已保留部分视频片段：{name}  ({size} MB)",
            "read_timeout": "读取光盘 {name} 超时（已停滞 {timeout} 秒）。正在终止进程。",
            "ffmpeg_err": "FFmpeg 处理错误：{name}",
            "exc": "异常：{err}",
            "stop_sum": "提取被用户停止。已完成 {success} 个文件。",
            "done_ok": "所有 {success} 个文件提取成功！输出至：{folder}",
            "open_err": "无法打开输出文件夹：{err}",
            "done_err": "完成，共有 {errors} 个错误。{success} 个文件保存至 {folder}",
            "cleared": "光盘信息已清除。",
            "cleared_all": "已清空影片列表与进度。",
            "eject_win32": "光盘已从驱动器 {drive} 弹出：(DeviceIoControl)",
            "eject_win32_fail": "DeviceIoControl 弹出失败：{err}",
            "eject_ps": "弹出命令已发送至驱动器 {drive}：(PowerShell)",
            "eject_ps_fail": "PowerShell 弹出也失败：{err}",
            "batch_renamed": "已批量重命名 {total} 个文件。",
            "ffmpeg_dl": "未找到 FFmpeg！请从 https://ffmpeg.org 下载并添加到 PATH。",
            "ffmpeg_hint": "或者将 ffmpeg.exe 放在本脚本旁边的 'ffmpeg/bin' 子文件夹中。",
            "timeline_done": "已生成章节时间轴文件：{name}",
            "timeline_no_chapters": "章节时间轴跳过（{name}）：输出文件中未找到章节元数据。",
            "timeline_ffprobe_missing": "跳过生成章节时间轴：未找到 FFprobe 可执行文件。",
            "timeline_failed": "生成章节时间轴失败（{name}）：{err}",
        }
    },
    "zh_TW": {
        "header": {
                "title": "Disc Ripper Pro",
                "console": "📋  執行記錄",
                "clear_all": "🗑  清空",
                "clear_all_tip": "清空已載入的影片列表與進度",
                "about": "⚙  設定",
                "batch_rename": "✏  批次重新命名",
                "eject_disc": "⏏  退出光碟",
                "no_disc": "⏺  未偵測到光碟",
                "vcd_on": "💿  VCD 位於 {drive}:",
                "dvd_on": "📀  DVD 位於 {drive}:",
                "disc_on": "💿  光碟位於 {drive}:",
                "drive_no_disc": "💿  光碟機 {drive}: (無光碟)",
                "drive_no_vcd": "💿  光碟機 {drive}: (無光碟)"
        },
        "drive": {
                "detect_vcd": "偵測到 VCD！",
                "detect_dvd": "偵測到 DVD-Video！",
                "detect_disc": "偵測到光碟！",
                "detecting": "正在偵測光碟機...",
                "detected": "已辨識到光碟機",
                "insert_vcd": "放入 VCD/DVD 光碟\n或點擊瀏覽",
                "insert_disc": "放入 VCD/DVD 光碟\n或點擊瀏覽",
                "folder_selected": "已選取光碟資料夾",
                "drive_label": "光碟機  {drive}:"
        },
        "source": {
                "title": "來源",
                "browse": "瀏覽資料夾",
                "scan": "掃描光碟",
                "scan_vcd": "掃描 VCD",
                "scan_dvd": "掃描 DVD"
        },
        "selection": {
                "title": "選取",
                "all": "全選",
                "none": "全部取消選取",
                "count": "已選取 {n} / {total}",
                "mode_title": "完整標題",
                "mode_chapters": "已選章節",
                "count_chapters": "已選取 {n}/{total} 個章節",
                "count_dvd_hierarchical": "已選取 {titles} 個標題 · {chapters} 個章節"
        },
        "format": {
                "title": "輸出格式",
                "video_mode": "🎬  影片",
                "audio_mode": "🎵  僅音訊",
                "both_mode": "🎬+🎵  影片與音訊",
                "video_lbl": "影片格式：",
                "dat_desc": "原始檔案直接複製 (僅限 VCD)",
                "mpg_desc": "MPEG-1/2 (光碟原生串流)",
                "mp4_desc": "H.264 + AAC (廣泛相容)",
                "mov_desc": "QuickTime / Apple 相容",
                "dat_mode_lbl": "DAT 輸出模式：",
                "dat_raw": "原始 .dat (不作變更)",
                "dat_mp4": "重新命名為 .mp4",
                "res_title": "匯出解析度：",
                "res_orig": "原始畫質",
                "res_1080p": "1440×1080 (升級至 1080p, 4:3)",
                "audio_lbl": "音訊格式：",
                "wav_desc": "無損 PCM 音訊",
                "mp3_desc": "高品質壓縮音訊",
                "audio_track_lbl": "DVD 音訊軌道：",
                "target_title_lbl": "目標標題：",
                "no_audio_tracks": "無可用音訊軌道"
        },
        "output": {
                "title": "輸出資料夾",
                "choose": "選擇資料夾",
                "auto_open": "擷取完成後開啟輸出資料夾",
                "dvd_title_folder": "依 DVD 標題建立資料夾",
                "dvd_timeline": "產生章節時間軸檔案 (.txt)"
        },
        "rip": {
                "start": "開始擷取",
                "stop": "停止擷取"
        },
        "content": {
                "title": "影片檔案",
                "badge": "  {n}  ",
                "badge_empty": "偵測到 0 個項目",
                "badge_tracks": "偵測到 {n} 個軌道",
                "badge_titles": "偵測到 {n} 個標題",
                "empty_title": "未載入光碟",
                "empty_sub": "放入光碟或瀏覽至 VCD/DVD 資料夾，然後點擊「掃描光碟」",
                "scan_prog_folder": "正在掃描資料夾：{name}...",
                "scan_prog_read": "正在讀取中繼資料 ({idx}/{total})：{name}",
                "scan_prog_dvd": "正在掃描 DVD 架構：{name}...",
                "scan_prog_titles": "正在尋找 DVD 標題 ({idx}/{total})：{name}",
                "rip_prog_proc": "正在處理 ({idx}/{total})：{name}",
                "rip_prog_stop": "已停止：成功儲存 {success}/{total} 個檔案",
                "rip_prog_done": "已完成：成功擷取 {success}/{total} 個檔案"
        },
        "console": {
                "title": "  📋  執行記錄",
                "clear": "清除"
        },
        "about": {
                "title": "設定",
                "app": "應用程式",
                "version": "版本",
                "dev": "開發者",
                "cat_appearance": "外觀與顯示",
                "cat_processing": "處理設定",
                "cat_diagnostics": "診斷與系統資訊",
                "ffmpeg": "FFmpeg 狀態",
                "ffmpeg_path": "FFmpeg 路徑",
                "handbrake": "HandBrakeCLI 狀態",
                "handbrake_path": "HandBrakeCLI 路徑",
                "copy_path": "複製",
                "copied": "已複製！",
                "copy_ffmpeg_tip": "複製完整 FFmpeg 路徑至剪貼簿",
                "copy_hb_tip": "複製完整 HandBrakeCLI 路徑至剪貼簿",
                "ready": "✓  就緒",
                "not_found": "✗  未找到",
                "license": "MIT 授權條款",
                "close": "關閉"
        },
        "language": {
                "title": "語言",
                "en": "English",
                "zh": "中文",
                "zh_cn": "簡體中文",
                "zh_tw": "繁體中文"
        },
        "appearance": {
                "title": "外觀",
                "system": "跟隨系統",
                "light": "淺色模式",
                "dark": "深色模式"
        },
        "scale": {
                "title": "介面縮放",
                "100": "100%",
                "125": "125%",
                "150": "150%",
                "100%": "100%",
                "125%": "125%",
                "150%": "150%"
        },
        "priority": {
                "title": "程序優先順序",
                "low": "低",
                "medium": "中",
                "high": "高"
        },
        "fps_mode": {
                "title": "影格率模式",
                "passthrough": "Passthrough",
                "cfr": "CFR"
        },
        "dvd_scanner": {
                "title": "DVD 掃描引擎",
                "auto": "自動",
                "direct_ifo": "Direct IFO",
                "handbrake": "HandBrake",
                "auto_tip": "自動模式：優先使用 HandBrake 掃描，必要時自動切換至 Direct IFO",
                "direct_ifo_tip": "Direct IFO 安全模式：完全略過 HandBrake 及底層 SCSI SPTI 指令",
                "handbrake_tip": "僅 HandBrake 模式：僅使用 HandBrakeCLI 掃描"
        },
        "notification": {
                "title": "系統通知",
                "enabled": "開啟",
                "disabled": "關閉",
                "tip": "轉換完成後在 Windows 發送系統提示通知",
                "rip_done": "轉換完成",
                "rip_done_with_err": "轉換完成 (存在失敗)",
                "rip_stopped": "轉換已停止",
                "rip_timeout": "轉換逾時",
                "rip_stats": "✓ 成功: {success} 個  |  ✗ 失敗: {errors} 個  (共 {total} 個)"
        },
        "diagnostics": {
            "title": "診斷與安全",
            "diag_scan": "診斷模式掃描",
            "export_zip": "匯出記錄檔 (.zip)",
            "stale_detected_title": "偵測到上次 DVD 掃描異常中斷",
            "stale_detected_body": "Disc Ripper Pro 偵測到上次 DVD 掃描異常終止（可能因 Windows 系統重新啟動、藍底白字當機 BSOD 或光碟機驅動程式錯誤所致）。",
            "stale_export_prompt": "是否立即匯出診斷記錄套件（ZIP）以利疑難排解？",
            "save_dialog_title": "匯出診斷記錄套件",
            "export_success_title": "匯出完成",
            "export_success_msg": "診斷記錄套件已成功匯出至：\n\n{path}",
            "export_fail_title": "匯出失敗",
            "diag_scan_started": "已啟動 DVD 診斷掃描：{path}（模式：{mode}）",
            "diag_scan_done": "DVD 診斷掃描已完成，記錄已寫入磁碟。",
            "health_check": "光碟健康檢查",
            "export_report": "匯出診斷報告 (.txt)",
            "health_check_tip": "在轉檔前評估光碟可讀性、結構完整性與章節邊界",
            "select_mode_title": "選取診斷模式",
            "mode_quick": "快速檢查 (預設)",
            "mode_quick_desc": "快速驗證光碟結構、導覽表與章節時間邊界 (~2-5秒)",
            "mode_thorough": "完整讀取測試 (選用)",
            "mode_thorough_desc": "跨媒體檔案執行多點資料讀取測試以偵測損壞磁區 (~15-45秒)",
            "start_check": "開始健康檢查",
            "results_title": "光碟健康檢查結果",
            "status_good": "狀態良好",
            "status_warnings": "發現警告",
            "status_problems": "偵測到問題",
            "status_inconclusive": "無法判定",
            "summary": "摘要說明",
            "checks_performed": "執行檢查項目",
            "findings": "診斷發現",
            "recommended_steps": "建議後續動作",
            "proceed_rip": "繼續前往轉檔",
            "export_txt_btn": "匯出報告 (.txt)",
            "no_findings": "在本次測試範圍內未發現任何錯誤或警告。",
            "save_txt_dialog": "儲存診斷報告 (.txt)",
            "export_txt_success_title": "報告匯出完成",
            "export_txt_success_msg": "診斷報告已成功匯出至：\n\n{path}",
            "cancel": "取消",
            "close": "關閉",
            "running_check": "正在執行光碟診斷...",
            "select_disc_folder": "選取健康檢查專用的 DVD/VCD 光碟機或資料夾",
            "no_disc_selected": "請先放入或選取光碟。",
            "confirm_rip_warn": "健康檢查過程中發現警告：\n\n{warnings}\n\n您仍要繼續前往轉檔畫面嗎？",
            "confirm_rip_problems": "健康檢查偵測到可能影響轉檔的嚴重問題：\n\n{problems}\n\n轉檔可能失敗或產生損毀檔案。您確定仍要繼續嗎？",
            "confirm_rip_inconclusive": "光碟健康檢查未完成或無法判定。\n\n您仍要繼續前往轉檔畫面嗎？",
        },
        "rename": {
                "title": "重新命名檔案",
                "inst": "輸出檔案名稱 (不含副檔名)：",
                "chapter_title": "重新命名章節",
                "chapter_inst": "輸出章節名稱 (不含副檔名)：",
                "apply": "套用",
                "cancel": "取消"
        },
        "batch": {
                "title": "批次重新命名",
                "header": "批次重新命名檔案",
                "inst": "在下方編輯輸出檔案名稱 (不含副檔名)：",
                "track": "軌道 {n}:",
                "title_item": "標題 {n}:",
                "chapter_item": "章節 {n}:",
                "tag_title": "[標題]",
                "tag_chapter": "[章節]",
                "tag_track": "[軌道]",
                "live_preview": "預覽：",
                "apply_all": "全部套用",
                "cancel": "取消",
                "no_files_title": "沒有檔案",
                "no_files_msg": "沒有可重新命名的檔案。請先掃描光碟。",
                "seq_enable": "啟用流水序號",
                "seq_base": "基本名稱：",
                "seq_start": "起始序號：",
                "seq_suffix": "後置文字：",
                "seq_preview": "預覽："
        },
        "messageboxes": {
                "no_source_title": "未指定來源",
                "no_source_msg": "請先放入 VCD/DVD 或瀏覽至光碟資料夾。",
                "invalid_path_title": "路徑無效",
                "invalid_path_msg": "路徑不存在：\n{path}",
                "no_files_title": "找不到檔案",
                "no_files_msg": "找不到有效的 VCD 影片檔案 (.DAT) 或 DVD 標題。\n請確認已選取 VCD 或 DVD 光碟/資料夾的根目錄。",
                "ffmpeg_req_title": "找不到 FFmpeg",
                "ffmpeg_req_msg": "音訊擷取、DVD 轉換與影片編碼需要 FFmpeg。\n\n請從 https://ffmpeg.org/download.html 下載，並確認\nffmpeg.exe 位於您的 PATH 環境變數中，或與本程式同層級的 'ffmpeg/bin' 資料夾中。\n\n提示：在 VCD 上選取 'DAT' 影片格式可直接複製原始檔案，無需使用 FFmpeg。",
                "no_sel_title": "未選取項目",
                "no_sel_msg": "未選取任何影片。要擷取所有影片嗎？",
                "no_sel_chaps_msg": "未選取任何章節。要擷取所有章節嗎？",
                "no_vid_title": "沒有影片",
                "no_vid_msg": "請先掃描光碟。",
                "stop_title": "工作已停止",
                "stop_msg": "擷取工作已被使用者停止。\n\n已將 {success} 部影片儲存至：\n{folder}",
                "eject_title": "退出光碟？",
                "eject_msg": "已成功擷取 {success} 個檔案！\n\n是否立即退出光碟？",
                "err_title": "完成但發生錯誤",
                "err_msg": "已成功擷取 {success} 個檔案。\n有 {errors} 個檔案發生錯誤 — 請查看執行記錄。",
                "no_drive_title": "找不到光碟機",
                "no_drive_msg": "未偵測到任何光碟機。",
                "eject_fail_title": "退出失敗",
                "eject_fail_msg": "無法退出光碟機 {drive}:\n{err}",
                "ejecting": "正在從光碟機 {drive} 退出光碟:...",
                "unsupported_disc_title": "不支援的光碟格式",
                "unsupported_disc_msg": "偵測到非 VCD 或 DVD-Video 光碟（如音樂 CD 或藍光光碟）。Disc Ripper Pro 僅支援 VCD 與標準 DVD-Video 光碟擷取與轉換。",
                "timeout_title": "光碟讀取逾時",
                "timeout_msg": "因光碟嚴重刮損或壞軌導致讀取逾時，已停止擷取。已為您保留已完成擷取的影片片段。",
                "dvd_encrypted_title": "加密或受保護的 DVD",
                "dvd_encrypted_msg": "此 DVD 光碟具有加密或版權保護 (CSS)。Disc Ripper Pro 不會繞過版權保護，僅支援未加密的標準 DVD-Video 光碟。",
                "btn_ok": "確定",
                "btn_eject": "退出光碟",
                "eject_busy_msg": "目前正在進行擷取。您確定要停止擷取並退出光碟嗎？"
        },
        "log": {
                "non_vcd_blocked": "在光碟機 {drive} 偵測到光碟，類型: {type}，已攔截處理流程。",
                "unsupported_blocked": "在 {drive} 偵測到光碟，類型: {type}。並非有效的 VCD 或 DVD-Video。",
                "vcd_auto": "已自動偵測到 VCD 光碟於 {drive}",
                "dvd_auto": "已自動偵測到 DVD-Video 光碟於 {drive}",
                "vcd_found": "在 {folder} 找到 VCD 架構",
                "dvd_found": "在 {folder} 找到 DVD-Video 架構",
                "vcd_not_std": "所選資料夾可能不是標準 VCD (未找到 .DAT 檔案)。仍將繼續掃描...",
                "scan_dir": "正在掃描 {path} …",
                "no_vid": "在所選路徑中未找到影片軌道或標題。",
                "found_files": "找到 {total} 個檔案。正在讀取中繼資料…",
                "loaded": "已從 VCD 載入 {total} 個影片。已全選。",
                "dvd_loaded": "已從 DVD-Video 載入 {total} 個標題。已全選。",
                "out_set": "輸出資料夾已設定為：{folder}",
                "cancel_req": "使用者要求取消… 正在停止處理程序。",
                "start_ext": "開始擷取 {total} 個檔案 → {fmt} 格式…",
                "start_chaps": "開始擷取 {total} 個章節 → {fmt} 格式…",
                "extracting": "正在擷取：{name} → {out}",
                "raw_dat_ok": "✓  已擷取原始 DAT → 儲存為：{name}  ({size} MB)",
                "copy_err": "直接複製錯誤：{err}",
                "saved_ok": "✓  已儲存：{name}  ({size} MB)",
                "saved_partial": "⚠  已保留部分影片片段：{name}  ({size} MB)",
                "read_timeout": "讀取光碟 {name} 逾時（已停滯 {timeout} 秒）。正在終止處理程序。",
                "ffmpeg_err": "FFmpeg 處理錯誤：{name}",
                "exc": "發生例外狀況：{err}",
                "stop_sum": "使用者已停止擷取。已完成 {success} 個檔案。",
                "done_ok": "所有 {success} 個檔案皆已成功擷取！輸出至：{folder}",
                "open_err": "無法開啟輸出資料夾：{err}",
                "done_err": "處理完成，共發生 {errors} 個錯誤。已將 {success} 個檔案儲存至 {folder}",
                "cleared": "光碟資訊已清除。",
                "cleared_all": "已清除影片列表與進度。",
                "eject_win32": "光碟已從光碟機 {drive}: 退出 (DeviceIoControl)",
                "eject_win32_fail": "DeviceIoControl 退出失敗：{err}",
                "eject_ps": "退出命令已傳送至光碟機 {drive}: (PowerShell)",
                "eject_ps_fail": "PowerShell 退出亦失敗：{err}",
                "batch_renamed": "已批次重新命名 {total} 個檔案。",
                "ffmpeg_dl": "找不到 FFmpeg！請從 https://ffmpeg.org 下載並新增至 PATH。",
                "ffmpeg_hint": "或將 ffmpeg.exe 放置於本程式旁的 'ffmpeg/bin' 子資料夾中。",
                "timeline_done": "已產生章節時間軸檔案：{name}",
                "timeline_no_chapters": "章節時間軸跳過（{name}）：輸出檔案中未找到章節中繼資料。",
                "timeline_ffprobe_missing": "略過產生章節時間軸：找不到 FFprobe 執行檔。",
                "timeline_failed": "產生章節時間軸失敗（{name}）：{err}"
        }
}
}
TRANSLATIONS["zh-CN"] = TRANSLATIONS["zh_CN"]
TRANSLATIONS["zh-TW"] = TRANSLATIONS["zh_TW"]

class I18n:
    def __init__(self):
        self.lang = "en"
        self.theme = "system"
        self.scale = "100%"
        self.priority = "High"
        self.fps_mode = "Passthrough"
        self.dvd_scanner = "auto"
        self.notification = True
        self._refresh_cb = None
        self._theme_cb = None
        self._scale_cb = None
        self._priority_cb = None
        self._fps_mode_cb = None
        self._dvd_scanner_cb = None
        self._load_config()

    @staticmethod
    def _get_config_path(*args, for_write=False, **kwargs):
        if args and isinstance(args[0], bool):
            for_write = args[0]
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        portable_cfg = os.path.join(exe_dir, "config.json")
        local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        appdata_dir = os.path.join(local_appdata, "Disc Ripper Pro")
        appdata_cfg = os.path.join(appdata_dir, "config.json")

        exe_dir_writable = False
        try:
            if os.path.exists(portable_cfg):
                with open(portable_cfg, "a"):
                    pass
                exe_dir_writable = True
            else:
                test_file = os.path.join(exe_dir, f".write_test_{os.getpid()}")
                with open(test_file, "w") as tf:
                    tf.write("1")
                os.remove(test_file)
                exe_dir_writable = True
        except Exception:
            exe_dir_writable = False

        if exe_dir_writable:
            # Portable mode: isolated alongside executable
            return portable_cfg
        else:
            # Non-writable directory (e.g. Program Files installation)
            if not for_write:
                # User config in AppData always takes precedence over read-only Program Files template
                if os.path.exists(appdata_cfg):
                    return appdata_cfg
                if os.path.exists(portable_cfg):
                    return portable_cfg
                return appdata_cfg
            else:
                try:
                    os.makedirs(appdata_dir, exist_ok=True)
                except Exception:
                    pass
                return appdata_cfg

    def _load_config(self):
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            meipass = getattr(sys, '_MEIPASS', None)
            # Allow external json translation files (en.json, zh-CN.json, zh-TW.json) to override/extend translations
            for lang_code, fname in (("en", "en.json"), ("zh_CN", "zh-CN.json"), ("zh_CN", "zh_CN.json"), ("zh_TW", "zh-TW.json"), ("zh_TW", "zh_TW.json")):
                l_path = os.path.join(exe_dir, fname)
                if not os.path.exists(l_path) and meipass:
                    l_path = os.path.join(meipass, fname)
                if os.path.exists(l_path):
                    try:
                        with open(l_path, "r", encoding="utf-8") as lf:
                            loaded = json.load(lf)
                            if lang_code in TRANSLATIONS and isinstance(loaded, dict):
                                for section, s_data in loaded.items():
                                    if isinstance(s_data, dict) and section in TRANSLATIONS[lang_code]:
                                        TRANSLATIONS[lang_code][section].update(s_data)
                                    else:
                                        TRANSLATIONS[lang_code][section] = s_data
                            elif isinstance(loaded, dict):
                                TRANSLATIONS[lang_code] = loaded
                    except Exception:
                        pass
            if "zh_CN" in TRANSLATIONS:
                TRANSLATIONS["zh-CN"] = TRANSLATIONS["zh_CN"]
            if "zh_TW" in TRANSLATIONS:
                TRANSLATIONS["zh-TW"] = TRANSLATIONS["zh_TW"]

            cfg_path = self._get_config_path(for_write=False)
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        data = {}
                    if "lang" in data:
                        l = str(data.get("lang", "")).strip()
                        if l.lower() in ("zh-cn", "zh_cn", "cn", "zh"):
                            l = "zh_CN"
                        elif l.lower() in ("zh-tw", "zh_tw", "tw", "hk"):
                            l = "zh_TW"
                        elif l.lower() in ("en", "en_us", "en-us", "en_gb", "en-gb"):
                            l = "en"
                        if l in TRANSLATIONS:
                            self.lang = l
                    if "theme" in data and data["theme"] in ("system", "light", "dark"):
                        self.theme = data["theme"]
                    if "scale" in data:
                        s_val = str(data.get("scale", "")).strip()
                        if s_val in ("1.0", "1", "100"):
                            s_val = "100%"
                        elif s_val in ("1.25", "125"):
                            s_val = "125%"
                        elif s_val in ("1.5", "1.50", "150"):
                            s_val = "150%"
                        if s_val in ("100%", "125%", "150%"):
                            self.scale = s_val
                    if "priority" in data and data["priority"] in ("Low", "Medium", "High"):
                        self.priority = data["priority"]
                    if "fps_mode" in data and data["fps_mode"] in ("CFR", "Passthrough"):
                        self.fps_mode = data["fps_mode"]
                    if "dvd_scanner" in data and data["dvd_scanner"] in ("auto", "handbrake", "direct_ifo"):
                        self.dvd_scanner = data["dvd_scanner"]
                    if "notification" in data:
                        self.notification = bool(data["notification"])
        except Exception:
            pass

    def _save_config(self):
        try:
            cfg_path = self._get_config_path(for_write=True)
            parent_dir = os.path.dirname(os.path.abspath(cfg_path))
            os.makedirs(parent_dir, exist_ok=True)
            data = {}
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            data = loaded
                except Exception:
                    data = {}
            data["lang"] = self.lang
            data["theme"] = self.theme
            data["scale"] = self.scale
            data["priority"] = self.priority
            data["fps_mode"] = self.fps_mode
            data["dvd_scanner"] = getattr(self, "dvd_scanner", "auto")
            data["notification"] = bool(getattr(self, "notification", True))

            tmp_path = cfg_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if os.path.exists(cfg_path):
                os.replace(tmp_path, cfg_path)
            else:
                os.rename(tmp_path, cfg_path)
        except Exception:
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def t(self, key, **kwargs):
        keys = key.split('.')
        val = TRANSLATIONS.get(self.lang, TRANSLATIONS.get("en", {}))
        found = True
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                found = False
                break
        if not found:
            val = TRANSLATIONS.get("en", {})
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return key
        if kwargs and isinstance(val, str):
            try:
                return val.format(**kwargs)
            except Exception:
                pass
        return val

    def switch(self, lang):
        if lang == "zh-TW":
            lang = "zh_TW"
        elif lang == "zh-CN":
            lang = "zh_CN"
        if lang in TRANSLATIONS:
            self.lang = lang
            self._save_config()
            if self._refresh_cb:
                try:
                    self._refresh_cb()
                except Exception:
                    pass

    def switch_theme(self, theme):
        if theme in ("system", "light", "dark"):
            self.theme = theme
            self._save_config()
            effective = self.get_effective_theme()
            apply_theme_palette(effective)
            if self._theme_cb:
                self._theme_cb()

    def get_scale_factor(self):
        factors = {"100%": 1.0, "125%": 1.25, "150%": 1.5}
        return factors.get(self.scale, 1.0)

    def switch_scale(self, scale):
        if scale in ("100%", "125%", "150%"):
            self.scale = scale
            self._save_config()
            if self._scale_cb:
                self._scale_cb(self.get_scale_factor())

    def get_effective_theme(self):
        if self.theme == "system":
            return get_windows_theme()
        return self.theme

    def set_refresh_callback(self, cb):
        self._refresh_cb = cb

    def set_theme_callback(self, cb):
        self._theme_cb = cb

    def set_scale_callback(self, cb):
        self._scale_cb = cb

    def switch_priority(self, priority):
        if priority in ("Low", "Medium", "High"):
            self.priority = priority
            self._save_config()
            if self._priority_cb:
                try:
                    self._priority_cb(self.priority)
                except Exception:
                    pass

    def set_priority_callback(self, cb):
        self._priority_cb = cb

    def switch_fps_mode(self, mode):
        if mode in ("CFR", "Passthrough"):
            self.fps_mode = mode
            self._save_config()
            if self._fps_mode_cb:
                try:
                    self._fps_mode_cb(self.fps_mode)
                except Exception:
                    pass

    def set_fps_mode_callback(self, cb):
        self._fps_mode_cb = cb

    def switch_dvd_scanner(self, scanner):
        if scanner in ("auto", "handbrake", "direct_ifo"):
            self.dvd_scanner = scanner
            self._save_config()
            if hasattr(self, "_dvd_scanner_cb") and self._dvd_scanner_cb:
                try:
                    self._dvd_scanner_cb(self.dvd_scanner)
                except Exception:
                    pass

    def set_dvd_scanner_callback(self, cb):
        self._dvd_scanner_cb = cb

    def switch_notification(self, enabled):
        self.notification = bool(enabled)
        self._save_config()
        if hasattr(self, "_notification_cb") and self._notification_cb:
            try:
                self._notification_cb(self.notification)
            except Exception:
                pass

    def set_notification_callback(self, cb):
        self._notification_cb = cb

i18n = I18n()
apply_theme_palette(i18n.get_effective_theme())

def t(key, **kwargs):
    return i18n.t(key, **kwargs)

_APP_ICON_PHOTO = None
_APP_ICON_ICO_PATH = None
_HEADER_ICONS = {}
_PIL_COMPACT_DISC_BASE_IMG = None

def _find_asset_path(filename):
    """Find path to an asset file in source or frozen PyInstaller environment."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, filename))
    base_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else base_dir
    candidates.append(os.path.join(exe_dir, filename))
    candidates.append(os.path.join(exe_dir, "_internal", filename))
    candidates.append(os.path.join(base_dir, filename))
    candidates.append(os.path.abspath(filename))
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None

def get_header_icon(size=64):
    size = int(round(size))
    if size in _HEADER_ICONS:
        try:
            icon = _HEADER_ICONS[size]
            if icon and tk._default_root:
                if getattr(icon, "tk", None) != getattr(tk._default_root, "tk", None):
                    _HEADER_ICONS.pop(size, None)
                else:
                    tk._default_root.tk.call("image", "type", str(icon))
            elif not tk._default_root:
                _HEADER_ICONS.pop(size, None)
        except Exception:
            _HEADER_ICONS.pop(size, None)
    if size not in _HEADER_ICONS:
        try:
            from PIL import Image, ImageTk
            global _PIL_COMPACT_DISC_BASE_IMG
            if _PIL_COMPACT_DISC_BASE_IMG is None:
                png_path = _find_asset_path("CompactDisc.png")
                if png_path and os.path.isfile(png_path):
                    _PIL_COMPACT_DISC_BASE_IMG = Image.open(png_path).convert("RGBA")
            if _PIL_COMPACT_DISC_BASE_IMG is not None:
                resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                img = _PIL_COMPACT_DISC_BASE_IMG.resize((size, size), resample_filter)
                _HEADER_ICONS[size] = ImageTk.PhotoImage(img)
            else:
                _HEADER_ICONS[size] = False
        except Exception:
            _HEADER_ICONS[size] = False
    return _HEADER_ICONS.get(size) if _HEADER_ICONS.get(size) else None

def _get_header_icon_64():
    return get_header_icon(scale_val(64))

def set_window_icon(window):
    """Set app icon on a Tk or Toplevel window using the multi-resolution CompactDisc.ico,
    PNG iconphoto, and Win32 WM_SETICON + SetClassLongPtrW to completely replace the Tk feather icon."""
    global _APP_ICON_PHOTO, _APP_ICON_ICO_PATH
    if window is None:
        return

    # Check if cached _APP_ICON_PHOTO belongs to an active Tk interp
    if _APP_ICON_PHOTO:
        try:
            _APP_ICON_PHOTO.width()
        except Exception:
            _APP_ICON_PHOTO = None

    # Ensure window is mapped and has an HWND
    try:
        window.update_idletasks()
    except Exception:
        pass

    # Discover CompactDisc.ico
    if _APP_ICON_ICO_PATH is None:
        p = _find_asset_path("CompactDisc.ico")
        _APP_ICON_ICO_PATH = p if p else False

    # Discover CompactDisc.png
    if _APP_ICON_PHOTO is None:
        png_path = _find_asset_path("CompactDisc.png")
        if png_path and os.path.isfile(png_path):
            try:
                from PIL import Image, ImageTk
                _APP_ICON_PHOTO = ImageTk.PhotoImage(Image.open(png_path))
            except Exception:
                _APP_ICON_PHOTO = False
        else:
            _APP_ICON_PHOTO = False

    # 1. Tkinter iconbitmap - sets on THIS window and sets default for future toplevels
    if _APP_ICON_ICO_PATH and os.path.isfile(_APP_ICON_ICO_PATH):
        try:
            window.iconbitmap(_APP_ICON_ICO_PATH)
        except Exception:
            pass
        try:
            window.iconbitmap(default=_APP_ICON_ICO_PATH)
        except Exception:
            pass

    # 2. Tkinter iconphoto (replaces Tk default feather icon across interpreter)
    if _APP_ICON_PHOTO:
        try:
            window.iconphoto(True, _APP_ICON_PHOTO)
            window._icon_photo_ref = _APP_ICON_PHOTO
        except Exception:
            pass

    # 3. Windows Native Win32 API enforcement (DWM title bar & taskbar)
    if sys.platform == "win32":
        try:
            win_id = window.winfo_id()
            top_hwnd = ctypes.windll.user32.GetAncestor(win_id, 2) or win_id

            # Title bar dark mode sync
            set_window_dark_mode(top_hwnd, i18n.get_effective_theme() == "dark")

            if _APP_ICON_ICO_PATH and os.path.isfile(_APP_ICON_ICO_PATH):
                IMAGE_ICON = 1
                LR_LOADFROMFILE = 0x00000010
                LR_DEFAULTSIZE = 0x00000040
                WM_SETICON = 0x0080
                ICON_SMALL = 0
                ICON_BIG = 1
                GCLP_HICON = -14
                GCLP_HICONSM = -34

                # Get Windows system metric icon sizes (typically 16x16 and 32x32, or scaled with DPI)
                cx_sm = ctypes.windll.user32.GetSystemMetrics(49) or 16
                cy_sm = ctypes.windll.user32.GetSystemMetrics(50) or 16
                cx_lg = ctypes.windll.user32.GetSystemMetrics(11) or 32
                cy_lg = ctypes.windll.user32.GetSystemMetrics(12) or 32

                hicon_sm = ctypes.windll.user32.LoadImageW(
                    None, _APP_ICON_ICO_PATH, IMAGE_ICON, cx_sm, cy_sm,
                    LR_LOADFROMFILE
                )
                hicon_big = ctypes.windll.user32.LoadImageW(
                    None, _APP_ICON_ICO_PATH, IMAGE_ICON, cx_lg, cy_lg,
                    LR_LOADFROMFILE
                )
                if not hicon_big:
                    hicon_big = ctypes.windll.user32.LoadImageW(
                        None, _APP_ICON_ICO_PATH, IMAGE_ICON, 0, 0,
                        LR_LOADFROMFILE | LR_DEFAULTSIZE
                    )

                for h in (top_hwnd, win_id):
                    if not h:
                        continue
                    if hicon_sm:
                        ctypes.windll.user32.SendMessageW(h, WM_SETICON, ICON_SMALL, hicon_sm)
                        try:
                            ctypes.windll.user32.SetClassLongPtrW(h, GCLP_HICONSM, hicon_sm)
                        except Exception:
                            try:
                                ctypes.windll.user32.SetClassLongW(h, GCLP_HICONSM, hicon_sm)
                            except Exception:
                                pass
                    if hicon_big:
                        ctypes.windll.user32.SendMessageW(h, WM_SETICON, ICON_BIG, hicon_big)
                        try:
                            ctypes.windll.user32.SetClassLongPtrW(h, GCLP_HICON, hicon_big)
                        except Exception:
                            try:
                                ctypes.windll.user32.SetClassLongW(h, GCLP_HICON, hicon_big)
                            except Exception:
                                pass
        except Exception:
            pass


def _register_app_user_model_id(aumid: str, display_name: str, icon_path: Optional[str] = None) -> bool:
    """Register AppUserModelID in HKCU so Windows Toast notifications display the app name and icon properly."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key_path = f"Software\\Classes\\AppUserModelId\\{aumid}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
            if icon_path and os.path.exists(icon_path):
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, os.path.abspath(icon_path))
                winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "0")
        return True
    except Exception:
        return False


def _show_balloon_fallback(parent_hwnd: int, title: str, text: str, icon_ico: Optional[str] = None):
    """Fallback notification using Windows Shell_NotifyIconW balloon tooltip."""
    if sys.platform != "win32":
        return
    try:
        from ctypes import wintypes
        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIF_ICON = 0x00000002
        NIF_TIP = 0x00000004
        NIF_INFO = 0x00000010
        NIIF_INFO = 0x00000001
        NIIF_USER = 0x00000004
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
            ]

        h_icon = 0
        if icon_ico and os.path.isfile(icon_ico):
            try:
                h_icon = ctypes.windll.user32.LoadImageW(
                    None, icon_ico, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
            except Exception:
                h_icon = 0

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = parent_hwnd or 0
        nid.uID = 2024
        nid.uFlags = NIF_ICON | NIF_TIP | NIF_INFO
        nid.hIcon = h_icon
        nid.szTip = title[:127]
        nid.szInfo = text[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_USER if h_icon else NIIF_INFO
        nid.uTimeoutOrVersion = 5000

        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        time.sleep(6)
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        if h_icon:
            ctypes.windll.user32.DestroyIcon(h_icon)
    except Exception:
        pass


def _send_windows_rip_notification(
    app_name: str,
    total: int,
    success: int,
    errors: int,
    out_folder: str = "",
    cancelled: bool = False,
    timed_out: bool = False,
    lang: str = "en",
    parent_hwnd: int = 0
):
    """
    Sends a rich Windows Toast notification (with fallback to Shell_NotifyIconW balloon)
    summarizing the ripping results: software name, app icon, succeeded count, failed count,
    total count, and output folder.
    Runs asynchronously in a background daemon thread to never block Tkinter UI thread.
    """
    def _worker():
        if sys.platform != "win32":
            return

        icon_ico = _find_asset_path("CompactDisc.ico")
        icon_png = _find_asset_path("CompactDisc.png")
        if not icon_png:
            icon_png = icon_ico

        _register_app_user_model_id(APP_USER_MODEL_ID, app_name, icon_ico)

        # Localized status & statistics: respect lang argument if provided, fallback to i18n.lang or en
        target_lang = lang or getattr(i18n, "lang", "en")
        if target_lang in ("zh-CN", "cn", "zh"):
            target_lang = "zh_CN"
        elif target_lang in ("zh-TW", "tw", "hk"):
            target_lang = "zh_TW"

        def _get_notif_text(sub_key, **kwargs):
            val = None
            if target_lang in TRANSLATIONS and "notification" in TRANSLATIONS[target_lang]:
                val = TRANSLATIONS[target_lang]["notification"].get(sub_key)
            if not val and "en" in TRANSLATIONS and "notification" in TRANSLATIONS["en"]:
                val = TRANSLATIONS["en"]["notification"].get(sub_key)
            if not val:
                val = t(f'notification.{sub_key}', **kwargs)
            elif kwargs and isinstance(val, str):
                try:
                    val = val.format(**kwargs)
                except Exception:
                    pass
            return val

        # Localized status title
        if timed_out:
            status_text = _get_notif_text('rip_timeout')
        elif cancelled:
            status_text = _get_notif_text('rip_stopped')
        elif errors == 0:
            status_text = _get_notif_text('rip_done')
        else:
            status_text = _get_notif_text('rip_done_with_err')

        # Localized statistics text
        stats_text = _get_notif_text('rip_stats', success=success, errors=errors, total=total)

        toast_sent = False
        # 1. Try Windows 10/11 WinRT Toast Notification via PowerShell
        try:
            import base64
            import xml.sax.saxutils as xml_escape

            icon_path_str = os.path.abspath(icon_png).replace("\\", "/") if icon_png else ""
            img_xml = f'<image placement="appLogoOverride" hint-crop="circle" src="{xml_escape.escape(icon_path_str)}"/>' if icon_path_str else ''

            toast_xml = f'''<toast duration="short">
  <visual>
    <binding template="ToastGeneric">
      {img_xml}
      <text>{xml_escape.escape(app_name)}</text>
      <text>{xml_escape.escape(status_text)}</text>
      <text>{xml_escape.escape(stats_text)}</text>
    </binding>
  </visual>
</toast>'''

            ps_code = f'''
$ProgressPreference = 'SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{toast_xml}
'@)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_USER_MODEL_ID}').Show($toast)
'''
            encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = 0x08000000  # CREATE_NO_WINDOW

            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True,
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
                timeout=8
            )
            if proc.returncode == 0:
                toast_sent = True
        except Exception:
            toast_sent = False

        # 2. Fallback to Shell_NotifyIconW balloon notification if WinRT toast was not sent
        if not toast_sent:
            try:
                _show_balloon_fallback(
                    parent_hwnd=parent_hwnd,
                    title=f"{app_name} - {status_text}",
                    text=stats_text,
                    icon_ico=icon_ico
                )
            except Exception:
                pass

    threading.Thread(target=_worker, name="RipNotificationThread", daemon=True).start()


# ─────────────────────────────────────────────
#  Multi-Monitor & Window Positioning Helpers
# ─────────────────────────────────────────────
if sys.platform == "win32":
    try:
        from ctypes import wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class _POINT(ctypes.Structure):
            _fields_ = [
                ("x", ctypes.c_long),
                ("y", ctypes.c_long),
            ]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", _RECT),
                ("rcWork", _RECT),
                ("dwFlags", wintypes.DWORD),
            ]
    except Exception:
        pass


def get_monitor_work_area(widget_or_hwnd):
    """
    Return (left, top, right, bottom) of the display monitor work area
    (excluding taskbar) containing the given widget or HWND.
    Works seamlessly across multi-monitor configurations (dual screen, triple screen,
    with negative coordinates or right/left/above/below screen placements).
    """
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hwnd = None
            if isinstance(widget_or_hwnd, int):
                hwnd = widget_or_hwnd
            elif hasattr(widget_or_hwnd, "winfo_id"):
                try:
                    win_id = widget_or_hwnd.winfo_id()
                    if win_id:
                        hwnd = user32.GetAncestor(win_id, 2) or win_id
                except Exception:
                    pass

            hmon = None
            if hwnd:
                hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST = 2

            if not hmon and hasattr(widget_or_hwnd, "winfo_rootx"):
                try:
                    px = widget_or_hwnd.winfo_rootx()
                    py = widget_or_hwnd.winfo_rooty()
                    pw = max(1, widget_or_hwnd.winfo_width())
                    ph = max(1, widget_or_hwnd.winfo_height())
                    pt = _POINT(px + pw // 2, py + ph // 2)
                    hmon = user32.MonitorFromPoint(pt, 2)
                except Exception:
                    pass

            if hmon:
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    return (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom)
        except Exception:
            pass

    # Fallback for non-Windows or if API call fails
    try:
        top = widget_or_hwnd.winfo_toplevel() if hasattr(widget_or_hwnd, "winfo_toplevel") else widget_or_hwnd
        rx = top.winfo_rootx()
        ry = top.winfo_rooty()
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        return (rx, ry, rx + sw, ry + sh)
    except Exception:
        return (0, 0, 1920, 1080)


def position_window_on_parent(window, parent=None, width=None, height=None, min_w=None, min_h=None, show=True):
    """
    Position and center a window (e.g. Toplevel dialog) relative to its parent window,
    guaranteeing that in dual-screen / multi-screen setups, the popup ALWAYS appears
    on the exact monitor where the parent/main application is currently located,
    clamped to that monitor's work area (excluding taskbar).
    """
    if window is None:
        return (0, 0, 400, 300)

    if parent is None:
        try:
            parent = window.master
        except Exception:
            pass

    parent_top = None
    if parent:
        try:
            parent_top = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent
        except Exception:
            parent_top = parent

    try:
        window.update_idletasks()
    except Exception:
        pass

    try:
        req_w = window.winfo_reqwidth()
        req_h = window.winfo_reqheight()
    except Exception:
        req_w, req_h = 400, 300

    dw = width if width is not None else req_w
    dh = height if height is not None else req_h
    if min_w is not None:
        dw = max(dw, min_w)
    if min_h is not None:
        dh = max(dh, min_h)

    # Work area of the monitor where the parent window currently resides
    mon_x1, mon_y1, mon_x2, mon_y2 = get_monitor_work_area(parent_top or window)
    mon_w = max(400, mon_x2 - mon_x1)
    mon_h = max(300, mon_y2 - mon_y1)

    # Ensure dialog does not exceed the monitor work area
    dw = min(dw, mon_w - 40)
    dh = min(dh, mon_h - 60)
    if min_w is not None and min_w <= dw:
        dw = max(min_w, dw)
    if min_h is not None and min_h <= dh:
        dh = max(min_h, dh)

    # Center relative to parent
    has_parent_coords = False
    if parent_top and hasattr(parent_top, "winfo_rootx"):
        try:
            parent_top.update_idletasks()
            pw = parent_top.winfo_width()
            ph = parent_top.winfo_height()
            px = parent_top.winfo_rootx()
            py = parent_top.winfo_rooty()
            if pw > 100 and ph > 100:
                has_parent_coords = True
                pcx = px + pw // 2
                pcy = py + ph // 2
        except Exception:
            has_parent_coords = False

    if not has_parent_coords:
        pcx = mon_x1 + mon_w // 2
        pcy = mon_y1 + mon_h // 2

    cx = pcx - dw // 2
    cy = pcy - dh // 2

    # Clamp strictly within the target monitor's work area
    nx = max(mon_x1, min(mon_x2 - dw, cx))
    ny = max(mon_y1, min(mon_y2 - dh, cy))

    try:
        window.geometry(f"{dw}x{dh}+{nx}+{ny}")
    except Exception:
        pass

    if parent_top and hasattr(window, "transient"):
        try:
            window.transient(parent_top)
        except Exception:
            pass

    if show and hasattr(window, "deiconify"):
        try:
            window.deiconify()
        except Exception:
            pass

    return nx, ny, dw, dh




# ─────────────────────────────────────────────
#  FFmpeg / FFprobe discovery
# ─────────────────────────────────────────────
def find_ffmpeg():
    """Return paths to ffmpeg and ffprobe, prioritizing bundled binaries over system PATH / WinGet."""
    return dvd_engine.find_ffmpeg_tools()


# ─────────────────────────────────────────────
#  Process Priority & Watchdog / Kill helpers
# ─────────────────────────────────────────────
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS         = 0x00000040
NORMAL_PRIORITY_CLASS       = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS         = 0x00000080

RIPPING_PRIORITY_MAP = {
    "Low": BELOW_NORMAL_PRIORITY_CLASS,
    "Medium": NORMAL_PRIORITY_CLASS,
    "High": HIGH_PRIORITY_CLASS,
}

DISC_READ_TIMEOUT_SECONDS   = 30.0  # Trigger timeout if no progress for 30s (allows optical drive seeking/layer switches)
GRACEFUL_TERMINATE_TIMEOUT  = 3.0   # Wait up to 3s for graceful exit before force kill

def get_subprocess_kwargs(extra_flags=0):
    """
    Return platform-specific kwargs to completely suppress console window creation
    and hide child process windows on Windows from a GUI / portable application.
    """
    kwargs = {}
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


def get_priority_creation_flag(priority_level="Low"):
    """Return Windows process creation flag corresponding to priority level ('Low', 'Medium', 'High')."""
    return RIPPING_PRIORITY_MAP.get(priority_level, BELOW_NORMAL_PRIORITY_CLASS)


def set_process_priority(proc, priority_level="Low", low_io=True):
    """Set CPU priority and I/O priority for a subprocess on Windows based on selected priority level."""
    if not proc or not hasattr(proc, "_handle"):
        return
    p_flag = RIPPING_PRIORITY_MAP.get(priority_level, BELOW_NORMAL_PRIORITY_CLASS)
    try:
        ctypes.windll.kernel32.SetPriorityClass(int(proc._handle), p_flag)
    except Exception:
        pass
    try:
        # ProcessIoPriority = 0x21 (33). Values: 0 = Very Low, 1 = Low, 2 = Normal
        # For Low priority: if low_io is True, set Low I/O (1), else Normal (2).
        # For Medium and High priority: set Normal I/O (2).
        io_val = 1 if (priority_level == "Low" and low_io) else 2
        io_priority = ctypes.c_ulong(io_val)
        ctypes.windll.ntdll.NtSetInformationProcess(
            int(proc._handle), 33, ctypes.byref(io_priority), ctypes.sizeof(io_priority)
        )
    except Exception:
        pass


def set_low_process_priority(proc, low_io=True):
    """Backward-compatible wrapper for setting Low process priority."""
    set_process_priority(proc, priority_level="Low", low_io=low_io)

def kill_process_tree(proc, force=False):
    """Terminate or force kill a subprocess and its entire process tree on Windows."""
    if not proc or proc.poll() is not None:
        return
    pid = getattr(proc, "pid", None)
    if not force:
        try:
            proc.terminate()
        except Exception:
            pass
    else:
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    **get_subprocess_kwargs()
                )
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass

def terminate_and_kill(proc, graceful_timeout=3.0):
    """Gracefully terminate with SIGTERM/terminate, then force kill after graceful_timeout seconds."""
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:
        pass

    deadline = time.time() + graceful_timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    if proc.poll() is None:
        kill_process_tree(proc, force=True)


# ─────────────────────────────────────────────
#  Single-Instance Lock & Window Activation helpers
# ─────────────────────────────────────────────
SINGLE_INSTANCE_MUTEX_NAME = "Global\\Disc_Ripper_Pro_Unique_Mutex_Lock"
_APP_MUTEX_HANDLE = None

def acquire_single_instance_lock(name=SINGLE_INSTANCE_MUTEX_NAME):
    """
    Attempt to acquire a system-level named mutex lock on Windows.
    Returns True if this is the first/only running instance.
    Returns False if another instance is already running.
    """
    global _APP_MUTEX_HANDLE
    if sys.platform != "win32":
        return True

    ERROR_ALREADY_EXISTS = 183
    ERROR_ACCESS_DENIED = 5

    try:
        # Try Global\ namespace first
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, name)
        err = ctypes.windll.kernel32.GetLastError()

        # Fallback to Local\ namespace if permissions restrict Global\
        if not handle and err == ERROR_ACCESS_DENIED:
            fallback_name = "Local\\" + name.replace("Global\\", "")
            handle = ctypes.windll.kernel32.CreateMutexW(None, True, fallback_name)
            err = ctypes.windll.kernel32.GetLastError()

        if err == ERROR_ALREADY_EXISTS:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
            return False  # An instance is already running

        _APP_MUTEX_HANDLE = handle
        return True
    except Exception:
        # If mutex creation fails for unexpected OS reasons, do not block app startup
        return True

def release_single_instance_lock():
    """Release and close the named mutex handle upon application termination."""
    global _APP_MUTEX_HANDLE
    if _APP_MUTEX_HANDLE:
        try:
            ctypes.windll.kernel32.ReleaseMutex(_APP_MUTEX_HANDLE)
        except Exception:
            pass
        try:
            ctypes.windll.kernel32.CloseHandle(_APP_MUTEX_HANDLE)
        except Exception:
            pass
        _APP_MUTEX_HANDLE = None

atexit.register(release_single_instance_lock)

def find_existing_window():
    """Find the HWND of the currently running Disc Ripper Pro main window."""
    if sys.platform != "win32":
        return None

    user32 = ctypes.windll.user32
    found_hwnd = [None]
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def enum_cb(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            # Match top-level main window whose title starts with APP_NAME ("Disc Ripper Pro")
            if title.startswith(APP_NAME):
                owner = user32.GetWindow(hwnd, 4)  # GW_OWNER = 4
                if owner == 0 or not user32.IsWindow(owner):
                    found_hwnd[0] = hwnd
                    return False
        return True

    proc = WNDENUMPROC(enum_cb)
    # Retry briefly up to 1 second in case the primary window is still being rendered
    for _ in range(10):
        user32.EnumWindows(proc, 0)
        if found_hwnd[0]:
            break
        time.sleep(0.1)

    return found_hwnd[0]

def activate_existing_window(hwnd=None):
    """Restore if minimized and bring existing window to the foreground."""
    if sys.platform != "win32":
        return False

    if not hwnd:
        hwnd = find_existing_window()
    if not hwnd:
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_SHOWNORMAL = 1
    SW_RESTORE = 9

    # If window is minimized (iconic), restore it
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)

    # Bring to foreground reliably using AttachThreadInput
    try:
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_thread_id = kernel32.GetCurrentThreadId()

        if foreground_thread_id != current_thread_id:
            user32.AttachThreadInput(foreground_thread_id, current_thread_id, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(foreground_thread_id, current_thread_id, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    return True


# ─────────────────────────────────────────────
#  VCD / Drive detection helpers
# ─────────────────────────────────────────────
def get_cd_drives():
    """Return list of optical drive letters on Windows."""
    return disc_detector.get_optical_drives()


def detect_disc(path_or_drive):
    """Inspect optical drive or folder and determine media type (VCD, DVD-Video, etc.)."""
    return disc_detector.detect_disc(path_or_drive)


def is_vcd_disc(drive_path):
    """
    Robust check if the given path/drive contains a valid VCD or DVD disc.
    Returns DiscCheckResult.
    """
    return disc_detector.detect_disc(drive_path)


def is_vcd_folder(path):
    """Return True if the given path looks like a VCD structure."""
    res = disc_detector.detect_disc(path)
    return res.is_vcd


def is_dvd_folder(path):
    """Return True if the given path looks like a DVD-Video structure."""
    res = disc_detector.detect_disc(path)
    return res.is_dvd


def find_dat_files(base_path):
    """Return list of unique .DAT file paths from a VCD directory."""
    base = Path(base_path)
    seen = set()
    found = []

    def add_file(p):
        try:
            real_p = p.resolve()
            key = str(real_p).lower()
            if key not in seen and real_p.is_file():
                seen.add(key)
                found.append(str(real_p))
        except Exception:
            pass

    for sub in VCD_DAT_PATHS:
        sub_path = base / sub
        if sub_path.is_dir():
            for p in sorted(sub_path.glob("*.[dD][aA][tT]")):
                add_file(p)
            for p in sorted(sub_path.glob("*.DAT")):
                add_file(p)

    if not found:
        for p in sorted(base.glob("*.[dD][aA][tT]")):
            add_file(p)
        for p in sorted(base.glob("*.DAT")):
            add_file(p)

    return found


def get_subprocess_env():
    """Return a copy of os.environ with UTF-8 encoding configured for child processes."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def sanitize_filename(name: str, fallback: str = "track") -> str:
    """
    Sanitize a filename or track/label string for safe filesystem usage on Windows/cross-platform.
    Removes or replaces invalid characters (< > : " / \\ | ? * and control chars),
    strips trailing dots and spaces, handles reserved Windows names, and falls back if empty.
    """
    if not name or not isinstance(name, str):
        return fallback

    # Replace colons and slashes with clean separators
    s = name.replace(":", " - ").replace("/", "_").replace("\\", "_")
    # Replace Windows illegal characters: < > : " / \ | ? * and ASCII control characters 0x00-0x1F, 0x7F
    s = re.sub(r'[\<\>\:"/\\\|\?\*\x00-\x1f\x7f]', '_', s)
    # Remove unicode replacement char or undefined characters
    s = s.replace("\ufffd", "_")
    # Collapse multiple consecutive underscores or spaces
    s = re.sub(r'_+', '_', s)
    s = re.sub(r'\s+', ' ', s)
    # Strip leading/trailing spaces and dots (forbidden by Windows filesystem)
    s = s.strip(" .")

    if not s:
        return fallback

    # Check for reserved Windows filenames (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    p = Path(s)
    stem_upper = p.stem.upper()
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10))
    }
    if stem_upper in reserved_names:
        s = f"{p.stem}_file{p.suffix}"

    # Avoid overly long filenames (max 200 chars for safety)
    if len(s) > 200:
        s = s[:200].rstrip(" .")

    return s if s else fallback


def sanitize_path(path_str: str) -> str:
    """Sanitize a full file path by normalizing directory and sanitizing filename."""
    if not path_str:
        return ""
    try:
        p = Path(path_str)
        safe_name = sanitize_filename(p.name)
        if p.parent and str(p.parent) != ".":
            return str(p.parent / safe_name)
        return safe_name
    except Exception:
        return path_str


def get_volume_label(path: str) -> str:
    """Return the sanitized volume label of a drive or directory on Windows, or empty string."""
    with disc_detector.suppress_windows_error_dialogs():
        try:
            drive = os.path.splitdrive(os.path.abspath(path))[0]
            if drive:
                if not drive.endswith("\\"):
                    drive += "\\"
                vol_buf = ctypes.create_unicode_buffer(261)
                ok = ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(drive),
                    vol_buf,
                    len(vol_buf),
                    None, None, None, None, 0
                )
                if not ok and ctypes.windll.kernel32.GetLastError() == 1110:
                    # ERROR_MEDIA_CHANGED: retry once
                    ok = ctypes.windll.kernel32.GetVolumeInformationW(
                        ctypes.c_wchar_p(drive),
                        vol_buf,
                        len(vol_buf),
                        None, None, None, None, 0
                    )
                if ok and vol_buf.value:
                    return sanitize_filename(vol_buf.value.strip())
        except Exception:
            pass
    return ""


def probe_video(ffprobe_path, file_path):
    """Use ffprobe to get video metadata. Returns dict or None."""
    try:
        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            file_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=get_subprocess_env(),
            timeout=15,
            **get_subprocess_kwargs(extra_flags=BELOW_NORMAL_PRIORITY_CLASS)
        )
        data = json.loads(result.stdout) if (result.stdout and result.stdout.strip()) else {}
        clean_filename = sanitize_filename(Path(file_path).name, fallback="track")
        info = {
            "path":     file_path,
            "filename": clean_filename,
            "size_mb":  round(os.path.getsize(file_path) / 1024**2, 1),
            "duration": 0,
            "width":    0,
            "height":   0,
            "codec":    "unknown",
            "fps":      "?",
            "bitrate":  "?",
        }
        fmt = data.get("format", {})
        if "duration" in fmt:
            try:
                info["duration"] = float(fmt["duration"])
            except (ValueError, TypeError):
                info["duration"] = 0
        if "bit_rate" in fmt:
            try:
                br = int(fmt["bit_rate"])
                info["bitrate"] = f"{br // 1000} kbps"
            except (ValueError, TypeError):
                pass

        # Extract and sanitize title/metadata tags if available
        tags = fmt.get("tags", {}) if isinstance(fmt, dict) else {}
        for k in ("title", "TITLE", "Title"):
            if k in tags and tags[k]:
                clean_title = sanitize_filename(str(tags[k]).strip())
                if clean_title:
                    info["title"] = clean_title
                    break

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["codec"]  = stream.get("codec_name", "unknown").upper()
                info["width"]  = stream.get("width", 0)
                info["height"] = stream.get("height", 0)
                # fps
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    n, d = fps_str.split("/")
                    info["fps"] = f"{int(n)//int(d)} fps" if int(d) else "?"
                except Exception:
                    info["fps"] = "?"
                break
        return info
    except Exception:
        safe_name = sanitize_filename(Path(file_path).name, fallback="track")
        size = 0.0
        try:
            size = round(os.path.getsize(file_path) / 1024**2, 1)
        except Exception:
            pass
        return {
            "path":     file_path,
            "filename": safe_name,
            "size_mb":  size,
            "duration": 0, "width": 0, "height": 0,
            "codec": "VCD", "fps": "29 fps", "bitrate": "~1150 kbps",
        }


def format_duration(seconds):
    if not seconds:
        return "--:--"
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ─────────────────────────────────────────────
#  Tooltip helper
# ─────────────────────────────────────────────
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self._text  = text
        self.tip    = None
        self._lbl   = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        try:
            widget.bind("<Destroy>", lambda e: self.hide(), add="+")
        except Exception:
            pass

    def get_text(self):
        if callable(self._text):
            try:
                return str(self._text())
            except Exception:
                return ""
        return str(self._text) if self._text is not None else ""

    @property
    def text(self):
        return self.get_text()

    @text.setter
    def text(self, val):
        self._text = val
        if self.tip and self._lbl:
            try:
                self._lbl.configure(text=self.get_text())
            except Exception:
                pass

    def set_text(self, val):
        self.text = val

    def show(self, _=None):
        text = self.get_text()
        if self.tip or not text:
            return
        try:
            x = self.widget.winfo_rootx() + 10
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            self._lbl = tk.Label(
                self.tip, text=text,
                bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                font=FONTS["small"], padx=8, pady=4,
                relief="flat", bd=0
            )
            self._lbl.pack()
        except Exception:
            pass

    def hide(self, _=None):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None
            self._lbl = None

    def update_theme(self):
        if self.tip and self._lbl:
            try:
                self._lbl.configure(
                    bg=COLORS["bg_hover"],
                    fg=COLORS["text_primary"],
                    font=FONTS["small"]
                )
            except Exception:
                pass


# ─────────────────────────────────────────────
#  Animated progress ring canvas widget
# ─────────────────────────────────────────────
class ProgressRing(tk.Canvas):
    def __init__(self, parent, size=48, **kwargs):
        super().__init__(
            parent, width=size, height=size,
            bg=COLORS["bg_card"], highlightthickness=0, **kwargs
        )
        self._size  = size
        self._angle = 0
        self._running = False
        self._arc = None
        self._draw_base()

    def _draw_base(self):
        m = 4
        s = self._size
        self.create_oval(m, m, s - m, s - m,
                         outline=COLORS["accent_dim"], width=4, tags="base")
        self._arc = self.create_arc(
            m, m, s - m, s - m,
            start=90, extent=60,
            outline=COLORS["accent"], width=4,
            style="arc", tags="ring"
        )

    def start(self):
        self._running = True
        self._animate()

    def stop(self):
        self._running = False

    def _animate(self):
        if not self._running:
            return
        self._angle = (self._angle - 8) % 360
        self.itemconfig("ring", start=self._angle)
        self.after(20, self._animate)


# ─────────────────────────────────────────────
#  Flat styled button
# ─────────────────────────────────────────────
class FlatButton(tk.Frame):
    def __init__(self, parent, text, command=None, style="primary",
                 icon="", width=None, **kwargs):
        styles = {
            "primary":  (COLORS["accent"],       COLORS["accent_hover"],  COLORS.get("btn_primary_fg", "#FFFFFF")),
            "ghost":    (COLORS["bg_card"],       COLORS["bg_hover"],      COLORS["text_primary"]),
            "danger":   (COLORS["error"],         "#FF6666",               "#FFFFFF"),
            "success":  (COLORS["success"],       "#30D870",               COLORS["bg_dark"]),
        }
        bg, bg_h, fg = styles.get(style, styles["primary"])
        if style == "ghost":
            super().__init__(parent, bg=bg, cursor="hand2", highlightthickness=1, highlightbackground=COLORS["border"], **kwargs)
        else:
            super().__init__(parent, bg=bg, cursor="hand2", **kwargs)
        self._style = style
        self._fg   = fg
        self._bg   = bg
        self._bg_h = bg_h
        self._active = False
        label_text = f"{icon}  {text}" if icon else text
        self._lbl = tk.Label(
            self, text=label_text, font=FONTS["subhead"],
            bg=bg, fg=fg, padx=scale_val(16), pady=scale_val(11)
        )
        self._lbl.pack(fill="both", expand=True)
        if width:
            self.configure(width=width)

        for w in (self, self._lbl):
            w.bind("<Enter>",   self._on_enter)
            w.bind("<Leave>",   self._on_leave)
            w.bind("<Button-1>",self._on_click)
        self._command = command

    def _on_enter(self, _=None):
        self.configure(bg=self._bg_h)
        self._lbl.configure(bg=self._bg_h)

    def _on_leave(self, _=None):
        self.configure(bg=self._bg)
        self._lbl.configure(bg=self._bg)

    def _on_click(self, _=None):
        if self._command:
            self._command()

    def configure_state(self, enabled=True):
        if enabled:
            cur_fg = COLORS["accent"] if getattr(self, "_active", False) else self._fg
            self._lbl.configure(fg=cur_fg)
            for w in (self, self._lbl):
                w.bind("<Button-1>", self._on_click)
                w.configure(cursor="hand2")
        else:
            self._lbl.configure(fg=COLORS["text_muted"])
            for w in (self, self._lbl):
                w.unbind("<Button-1>")
                w.configure(cursor="")

    def set_text(self, text, icon=""):
        label_text = f"{icon}  {text}" if icon else text
        self._lbl.configure(text=label_text)

    def set_active(self, active: bool = True):
        self._active = bool(active)
        cur_fg = COLORS["accent"] if self._active else self._fg
        self._lbl.configure(fg=cur_fg)
        if self._style == "ghost":
            border_col = COLORS["accent"] if self._active else COLORS["border"]
            self.configure(highlightbackground=border_col)

    def is_active(self) -> bool:
        return getattr(self, "_active", False)

    def apply_theme(self):
        styles = {
            "primary":  (COLORS["accent"],       COLORS["accent_hover"],  COLORS.get("btn_primary_fg", "#FFFFFF")),
            "ghost":    (COLORS["bg_card"],       COLORS["bg_hover"],      COLORS["text_primary"]),
            "danger":   (COLORS["error"],         "#FF6666",               "#FFFFFF"),
            "success":  (COLORS["success"],       "#30D870",               COLORS["bg_dark"]),
        }
        bg, bg_h, fg = styles.get(self._style, styles["primary"])
        self._bg = bg
        self._bg_h = bg_h
        self._fg = fg
        self.configure(bg=bg)
        cur_fg = COLORS["accent"] if getattr(self, "_active", False) else fg
        self._lbl.configure(bg=bg, fg=cur_fg)
        if self._style == "ghost":
            border = COLORS["accent"] if getattr(self, "_active", False) else COLORS["border"]
            self.configure(highlightthickness=1, highlightbackground=border)


# ─────────────────────────────────────────────
#  Video card widget (inside the file list)
# ─────────────────────────────────────────────
class VideoCard(tk.Frame):
    def __init__(self, parent, info, index, on_toggle, on_chapter_toggle=None, **kwargs):
        super().__init__(parent, bg=COLORS["bg_card"],
                         highlightbackground=COLORS["border"],
                         highlightthickness=1, **kwargs)
        self.info              = info
        self.index             = index
        self.on_toggle         = on_toggle
        self.on_chapter_toggle = on_chapter_toggle
        self._selected         = False
        self._chapters_expanded = False
        self._chapter_vars     = {}   # c_num -> BooleanVar
        self._chapter_name_labels = {}  # c_num -> Label widget
        self._chapter_rows     = []   # row Frame widgets
        self._build()
        self._bind_all()

    def _build(self):
        # Checkbox column
        self._chk_frame = tk.Frame(self, bg=COLORS["bg_card"], width=scale_val(56))
        self._chk_frame.pack(side="left", fill="y")
        self._chk_frame.pack_propagate(False)
        self._chk_var = tk.BooleanVar(value=False)
        self._chk = tk.Checkbutton(
            self._chk_frame, variable=self._chk_var,
            bg=COLORS["bg_card"], activebackground=COLORS["bg_hover"],
            fg=COLORS["accent"], selectcolor=COLORS["bg_card"],
            command=self._toggle, cursor="hand2",
            relief="flat", bd=0
        )
        self._chk.place(relx=0.5, rely=0.5, anchor="center")

        # Rename button (right side) — anchored to right before content expands
        self._rename_btn = tk.Button(
            self, text="✏",
            font=FONTS["rename_btn"], bg=COLORS["bg_card"],
            fg=COLORS.get("rename_btn", "#38BDF8"), relief="flat", bd=0,
            cursor="hand2", activebackground=COLORS["bg_hover"],
            activeforeground=COLORS.get("rename_btn_hover", "#7DD3FC"),
            command=self._on_rename
        )
        self._rename_btn.pack(side="right", padx=(0, scale_val(14)), pady=0)

        # Content (center - expands to fill space)
        self._content_frame = tk.Frame(self, bg=COLORS["bg_card"], padx=scale_val(14), pady=scale_val(14))
        self._content_frame.pack(side="left", fill="both", expand=True)

        # Row 1: filename + size badge
        self._row1 = tk.Frame(self._content_frame, bg=COLORS["bg_card"])
        self._row1.pack(fill="x")
        self._filename_lbl = tk.Label(
            self._row1, text=f"📼  {self.info['filename']}",
            font=FONTS["subhead"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self._filename_lbl.pack(side="left")
        self._size_lbl = tk.Label(
            self._row1, text=f"{self.info.get('size_mb', 0.0)} MB",
            font=FONTS["badge"], bg=COLORS["accent_dim"],
            fg=COLORS.get("badge_fg", COLORS["text_primary"]), padx=scale_val(8), pady=scale_val(3)
        )
        self._size_lbl.pack(side="right", padx=(0, scale_val(4)))

        # Row 2: metadata
        self._row2 = tk.Frame(self._content_frame, bg=COLORS["bg_card"])
        self._row2.pack(fill="x", pady=(scale_val(6), 0))
        chapters_data = self.info.get("chapters_data", [])
        if self.info.get("disc_type") == "DVD":
            dur_str = f"⏱  {format_duration(self.info.get('duration', 0))}"
            chaps = len(chapters_data) if chapters_data else self.info.get("chapter_count", 0)
            ch_str = f"📑 {chaps} ch" if chaps > 1 else ""
            w = self.info.get('width', 720)
            h = self.info.get('height', 480)
            res_str = f"📐 {w}×{h}"
            ar = self.info.get("aspect_ratio")
            if ar:
                res_str += f" ({ar})"
            codec_str = f"🎬 {self.info.get('codec', 'MPEG-2')}"
            fps_val = self.info.get('fps', '')
            fps_str = f"🎞 {fps_val}" if fps_val else ""
            aud = self.info.get('audio_summary', '')
            aud_str = f"🔊 {aud}" if aud else ""

            meta_parts = [p for p in (dur_str, ch_str, res_str, codec_str, fps_str, aud_str) if p]
            meta = "     ".join(meta_parts)
        else:
            w_h = f"{self.info.get('width', 352)}×{self.info.get('height', 288)}" if ('width' in self.info or 'height' in self.info) else ""
            meta_parts = [
                f"⏱  {format_duration(self.info.get('duration', 0.0))}" if 'duration' in self.info else "",
                f"📐 {w_h}" if w_h else "",
                f"🎬 {self.info.get('codec', '')}" if self.info.get('codec') else "",
                f"🎞 {self.info.get('fps', '')}" if self.info.get('fps') else "",
                f"📊 {self.info.get('bitrate', '')}" if self.info.get('bitrate') else ""
            ]
            meta = "     ".join([p for p in meta_parts if p])
        self._meta_lbl = tk.Label(self._row2, text=meta, font=FONTS["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        self._meta_lbl.pack(side="left")

        # Initialize chapter variables
        for ch in chapters_data:
            c_num = int(ch.get("chapter_number", 1))
            self._chapter_vars[c_num] = tk.BooleanVar(value=False)

        # If DVD and multiple chapters exist, add expandable button and expand by default
        if self.info.get("disc_type") == "DVD" and len(chapters_data) > 1:
            self._expand_btn = tk.Button(
                self._row2,
                text=f"📑 {len(chapters_data)} Chapters ▲",
                font=FONTS["small_bold"],
                bg=COLORS["bg_hover"],
                fg=COLORS["accent"],
                relief="flat", bd=0, padx=scale_val(8), pady=scale_val(1),
                cursor="hand2", activebackground=COLORS["bg_dark"], activeforeground=COLORS["accent"],
                command=self._toggle_chapters
            )
            self._expand_btn.pack(side="left", padx=(scale_val(12), 0))

            self._chapters_container = tk.Frame(self._content_frame, bg=COLORS["bg_card"])
            # Expand all chapters by default so user sees them right away
            self.expand_chapters(True)

    def _build_chapters(self):
        if not hasattr(self, "_chapters_container"):
            return
        for w in self._chapters_container.winfo_children():
            w.destroy()
        self._chapter_rows.clear()

        chapters = self.info.get("chapters_data", [])
        if not chapters:
            return

        header = tk.Frame(self._chapters_container, bg=COLORS["bg_dark"], padx=scale_val(8), pady=scale_val(4))
        header.pack(fill="x", pady=(scale_val(4), scale_val(2)))
        tk.Label(
            header, text="Chapter", font=FONTS["badge"],
            bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]
        ).pack(side="left", padx=(scale_val(28), scale_val(10)))
        tk.Label(
            header, text="Time Range", font=FONTS["badge"],
            bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]
        ).pack(side="left", padx=scale_val(10))
        tk.Label(
            header, text="Duration", font=FONTS["badge"],
            bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]
        ).pack(side="right", padx=scale_val(10))

        for ch in chapters:
            c_num = int(ch.get("chapter_number", 1))
            c_dur = float(ch.get("duration", 0.0))
            is_valid_timing = bool(ch.get("is_valid_timing", True)) and (c_dur > 0.0)
            if c_num not in self._chapter_vars:
                self._chapter_vars[c_num] = tk.BooleanVar(value=False)
            var = self._chapter_vars[c_num]

            row = tk.Frame(self._chapters_container, bg=COLORS["bg_card"], padx=scale_val(8), pady=scale_val(3))
            row.pack(fill="x")
            self._chapter_rows.append(row)

            cb = tk.Checkbutton(
                row, variable=var,
                bg=COLORS["bg_card"], activebackground=COLORS["bg_hover"],
                fg=COLORS["accent"], selectcolor=COLORS["bg_card"],
                command=lambda cn=c_num: self._on_chapter_cb(cn),
                cursor="hand2" if is_valid_timing else "arrow", relief="flat", bd=0
            )
            if not is_valid_timing:
                cb.configure(state="disabled")
            cb.pack(side="left")

            display_name = ch.get("custom_stem") or ch.get("name") or f"Chapter {c_num:02d}"
            name_lbl = tk.Label(
                row, text=display_name,
                font=FONTS["small_bold"], bg=COLORS["bg_card"],
                fg=COLORS["text_primary"] if is_valid_timing else COLORS["text_secondary"]
            )
            name_lbl.pack(side="left", padx=(scale_val(6), scale_val(10)))
            self._chapter_name_labels[c_num] = name_lbl

            range_text = f"{ch.get('start_str', '0:00')} → {ch.get('end_str', '')}"
            range_lbl = tk.Label(
                row, text=range_text,
                font=FONTS["mono"], bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
            )
            range_lbl.pack(side="left", padx=scale_val(10))

            # Single-item rename button for chapter
            if is_valid_timing:
                ch_rename_btn = tk.Button(
                    row, text="✏",
                    font=FONTS["small_bold"], bg=COLORS["bg_card"],
                    fg=COLORS.get("rename_btn", "#38BDF8"), relief="flat", bd=0,
                    cursor="hand2", activebackground=COLORS["bg_hover"],
                    activeforeground=COLORS.get("rename_btn_hover", "#7DD3FC"),
                    command=lambda cn=c_num: self._on_rename_chapter(cn)
                )
                ch_rename_btn.pack(side="right", padx=(scale_val(4), scale_val(8)))

            if not is_valid_timing:
                dur_text = "⏱ Invalid Timing (0.0s)"
                dur_lbl = tk.Label(
                    row, text=dur_text,
                    font=FONTS["small"], bg=COLORS["bg_card"], fg=COLORS.get("warning", "#F59E0B")
                )
            else:
                dur_text = f"⏱ {ch.get('duration_str', '')}"
                dur_lbl = tk.Label(
                    row, text=dur_text,
                    font=FONTS["small"], bg=COLORS["bg_card"], fg=COLORS["accent"]
                )
            dur_lbl.pack(side="right", padx=scale_val(6))

    def _toggle_chapters(self):
        self.expand_chapters(not self._chapters_expanded)

    def toggle_chapters(self, expand: bool = True):
        self.expand_chapters(expand)

    def expand_chapters(self, expand: bool = True):
        if not hasattr(self, "_chapters_container") or not self.info.get("chapters_data"):
            return
        chaps = self.info.get("chapters_data", [])
        if expand and not self._chapters_expanded:
            self._build_chapters()
            self._chapters_container.pack(fill="x", pady=(scale_val(6), 0))
            self._chapters_expanded = True
            if hasattr(self, "_expand_btn"):
                self._expand_btn.configure(text=f"📑 {len(chaps)} Chapters ▲")
        elif not expand and self._chapters_expanded:
            self._chapters_container.pack_forget()
            self._chapters_expanded = False
            if hasattr(self, "_expand_btn"):
                self._expand_btn.configure(text=f"📑 {len(chaps)} Chapters ▼")

    def _on_chapter_cb(self, c_num):
        val = self._chapter_vars[c_num].get()
        if val:
            # Checking any Chapter clears its parent Main Title's complete-title selection
            self._chk_var.set(False)
            self._selected = False
        any_chap = any(v.get() for v in self._chapter_vars.values())
        self.configure(highlightbackground=COLORS["accent"] if (self._selected or any_chap) else COLORS["border"])
        if self.on_chapter_toggle:
            self.on_chapter_toggle(self.index, c_num, val)

    def _bind_all(self):
        for w in self.winfo_children():
            if w not in (getattr(self, "_rename_btn", None), getattr(self, "_expand_btn", None)):
                w.bind("<Enter>", self._hover_on)
                w.bind("<Leave>", self._hover_off)
        self.bind("<Enter>", self._hover_on)
        self.bind("<Leave>", self._hover_off)

    def _hover_on(self, _=None):
        any_chap = any(v.get() for v in self._chapter_vars.values())
        if not (self._selected or any_chap):
            self.configure(bg=COLORS["bg_hover"],
                           highlightbackground=COLORS["border_accent"])

    def _hover_off(self, _=None):
        any_chap = any(v.get() for v in self._chapter_vars.values())
        if not (self._selected or any_chap):
            self.configure(bg=COLORS["bg_card"],
                           highlightbackground=COLORS["border"])

    def _toggle(self):
        self._selected = self._chk_var.get()
        if self._selected:
            self.configure(highlightbackground=COLORS["accent"])
            # Checking a Main Title selects it for complete-title ripping
            # and immediately clears all child Chapter selections under that title
            self.clear_all_chapters()
        else:
            any_chap = any(v.get() for v in self._chapter_vars.values())
            self.configure(highlightbackground=COLORS["accent"] if any_chap else COLORS["border"])
        self.on_toggle(self.index, self._selected)

    def set_selected(self, val: bool):
        self._chk_var.set(val)
        self._selected = val
        any_chap = any(v.get() for v in self._chapter_vars.values())
        self.configure(highlightbackground=COLORS["accent"] if (val or any_chap) else COLORS["border"])

    def set_title_selected(self, val: bool):
        self.set_selected(val)

    def clear_all_chapters(self, notify: bool = True):
        for c_num, var in self._chapter_vars.items():
            if var.get():
                var.set(False)
                if notify and self.on_chapter_toggle:
                    self.on_chapter_toggle(self.index, c_num, False)
        self.configure(highlightbackground=COLORS["accent"] if self._selected else COLORS["border"])

    def select_all_chapters(self, notify: bool = False):
        if not self._chapter_vars and self.info.get("chapters_data"):
            self._build_chapters()
        self._chk_var.set(False)
        self._selected = False
        chaps_data = {int(c.get("chapter_number", 1)): c for c in self.info.get("chapters_data", [])}
        for c_num, var in self._chapter_vars.items():
            ch = chaps_data.get(c_num, {})
            c_dur = float(ch.get("duration", 0.0))
            is_valid = bool(ch.get("is_valid_timing", True)) and (c_dur > 0.0)
            if not is_valid:
                var.set(False)
                continue
            if not var.get():
                var.set(True)
                if notify and self.on_chapter_toggle:
                    self.on_chapter_toggle(self.index, c_num, True)
            else:
                var.set(True)
        any_chap = any(v.get() for v in self._chapter_vars.values())
        self.configure(highlightbackground=COLORS["accent"] if any_chap else COLORS["border"])

    def set_chapter_selected(self, c_num: int, val: bool):
        if not self._chapter_vars and self.info.get("chapters_data"):
            self._build_chapters()
        if c_num in self._chapter_vars:
            self._chapter_vars[c_num].set(val)
        any_chap = any(v.get() for v in self._chapter_vars.values())
        self.configure(highlightbackground=COLORS["accent"] if (self._selected or any_chap) else COLORS["border"])

    @property
    def video_info(self):
        return self.info

    @property
    def selected(self) -> bool:
        return self._selected

    def is_selected(self) -> bool:
        return self._selected

    def are_any_chapters_selected(self) -> bool:
        return any(v.get() for v in self._chapter_vars.values())

    def set_custom_name(self, name: str):
        clean = sanitize_filename(name, fallback=self.info.get("filename", "Title"))
        self.info["custom_stem"] = clean
        self.info["filename"] = clean
        if hasattr(self, "_filename_lbl"):
            self._filename_lbl.configure(text=f"📼  {clean}")

    def apply_theme(self):
        border_color = COLORS["accent"] if self._selected else COLORS["border"]
        self.configure(bg=COLORS["bg_card"], highlightbackground=border_color)
        if hasattr(self, "_chk_frame"):
            self._chk_frame.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_chk"):
            self._chk.configure(
                bg=COLORS["bg_card"], activebackground=COLORS["bg_hover"],
                fg=COLORS["accent"], selectcolor=COLORS["bg_card"]
            )
        if hasattr(self, "_content_frame"):
            self._content_frame.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_row1"):
            self._row1.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_filename_lbl"):
            self._filename_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        if hasattr(self, "_size_lbl"):
            self._size_lbl.configure(
                bg=COLORS["accent_dim"],
                fg=COLORS.get("badge_fg", COLORS["text_primary"])
            )
        if hasattr(self, "_row2"):
            self._row2.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_meta_lbl"):
            self._meta_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        if hasattr(self, "_expand_btn"):
            self._expand_btn.configure(
                bg=COLORS["bg_hover"], fg=COLORS["accent"],
                activebackground=COLORS["bg_dark"], activeforeground=COLORS["accent"]
            )
        if hasattr(self, "_chapters_container"):
            self._chapters_container.configure(bg=COLORS["bg_card"])
            if getattr(self, "_chapters_expanded", False):
                self._build_chapters()
        for r in getattr(self, "_chapter_rows", []):
            try:
                r.configure(bg=COLORS["bg_card"])
                for child in r.winfo_children():
                    if isinstance(child, tk.Checkbutton):
                        child.configure(
                            bg=COLORS["bg_card"], activebackground=COLORS["bg_hover"],
                            fg=COLORS["accent"], selectcolor=COLORS["bg_card"]
                        )
                    elif isinstance(child, tk.Button):
                        child.configure(
                            bg=COLORS["bg_card"],
                            fg=COLORS.get("rename_btn", "#38BDF8"),
                            activebackground=COLORS["bg_hover"],
                            activeforeground=COLORS.get("rename_btn_hover", "#7DD3FC")
                        )
                    elif isinstance(child, tk.Label):
                        child.configure(bg=COLORS["bg_card"])
            except Exception:
                pass
        if hasattr(self, "_rename_btn"):
            self._rename_btn.configure(
                bg=COLORS["bg_card"],
                fg=COLORS.get("rename_btn", "#38BDF8"),
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS.get("rename_btn_hover", "#7DD3FC")
            )

    def _on_rename(self):
        """Inline rename dialog — let user pick a new output stem for this file."""
        parent_top = self.winfo_toplevel()
        dlg = tk.Toplevel(parent_top)
        dlg.withdraw()
        dlg.title(t("rename.title"))
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.resizable(False, False)
        set_window_icon(dlg)

        stem = self.info.get("custom_stem") or Path(self.info["filename"]).stem
        self._rename_inst_lbl = tk.Label(
            dlg, text=t("rename.inst"),
            font=FONTS["body"], bg=COLORS["bg_panel"], fg=COLORS["text_secondary"]
        )
        self._rename_inst_lbl.pack(padx=24, pady=(20, 6), anchor="w")

        entry_var = tk.StringVar(value=stem)
        entry = tk.Entry(
            dlg, textvariable=entry_var,
            font=FONTS["body"], width=36,
            bg=COLORS["bg_card"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat",
            bd=6
        )
        entry.pack(padx=24, pady=(0, 4))
        entry.select_range(0, "end")
        entry.focus_set()

        btn_row = tk.Frame(dlg, bg=COLORS["bg_panel"])
        btn_row.pack(padx=24, pady=(8, 20), fill="x")

        def apply():
            new_stem = entry_var.get().strip()
            if new_stem:
                clean_stem = sanitize_filename(new_stem, fallback=stem)
                self.info["custom_stem"] = clean_stem
                self._filename_lbl.configure(text=f"📼  {clean_stem}")
            dlg.destroy()

        self._rename_apply_btn = tk.Button(
            btn_row, text=t("rename.apply"),
            font=FONTS["body"], bg=COLORS["accent"],
            fg=COLORS["text_primary"], relief="flat", bd=0,
            padx=20, pady=6, cursor="hand2",
            command=apply
        )
        self._rename_apply_btn.pack(side="left", padx=(0, 8))
        self._rename_cancel_btn = tk.Button(
            btn_row, text=t("rename.cancel"),
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["text_muted"], relief="flat", bd=0,
            padx=20, pady=6, cursor="hand2",
            command=dlg.destroy
        )
        self._rename_cancel_btn.pack(side="left")

        dlg.bind("<Return>", lambda e: apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        position_window_on_parent(dlg, parent_top)
        dlg.grab_set()

    def _on_rename_chapter(self, c_num: int):
        """Single-item rename dialog for an individual chapter."""
        ch = None
        for item in self.info.get("chapters_data", []):
            if int(item.get("chapter_number", 1)) == c_num:
                ch = item
                break
        if not ch:
            return

        parent_top = self.winfo_toplevel()
        dlg = tk.Toplevel(parent_top)
        dlg.withdraw()
        dlg.title(t("rename.chapter_title"))
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.resizable(False, False)
        set_window_icon(dlg)

        current_name = ch.get("custom_stem") or ch.get("name") or f"Chapter {c_num:02d}"
        inst_lbl = tk.Label(
            dlg, text=t("rename.chapter_inst"),
            font=FONTS["body"], bg=COLORS["bg_panel"], fg=COLORS["text_secondary"]
        )
        inst_lbl.pack(padx=24, pady=(20, 6), anchor="w")

        entry_var = tk.StringVar(value=current_name)
        entry = tk.Entry(
            dlg, textvariable=entry_var,
            font=FONTS["body"], width=36,
            bg=COLORS["bg_card"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat",
            bd=6
        )
        entry.pack(padx=24, pady=(0, 4))
        entry.select_range(0, "end")
        entry.focus_set()

        btn_row = tk.Frame(dlg, bg=COLORS["bg_panel"])
        btn_row.pack(padx=24, pady=(8, 20), fill="x")

        def apply():
            new_stem = entry_var.get().strip()
            if new_stem:
                clean_stem = sanitize_filename(new_stem, fallback=f"Chapter_{c_num:02d}")
                ch["custom_stem"] = clean_stem
                ch["name"] = clean_stem
                self.update_chapter_name_display(c_num, clean_stem)
            dlg.destroy()

        apply_btn = tk.Button(
            btn_row, text=t("rename.apply"),
            font=FONTS["body"], bg=COLORS["accent"],
            fg=COLORS["text_primary"], relief="flat", bd=0,
            padx=20, pady=6, cursor="hand2",
            command=apply
        )
        apply_btn.pack(side="left", padx=(0, 8))
        cancel_btn = tk.Button(
            btn_row, text=t("rename.cancel"),
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["text_muted"], relief="flat", bd=0,
            padx=20, pady=6, cursor="hand2",
            command=dlg.destroy
        )
        cancel_btn.pack(side="left")

        dlg.bind("<Return>", lambda e: apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        position_window_on_parent(dlg, parent_top)
        dlg.grab_set()

    def update_chapter_name_display(self, c_num: int, new_name: str):
        for ch in self.info.get("chapters_data", []):
            if int(ch.get("chapter_number", 1)) == c_num:
                ch["custom_stem"] = new_name
                ch["name"] = new_name
                break
        if hasattr(self, "_chapter_name_labels") and c_num in self._chapter_name_labels:
            self._chapter_name_labels[c_num].configure(text=new_name)

    @property
    def selected(self):
        return self._chk_var.get()


# ─────────────────────────────────────────────
#  Log console widget
# ─────────────────────────────────────────────
class LogConsole(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS["bg_dark"], **kwargs)
        self._text = tk.Text(
            self, bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
            font=FONTS["mono"], relief="flat", bd=0,
            state="disabled", wrap="word", height=3,
            insertbackground=COLORS["accent"]
        )
        sb = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(fill="both", expand=True)

        # Tag colours
        self._text.tag_configure("info",    foreground=COLORS["text_secondary"])
        self._text.tag_configure("success", foreground=COLORS["success"])
        self._text.tag_configure("warning", foreground=COLORS["warning"])
        self._text.tag_configure("error",   foreground=COLORS["error"])
        self._text.tag_configure("accent",  foreground=COLORS["accent"])

    def apply_theme(self):
        self.configure(bg=COLORS["bg_dark"])
        self._text.configure(
            bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
            insertbackground=COLORS["accent"]
        )
        self._text.tag_configure("info",    foreground=COLORS["text_secondary"])
        self._text.tag_configure("success", foreground=COLORS["success"])
        self._text.tag_configure("warning", foreground=COLORS["warning"])
        self._text.tag_configure("error",   foreground=COLORS["error"])
        self._text.tag_configure("accent",  foreground=COLORS["accent"])

    def log(self, message, level="info"):
        if threading.current_thread() is not threading.main_thread():
            try:
                self.after(0, lambda: self.log(message, level))
            except Exception:
                pass
            return
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {"info": "●", "success": "✓", "warning": "⚠", "error": "✗", "accent": "►"}
        icon = icons.get(level, "●")
        # Ensure message is safely encoded/decoded with UTF-8 and errors replaced
        safe_msg = str(message).encode("utf-8", errors="replace").decode("utf-8")
        line = f"[{ts}]  {icon}  {safe_msg}\n"
        try:
            self._text.configure(state="normal")
            self._text.insert("end", line, level)
            self._text.see("end")
            self._text.configure(state="disabled")
        except Exception:
            pass

    def clear(self):
        if threading.current_thread() is not threading.main_thread():
            try:
                self.after(0, self.clear)
            except Exception:
                pass
            return
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ─────────────────────────────────────────────
#  Windows Taskbar Progress Helper (ITaskbarList3)
# ─────────────────────────────────────────────
class WindowsTaskbarProgress:
    """Controls the Windows Taskbar button progress indicator using ITaskbarList3 COM interface."""
    TBPF_NOPROGRESS    = 0x00000000
    TBPF_INDETERMINATE = 0x00000001
    TBPF_NORMAL        = 0x00000002
    TBPF_ERROR         = 0x00000004
    TBPF_PAUSED        = 0x00000008

    def __init__(self, root_widget):
        self._root = root_widget
        self._taskbar = None
        self._set_progress_val_fn = None
        self._set_progress_state_fn = None
        self._hwnd = None
        self._supported = False
        self._init_taskbar()

    def _init_taskbar(self):
        if sys.platform != "win32":
            return
        try:
            from ctypes import (
                wintypes, Structure, c_byte, c_ushort, c_ulong,
                POINTER, c_void_p, c_ulonglong, c_int, WINFUNCTYPE, c_long
            )

            class GUID(Structure):
                _fields_ = [
                    ("Data1", c_ulong),
                    ("Data2", c_ushort),
                    ("Data3", c_ushort),
                    ("Data4", c_byte * 8)
                ]

            CLSID_TaskbarList = GUID(
                0x56FDF344, 0xFD6D, 0x11D0,
                (c_byte * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90)
            )
            IID_ITaskbarList3 = GUID(
                0xEA1AFB91, 0x9E28, 0x4B86,
                (c_byte * 8)(0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF)
            )

            ctypes.windll.ole32.CoInitialize(None)
            taskbar = c_void_p()
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(CLSID_TaskbarList),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(IID_ITaskbarList3),
                ctypes.byref(taskbar)
            )
            if hr != 0 or not taskbar.value:
                return

            vtable = ctypes.cast(taskbar.value, POINTER(POINTER(c_void_p))).contents
            self._taskbar = taskbar
            # slot 9: SetProgressValue(this, hwnd, completed, total)
            self._set_progress_val_fn = WINFUNCTYPE(
                c_long, c_void_p, wintypes.HWND, c_ulonglong, c_ulonglong
            )(vtable[9])
            # slot 10: SetProgressState(this, hwnd, flags)
            self._set_progress_state_fn = WINFUNCTYPE(
                c_long, c_void_p, wintypes.HWND, c_int
            )(vtable[10])
            self._supported = True
        except Exception:
            self._supported = False

    def _get_hwnd(self):
        if not self._supported:
            return None
        if self._hwnd:
            return self._hwnd
        try:
            client_hwnd = self._root.winfo_id()
            if client_hwnd:
                # GA_ROOT = 2: retrieves the root window by walking the chain of parent windows
                hwnd = ctypes.windll.user32.GetAncestor(client_hwnd, 2)
                self._hwnd = hwnd if hwnd else client_hwnd
        except Exception:
            pass
        return self._hwnd

    def set_state(self, state):
        hwnd = self._get_hwnd()
        if not hwnd or not self._supported:
            return
        try:
            self._set_progress_state_fn(self._taskbar, hwnd, state)
        except Exception:
            pass

    def set_value(self, completed, total=100):
        hwnd = self._get_hwnd()
        if not hwnd or not self._supported:
            return
        try:
            if total <= 0:
                total = 100
            completed = max(0, min(int(completed), int(total)))
            self._set_progress_state_fn(self._taskbar, hwnd, self.TBPF_NORMAL)
            self._set_progress_val_fn(self._taskbar, hwnd, completed, int(total))
        except Exception:
            pass

    def set_error(self):
        self.set_state(self.TBPF_ERROR)

    def set_paused(self):
        self.set_state(self.TBPF_PAUSED)

    def reset(self):
        self.set_state(self.TBPF_NOPROGRESS)


# ─────────────────────────────────────────────────────────────
#  Disc Health Check Dialogs & Results UI
# ─────────────────────────────────────────────────────────────

class DiscHealthModeDialog(tk.Toplevel):
    """Dialog allowing user to choose between Quick Check and Thorough Read Test."""
    def __init__(self, parent, source_path: str, on_start):
        super().__init__(parent)
        self.withdraw()
        self.parent = parent
        self.source_path = source_path
        self.on_start = on_start
        self.selected_mode = tk.StringVar(value="quick")

        self.title(t('diagnostics.select_mode_title'))
        self.configure(bg=COLORS["bg_panel"])
        self.resizable(False, False)
        if hasattr(parent, "_set_window_icon"):
            parent._set_window_icon(self)

        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
            set_window_dark_mode(hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        # Header banner
        header = tk.Frame(self, bg=COLORS["bg_dark"])
        header.pack(side="top", fill="x")
        h_inner = tk.Frame(header, bg=COLORS["bg_dark"])
        h_inner.pack(fill="x", padx=scale_val(16), pady=scale_val(10))
        lbl_h = tk.Label(
            h_inner, text=f"🩺  {t('diagnostics.health_check')}",
            font=FONTS["header"], bg=COLORS["bg_dark"], fg=COLORS["text_primary"]
        )
        lbl_h.pack(side="left")

        # Footer action buttons (packed to bottom first so they never get compressed)
        btn_box = tk.Frame(self, bg=COLORS["bg_panel"])
        btn_box.pack(side="bottom", fill="x", padx=scale_val(18), pady=(scale_val(12), scale_val(16)))

        def do_start():
            mode = self.selected_mode.get()
            self.destroy()
            if self.on_start:
                self.on_start(mode)

        btn_cancel = tk.Button(
            btn_box, text=t('diagnostics.cancel'), font=FONTS["small"],
            bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            relief="flat", bd=0, padx=scale_val(16), pady=scale_val(6),
            cursor="hand2", command=self.destroy
        )
        btn_cancel.pack(side="right", padx=(scale_val(10), 0))

        btn_go = tk.Button(
            btn_box, text=t('diagnostics.start_check'), font=FONTS["small_bold"],
            bg=COLORS["accent"], fg=COLORS.get("btn_primary_fg", "#FFFFFF"),
            relief="flat", bd=0, padx=scale_val(18), pady=scale_val(6),
            cursor="hand2", activebackground=COLORS["accent_hover"],
            activeforeground=COLORS.get("btn_primary_fg", "#FFFFFF"),
            command=do_start
        )
        btn_go.pack(side="right")

        # Source row
        src_frame = tk.Frame(self, bg=COLORS["bg_panel"])
        src_frame.pack(side="top", fill="x", padx=scale_val(18), pady=(scale_val(10), scale_val(6)))
        src_disp = dvd_diagnostics.mask_private_path(source_path) if dvd_diagnostics else source_path
        lbl_src_title = tk.Label(
            src_frame, text=f"Source:  {src_disp}", font=FONTS["small_bold"],
            bg=COLORS["bg_panel"], fg=COLORS["text_secondary"], anchor="w"
        )
        lbl_src_title.pack(fill="x")

        # Option cards container
        opts_frame = tk.Frame(self, bg=COLORS["bg_panel"])
        opts_frame.pack(side="top", fill="both", expand=True, padx=scale_val(18), pady=scale_val(4))

        # Mode A: Quick Check (Default)
        card_quick = tk.Frame(opts_frame, bg=COLORS["bg_card"], highlightbackground=COLORS["accent"], highlightthickness=1)
        card_quick.pack(fill="x", pady=(0, scale_val(8)))
        rb_quick = tk.Radiobutton(
            card_quick, text=t('diagnostics.mode_quick'), variable=self.selected_mode, value="quick",
            font=FONTS["small_bold"], bg=COLORS["bg_card"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"], activeforeground=COLORS["text_primary"],
            cursor="hand2"
        )
        rb_quick.pack(anchor="w", padx=scale_val(10), pady=(scale_val(6), 0))
        lbl_quick_desc = tk.Label(
            card_quick, text=t('diagnostics.mode_quick_desc'),
            font=FONTS["tiny"], bg=COLORS["bg_card"], fg=COLORS["text_secondary"], wraplength=scale_val(460), justify="left"
        )
        lbl_quick_desc.pack(anchor="w", padx=(scale_val(32), scale_val(10)), pady=(0, scale_val(8)))

        # Mode B: Thorough Read Test (Optional)
        card_thorough = tk.Frame(opts_frame, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        card_thorough.pack(fill="x", pady=(0, scale_val(6)))
        rb_thorough = tk.Radiobutton(
            card_thorough, text=t('diagnostics.mode_thorough'), variable=self.selected_mode, value="thorough",
            font=FONTS["small_bold"], bg=COLORS["bg_card"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"], activeforeground=COLORS["text_primary"],
            cursor="hand2"
        )
        rb_thorough.pack(anchor="w", padx=scale_val(10), pady=(scale_val(6), 0))
        lbl_thorough_desc = tk.Label(
            card_thorough, text=t('diagnostics.mode_thorough_desc'),
            font=FONTS["tiny"], bg=COLORS["bg_card"], fg=COLORS["text_secondary"], wraplength=scale_val(460), justify="left"
        )
        lbl_thorough_desc.pack(anchor="w", padx=(scale_val(32), scale_val(10)), pady=(0, scale_val(8)))

        def on_mode_change(*args):
            is_q = (self.selected_mode.get() == "quick")
            card_quick.configure(highlightbackground=COLORS["accent"] if is_q else COLORS["border"])
            card_thorough.configure(highlightbackground=COLORS["accent"] if not is_q else COLORS["border"])
        self.selected_mode.trace_add("write", on_mode_change)

        self.update_idletasks()
        req_w = self.winfo_reqwidth()
        req_h = self.winfo_reqheight()
        w = max(scale_val(520), req_w)
        h = max(scale_val(370), req_h)
        self.minsize(w, h)
        position_window_on_parent(self, parent, width=w, height=h, min_w=w, min_h=h)
        self.grab_set()


class DiscHealthProgressDialog(tk.Toplevel):
    """Modal dialog displaying active health check progress and cancellation."""
    def __init__(self, parent, mode_label: str, on_cancel):
        super().__init__(parent)
        self.withdraw()
        self.on_cancel = on_cancel
        self.title(t('diagnostics.health_check'))
        self.configure(bg=COLORS["bg_panel"])
        self.resizable(False, False)
        if hasattr(parent, "_set_window_icon"):
            parent._set_window_icon(self)

        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
            set_window_dark_mode(hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        inner = tk.Frame(self, bg=COLORS["bg_panel"], padx=scale_val(20), pady=scale_val(16))
        inner.pack(fill="both", expand=True)

        lbl_top = tk.Label(
            inner, text=f"🩺  {t('diagnostics.health_check')}",
            font=FONTS["subheading"], bg=COLORS["bg_panel"], fg=COLORS["text_primary"]
        )
        lbl_top.pack(anchor="w", pady=(0, scale_val(4)))

        lbl_mode = tk.Label(
            inner, text=f"Mode: {mode_label}",
            font=FONTS["tiny"], bg=COLORS["bg_panel"], fg=COLORS["accent"]
        )
        lbl_mode.pack(anchor="w", pady=(0, scale_val(10)))

        self.lbl_stage = tk.Label(
            inner, text=t('diagnostics.running_check'),
            font=FONTS["small"], bg=COLORS["bg_panel"], fg=COLORS["text_secondary"]
        )
        self.lbl_stage.pack(anchor="w", pady=(0, scale_val(6)))

        self.pbar = ttk.Progressbar(inner, orient="horizontal", mode="determinate", maximum=100)
        self.pbar.pack(fill="x", pady=(0, scale_val(14)))

        self.btn_cancel = tk.Button(
            inner, text=t('diagnostics.cancel'), font=FONTS["small"],
            bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            relief="flat", bd=0, padx=scale_val(16), pady=scale_val(4),
            cursor="hand2", command=self._do_cancel
        )
        self.btn_cancel.pack(anchor="e")

        self.update_idletasks()
        req_w = self.winfo_reqwidth()
        req_h = self.winfo_reqheight()
        w = max(scale_val(460), req_w)
        h = max(scale_val(210), req_h)
        self.minsize(w, h)
        position_window_on_parent(self, parent, width=w, height=h, min_w=w, min_h=h)
        self.grab_set()

    def update_progress(self, pct: int, msg: str):
        try:
            self.lbl_stage.configure(text=msg)
            self.pbar["value"] = pct
            self.update_idletasks()
        except Exception:
            pass

    def _do_cancel(self):
        self.btn_cancel.configure(state="disabled", text=t('diagnostics.cancel'))
        if self.on_cancel:
            self.on_cancel()


class DiscHealthResultDialog(tk.Toplevel):
    """Dedicated diagnostic results dialog with findings, check results, and export."""
    def __init__(self, parent, report, on_proceed_rip=None, on_export_txt=None):
        super().__init__(parent)
        self.withdraw()
        self.parent = parent
        self.report = report
        self.on_proceed_rip = on_proceed_rip
        self.on_export_txt = on_export_txt

        self.title(t('diagnostics.results_title'))
        self.configure(bg=COLORS["bg_panel"])
        self.resizable(True, True)
        if hasattr(parent, "_set_window_icon"):
            parent._set_window_icon(self)

        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
            set_window_dark_mode(hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        # Overall Status Badge configuration
        st = report.overall_status
        if st == dvd_diagnostics.HealthStatus.GOOD:
            st_color = COLORS["success"]
            st_icon = "✓"
            st_text = t('diagnostics.status_good')
        elif st == dvd_diagnostics.HealthStatus.WARNINGS:
            st_color = COLORS["warning"]
            st_icon = "⚠️"
            st_text = t('diagnostics.status_warnings')
        elif st == dvd_diagnostics.HealthStatus.PROBLEMS:
            st_color = COLORS["error"]
            st_icon = "⛔"
            st_text = t('diagnostics.status_problems')
        else:
            st_color = COLORS["text_secondary"]
            st_icon = "❓"
            st_text = t('diagnostics.status_inconclusive')

        # Header banner
        header = tk.Frame(self, bg=COLORS["bg_dark"])
        header.pack(fill="x")
        h_inner = tk.Frame(header, bg=COLORS["bg_dark"])
        h_inner.pack(fill="x", padx=scale_val(18), pady=scale_val(12))

        # Status badge frame on left
        badge_box = tk.Frame(h_inner, bg=COLORS["bg_card"], highlightbackground=st_color, highlightthickness=2)
        badge_box.pack(side="left", padx=(0, scale_val(14)))
        lbl_badge_icon = tk.Label(badge_box, text=f" {st_icon} ", font=FONTS["emoji_32"], bg=COLORS["bg_card"], fg=st_color)
        lbl_badge_icon.pack(side="left", padx=scale_val(6), pady=scale_val(4))

        # Title and details on right
        h_text_box = tk.Frame(h_inner, bg=COLORS["bg_dark"])
        h_text_box.pack(side="left", fill="both", expand=True)

        row_t = tk.Frame(h_text_box, bg=COLORS["bg_dark"])
        row_t.pack(anchor="w")
        lbl_res_title = tk.Label(row_t, text=t('diagnostics.results_title'), font=FONTS["header"], bg=COLORS["bg_dark"], fg=COLORS["text_primary"])
        lbl_res_title.pack(side="left", padx=(0, scale_val(8)))

        lbl_res_st = tk.Label(row_t, text=f"[{st_text}]", font=FONTS["small_bold"], bg=COLORS["bg_dark"], fg=st_color)
        lbl_res_st.pack(side="left")

        # Sub meta line
        mode_str = t('diagnostics.mode_quick') if report.mode == "quick" else t('diagnostics.mode_thorough')
        src_disp = dvd_diagnostics.mask_private_path(report.source_path) if dvd_diagnostics else report.source_path
        meta_line = f"{mode_str}  •  {report.media_type}  •  {src_disp}  •  {report.duration_sec:.2f}s"
        lbl_meta = tk.Label(h_text_box, text=meta_line, font=FONTS["tiny"], bg=COLORS["bg_dark"], fg=COLORS["text_secondary"])
        lbl_meta.pack(anchor="w", pady=(scale_val(2), 0))

        # Divider
        sep = tk.Frame(self, bg=COLORS["border"], height=1)
        sep.pack(fill="x", padx=scale_val(18))

        # Scrollable Content Area
        canvas = tk.Canvas(self, bg=COLORS["bg_panel"], highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll_content = tk.Frame(canvas, bg=COLORS["bg_panel"])

        scroll_content.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_win = canvas.create_window((0, 0), window=scroll_content, anchor="nw")

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mousewheel scroll binding
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self.bind("<MouseWheel>", _on_mousewheel)

        canvas.pack(side="top", fill="both", expand=True, padx=scale_val(18), pady=scale_val(8))
        scrollbar.pack(side="right", fill="y")

        card_px = scale_val(14)
        card_py = scale_val(8)

        # ── Card 1: Summary ──
        c_summary = tk.Frame(scroll_content, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        c_summary.pack(fill="x", pady=(0, card_py))
        lbl_sum_head = tk.Label(
            c_summary, text=f"📝  {t('diagnostics.summary')}", font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["accent"]
        )
        lbl_sum_head.pack(anchor="w", padx=card_px, pady=(scale_val(8), scale_val(4)))

        lbl_sum_body = tk.Label(
            c_summary, text=report.summary, font=FONTS["small"],
            bg=COLORS["bg_card"], fg=COLORS["text_primary"], wraplength=scale_val(560), justify="left"
        )
        lbl_sum_body.pack(anchor="w", padx=card_px, pady=(0, scale_val(10)))

        # ── Card 2: Checks Performed ──
        c_checks = tk.Frame(scroll_content, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        c_checks.pack(fill="x", pady=(0, card_py))
        lbl_chk_head = tk.Label(
            c_checks, text=f"📋  {t('diagnostics.checks_performed')}", font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["accent"]
        )
        lbl_chk_head.pack(anchor="w", padx=card_px, pady=(scale_val(8), scale_val(6)))

        for chk in report.checks:
            row_chk = tk.Frame(c_checks, bg=COLORS["bg_card"])
            row_chk.pack(fill="x", padx=card_px, pady=scale_val(2))

            # Status pill
            if chk.status == dvd_diagnostics.CheckStatus.PASSED:
                c_fg = COLORS["success"]
                c_txt = " [PASS] "
            elif chk.status == dvd_diagnostics.CheckStatus.WARNING:
                c_fg = COLORS["warning"]
                c_txt = " [WARN] "
            elif chk.status == dvd_diagnostics.CheckStatus.FAILED:
                c_fg = COLORS["error"]
                c_txt = " [FAIL] "
            elif chk.status == dvd_diagnostics.CheckStatus.NOT_TESTED:
                c_fg = COLORS["text_secondary"]
                c_txt = " [SKIP] "
            else:
                c_fg = COLORS["text_muted"]
                c_txt = " [INCL] "

            lbl_chk_badge = tk.Label(row_chk, text=c_txt, font=FONTS["mono"], bg=COLORS["bg_panel"], fg=c_fg, highlightbackground=COLORS["border"], highlightthickness=1)
            lbl_chk_badge.pack(side="left", padx=(0, scale_val(8)))

            dur_str = f"({chk.duration_sec:.2f}s) " if chk.duration_sec > 0 else ""
            lbl_chk_desc = tk.Label(row_chk, text=f"{chk.name} {dur_str}— {chk.details}", font=FONTS["small"], bg=COLORS["bg_card"], fg=COLORS["text_secondary"], anchor="w")
            lbl_chk_desc.pack(side="left", fill="x", expand=True)

        tk.Frame(c_checks, height=scale_val(8), bg=COLORS["bg_card"]).pack()

        # ── Card 3: Findings ──
        c_findings = tk.Frame(scroll_content, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        c_findings.pack(fill="x", pady=(0, card_py))
        lbl_f_head = tk.Label(
            c_findings, text=f"🔍  {t('diagnostics.findings')}", font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["accent"]
        )
        lbl_f_head.pack(anchor="w", padx=card_px, pady=(scale_val(8), scale_val(6)))

        if not report.findings:
            row_nf = tk.Frame(c_findings, bg=COLORS["bg_card"])
            row_nf.pack(fill="x", padx=card_px, pady=(0, scale_val(10)))
            lbl_nf = tk.Label(row_nf, text=f"✓  {t('diagnostics.no_findings')}", font=FONTS["small"], bg=COLORS["bg_card"], fg=COLORS["success"])
            lbl_nf.pack(anchor="w")
        else:
            for idx, f in enumerate(report.findings):
                box_f = tk.Frame(c_findings, bg=COLORS["bg_panel"], highlightbackground=COLORS["border"], highlightthickness=1)
                box_f.pack(fill="x", padx=card_px, pady=(0, scale_val(6)))

                if f.severity == dvd_diagnostics.FindingSeverity.ERROR:
                    f_fg = COLORS["error"]
                    f_tag = "ERROR"
                elif f.severity == dvd_diagnostics.FindingSeverity.WARNING:
                    f_fg = COLORS["warning"]
                    f_tag = "WARNING"
                else:
                    f_fg = COLORS["accent"]
                    f_tag = "INFO"

                t_row = tk.Frame(box_f, bg=COLORS["bg_panel"])
                t_row.pack(fill="x", padx=scale_val(10), pady=(scale_val(6), scale_val(2)))
                lbl_tag = tk.Label(t_row, text=f"[{f_tag}]", font=FONTS["mono_bold"], bg=COLORS["bg_panel"], fg=f_fg)
                lbl_tag.pack(side="left", padx=(0, scale_val(6)))
                lbl_f_title = tk.Label(t_row, text=f.title, font=FONTS["small_bold"], bg=COLORS["bg_panel"], fg=COLORS["text_primary"])
                lbl_f_title.pack(side="left")

                lbl_f_exp = tk.Label(box_f, text=f.explanation, font=FONTS["small"], bg=COLORS["bg_panel"], fg=COLORS["text_secondary"], wraplength=scale_val(540), justify="left")
                lbl_f_exp.pack(anchor="w", padx=scale_val(10), pady=(0, scale_val(2)))

                if f.location or f.evidence:
                    det_txt = (f"Location: {f.location}  " if f.location else "") + (f"Evidence: {f.evidence}" if f.evidence else "")
                    lbl_f_det = tk.Label(box_f, text=det_txt, font=FONTS["tiny"], bg=COLORS["bg_panel"], fg=COLORS["text_muted"], wraplength=scale_val(540), justify="left")
                    lbl_f_det.pack(anchor="w", padx=scale_val(10), pady=(0, scale_val(2)))

                if f.recommended_action:
                    lbl_f_act = tk.Label(box_f, text=f"Action: {f.recommended_action}", font=FONTS["tiny_bold"], bg=COLORS["bg_panel"], fg=COLORS["accent"], wraplength=scale_val(540), justify="left")
                    lbl_f_act.pack(anchor="w", padx=scale_val(10), pady=(0, scale_val(6)))

        # ── Card 4: Recommended Next Steps ──
        c_steps = tk.Frame(scroll_content, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        c_steps.pack(fill="x", pady=(0, card_py))
        lbl_st_head = tk.Label(
            c_steps, text=f"💡  {t('diagnostics.recommended_steps')}", font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["accent"]
        )
        lbl_st_head.pack(anchor="w", padx=card_px, pady=(scale_val(8), scale_val(6)))

        for step in report.recommended_next_steps:
            lbl_st = tk.Label(
                c_steps, text=f"•  {step}", font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_primary"], wraplength=scale_val(560), justify="left"
            )
            lbl_st.pack(anchor="w", padx=card_px, pady=(0, scale_val(4)))

        tk.Frame(c_steps, height=scale_val(6), bg=COLORS["bg_card"]).pack()

        # ── Footer Toolbar ──
        footer = tk.Frame(self, bg=COLORS["bg_panel"])
        footer.pack(fill="x", padx=scale_val(18), pady=(scale_val(8), scale_val(14)))

        # Left button: Export TXT Report
        btn_exp_txt = tk.Button(
            footer, text=f"📄  {t('diagnostics.export_txt_btn')}", font=FONTS["small"],
            bg=COLORS["bg_panel"], fg=COLORS["success"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(5),
            cursor="hand2", activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["success"],
            command=self._do_export_txt
        )
        btn_exp_txt.pack(side="left")

        # Right buttons: Close & Proceed to Ripping
        btn_close_dlg = tk.Button(
            footer, text=t('diagnostics.close'), font=FONTS["small"],
            bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(5),
            cursor="hand2", command=self.destroy
        )
        btn_close_dlg.pack(side="right", padx=(scale_val(8), 0))

        btn_rip = tk.Button(
            footer, text=f"🎬  {t('diagnostics.proceed_rip')}", font=FONTS["small_bold"],
            bg=COLORS["accent"], fg=COLORS.get("btn_primary_fg", "#FFFFFF"),
            relief="flat", bd=0, padx=scale_val(16), pady=scale_val(5),
            cursor="hand2", activebackground=COLORS["accent_hover"],
            activeforeground=COLORS.get("btn_primary_fg", "#FFFFFF"),
            command=self._do_proceed_rip
        )
        btn_rip.pack(side="right")

        self.update_idletasks()
        w = scale_val(640)
        mon_x1, mon_y1, mon_x2, mon_y2 = get_monitor_work_area(parent)
        mon_h = mon_y2 - mon_y1
        h = min(scale_val(680), mon_h - 80)
        self.minsize(scale_val(540), scale_val(480))
        position_window_on_parent(self, parent, width=w, height=h, min_w=scale_val(540), min_h=scale_val(480))
        self.grab_set()

    def _do_export_txt(self):
        if self.on_export_txt:
            self.on_export_txt(report=self.report, dlg_parent=self)

    def _do_proceed_rip(self):
        self.destroy()
        if self.on_proceed_rip:
            self.on_proceed_rip(self.report)

# ─────────────────────────────────────────────
#  Main Application Window
# ─────────────────────────────────────────────
class VCDRipperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.i18n = i18n
        self.title(t('header.title'))
        self.configure(bg=COLORS["bg_dark"])

        # DPI awareness
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # Explicit AppUserModelID so Windows taskbar uses CompactDisc.ico
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
            _register_app_user_model_id(APP_USER_MODEL_ID, APP_NAME, _find_asset_path("CompactDisc.ico"))
        except Exception:
            pass

        # Apply fonts and window scale
        apply_font_scale(self, i18n.get_scale_factor())
        self._apply_window_scale()

        # State
        self._source_type      = "NONE"        # "VCD", "DVD", "NONE"
        self._source_disc_type = ""
        self._videos: list[dict] = []
        self._cards:  list[VideoCard] = []
        self._selected_indices: set[int] = set()
        self._selected_chapters: set[tuple[int, int]] = set()  # set of (card_idx, chapter_num)
        self._dvd_rip_mode     = tk.StringVar(value="title")   # "title" or "chapter"
        self._output_folder    = tk.StringVar(value="")
        self._output_format    = tk.StringVar(value="MP4")
        self._output_mode      = tk.StringVar(value="video")   # "video" or "audio"
        self._audio_format     = tk.StringVar(value="WAV")     # "WAV" or "MP3"
        self._vcd_path         = tk.StringVar(value="")
        self._dat_rename_mp4   = tk.BooleanVar(value=True)   # DAT sub-option: rename to .mp4
        self._use_1080p        = tk.BooleanVar(value=False)  # MP4/MOV resolution: False=original
        self._auto_open_folder = tk.BooleanVar(value=True)   # Auto open folder after rip
        self._dvd_title_folder_var = tk.BooleanVar(value=False)  # Create folder with DVD title
        self._dvd_timeline_var = tk.BooleanVar(value=False)  # Generate Chapter Timeline File (.txt)
        self._dvd_selected_audio_tracks: dict[int, str] = {}  # title_number -> track_id
        self._active_dvd_title_idx: int = 0
        self._audio_track_var  = tk.StringVar(value="")
        self._target_title_var = tk.StringVar(value="")
        self._ripping          = False
        self._scanning         = False
        self._poll_job         = None
        self._cancel_requested = False
        self._current_proc     = None
        
        # Batch rename session memory
        self._batch_seq_enabled = False
        self._batch_base_name   = "Track"
        self._batch_start_index = "1"
        
        # Windows taskbar progress
        self._taskbar_progress = WindowsTaskbarProgress(self)
        self._about_dialog     = None
        self._last_non_vcd_drive = None
        self._unsupported_dlg_open = False

        i18n.set_refresh_callback(self._refresh_ui)
        i18n.set_theme_callback(self._on_theme_changed)
        i18n.set_scale_callback(self._on_scale_changed)

        # FFmpeg
        self._ffmpeg, self._ffprobe = find_ffmpeg()
        self._handbrake = dvd_engine.find_handbrake()
        self._handbrake_version = dvd_engine.get_handbrake_version(self._handbrake) if self._handbrake else None

        self._build_ui()
        self._apply_ttk_styles()
        self._start_drive_poll()

        # Log tool status
        if self._handbrake:
            self._log.log(f"HandBrakeCLI detected: {self._handbrake_version or self._handbrake}", "success")
        else:
            self._log.log("HandBrakeCLI not detected. DVD pipeline will use FFmpeg / IFO backend.", "info")

        # App icon — multi-resolution CompactDisc.ico
        self._set_window_icon(self)
        self.after(50, lambda: self._set_window_icon(self))
        self.after(200, lambda: self._set_window_icon(self))

        # Global MouseWheel scroll dispatcher
        self.bind_all("<MouseWheel>", self._on_global_mousewheel)

        if not self._ffmpeg:
            self._show_ffmpeg_warning()

        # Check for interrupted/stale DVD scan session from a previous run (e.g. system crash or BSOD)
        self._stale_check_job = self.after(500, self._check_stale_dvd_scan_session)

    def _apply_window_scale(self):
        s = i18n.get_scale_factor()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        target_w = min(int(round(1360 * s)), screen_w - 40)
        target_h = min(int(round(920 * s)), screen_h - 80)
        min_w = min(int(round(1100 * s)), screen_w - 60)
        min_h = min(int(round(750 * s)), screen_h - 100)
        self.minsize(min_w, min_h)
        if self.state() != "zoomed":
            self.geometry(f"{target_w}x{target_h}")

    def _schedule_rebuild_ui(self, delay_ms=120):
        if getattr(self, "_rebuild_ui_job", None):
            try:
                self.after_cancel(self._rebuild_ui_job)
            except Exception:
                pass
            self._rebuild_ui_job = None

        def _do_rebuild():
            self._rebuild_ui_job = None
            if self.winfo_exists():
                self._rebuild_ui()
                self._set_window_icon(self)
                self.after(50, lambda: self._set_window_icon(self))
                self.bind_all("<MouseWheel>", self._on_global_mousewheel)
                if not self._ffmpeg:
                    self._show_ffmpeg_warning()

        if delay_ms > 0:
            self._rebuild_ui_job = self.after(delay_ms, _do_rebuild)
        else:
            self.after_idle(_do_rebuild)

    def _on_scale_changed(self, scale_factor):
        apply_font_scale(self, scale_factor)
        self._apply_window_scale()
        has_dialog = bool(hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists())
        if has_dialog:
            if hasattr(self._about_dialog, "update_scale"):
                try:
                    self._about_dialog.update_scale()
                except Exception:
                    pass
            self._schedule_rebuild_ui(delay_ms=120)
        else:
            self._rebuild_ui()
            # App icon — works for both plain Python and PyInstaller onedir
            self._set_window_icon(self)
            self.after(50, lambda: self._set_window_icon(self))

            # Global MouseWheel scroll dispatcher
            self.bind_all("<MouseWheel>", self._on_global_mousewheel)

            if not self._ffmpeg:
                self._show_ffmpeg_warning()

    def _on_theme_changed(self):
        self._rebuild_ui()

    def _apply_theme(self):
        # 1. Root window & Title bar
        self.configure(bg=COLORS["bg_dark"])
        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
            set_window_dark_mode(hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        # 2. TTK styles (progressbars, scrollbars)
        self._apply_ttk_styles()

        # 3. Header bar
        if hasattr(self, "_header"):
            self._header.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_logo_lbl") and self._logo_lbl:
            self._logo_lbl.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_title_lbl"):
            self._title_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_primary"])
        if hasattr(self, "_version_lbl"):
            self._version_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_muted"])
        if hasattr(self, "_clear_all_btn"):
            self._clear_all_btn.configure(
                bg=COLORS["bg_card"],
                fg=COLORS["text_muted"] if self._ripping else COLORS["text_secondary"],
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS["accent"]
            )
        if hasattr(self, "_console_btn"):
            self._console_btn.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                activebackground=COLORS["bg_hover"], activeforeground=COLORS["accent"]
            )
        if hasattr(self, "_about_btn"):
            self._about_btn.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                activebackground=COLORS["bg_hover"], activeforeground=COLORS["accent"]
            )
        if hasattr(self, "_batch_rename_btn"):
            self._batch_rename_btn.configure(
                bg=COLORS["bg_card"], fg=COLORS["accent"],
                activebackground=COLORS["bg_hover"], activeforeground=COLORS["accent_hover"]
            )
        if hasattr(self, "_eject_btn"):
            self._eject_btn.configure(
                bg=COLORS["bg_card"], fg=COLORS["warning"],
                activebackground=COLORS["bg_hover"], activeforeground=COLORS["warning"]
            )
        if hasattr(self, "_drive_lbl"):
            d = self._vcd_path.get()
            self._drive_lbl.configure(
                bg=COLORS["bg_panel"],
                fg=COLORS["text_secondary"] if d else COLORS["text_muted"]
            )

        # 4. Left sidebar
        if hasattr(self, "_top_frame"):
            self._top_frame.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_left_sidebar"):
            self._left_sidebar.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_left_scroll_area"):
            self._left_scroll_area.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_left_canvas"):
            self._left_canvas.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_left_content"):
            self._left_content.configure(bg=COLORS["bg_panel"])

        if hasattr(self, "_source_section_lbl"):
            self._source_section_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["accent"])
        if hasattr(self, "_detect_card"):
            self._detect_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        if hasattr(self, "_detect_icon"):
            self._detect_icon.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_detect_label"):
            d = self._vcd_path.get()
            fg_col = COLORS["cyan"] if getattr(self, "_videos", None) else (COLORS["success"] if (d and is_vcd_folder(d)) else COLORS["text_muted"])
            self._detect_label.configure(
                bg=COLORS["bg_card"],
                fg=fg_col
            )
        if hasattr(self, "_detected_drive_lbl"):
            self._detected_drive_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["accent"])

        if hasattr(self, "_browse_btn"):
            self._browse_btn.apply_theme()
        if hasattr(self, "_scan_btn"):
            self._scan_btn.apply_theme()
        if hasattr(self, "_path_lbl"):
            self._path_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_muted"])
        if hasattr(self, "_left_sep"):
            self._left_sep.configure(bg=COLORS["border"])

        if hasattr(self, "_sel_section_lbl"):
            self._sel_section_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["accent"])
        if hasattr(self, "_sel_row"):
            self._sel_row.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_sel_all_btn"):
            self._sel_all_btn.apply_theme()
        if hasattr(self, "_sel_none_btn"):
            self._sel_none_btn.apply_theme()
        if hasattr(self, "_sel_count_lbl"):
            self._sel_count_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_muted"])

        # 5. Right sidebar
        if hasattr(self, "_right_sidebar"):
            self._right_sidebar.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_right_bottom_frame"):
            self._right_bottom_frame.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_rip_btn"):
            self._rip_btn.apply_theme()
        if hasattr(self, "_stop_btn"):
            self._stop_btn.apply_theme()
        if hasattr(self, "_right_scroll_area"):
            self._right_scroll_area.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_right_canvas"):
            self._right_canvas.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_right_content"):
            self._right_content.configure(bg=COLORS["bg_panel"])

        if hasattr(self, "_format_section_lbl"):
            self._format_section_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["accent"])
        if hasattr(self, "_mode_card"):
            self._mode_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        if hasattr(self, "_video_mode_rb"):
            self._video_mode_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["accent"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["accent"]
            )
        if hasattr(self, "_audio_mode_rb"):
            self._audio_mode_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["success"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["success"]
            )
        if hasattr(self, "_both_mode_rb"):
            self._both_mode_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["warning"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["warning"]
            )

        if hasattr(self, "_fmt_container"):
            self._fmt_container.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_video_panel"):
            self._video_panel.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_video_fmt_lbl"):
            self._video_fmt_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_secondary"])
        if hasattr(self, "_fmt_card"):
            self._fmt_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        for item in getattr(self, "_fmt_items", []):
            item["frame"].configure(bg=COLORS["bg_card"])
            item["rb"].configure(
                bg=COLORS["bg_card"], selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"]
            )
            item["lbl"].configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])

        if hasattr(self, "_dat_suboption_frame"):
            self._dat_suboption_frame.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        if hasattr(self, "_dat_mode_lbl"):
            self._dat_mode_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        if hasattr(self, "_rb_row"):
            self._rb_row.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_dat_raw_rb"):
            self._dat_raw_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_panel"], activebackground=COLORS["bg_card"]
            )
        if hasattr(self, "_dat_mp4_rb"):
            self._dat_mp4_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_panel"], activebackground=COLORS["bg_card"]
            )

        if hasattr(self, "_res_suboption_frame"):
            self._res_suboption_frame.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        if hasattr(self, "_res_title_lbl"):
            self._res_title_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        if hasattr(self, "_res_rb_row"):
            self._res_rb_row.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_res_orig_rb"):
            self._res_orig_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_panel"], activebackground=COLORS["bg_card"]
            )
        if hasattr(self, "_res_1080p_rb"):
            self._res_1080p_rb.configure(
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_panel"], activebackground=COLORS["bg_card"]
            )

        if hasattr(self, "_audio_track_panel"):
            self._audio_track_panel.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_audio_track_lbl"):
            self._audio_track_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_secondary"])
        if hasattr(self, "_audio_track_card"):
            self._audio_track_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        if hasattr(self, "_audio_track_title_frame"):
            self._audio_track_title_frame.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_target_title_lbl"):
            self._target_title_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        if hasattr(self, "_audio_track_cb_frame"):
            self._audio_track_cb_frame.configure(bg=COLORS["bg_card"])
        if hasattr(self, "_audio_track_detail_lbl"):
            self._audio_track_detail_lbl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])

        if hasattr(self, "_audio_panel"):
            self._audio_panel.configure(bg=COLORS["bg_panel"])
        if hasattr(self, "_audio_fmt_lbl"):
            self._audio_fmt_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_secondary"])
        if hasattr(self, "_audio_fmt_card"):
            self._audio_fmt_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        for item in getattr(self, "_audio_items", []):
            item["frame"].configure(bg=COLORS["bg_card"])
            item["rb"].configure(
                bg=COLORS["bg_card"], selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"]
            )
            item["lbl"].configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])

        if hasattr(self, "_update_format_greyout"):
            self._update_format_greyout()

        if hasattr(self, "_right_sep"):
            self._right_sep.configure(bg=COLORS["border"])
        if hasattr(self, "_output_section_lbl"):
            self._output_section_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["accent"])
        if hasattr(self, "_choose_folder_btn"):
            self._choose_folder_btn.apply_theme()
        if hasattr(self, "_out_lbl"):
            self._out_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_muted"])
        if hasattr(self, "_dvd_title_folder_chk"):
            self._dvd_title_folder_chk.configure(
                bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_panel"]
            )
        if hasattr(self, "_auto_open_chk"):
            self._auto_open_chk.configure(
                bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_panel"]
            )
        if hasattr(self, "_dvd_timeline_chk"):
            self._dvd_timeline_chk.configure(
                bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_panel"]
            )

        # 6. Center Content (Video List & Empty State)
        if hasattr(self, "_content_container"):
            self._content_container.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_content_title_bar"):
            self._content_title_bar.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_content_title"):
            self._content_title.configure(bg=COLORS["bg_dark"], fg=COLORS["text_primary"])
        if hasattr(self, "_video_count_badge"):
            self._video_count_badge.configure(bg=COLORS["accent_dim"], fg=COLORS["text_primary"])
        if hasattr(self, "_list_container"):
            self._list_container.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_canvas"):
            self._canvas.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_list_frame"):
            self._list_frame.configure(bg=COLORS["bg_dark"])

        if hasattr(self, "_empty_frame"):
            self._empty_frame.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_empty_icon_lbl"):
            self._empty_icon_lbl.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_empty_title_lbl"):
            self._empty_title_lbl.configure(bg=COLORS["bg_dark"], fg=COLORS["text_secondary"])
        if hasattr(self, "_empty_sub_lbl"):
            self._empty_sub_lbl.configure(bg=COLORS["bg_dark"], fg=COLORS["text_muted"])

        for card in self._cards:
            card.apply_theme()

        # Progress bars
        if hasattr(self, "_scan_progress_frame"):
            self._scan_progress_frame.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_scan_progress_lbl"):
            self._scan_progress_lbl.configure(bg=COLORS["bg_dark"], fg=COLORS["text_secondary"])
        if hasattr(self, "_scan_progress_pct"):
            self._scan_progress_pct.configure(bg=COLORS["bg_dark"], fg=COLORS["cyan"])
        if hasattr(self, "_progress_frame"):
            self._progress_frame.configure(bg=COLORS["bg_dark"])
        if hasattr(self, "_progress_lbl"):
            self._progress_lbl.configure(bg=COLORS["bg_dark"], fg=COLORS["text_secondary"])
        if hasattr(self, "_progress_pct"):
            self._progress_pct.configure(bg=COLORS["bg_dark"], fg=COLORS["accent"])

        # 7. Log Window
        if hasattr(self, "_log_window") and self._log_window.winfo_exists():
            self._log_window.configure(bg=COLORS["bg_dark"])
            if hasattr(self, "_log_header"):
                self._log_header.configure(bg=COLORS["bg_panel"])
            if hasattr(self, "_console_title_lbl"):
                self._console_title_lbl.configure(bg=COLORS["bg_panel"], fg=COLORS["text_secondary"])
            if hasattr(self, "_console_clear_btn"):
                self._console_clear_btn.configure(
                    bg=COLORS["bg_panel"], fg=COLORS["text_muted"],
                    activebackground=COLORS["bg_panel"]
                )
            if hasattr(self, "_log"):
                self._log.apply_theme()
            try:
                log_hwnd = ctypes.windll.user32.GetAncestor(self._log_window.winfo_id(), 2) or self._log_window.winfo_id()
                set_window_dark_mode(log_hwnd, i18n.get_effective_theme() == "dark")
            except Exception:
                pass

        # 8. Settings Dialog (if open)
        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            if hasattr(self._about_dialog, "update_theme"):
                self._about_dialog.update_theme()

    def _rebuild_ui(self):
        # Cancel any pending configure debounce jobs
        for job_attr in ("_canvas_resize_job", "_list_cfg_job", "_left_content_job", "_right_content_job", "_rebuild_ui_job"):
            job = getattr(self, job_attr, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, job_attr, None)

        # Clear cached canvas dimensions so newly built widgets configure cleanly
        self._last_canvas_width = None
        self._last_left_canvas_w = None
        self._last_right_canvas_w = None

        # Save log contents
        log_text = ""
        if hasattr(self, '_log') and hasattr(self._log, '_text'):
            try:
                log_text = self._log._text.get("1.0", "end")
            except Exception:
                pass

        # Destroy old log window so it gets recreated with new theme
        log_shown = False
        if hasattr(self, '_log_window') and self._log_window.winfo_exists():
            log_shown = (self._log_window.state() != "withdrawn" and self._log_window.state() != "iconic")
            self._log_window.destroy()

        # Destroy all direct child widgets of root (preserving _about_dialog if open)
        for child in list(self.winfo_children()):
            if hasattr(self, "_about_dialog") and self._about_dialog and child == self._about_dialog:
                continue
            try:
                child.destroy()
            except Exception:
                pass

        # Set root window background and native titlebar mode
        self.configure(bg=COLORS["bg_dark"])
        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
            set_window_dark_mode(hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        # Re-build UI
        self._build_ui()
        self._apply_ttk_styles()

        # Restore log
        if log_text.strip():
            self._log._text.configure(state="normal")
            self._log._text.delete("1.0", "end")
            self._log._text.insert("1.0", log_text.rstrip("\n") + "\n")
            self._log._text.see("end")
            self._log._text.configure(state="disabled")
        if log_shown:
            self._log_window.deiconify()

        # Restore video tracks if any
        if self._videos:
            saved_selected = set(self._selected_indices)
            self._cards.clear()
            self._selected_indices.clear()
            self._clear_list()
            if hasattr(self, "_empty_frame") and self._empty_frame.winfo_exists():
                self._empty_frame.pack_forget()

            for i, info in enumerate(self._videos):
                card = VideoCard(
                    self._list_frame, info, i,
                    on_toggle=self._on_card_toggle,
                    on_chapter_toggle=self._on_chapter_toggle
                )
                card.pack(fill="x", padx=4, pady=3)
                self._cards.append(card)

            for idx in saved_selected:
                if idx < len(self._cards):
                    self._cards[idx].set_selected(True)
                    self._selected_indices.add(idx)

            for (c_idx, c_num) in self._selected_chapters:
                if c_idx < len(self._cards):
                    self._cards[c_idx].set_chapter_selected(c_num, True)

            self._update_sel_count()
            self._update_format_visibility_for_source()
            self._update_audio_track_selector()
        else:
            self._clear_list()
            if hasattr(self, "_empty_frame") and self._empty_frame.winfo_exists():
                self._empty_frame.pack(fill="both", expand=True, pady=100)

        # Refresh all localized text & drive status
        self._refresh_ui()

        # Update about dialog if open
        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            if hasattr(self._about_dialog, "update_theme"):
                try:
                    self._about_dialog.update_theme()
                except Exception:
                    pass
            try:
                self._about_dialog.lift()
            except Exception:
                pass

    # ── UI Construction ──────────────────────
    def _build_ui(self):
        # Reset cached widths on UI construction so all canvases initialize their window item widths cleanly
        self._last_canvas_width = None
        self._last_left_canvas_w = None
        self._last_right_canvas_w = None

        # ── Header bar ──────────────────────
        self._header = tk.Frame(self, bg=COLORS["bg_panel"], height=scale_val(68))
        self._header.pack(fill="x", side="top")
        self._header.pack_propagate(False)
        header = self._header

        # Software logo on the left of title
        header_icon = get_header_icon(scale_val(32))
        if header_icon:
            self._logo_lbl = tk.Label(header, image=header_icon, bg=COLORS["bg_panel"])
            self._logo_lbl.image = header_icon
            self._logo_lbl.pack(side="left", padx=(scale_val(24), scale_val(10)), pady=0)
            self._title_lbl = tk.Label(
                header, text=t('header.title'),
                font=FONTS["title"], bg=COLORS["bg_panel"],
                fg=COLORS["text_primary"]
            )
            self._title_lbl.pack(side="left", padx=(0, scale_val(12)), pady=0)
        else:
            self._logo_lbl = None
            self._title_lbl = tk.Label(
                header, text=t('header.title'),
                font=FONTS["title"], bg=COLORS["bg_panel"],
                fg=COLORS["text_primary"]
            )
            self._title_lbl.pack(side="left", padx=scale_val(28), pady=0)

        self._version_lbl = tk.Label(
            header, text=f"v{APP_VERSION}",
            font=FONTS["body"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"]
        )
        self._version_lbl.pack(side="left", pady=(scale_val(16), 0))

        # Clear All button (Far Right, immediately right of Console Log)
        self._clear_all_btn = tk.Button(
            header, text=t('header.clear_all'),
            font=FONTS["badge"],
            bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["accent"],
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(6),
            cursor="hand2",
            command=self._clear_all_action
        )
        self._clear_all_btn.pack(side="right", padx=(scale_val(6), scale_val(24)))
        self._clear_all_tip = Tooltip(self._clear_all_btn, t('header.clear_all_tip'))

        # Console Log button (Immediately left of Clear All)
        self._console_btn = tk.Button(
            header, text=t('header.console'),
            font=FONTS["badge"],
            bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["accent"],
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(6),
            cursor="hand2",
            command=self._toggle_console
        )
        self._console_btn.pack(side="right", padx=scale_val(6))

        # Setting button
        self._about_btn = tk.Button(
            header, text=t('header.about'),
            font=FONTS["badge"],
            bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["accent"],
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(6),
            cursor="hand2",
            command=self._show_about
        )
        self._about_btn.pack(side="right", padx=scale_val(6))

        # Batch Rename button
        self._batch_rename_btn = tk.Button(
            header, text=t('header.batch_rename'),
            font=FONTS["badge"],
            bg=COLORS["bg_card"], fg=COLORS["accent"],
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["accent_hover"],
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(6),
            cursor="hand2",
            command=self._batch_rename
        )
        self._batch_rename_btn.pack(side="right", padx=scale_val(6))

        # Eject Disc button
        self._eject_btn = tk.Button(
            header, text=t('header.eject_disc'),
            font=FONTS["badge"],
            bg=COLORS["bg_card"], fg=COLORS["warning"],
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["warning"],
            relief="flat", bd=0, padx=scale_val(14), pady=scale_val(6),
            cursor="hand2",
            command=self._eject_disc
        )
        self._eject_btn.pack(side="right", padx=scale_val(6))

        # Drive status indicator
        self._drive_lbl = tk.Label(
            header, text=t('header.no_disc'),
            font=FONTS["badge"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"]
        )
        self._drive_lbl.pack(side="right", padx=(scale_val(20), scale_val(6)))

        # ── Main layout (full height) ────────────────
        self._top_frame = tk.Frame(self, bg=COLORS["bg_dark"])
        self._top_frame.pack(fill="both", expand=True)
        top_frame = self._top_frame

        # ── Left sidebar (Source & Selection) ──
        self._left_sidebar = tk.Frame(top_frame, bg=COLORS["bg_panel"], width=scale_val(280))
        self._left_sidebar.pack(side="left", fill="y")
        self._left_sidebar.pack_propagate(False)
        left_sidebar = self._left_sidebar

        self._left_scroll_area = tk.Frame(left_sidebar, bg=COLORS["bg_panel"])
        self._left_scroll_area.pack(fill="both", expand=True)

        self._left_canvas = tk.Canvas(self._left_scroll_area, bg=COLORS["bg_panel"], highlightthickness=0)
        left_vsb = ttk.Scrollbar(self._left_scroll_area, orient="vertical", command=self._left_canvas.yview)
        self._left_canvas.configure(yscrollcommand=left_vsb.set)
        left_vsb.pack(side="right", fill="y")

        self._left_content = tk.Frame(self._left_canvas, bg=COLORS["bg_panel"])
        left_window = self._left_canvas.create_window((0, 0), window=self._left_content, anchor="nw")

        def _on_left_canvas_cfg(e):
            try:
                cur_item_w = int(float(self._left_canvas.itemcget(left_window, "width")))
            except Exception:
                cur_item_w = 0
            if getattr(self, "_last_left_canvas_w", None) != e.width or cur_item_w != e.width:
                self._last_left_canvas_w = e.width
                self._left_canvas.itemconfig(left_window, width=e.width)
        self._left_canvas.bind("<Configure>", _on_left_canvas_cfg)

        def _on_left_content_cfg(e):
            if getattr(self, "_left_content_job", None):
                try:
                    self.after_cancel(self._left_content_job)
                except Exception:
                    pass
            self._left_content_job = self.after(20, lambda: self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all")) if hasattr(self, "_left_canvas") and self._left_canvas.winfo_exists() else None)
        self._left_content.bind("<Configure>", _on_left_content_cfg)
        self._left_canvas._can_scroll = True
        self._left_canvas.pack(side="left", fill="both", expand=True)
        self._build_left_sidebar(self._left_content)

        # ── Right sidebar (Output Format, Output Folder, Rip Controls) ──
        # Pinned to side="right" before center container so it is strictly anchored to the window's right border
        self._right_sidebar = tk.Frame(top_frame, bg=COLORS["bg_panel"], width=scale_val(420))
        self._right_sidebar.pack(side="right", fill="y")
        self._right_sidebar.pack_propagate(False)
        right_sidebar = self._right_sidebar

        # Fixed bottom container for "Start Ripping" and "Stop Ripping" buttons
        self._right_bottom_frame = tk.Frame(right_sidebar, bg=COLORS["bg_panel"])
        self._right_bottom_frame.pack(side="bottom", fill="x", padx=scale_val(16), pady=scale_val(16))

        self._rip_btn = FlatButton(
            self._right_bottom_frame, text=t('rip.start'), icon="⚡",
            style="primary", command=self._start_rip
        )
        self._rip_btn.pack(fill="x", pady=(0, 8))

        self._stop_btn = FlatButton(
            self._right_bottom_frame, text=t('rip.stop'), icon="⏹",
            style="danger", command=self._stop_rip
        )
        self._stop_btn.pack(fill="x")
        self._stop_btn.configure_state(False)

        # Scrollable container for Output Format & Output Folder
        self._right_scroll_area = tk.Frame(right_sidebar, bg=COLORS["bg_panel"])
        self._right_scroll_area.pack(side="top", fill="both", expand=True)

        self._right_canvas = tk.Canvas(self._right_scroll_area, bg=COLORS["bg_panel"], highlightthickness=0)
        right_vsb = ttk.Scrollbar(self._right_scroll_area, orient="vertical", command=self._right_canvas.yview)
        self._right_canvas.configure(yscrollcommand=right_vsb.set)
        right_vsb.pack(side="right", fill="y")

        self._right_content = tk.Frame(self._right_canvas, bg=COLORS["bg_panel"])
        right_window = self._right_canvas.create_window((0, 0), window=self._right_content, anchor="nw")

        def _on_right_canvas_cfg(e):
            try:
                cur_item_w = int(float(self._right_canvas.itemcget(right_window, "width")))
            except Exception:
                cur_item_w = 0
            if getattr(self, "_last_right_canvas_w", None) != e.width or cur_item_w != e.width:
                self._last_right_canvas_w = e.width
                self._right_canvas.itemconfig(right_window, width=e.width)
        self._right_canvas.bind("<Configure>", _on_right_canvas_cfg)

        def _on_right_content_cfg(e):
            if getattr(self, "_right_content_job", None):
                try:
                    self.after_cancel(self._right_content_job)
                except Exception:
                    pass
            self._right_content_job = self.after(20, lambda: self._right_canvas.configure(scrollregion=self._right_canvas.bbox("all")) if hasattr(self, "_right_canvas") and self._right_canvas.winfo_exists() else None)
        self._right_content.bind("<Configure>", _on_right_content_cfg)
        self._right_canvas._can_scroll = True
        self._right_canvas.pack(side="left", fill="both", expand=True)
        self._build_right_sidebar(self._right_content)

        # ── Center content area (VCD Tracks) ──
        # Absorbs all remaining space between left and right sidebars dynamically
        self._content_container = tk.Frame(top_frame, bg=COLORS["bg_dark"])
        self._content_container.pack(side="left", fill="both", expand=True)
        self._build_content(self._content_container)

        # ── Console Log (popup window) ───────────────
        self._log_window = tk.Toplevel(self)
        self._log_window.title(f"Console Log — {APP_NAME}")
        self._log_window.configure(bg=COLORS["bg_dark"])
        self._log_window.geometry(f"{scale_val(700)}x{scale_val(400)}")
        self._log_window.protocol("WM_DELETE_WINDOW", self._log_window.withdraw)
        self._log_window.withdraw()  # Start hidden

        # Set icon on log window
        self._set_window_icon(self._log_window)

        self._log_header = tk.Frame(self._log_window, bg=COLORS["bg_panel"], height=scale_val(36))
        self._log_header.pack(fill="x")
        self._log_header.pack_propagate(False)
        self._console_title_lbl = tk.Label(
            self._log_header, text=t('console.title'),
            font=FONTS["subhead"], bg=COLORS["bg_panel"],
            fg=COLORS["text_secondary"]
        )
        self._console_title_lbl.pack(side="left", pady=6)
        self._console_clear_btn = tk.Button(
            self._log_header, text=t('console.clear'),
            font=FONTS["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"], bd=0, cursor="hand2",
            activebackground=COLORS["bg_panel"],
            command=lambda: self._log.clear()
        )
        self._console_clear_btn.pack(side="right", padx=16)

        self._log = LogConsole(self._log_window)
        self._log.pack(fill="both", expand=True)

    def _build_left_sidebar(self, parent):
        pad = {"padx": 20}

        # ── Source section ───────────────────
        self._source_section_lbl = self._section_label(parent, t('source.title'))

        # Auto-detect display
        self._detect_card = tk.Frame(
            parent, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        self._detect_card.pack(fill="x", padx=20, pady=(6, 0))
        detect_card = self._detect_card

        self._detect_icon = tk.Label(
            detect_card, text="💿", font=FONTS["emoji_32"],
            bg=COLORS["bg_card"]
        )
        self._detect_icon.pack(pady=(14, 0))

        self._detect_label = tk.Label(
            detect_card, text=t('drive.insert_vcd'),
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["text_muted"], justify="center"
        )
        self._detect_label.pack(pady=(6, 0))

        self._detected_drive_lbl = tk.Label(
            detect_card, text="",
            font=FONTS["subhead"], bg=COLORS["bg_card"],
            fg=COLORS["accent"]
        )
        self._detected_drive_lbl.pack(pady=(4, 12))

        # Manual browse button
        self._browse_btn = FlatButton(
            parent, text=t('source.browse'),
            icon="📁",
            style="ghost", command=self._browse_source
        )
        self._browse_btn.pack(fill="x", padx=20, pady=(10, 0))

        # Scan button
        self._scan_btn = FlatButton(
            parent, text=t('source.scan'),
            icon="🔍",
            style="primary", command=self._scan_disc
        )
        self._scan_btn.pack(fill="x", padx=20, pady=(8, 0))

        # Path display
        self._path_lbl = tk.Label(
            parent, textvariable=self._vcd_path,
            font=FONTS["mono"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"], wraplength=scale_val(240),
            justify="left"
        )
        self._path_lbl.pack(fill="x", padx=20, pady=(6, 0))

        # ── Separator ───────────────────────
        self._left_sep = tk.Frame(parent, bg=COLORS["border"], height=1)
        self._left_sep.pack(fill="x", padx=20, pady=12)

        # ── Selection section ────────────────
        self._sel_section_lbl = self._section_label(parent, t('selection.title'))

        self._sel_row = tk.Frame(parent, bg=COLORS["bg_panel"])
        self._sel_row.pack(fill="x", padx=20, pady=(6, 0))
        sel_row = self._sel_row

        self._sel_all_btn = FlatButton(
            sel_row, text=t('selection.all'),
            icon="☐",
            style="ghost", command=self._select_all
        )
        self._sel_all_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._sel_none_btn = FlatButton(
            sel_row, text=t('selection.none'),
            icon="☐",
            style="ghost", command=self._select_none
        )
        self._sel_none_btn.pack(side="left", fill="x", expand=True)

        self._sel_count_lbl = tk.Label(
            parent, text=t('selection.count').format(n=0, total=0),
            font=FONTS["body"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"]
        )
        self._sel_count_lbl.pack(padx=20, pady=(6, 12))

    def _build_right_sidebar(self, parent):
        # ── Output section ───────────────────
        self._format_section_lbl = self._section_label(parent, t('format.title'))

        # ── Mode toggle: Video / Audio Only (boxed 2-line card) ──
        self._mode_card = tk.Frame(
            parent, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        self._mode_card.pack(fill="x", padx=20, pady=(8, 0))
        mode_card = self._mode_card

        self._video_mode_rb = tk.Radiobutton(
            mode_card, text=t('format.video_mode'),
            variable=self._output_mode, value="video",
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["accent"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            cursor="hand2",
            command=self._on_mode_change
        )
        self._video_mode_rb.pack(anchor="w", padx=16, pady=(8, 4))

        self._audio_mode_rb = tk.Radiobutton(
            mode_card, text=t('format.audio_mode'),
            variable=self._output_mode, value="audio",
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["success"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_card"],
            activeforeground=COLORS["success"],
            cursor="hand2",
            command=self._on_mode_change
        )
        self._audio_mode_rb.pack(anchor="w", padx=16, pady=(0, 4))

        self._both_mode_rb = tk.Radiobutton(
            mode_card, text=t('format.both_mode'),
            variable=self._output_mode, value="both",
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"], fg=COLORS["warning"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_card"],
            activeforeground=COLORS["warning"],
            cursor="hand2",
            command=self._on_mode_change
        )
        self._both_mode_rb.pack(anchor="w", padx=16, pady=(0, 8))

        # ── Format options container (holds video_panel & audio_panel) ──
        self._fmt_container = tk.Frame(parent, bg=COLORS["bg_panel"])
        self._fmt_container.pack(fill="x", padx=0, pady=(4, 0))

        # ── Video sub-panel ─────────────────
        self._video_panel = tk.Frame(self._fmt_container, bg=COLORS["bg_panel"])
        self._video_panel.pack(fill="x", padx=0, pady=0)

        self._video_fmt_lbl = tk.Label(
            self._video_panel, text=t('format.video_lbl'),
            font=FONTS["small_bold"], bg=COLORS["bg_panel"],
            fg=COLORS["text_secondary"]
        )
        self._video_fmt_lbl.pack(anchor="w", padx=20, pady=(8, 4))

        self._fmt_card = tk.Frame(
            self._video_panel, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        self._fmt_card.pack(fill="x", padx=20, pady=(0, 4))
        fmt_card = self._fmt_card

        self._fmt_desc_lbls = {}
        self._fmt_items = []
        for idx, (fmt, info) in enumerate(OUTPUT_FORMATS.items()):
            item_frame = tk.Frame(fmt_card, bg=COLORS["bg_card"])
            item_frame.pack(fill="x", padx=14, pady=(6 if idx == 0 else 4, 6))

            rb = tk.Radiobutton(
                item_frame, text=fmt,
                variable=self._output_format, value=fmt,
                font=FONTS["body_bold"],
                bg=COLORS["bg_card"],
                fg=info["color"],
                selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"],
                activeforeground=info["color"],
                cursor="hand2",
                command=self._on_format_change
            )
            rb.pack(anchor="w")

            desc_key = f"format.{fmt.lower()}_desc"
            desc_lbl = tk.Label(
                item_frame, text=t(desc_key),
                font=FONTS["tiny"], bg=COLORS["bg_card"],
                fg=COLORS["text_secondary"], justify="left"
            )
            desc_lbl.pack(anchor="w", padx=(28, 0), pady=(1, 0))
            self._fmt_desc_lbls[fmt] = desc_lbl
            self._fmt_items.append({"fmt": fmt, "frame": item_frame, "rb": rb, "lbl": desc_lbl})

        # DAT sub-option
        self._dat_suboption_frame = tk.Frame(self._video_panel, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"], highlightthickness=1)
        self._dat_suboption_frame.pack(fill="x", padx=20, pady=(6, 0))

        self._dat_mode_lbl = tk.Label(
            self._dat_suboption_frame, text=t('format.dat_mode_lbl'),
            font=FONTS["small_bold"], bg=COLORS["bg_card"],
            fg=COLORS["text_secondary"]
        )
        self._dat_mode_lbl.pack(anchor="w", padx=14, pady=(8, 4))

        self._rb_row = tk.Frame(self._dat_suboption_frame, bg=COLORS["bg_card"])
        self._rb_row.pack(fill="x", padx=14, pady=(0, 8))
        rb_row = self._rb_row

        self._dat_raw_rb = tk.Radiobutton(
            rb_row, text=t('format.dat_raw'),
            variable=self._dat_rename_mp4, value=False,
            font=FONTS["small"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel"],
            activebackground=COLORS["bg_card"],
            cursor="hand2"
        )
        self._dat_raw_rb.pack(anchor="w")

        self._dat_mp4_rb = tk.Radiobutton(
            rb_row, text=t('format.dat_mp4'),
            variable=self._dat_rename_mp4, value=True,
            font=FONTS["small"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel"],
            activebackground=COLORS["bg_card"],
            cursor="hand2"
        )
        self._dat_mp4_rb.pack(anchor="w", pady=(4, 0))

        # ── MP4 / MOV resolution sub-panel ──────
        self._res_suboption_frame = tk.Frame(self._video_panel, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"], highlightthickness=1)
        # hidden by default (only shown for MP4/MOV)

        self._res_title_lbl = tk.Label(
            self._res_suboption_frame, text=t('format.res_title'),
            font=FONTS["small_bold"], bg=COLORS["bg_card"],
            fg=COLORS["text_secondary"]
        )
        self._res_title_lbl.pack(anchor="w", padx=14, pady=(8, 4))

        self._res_rb_row = tk.Frame(self._res_suboption_frame, bg=COLORS["bg_card"])
        self._res_rb_row.pack(fill="x", padx=14, pady=(0, 8))
        res_rb_row = self._res_rb_row

        self._res_orig_rb = tk.Radiobutton(
            res_rb_row, text=t('format.res_orig'),
            variable=self._use_1080p, value=False,
            font=FONTS["small_bold"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel"],
            activebackground=COLORS["bg_card"],
            cursor="hand2"
        )
        self._res_orig_rb.pack(anchor="w")

        self._res_1080p_rb = tk.Radiobutton(
            res_rb_row, text=t('format.res_1080p'),
            variable=self._use_1080p, value=True,
            font=FONTS["small_bold"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel"],
            activebackground=COLORS["bg_card"],
            cursor="hand2"
        )
        self._res_1080p_rb.pack(anchor="w", pady=(6, 0))

        # ── DVD Audio Track sub-panel ─────────────
        self._audio_track_panel = tk.Frame(self._fmt_container, bg=COLORS["bg_panel"])
        # (Packed dynamically in _update_format_visibility_for_source before _audio_panel for DVD sources)

        self._audio_track_lbl = tk.Label(
            self._audio_track_panel, text=t('format.audio_track_lbl'),
            font=FONTS["small_bold"], bg=COLORS["bg_panel"],
            fg=COLORS["text_secondary"]
        )
        self._audio_track_lbl.pack(anchor="w", padx=20, pady=(8, 4))

        self._audio_track_card = tk.Frame(
            self._audio_track_panel, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        self._audio_track_card.pack(fill="x", padx=20, pady=(0, 4))

        # Title switcher row (displayed when multiple DVD titles exist)
        self._audio_track_title_frame = tk.Frame(self._audio_track_card, bg=COLORS["bg_card"])
        self._audio_track_title_frame.pack(fill="x", padx=12, pady=(8, 4))

        self._target_title_lbl = tk.Label(
            self._audio_track_title_frame, text=t('format.target_title_lbl'),
            font=FONTS["tiny"], bg=COLORS["bg_card"],
            fg=COLORS["text_secondary"]
        )
        self._target_title_lbl.pack(anchor="w")

        self._target_title_cb = ttk.Combobox(
            self._audio_track_title_frame,
            textvariable=self._target_title_var,
            state="readonly",
            style="AudioTrack.TCombobox",
            font=FONTS["small"]
        )
        self._target_title_cb.pack(fill="x", pady=(2, 0))
        self._target_title_cb.bind("<<ComboboxSelected>>", self._on_audio_track_title_changed)

        # Track combobox frame
        self._audio_track_cb_frame = tk.Frame(self._audio_track_card, bg=COLORS["bg_card"])
        self._audio_track_cb_frame.pack(fill="x", padx=12, pady=(4, 6))

        self._audio_track_cb = ttk.Combobox(
            self._audio_track_cb_frame,
            textvariable=self._audio_track_var,
            state="readonly",
            style="AudioTrack.TCombobox",
            font=FONTS["small"]
        )
        self._audio_track_cb.pack(fill="x")
        self._audio_track_cb.bind("<<ComboboxSelected>>", self._on_audio_track_selected)

        # Track metadata details label
        self._audio_track_detail_lbl = tk.Label(
            self._audio_track_card,
            text="",
            font=FONTS["tiny"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_secondary"],
            justify="left",
            wraplength=scale_val(220)
        )
        self._audio_track_detail_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Audio sub-panel ──────────────────
        self._audio_panel = tk.Frame(self._fmt_container, bg=COLORS["bg_panel"])
        self._audio_panel.pack(fill="x", padx=0, pady=(6, 0))

        self._audio_fmt_lbl = tk.Label(
            self._audio_panel, text=t('format.audio_lbl'),
            font=FONTS["small_bold"], bg=COLORS["bg_panel"],
            fg=COLORS["text_secondary"]
        )
        self._audio_fmt_lbl.pack(anchor="w", padx=20, pady=(8, 4))

        self._audio_fmt_card = tk.Frame(
            self._audio_panel, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1
        )
        self._audio_fmt_card.pack(fill="x", padx=20, pady=(0, 4))
        audio_fmt_card = self._audio_fmt_card

        self._audio_desc_lbls = {}
        self._audio_items = []
        for idx, (afmt, ainfo) in enumerate(AUDIO_FORMATS.items()):
            aitem_frame = tk.Frame(audio_fmt_card, bg=COLORS["bg_card"])
            aitem_frame.pack(fill="x", padx=14, pady=(6 if idx == 0 else 4, 6))

            arb = tk.Radiobutton(
                aitem_frame, text=afmt,
                variable=self._audio_format, value=afmt,
                font=FONTS["body_bold"],
                bg=COLORS["bg_card"],
                fg=ainfo["color"],
                selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"],
                activeforeground=ainfo["color"],
                cursor="hand2",
                command=self._on_audio_format_change
            )
            arb.pack(anchor="w")

            desc_key = f"format.{afmt.lower()}_desc"
            adesc_lbl = tk.Label(
                aitem_frame, text=t(desc_key),
                font=FONTS["tiny"], bg=COLORS["bg_card"],
                fg=COLORS["text_secondary"], justify="left"
            )
            adesc_lbl.pack(anchor="w", padx=(28, 0), pady=(1, 0))
            self._audio_desc_lbls[afmt] = adesc_lbl
            self._audio_items.append({"fmt": afmt, "frame": aitem_frame, "rb": arb, "lbl": adesc_lbl})

        # ── Separator ───────────────────────
        self._right_sep = tk.Frame(parent, bg=COLORS["border"], height=1)
        self._right_sep.pack(fill="x", padx=20, pady=12)

        # ── Output folder section ────────────
        self._output_section_lbl = self._section_label(parent, t('output.title'))

        self._choose_folder_btn = FlatButton(
            parent, text=t('output.choose'),
            icon="💾",
            style="ghost", command=self._choose_output
        )
        self._choose_folder_btn.pack(fill="x", padx=20, pady=(10, 0))

        self._out_lbl = tk.Label(
            parent, textvariable=self._output_folder,
            font=FONTS["mono"], bg=COLORS["bg_panel"],
            fg=COLORS["text_muted"], wraplength=scale_val(360),
            justify="left"
        )
        self._out_lbl.pack(fill="x", padx=20, pady=(6, 4))

        self._dvd_title_folder_chk = tk.Checkbutton(
            parent, text=t('output.dvd_title_folder'),
            variable=self._dvd_title_folder_var,
            font=FONTS["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_panel"],
            cursor="hand2", relief="flat", bd=0
        )
        # Note: _dvd_title_folder_chk is packed dynamically above _auto_open_chk for DVD sources only

        self._auto_open_chk = tk.Checkbutton(
            parent, text=t('output.auto_open'),
            variable=self._auto_open_folder,
            font=FONTS["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_panel"],
            cursor="hand2", relief="flat", bd=0
        )
        self._auto_open_chk.pack(anchor="w", padx=20, pady=(4, 12))

        self._dvd_timeline_chk = tk.Checkbutton(
            parent, text=t('output.dvd_timeline'),
            variable=self._dvd_timeline_var,
            font=FONTS["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_dark"],
            activebackground=COLORS["bg_panel"],
            cursor="hand2", relief="flat", bd=0
        )
        # Note: _dvd_timeline_chk is packed dynamically below _auto_open_chk for DVD sources only

        # Apply initial greyout/enable state after all widgets are created
        self._update_format_greyout()

    def _build_content(self, parent):
        # ── Title bar ───────────────────────
        self._content_title_bar = tk.Frame(parent, bg=COLORS["bg_dark"], height=scale_val(56))
        self._content_title_bar.pack(fill="x")
        self._content_title_bar.pack_propagate(False)
        title_bar = self._content_title_bar

        self._content_title = tk.Label(
            title_bar, text=t('content.title'),
            font=FONTS["heading"], bg=COLORS["bg_dark"],
            fg=COLORS["text_primary"]
        )
        self._content_title.pack(side="left", padx=20, pady=14)

        self._video_count_badge = tk.Label(
            title_bar, text=t('content.badge_empty'),
            font=FONTS["badge"], bg=COLORS["accent_dim"],
            fg=COLORS["text_primary"], padx=10, pady=4
        )
        self._video_count_badge.pack(side="left", pady=16)


        # ── Scrollable video list ─────────────
        self._list_container = tk.Frame(parent, bg=COLORS["bg_dark"])
        self._list_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        list_container = self._list_container

        self._canvas = tk.Canvas(
            list_container, bg=COLORS["bg_dark"],
            highlightthickness=0
        )
        self._vsb = ttk.Scrollbar(
            list_container, orient="vertical",
            command=self._canvas.yview
        )
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._list_frame = tk.Frame(self._canvas, bg=COLORS["bg_dark"])
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw"
        )
        self._list_frame.bind("<Configure>", self._on_list_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas._can_scroll = True

        # Empty state
        self._empty_frame = tk.Frame(self._list_frame, bg=COLORS["bg_dark"])
        self._empty_frame.pack(fill="both", expand=True, pady=100)
        self._empty_icon_lbl = tk.Label(
            self._empty_frame, text="💿",
            font=FONTS["emoji_64"],
            bg=COLORS["bg_dark"]
        )
        self._empty_icon_lbl.pack()
        self._empty_title_lbl = tk.Label(
            self._empty_frame,
            text=t('content.empty_title'),
            font=FONTS["heading"], bg=COLORS["bg_dark"],
            fg=COLORS["text_secondary"], justify="center"
        )
        self._empty_title_lbl.pack(pady=(12, 0))
        self._empty_sub_lbl = tk.Label(
            self._empty_frame,
            text=t('content.empty_sub'),
            font=FONTS["body"], bg=COLORS["bg_dark"],
            fg=COLORS["text_muted"], justify="center"
        )
        self._empty_sub_lbl.pack(pady=(6, 0))

        # ── Scan progress bar (cyan, hidden initially) ──
        self._scan_progress_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        self._scan_progress_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._scan_progress_frame.pack_forget()

        self._scan_progress_lbl = tk.Label(
            self._scan_progress_frame, text="",
            font=FONTS["body"], bg=COLORS["bg_dark"],
            fg=COLORS["text_secondary"]
        )
        self._scan_progress_lbl.pack(side="left", padx=(8, 0))

        self._scan_progress_pct = tk.Label(
            self._scan_progress_frame, text="",
            font=FONTS["body"], bg=COLORS["bg_dark"],
            fg=COLORS["cyan"]
        )
        self._scan_progress_pct.pack(side="right", padx=(0, 8))

        self._scan_progress_var = tk.DoubleVar(value=0)
        self._scan_progress_bar = ttk.Progressbar(
            parent, variable=self._scan_progress_var,
            style="Scan.Horizontal.TProgressbar"
        )
        self._scan_progress_bar.pack(fill="x", padx=8, pady=(0, 8))
        self._scan_progress_bar.pack_forget()

        # ── Progress bar (hidden initially) ──
        self._progress_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        self._progress_frame.pack(fill="x", padx=8, pady=(0, 4))

        self._progress_lbl = tk.Label(
            self._progress_frame, text="",
            font=FONTS["body"], bg=COLORS["bg_dark"],
            fg=COLORS["text_secondary"]
        )
        self._progress_lbl.pack(side="left", padx=(8, 0))

        self._progress_pct = tk.Label(
            self._progress_frame, text="",
            font=FONTS["body"], bg=COLORS["bg_dark"],
            fg=COLORS["accent"]
        )
        self._progress_pct.pack(side="right", padx=(0, 8))

        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(
            parent, variable=self._progress_var,
            style="Custom.Horizontal.TProgressbar"
        )
        self._progress_bar.pack(fill="x", padx=8, pady=(0, 8))
        self._progress_bar.pack_forget()

    def _section_label(self, parent, text):
        lbl = tk.Label(
            parent, text=text,
            font=FONTS["badge"], bg=COLORS["bg_panel"],
            fg=COLORS["accent"], padx=20
        )
        lbl.pack(fill="x", pady=(18, 0))
        return lbl

    # ── TTK Styles ───────────────────────────
    def _apply_ttk_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor=COLORS["progress_bg"],
            background=COLORS["accent"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            bordercolor=COLORS["bg_dark"],
            thickness=8
        )
        style.configure(
            "Scan.Horizontal.TProgressbar",
            troughcolor=COLORS["progress_bg"],
            background=COLORS["cyan"],
            lightcolor=COLORS["cyan"],
            darkcolor=COLORS["cyan"],
            bordercolor=COLORS["bg_dark"],
            thickness=8
        )
        style.configure(
            "TScrollbar",
            troughcolor=COLORS["bg_dark"],
            background=COLORS["bg_card"],
            bordercolor=COLORS["bg_dark"],
            arrowcolor=COLORS["text_muted"]
        )
        style.configure(
            "AudioTrack.TCombobox",
            fieldbackground=COLORS["bg_card"],
            background=COLORS["bg_card"],
            foreground=COLORS["text_primary"],
            darkcolor=COLORS["border"],
            lightcolor=COLORS["border"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["accent"],
            padding=scale_val(4)
        )
        style.map(
            "AudioTrack.TCombobox",
            fieldbackground=[("readonly", COLORS["bg_card"]), ("disabled", COLORS["bg_dark"])],
            foreground=[("readonly", COLORS["text_primary"]), ("disabled", COLORS["text_muted"])],
            selectbackground=[("readonly", COLORS["accent_dim"])],
            selectforeground=[("readonly", COLORS["accent"])],
        )
        try:
            self.option_add("*TCombobox*Listbox.background", COLORS["bg_card"])
            self.option_add("*TCombobox*Listbox.foreground", COLORS["text_primary"])
            self.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent_dim"])
            self.option_add("*TCombobox*Listbox.selectForeground", COLORS["accent"])
            self.option_add("*TCombobox*Listbox.font", FONTS["small"])
        except Exception:
            pass

    # ── Drive polling ─────────────────────────
    def _start_drive_poll(self):
        self._poll_in_flight = False
        self._poll_drives()

    def _poll_drives(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

        if (
            getattr(self, "_poll_in_flight", False)
            or self._ripping
            or getattr(self, "_scanning", False)
            or getattr(self, "_pause_drive_poll", False)
        ):
            self._poll_job = self.after(3000, self._poll_drives)
            return

        self._poll_in_flight = True

        def _bg_poll():
            try:
                # Use global drive lock with timeout to prevent collision with active DVD/VCD scans
                drive_lock = dvd_diagnostics.get_drive_io_lock()
                if not drive_lock.acquire(timeout=1.0):
                    return

                try:
                    if getattr(self, "_pause_drive_poll", False):
                        return

                    drives = get_cd_drives()
                    vcd_drives = []
                    dvd_drives = []
                    non_vcd_drives = []
                    if drives:
                        for d in drives:
                            if getattr(self, "_pause_drive_poll", False):
                                break
                            check = disc_detector.detect_disc(d)
                            if check.is_dvd:
                                dvd_drives.append((d, check))
                            elif check.is_vcd:
                                vcd_drives.append((d, check))
                            elif check.disc_type not in ("No Disc", "Empty Disc", "Empty Drive", "Unreadable Disc"):
                                non_vcd_drives.append((d, check))
                finally:
                    drive_lock.release()

                theme_changed = False
                current_effective = None
                if i18n.theme == "system" and not self._ripping:
                    current_effective = i18n.get_effective_theme()
                    expected_bg = THEME_LIGHT["bg_dark"] if current_effective == "light" else THEME_DARK["bg_dark"]
                    if COLORS["bg_dark"] != expected_bg:
                        theme_changed = True

                self.after(0, lambda: self._apply_poll_results(drives, vcd_drives, dvd_drives, non_vcd_drives, theme_changed, current_effective))
            except Exception:
                pass
            finally:
                self._poll_in_flight = False
                def _reschedule_poll():
                    if getattr(self, "_poll_job", None):
                        try:
                            self.after_cancel(self._poll_job)
                        except Exception:
                            pass
                    self._poll_job = self.after(3000, self._poll_drives)
                try:
                    self.after(0, _reschedule_poll)
                except Exception:
                    pass

        threading.Thread(target=_bg_poll, daemon=True).start()

    def _update_format_visibility_for_source(self):
        """Dynamically configure format options based on current source (VCD vs DVD)."""
        if not hasattr(self, "_fmt_items") or not self._fmt_items:
            return
        video_active = (self._output_mode.get() in ("video", "both"))

        if self._source_type == "DVD":
            for item in self._fmt_items:
                if item.get("fmt") == "DAT":
                    item["frame"].pack_forget()
            if self._output_format.get() == "DAT":
                self._output_format.set("MP4")
            if hasattr(self, "_dat_suboption_frame"):
                self._dat_suboption_frame.pack_forget()
            if hasattr(self, "_res_suboption_frame"):
                if self._output_format.get() in ("MP4", "MOV"):
                    self._res_suboption_frame.pack(fill="x", padx=20, pady=(6, 0))
                else:
                    self._res_suboption_frame.pack_forget()
            if hasattr(self, "_scan_btn"):
                self._scan_btn.set_text(t('source.scan'), icon="🔍")
        else:
            for item in self._fmt_items:
                item["frame"].pack_forget()
            for idx, item in enumerate(self._fmt_items):
                item["frame"].pack(fill="x", padx=14, pady=(6 if idx == 0 else 4, 6))
            if hasattr(self, "_dat_suboption_frame"):
                if self._output_format.get() == "DAT":
                    self._dat_suboption_frame.pack(fill="x", padx=20, pady=(6, 0))
                else:
                    self._dat_suboption_frame.pack_forget()
            if hasattr(self, "_res_suboption_frame"):
                if self._output_format.get() in ("MP4", "MOV"):
                    self._res_suboption_frame.pack(fill="x", padx=20, pady=(6, 0))
                else:
                    self._res_suboption_frame.pack_forget()
            if hasattr(self, "_scan_btn"):
                self._scan_btn.set_text(t('source.scan_vcd') if self._source_type == "VCD" else t('source.scan'), icon="🔍")

        # DVD audio track panel and DVD title subfolder option are strictly visible only for DVD sources
        is_dvd = (self._source_type == "DVD") or any(v.get("disc_type") == "DVD" for v in getattr(self, "_videos", []))
        if (hasattr(self, "_audio_track_panel") and self._audio_track_panel.winfo_exists()
            and hasattr(self, "_audio_panel") and self._audio_panel.winfo_exists()):
            if is_dvd:
                self._audio_track_panel.pack(before=self._audio_panel, fill="x", padx=0, pady=(6, 0))
                self._update_audio_track_selector()
            else:
                self._audio_track_panel.pack_forget()

        if (hasattr(self, "_dvd_title_folder_chk") and self._dvd_title_folder_chk.winfo_exists()
            and hasattr(self, "_auto_open_chk") and self._auto_open_chk.winfo_exists()):
            if is_dvd:
                self._dvd_title_folder_chk.pack(before=self._auto_open_chk, anchor="w", padx=20, pady=(4, 2))
                self._auto_open_chk.pack_configure(pady=(2, 2))
                if hasattr(self, "_dvd_timeline_chk") and self._dvd_timeline_chk.winfo_exists():
                    self._dvd_timeline_chk.pack(after=self._auto_open_chk, anchor="w", padx=20, pady=(2, 12))
            else:
                self._dvd_title_folder_chk.pack_forget()
                if hasattr(self, "_dvd_timeline_chk") and self._dvd_timeline_chk.winfo_exists():
                    self._dvd_timeline_chk.pack_forget()
                self._auto_open_chk.pack_configure(pady=(4, 12))

    def _update_audio_track_selector(self):
        """Populate the Audio Track selector based on the active DVD title and its audio tracks."""
        if not hasattr(self, "_audio_track_cb"):
            return

        is_dvd = (self._source_type == "DVD") or any(v.get("disc_type") == "DVD" for v in getattr(self, "_videos", []))
        if not is_dvd or not getattr(self, "_videos", []):
            self._audio_track_cb.configure(state="disabled", values=[])
            self._audio_track_var.set("")
            if hasattr(self, "_audio_track_detail_lbl"):
                self._audio_track_detail_lbl.configure(text="")
            return

        if self._active_dvd_title_idx >= len(self._videos):
            self._active_dvd_title_idx = 0

        # Update Target Title combobox
        title_names = []
        for idx, v in enumerate(self._videos):
            t_num = v.get("title_number", idx + 1)
            t_name = v.get("filename") or f"Title {t_num:02d}"
            title_names.append(t_name)

        self._target_title_cb.configure(values=title_names)
        if 0 <= self._active_dvd_title_idx < len(title_names):
            self._target_title_var.set(title_names[self._active_dvd_title_idx])

        if len(self._videos) <= 1:
            self._audio_track_title_frame.pack_forget()
        else:
            self._audio_track_title_frame.pack(fill="x", padx=12, pady=(8, 4), before=self._audio_track_cb_frame)

        active_title = self._videos[self._active_dvd_title_idx]
        title_num = active_title.get("title_number", self._active_dvd_title_idx + 1)
        raw_tracks = active_title.get("audio_tracks", [])

        # If audio_tracks is empty, normalize from audio_streams if available
        if not raw_tracks and active_title.get("audio_streams"):
            raw_tracks = []
            for a_i, a_st in enumerate(active_title["audio_streams"]):
                trk = dvd_engine.normalize_audio_track(
                    title_number=title_num,
                    track_number=a_i + 1,
                    stream_index=a_i,
                    raw_codec=a_st.get("format", "AC3"),
                    raw_channels=a_st.get("channels", "2.0"),
                    raw_lang=a_st.get("lang", "und"),
                    raw_lang_name=a_st.get("lang_name"),
                    hb_track_index=a_i + 1,
                    ffmpeg_stream_index=a_i
                )
                raw_tracks.append(trk.to_dict())
            active_title["audio_tracks"] = raw_tracks

        if not raw_tracks:
            no_trk_text = t('format.no_audio_tracks')
            self._audio_track_cb.configure(values=[no_trk_text], state="disabled")
            self._audio_track_var.set(no_trk_text)
            self._audio_track_detail_lbl.configure(text=no_trk_text, fg=COLORS["text_muted"])
            return

        track_labels = []
        track_map = {}
        for t_item in raw_tracks:
            t_dict = t_item.to_dict() if isinstance(t_item, dvd_engine.DVDAudioTrack) else t_item
            label = t_dict.get("display_label")
            if not label:
                trk_obj = dvd_engine.normalize_audio_track(
                    title_number=t_dict.get("title_number", title_num),
                    track_number=t_dict.get("track_number", 1),
                    stream_index=t_dict.get("stream_index", 0),
                    raw_codec=t_dict.get("codec") or t_dict.get("format", "AC-3"),
                    raw_channels=t_dict.get("channels", "Stereo"),
                    raw_lang=t_dict.get("lang") or t_dict.get("lang_code", "und"),
                    raw_lang_name=t_dict.get("lang_name"),
                    hb_track_index=t_dict.get("hb_track_index", 1),
                    ffmpeg_stream_index=t_dict.get("ffmpeg_stream_index", 0),
                )
                label = trk_obj.display_label()
                t_dict["display_label"] = label
            track_labels.append(label)
            track_map[label] = t_dict

        self._audio_track_cb.configure(values=track_labels, state="readonly")

        selected_id = self._dvd_selected_audio_tracks.get(title_num)
        selected_label = None
        if selected_id:
            for lbl, t_dict in track_map.items():
                if t_dict.get("track_id") == selected_id:
                    selected_label = lbl
                    break

        if not selected_label:
            selected_label = track_labels[0]
            chosen_track = track_map[selected_label]
            self._dvd_selected_audio_tracks[title_num] = chosen_track.get("track_id", f"T{title_num:02d}_A01")

        self._audio_track_var.set(selected_label)
        curr_track = track_map[selected_label]

        details = []
        c = curr_track.get("codec") or curr_track.get("format")
        if c:
            details.append(f"Codec: {c}")
        ch = curr_track.get("channels")
        if ch:
            details.append(f"Channels: {ch}")
        sr = curr_track.get("sample_rate")
        if sr:
            details.append(f"{sr} Hz")
        br = curr_track.get("bitrate")
        if br and br > 0:
            details.append(f"{round(br/1000)} kbps")
        self._audio_track_detail_lbl.configure(
            text=" | ".join(details) if details else "",
            fg=COLORS["text_secondary"]
        )

    def _on_audio_track_selected(self, event=None):
        """User selected a different audio track in the combobox."""
        if not getattr(self, "_videos", []) or self._active_dvd_title_idx >= len(self._videos):
            return
        active_title = self._videos[self._active_dvd_title_idx]
        title_num = active_title.get("title_number", self._active_dvd_title_idx + 1)
        raw_tracks = active_title.get("audio_tracks", [])
        chosen_label = self._audio_track_var.get()

        for t_item in raw_tracks:
            t_dict = t_item.to_dict() if isinstance(t_item, dvd_engine.DVDAudioTrack) else t_item
            if t_dict.get("display_label") == chosen_label:
                self._dvd_selected_audio_tracks[title_num] = t_dict.get("track_id", f"T{title_num:02d}_A01")
                details = []
                c = t_dict.get("codec") or t_dict.get("format")
                if c:
                    details.append(f"Codec: {c}")
                ch = t_dict.get("channels")
                if ch:
                    details.append(f"Channels: {ch}")
                sr = t_dict.get("sample_rate")
                if sr:
                    details.append(f"{sr} Hz")
                br = t_dict.get("bitrate")
                if br and br > 0:
                    details.append(f"{round(br/1000)} kbps")
                self._audio_track_detail_lbl.configure(
                    text=" | ".join(details) if details else "",
                    fg=COLORS["text_secondary"]
                )
                self._log.log(f"Selected audio track for Title {title_num}: {chosen_label}", "info")
                break

    def _on_audio_track_title_changed(self, event=None):
        """User selected a different DVD title from the Target Title dropdown."""
        idx = self._target_title_cb.current()
        if idx < 0:
            val = self._target_title_var.get()
            vals = list(self._target_title_cb.cget("values"))
            if val in vals:
                idx = vals.index(val)
        if 0 <= idx < len(getattr(self, "_videos", [])):
            self._active_dvd_title_idx = idx
            self._update_audio_track_selector()

    def _apply_poll_results(self, drives, vcd_drives, dvd_drives, non_vcd_drives, theme_changed, current_effective):
        if self._ripping or getattr(self, "_scanning", False) or getattr(self, "_pause_drive_poll", False):
            return

        if dvd_drives:
            drive, check = dvd_drives[0]
            self._last_non_vcd_drive = None
            vol_name = get_volume_label(drive)
            prev_vol = getattr(self, "_last_disc_vol_name", None)
            if self._vcd_path.get() != drive or self._source_type != "DVD" or (vol_name and vol_name != prev_vol):
                self._source_type = "DVD"
                self._last_disc_vol_name = vol_name
                self._vcd_path.set(drive)
                self._batch_base_name = vol_name if vol_name else "Title"
                self._detected_drive_lbl.configure(text=t('drive.drive_label').format(drive=drive[0]))
                self._detect_label.configure(text=t('drive.detect_dvd'), fg=COLORS["success"])
                self._drive_lbl.configure(text=t('header.dvd_on').format(drive=drive[0]), fg=COLORS["success"])
                self._update_format_visibility_for_source()
                log_text = f"{drive} [{vol_name}]" if vol_name else drive
                self._log.log(t('log.dvd_auto').format(drive=log_text), "success")
                self.after(500, self._scan_disc)
        elif vcd_drives:
            drive, check = vcd_drives[0]
            self._last_non_vcd_drive = None
            vol_name = get_volume_label(drive)
            prev_vol = getattr(self, "_last_disc_vol_name", None)
            if self._vcd_path.get() != drive or self._source_type != "VCD" or (vol_name and vol_name != prev_vol):
                self._source_type = "VCD"
                self._last_disc_vol_name = vol_name
                self._vcd_path.set(drive)
                self._batch_base_name = vol_name if vol_name else "Track"
                self._detected_drive_lbl.configure(text=t('drive.drive_label').format(drive=drive[0]))
                self._detect_label.configure(text=t('drive.detect_vcd'), fg=COLORS["success"])
                self._drive_lbl.configure(text=t('header.vcd_on').format(drive=drive[0]), fg=COLORS["success"])
                self._update_format_visibility_for_source()
                log_text = f"{drive} [{vol_name}]" if vol_name else drive
                self._log.log(t('log.vcd_auto').format(drive=log_text), "success")
                self.after(500, self._scan_disc)
        elif non_vcd_drives:
            drive, check = non_vcd_drives[0]
            self._source_type = "NONE"
            self._last_disc_vol_name = None
            self._update_format_visibility_for_source()
            self._drive_lbl.configure(
                text=f"💿  {drive[0]}: ({check.disc_type})",
                fg=COLORS["warning"]
            )
            self._detected_drive_lbl.configure(text=t('drive.drive_label').format(drive=drive[0]))
            self._detect_label.configure(text=f"{check.disc_type}", fg=COLORS["warning"])
            if self._last_non_vcd_drive != drive:
                self._last_non_vcd_drive = drive
                self._vcd_path.set(drive)
                log_msg = t('log.unsupported_blocked').format(drive=drive, type=check.disc_type)
                self._log.log(log_msg, "warning")
                self._show_unsupported_disc_dialog(drive, check.disc_type)
        else:
            self._last_non_vcd_drive = None
            self._last_disc_vol_name = None
            if drives:
                self._drive_lbl.configure(
                    text=t('header.drive_no_disc').format(drive=drives[0][0]),
                    fg=COLORS["warning"]
                )
            else:
                self._drive_lbl.configure(text=t('header.no_disc'), fg=COLORS["text_muted"])
            current_p = self._vcd_path.get()
            if current_p and any(current_p.upper().startswith(d[0].upper()) for d in drives):
                if not self._ripping:
                    self._clear_disc_info()

        # Auto-detect Windows theme changes in system mode
        if theme_changed and current_effective:
            apply_theme_palette(current_effective)
            self._on_theme_changed()

    # ── Diagnostic & Crash Recovery ───────────
    def _check_stale_dvd_scan_session(self):
        """Checks if a previous DVD scan was interrupted (e.g. BSOD or sudden reboot)."""
        self._stale_check_job = None
        try:
            if not self.winfo_exists():
                return
            stale = dvd_diagnostics.check_stale_session()
            if not stale:
                return

            stage = stale.get("stage", "UNKNOWN")
            detail = stale.get("stage_details", "")
            target = stale.get("drive_path", "unknown")
            session_id = stale.get("session_id", "unknown")

            self._log.log(
                f"[Diagnostic Notice] Interrupted DVD scan session detected: {session_id} on '{target}' at stage '{stage}' ({detail})",
                "warning"
            )

            prompt_msg = (
                f"{t('diagnostics.stale_detected_body')}\n\n"
                f"• Target: {target}\n"
                f"• Interrupted Stage: {stage}\n"
                f"• Detail: {detail}\n\n"
                f"{t('diagnostics.stale_export_prompt')}"
            )

            # Archive the session marker so user is not prompted again repeatedly
            dvd_diagnostics.acknowledge_stale_session()

            should_export = messagebox.askyesno(
                t('diagnostics.stale_detected_title'),
                prompt_msg,
                icon="warning",
                parent=self
            )

            if should_export:
                self._export_diagnostics(session_id=session_id)
        except Exception:
            pass

    def _export_diagnostics(self, session_id=None):
        """Export diagnostic logs and system info into a ZIP file chosen by user."""
        try:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_zip_name = f"Disc_Ripper_Pro_Diagnostics_{ts_str}.zip"
            dest = filedialog.asksaveasfilename(
                title=t('diagnostics.save_dialog_title'),
                initialfile=default_zip_name,
                defaultextension=".zip",
                filetypes=[("ZIP archive", "*.zip"), ("All Files", "*.*")],
                parent=self
            )
            if not dest:
                return

            zip_result = dvd_diagnostics.export_diagnostic_package(
                output_zip_path=dest,
                session_id=session_id,
                hb_path=self._handbrake,
                ffmpeg_path=self._ffmpeg,
                ffprobe_path=self._ffprobe
            )

            self._log.log(f"Diagnostic package exported: {zip_result}", "success")
            messagebox.showinfo(
                t('diagnostics.export_success_title'),
                t('diagnostics.export_success_msg').format(path=zip_result),
                parent=self
            )
            try:
                subprocess.Popen(f'explorer /select,"{os.path.abspath(zip_result)}"', **get_subprocess_kwargs())
            except Exception:
                pass
        except Exception as ex:
            self._log.log(f"Export diagnostic failed: {ex}", "error")
            messagebox.showerror(t('diagnostics.export_fail_title'), str(ex), parent=self)

    def _run_diagnostic_dvd_scan(self):
        """Run a DVD scan with active diagnostic tracking."""
        path = self._vcd_path.get().strip()
        if not path:
            folder = filedialog.askdirectory(title="Select DVD Folder or Drive for Diagnostic Scan", parent=self)
            if not folder:
                return
            self._vcd_path.set(folder)
            path = folder

        self._log.log(t('diagnostics.diag_scan_started').format(path=path, mode=getattr(i18n, 'dvd_scanner', 'auto')), "accent")
        self._scan_dvd(path)

    def _open_health_check(self, initial_mode=None, parent_dlg=None):
        """Open the Disc Health Check flow (mode selection or direct check)."""
        if self._ripping or getattr(self, "_scanning", False) or getattr(self, "_health_checking", False):
            return

        path = self._vcd_path.get().strip()
        if not path:
            folder = filedialog.askdirectory(
                parent=parent_dlg or self,
                title=t('diagnostics.select_disc_folder')
            )
            if not folder:
                return
            self._vcd_path.set(folder)
            path = folder

        if initial_mode in ("quick", "thorough"):
            self._start_health_check(mode=initial_mode, source_path=path, parent_dlg=parent_dlg)
        else:
            DiscHealthModeDialog(
                parent=parent_dlg or self,
                source_path=path,
                on_start=lambda m: self._start_health_check(mode=m, source_path=path, parent_dlg=parent_dlg)
            )

    def _start_health_check(self, mode="quick", source_path=None, parent_dlg=None):
        """Start non-destructive Disc Health Check in a background thread."""
        if getattr(self, "_health_checking", False):
            return
        if not source_path:
            source_path = self._vcd_path.get().strip()
        if not source_path:
            messagebox.showwarning(
                t('diagnostics.health_check'),
                t('diagnostics.no_disc_selected'),
                parent=parent_dlg or self
            )
            return

        self._health_checking = True
        cancel_event = threading.Event()

        # Update button text in settings dialog if open
        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            if hasattr(self._about_dialog, "btn_health_check"):
                self._about_dialog.btn_health_check.configure(
                    state="disabled",
                    text=f"⏳  {t('diagnostics.running_check')}",
                    fg=COLORS["text_muted"],
                    cursor=""
                )

        mode_lbl = t('diagnostics.mode_quick') if mode == "quick" else t('diagnostics.mode_thorough')
        progress_dlg = DiscHealthProgressDialog(
            parent=parent_dlg or self,
            mode_label=mode_lbl,
            on_cancel=lambda: cancel_event.set()
        )

        def worker():
            def progress_cb(pct, msg):
                self.after(0, lambda: progress_dlg.update_progress(pct, msg))

            report = dvd_diagnostics.run_disc_health_check(
                source_path=source_path,
                mode=mode,
                hb_path=getattr(self, "_handbrake", None),
                ffmpeg_path=getattr(self, "_ffmpeg", None),
                ffprobe_path=getattr(self, "_ffprobe", None),
                progress_callback=progress_cb,
                cancel_event=cancel_event,
                lang=getattr(i18n, "lang", "en")
            )

            def on_complete():
                self._health_checking = False
                try:
                    progress_dlg.destroy()
                except Exception:
                    pass

                # Restore settings button state if settings dialog is still open
                if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
                    if hasattr(self._about_dialog, "btn_health_check"):
                        self._about_dialog.btn_health_check.configure(
                            state="normal" if not self._ripping else "disabled",
                            text=f"🩺  {t('diagnostics.health_check')}",
                            fg=COLORS["text_primary"] if not self._ripping else COLORS["text_muted"],
                            cursor="hand2" if not self._ripping else ""
                        )

                self.last_health_report = report

                # Log to log console
                status_text = {
                    dvd_diagnostics.HealthStatus.GOOD: t('diagnostics.status_good'),
                    dvd_diagnostics.HealthStatus.WARNINGS: t('diagnostics.status_warnings'),
                    dvd_diagnostics.HealthStatus.PROBLEMS: t('diagnostics.status_problems'),
                    dvd_diagnostics.HealthStatus.INCONCLUSIVE: t('diagnostics.status_inconclusive')
                }.get(report.overall_status, str(report.overall_status))

                tag = "success" if report.overall_status == dvd_diagnostics.HealthStatus.GOOD else (
                    "warning" if report.overall_status == dvd_diagnostics.HealthStatus.WARNINGS else "error"
                )
                self._log.log(
                    f"[{t('diagnostics.health_check')}] {status_text} — {report.summary}",
                    tag
                )

                # Open the Diagnostic Results Window
                res_parent = parent_dlg if (parent_dlg and parent_dlg.winfo_exists()) else self
                DiscHealthResultDialog(
                    parent=res_parent,
                    report=report,
                    on_proceed_rip=self._on_health_proceed_rip,
                    on_export_txt=self._export_diagnostic_report_txt
                )

            self.after(0, on_complete)

        t_th = threading.Thread(target=worker, daemon=True)
        t_th.start()

    def _on_health_proceed_rip(self, report):
        """Handle user clicking Proceed to Ripping from the Diagnostic Results Dialog."""
        proceed = False
        if report.overall_status == dvd_diagnostics.HealthStatus.GOOD:
            proceed = True
        elif report.overall_status == dvd_diagnostics.HealthStatus.WARNINGS:
            warn_lines = "\n".join(f"• {f.title}: {f.explanation}" for f in report.findings if f.severity == dvd_diagnostics.FindingSeverity.WARNING)
            if not warn_lines:
                warn_lines = report.summary
            msg = t('diagnostics.confirm_rip_warn').format(warnings=warn_lines)
            proceed = messagebox.askyesno(
                t('diagnostics.status_warnings'),
                msg,
                parent=self
            )
        elif report.overall_status == dvd_diagnostics.HealthStatus.PROBLEMS:
            prob_lines = "\n".join(f"• {f.title}: {f.explanation}" for f in report.findings if f.severity == dvd_diagnostics.FindingSeverity.ERROR)
            if not prob_lines:
                prob_lines = report.summary
            msg = t('diagnostics.confirm_rip_problems').format(problems=prob_lines)
            proceed = messagebox.askyesno(
                t('diagnostics.status_problems'),
                msg,
                icon="warning",
                parent=self
            )
        else:
            msg = t('diagnostics.confirm_rip_inconclusive')
            proceed = messagebox.askyesno(
                t('diagnostics.status_inconclusive'),
                msg,
                parent=self
            )

        if not proceed:
            return

        if report.source_path:
            self._vcd_path.set(report.source_path)

        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            try:
                self._about_dialog.destroy()
            except Exception:
                pass

        self.deiconify()
        self.lift()
        self.focus_force()
        self._log.log(
            f"Disc Health Check completed ({report.overall_status}). Ready for user to start ripping.",
            "accent"
        )

    def _export_diagnostic_report_txt(self, report=None, dlg_parent=None):
        """Export clean, human-readable .txt diagnostic report."""
        try:
            if report is None:
                report = getattr(self, "last_health_report", None)

            if report is None:
                path = self._vcd_path.get().strip()
                if not path:
                    messagebox.showwarning(
                        t('diagnostics.health_check'),
                        t('diagnostics.no_disc_selected'),
                        parent=dlg_parent or self
                    )
                    return
                report = dvd_diagnostics.run_disc_health_check(path, mode="quick")
                self.last_health_report = report

            default_fn = f"Disc_Health_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            dest = filedialog.asksaveasfilename(
                parent=dlg_parent or self,
                title=t('diagnostics.save_txt_dialog'),
                initialfile=default_fn,
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if not dest:
                # User cancelled Save As dialog
                return

            saved_path = dvd_diagnostics.export_diagnostic_report_txt(
                report=report,
                dest_path=dest,
                mask_privacy=True,
                lang=getattr(i18n, "lang", "en")
            )

            if saved_path and os.path.isfile(saved_path):
                self._log.log(f"Diagnostic report exported: {saved_path}", "success")
                messagebox.showinfo(
                    t('diagnostics.export_txt_success_title'),
                    t('diagnostics.export_txt_success_msg').format(path=saved_path),
                    parent=dlg_parent or self
                )
            else:
                raise IOError("Target file could not be verified after export.")

        except (PermissionError, OSError, IOError) as ex:
            self._log.log(f"Failed to export diagnostic report: {ex}", "error")
            err_title = t('diagnostics.export_fail_title') if hasattr(t, '__call__') else "Export Failed"
            messagebox.showerror(
                err_title,
                f"{err_title}: {ex}",
                parent=dlg_parent or self
            )
        except Exception as ex:
            self._log.log(f"Unexpected error exporting diagnostic report: {ex}", "error")
            err_title = t('diagnostics.export_fail_title') if hasattr(t, '__call__') else "Export Failed"
            messagebox.showerror(
                err_title,
                str(ex),
                parent=dlg_parent or self
            )


    # ── Actions ───────────────────────────────
    def _show_about(self):
        """Open the About / Settings dialog."""
        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            self._about_dialog.lift()
            self._about_dialog.focus_force()
            return

        dlg = tk.Toplevel(self)
        dlg.update_theme = lambda: None
        dlg.update_lang = lambda: None
        dlg.update_scale = lambda: None
        self._about_dialog = dlg

        def _on_destroy(event):
            if event.widget == dlg:
                self._about_dialog = None
                if getattr(self, "_rebuild_ui_job", None):
                    try:
                        self.after_cancel(self._rebuild_ui_job)
                    except Exception:
                        pass
                    self._rebuild_ui_job = None
                    self._rebuild_ui()
        dlg.bind("<Destroy>", _on_destroy)

        dlg.title(t('about.title'))
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.resizable(True, True)
        self._set_window_icon(dlg)
        dlg.grab_set()

        try:
            dlg_hwnd = ctypes.windll.user32.GetAncestor(dlg.winfo_id(), 2) or dlg.winfo_id()
            set_window_dark_mode(dlg_hwnd, i18n.get_effective_theme() == "dark")
        except Exception:
            pass

        def build_content(rebuild=False):
            if rebuild:
                for c in dlg.winfo_children():
                    c.destroy()

            # ── Shared Scaled Layout Tokens ──────────
            card_px = scale_val(16)
            card_py = (scale_val(6), 0)
            inner_px = scale_val(14)
            row_py = scale_val(3)
            lbl_col_w = scale_val(148)
            btn_w = 11

            def format_path_display(p, max_len=44):
                if not p:
                    return "—"
                if len(p) <= max_len:
                    return p
                drive, rest = os.path.splitdrive(p)
                parts = [seg for seg in rest.replace("/", "\\").split("\\") if seg]
                if len(parts) >= 2:
                    short = f"{drive}\\{parts[0]}\\...\\{parts[-1]}"
                    if len(short) <= max_len:
                        return short
                    short2 = f"...\\{parts[-2]}\\{parts[-1]}"
                    if len(short2) <= max_len:
                        return short2
                return os.path.basename(p)

            # ── Header Banner ─────────────────────
            header_frame = tk.Frame(dlg, bg=COLORS["bg_dark"])
            header_frame.pack(fill="x")

            header_inner = tk.Frame(header_frame, bg=COLORS["bg_dark"])
            header_inner.pack(fill="x", padx=card_px, pady=scale_val(10))

            header_icon = get_header_icon(scale_val(44))
            if header_icon:
                lbl_img = tk.Label(header_inner, image=header_icon, bg=COLORS["bg_dark"])
                lbl_img.image = header_icon
                lbl_img.pack(side="left", padx=(0, scale_val(14)))
            else:
                lbl_img = tk.Label(
                    header_inner, text="💿", font=FONTS["emoji_32"],
                    bg=COLORS["bg_dark"], fg=COLORS["text_primary"]
                )
                lbl_img.pack(side="left", padx=(0, scale_val(14)))
            dlg.lbl_img = lbl_img

            header_text = tk.Frame(header_inner, bg=COLORS["bg_dark"])
            header_text.pack(side="left", fill="y")

            title_row = tk.Frame(header_text, bg=COLORS["bg_dark"])
            title_row.pack(anchor="w")

            lbl_app_name = tk.Label(
                title_row, text=APP_NAME,
                font=FONTS["heading"],
                bg=COLORS["bg_dark"], fg=COLORS["text_primary"]
            )
            lbl_app_name.pack(side="left")

            lbl_version = tk.Label(
                title_row, text=f"v{APP_VERSION}",
                font=FONTS["badge"],
                bg=COLORS["bg_dark"], fg=COLORS["accent"]
            )
            lbl_version.pack(side="left", padx=(8, 0), pady=(4, 0))

            lbl_author = tk.Label(
                header_text, text="Developed by jjsiew2014-art",
                font=FONTS["tiny"],
                bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]
            )
            lbl_author.pack(anchor="w", pady=(1, 0))

            header_sep = tk.Frame(dlg, bg=COLORS["border"], height=1)
            header_sep.pack(fill="x", padx=card_px)

            # ── Footer Container (pinned to bottom of dialog) ──
            footer_frame = tk.Frame(dlg, bg=COLORS["bg_panel"])
            footer_frame.pack(side="bottom", fill="x")

            lbl_license = tk.Label(
                footer_frame, text=t('about.license'),
                font=FONTS["small"], bg=COLORS["bg_panel"],
                fg=COLORS["text_secondary"]
            )
            lbl_license.pack(side="top", pady=(scale_val(4), 0))

            btn_close = tk.Button(
                footer_frame, text=t('about.close'),
                font=FONTS["body_bold"], bg=COLORS["accent"],
                fg=COLORS.get("btn_primary_fg", "#FFFFFF"), relief="flat", bd=0,
                padx=scale_val(36), pady=scale_val(6), cursor="hand2",
                activebackground=COLORS["accent_hover"],
                activeforeground=COLORS.get("btn_primary_fg", "#FFFFFF"),
                command=dlg.destroy
            )
            btn_close.pack(side="top", pady=(scale_val(4), scale_val(10)))

            # ── Category A: Appearance & Display ──
            card_appearance = tk.Frame(
                dlg, bg=COLORS["bg_card"],
                highlightbackground=COLORS["border"],
                highlightthickness=1
            )
            card_appearance.pack(fill="x", padx=card_px, pady=card_py)

            lbl_cat_a = tk.Label(
                card_appearance, text=f"🎨  {t('about.cat_appearance')}",
                font=FONTS["small_bold"],
                bg=COLORS["bg_card"], fg=COLORS["accent"],
                anchor="w"
            )
            lbl_cat_a.pack(fill="x", padx=inner_px, pady=(scale_val(6), scale_val(4)))

            # A1. Language row
            row_language = tk.Frame(card_appearance, bg=COLORS["bg_card"])
            row_language.pack(fill="x", padx=inner_px, pady=row_py)
            row_language.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_language.grid_columnconfigure(1, weight=1)

            lbl_lang_title = tk.Label(
                row_language, text=t('language.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_lang_title.grid(row=0, column=0, sticky="w")

            btn_lang_frame = tk.Frame(row_language, bg=COLORS["bg_card"])
            btn_lang_frame.grid(row=0, column=1, sticky="ew")

            lang_buttons = {}
            languages = [
                ("en",    "English"),
                ("zh_CN", "简体中文"),
                ("zh_TW", "繁體中文"),
            ]
            for idx, (l_key, l_label) in enumerate(languages):
                btn_lang_frame.grid_columnconfigure(idx, weight=1, uniform="lang_btns")
                is_active = (i18n.lang == l_key)
                l_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                l_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                l_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    btn_lang_frame, text=l_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=l_bg, fg=l_fg,
                    highlightbackground=l_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=l_fg if is_active else COLORS["text_primary"],
                    command=lambda lk=l_key: set_lang(lk)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(languages) - 1 else 0))
                lang_buttons[l_key] = btn

            # A2. Appearance row
            row_appearance = tk.Frame(card_appearance, bg=COLORS["bg_card"])
            row_appearance.pack(fill="x", padx=inner_px, pady=row_py)
            row_appearance.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_appearance.grid_columnconfigure(1, weight=1)

            lbl_appearance_title = tk.Label(
                row_appearance, text=t('appearance.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_appearance_title.grid(row=0, column=0, sticky="w")

            theme_btn_frame = tk.Frame(row_appearance, bg=COLORS["bg_card"])
            theme_btn_frame.grid(row=0, column=1, sticky="ew")

            theme_buttons = {}
            modes = [
                ("system", t('appearance.system')),
                ("light",  t('appearance.light')),
                ("dark",   t('appearance.dark')),
            ]
            for idx, (m_key, m_label) in enumerate(modes):
                theme_btn_frame.grid_columnconfigure(idx, weight=1, uniform="theme_btns")
                is_active = (i18n.theme == m_key)
                m_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                m_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                m_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    theme_btn_frame, text=m_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=m_bg, fg=m_fg,
                    highlightbackground=m_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=m_fg if is_active else COLORS["text_primary"],
                    command=lambda m=m_key: set_appearance(m)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(modes) - 1 else 0))
                theme_buttons[m_key] = btn

            # A3. Scale row
            row_scale = tk.Frame(card_appearance, bg=COLORS["bg_card"])
            row_scale.pack(fill="x", padx=inner_px, pady=(row_py, scale_val(6)))
            row_scale.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_scale.grid_columnconfigure(1, weight=1)

            lbl_scale_title = tk.Label(
                row_scale, text=t('scale.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_scale_title.grid(row=0, column=0, sticky="w")

            scale_btn_frame = tk.Frame(row_scale, bg=COLORS["bg_card"])
            scale_btn_frame.grid(row=0, column=1, sticky="ew")

            scale_buttons = {}
            scales = [
                ("100%", t('scale.100')),
                ("125%", t('scale.125')),
                ("150%", t('scale.150')),
            ]
            for idx, (s_key, s_label) in enumerate(scales):
                scale_btn_frame.grid_columnconfigure(idx, weight=1, uniform="scale_btns")
                is_active = (i18n.scale == s_key)
                s_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                s_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                s_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    scale_btn_frame, text=s_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=s_bg, fg=s_fg,
                    highlightbackground=s_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=s_fg if is_active else COLORS["text_primary"],
                    command=lambda sk=s_key: set_scale(sk)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(scales) - 1 else 0))
                scale_buttons[s_key] = btn

            # ── Category B: Processing Settings ───
            card_processing = tk.Frame(
                dlg, bg=COLORS["bg_card"],
                highlightbackground=COLORS["border"],
                highlightthickness=1
            )
            card_processing.pack(fill="x", padx=card_px, pady=card_py)

            lbl_cat_b = tk.Label(
                card_processing, text=f"⚙️  {t('about.cat_processing')}",
                font=FONTS["small_bold"],
                bg=COLORS["bg_card"], fg=COLORS["accent"],
                anchor="w"
            )
            lbl_cat_b.pack(fill="x", padx=inner_px, pady=(scale_val(6), scale_val(4)))

            # B1. Ripping FPS Mode row (Balanced width, Passthrough does not dominate)
            row_fps_mode = tk.Frame(card_processing, bg=COLORS["bg_card"])
            row_fps_mode.pack(fill="x", padx=inner_px, pady=row_py)
            row_fps_mode.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_fps_mode.grid_columnconfigure(1, weight=1)

            lbl_fps_mode_title = tk.Label(
                row_fps_mode, text=t('fps_mode.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_fps_mode_title.grid(row=0, column=0, sticky="w")

            fps_btn_frame = tk.Frame(row_fps_mode, bg=COLORS["bg_card"])
            fps_btn_frame.grid(row=0, column=1, sticky="ew")

            fps_buttons = {}
            fps_modes = [
                ("Passthrough", t('fps_mode.passthrough')),
                ("CFR",         t('fps_mode.cfr')),
            ]
            for idx, (f_key, f_label) in enumerate(fps_modes):
                fps_btn_frame.grid_columnconfigure(idx, weight=1, uniform="fps_btns")
                is_active = (i18n.fps_mode == f_key)
                f_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                f_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                f_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    fps_btn_frame, text=f_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=f_bg, fg=f_fg,
                    highlightbackground=f_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=f_fg if is_active else COLORS["text_primary"],
                    command=lambda fk=f_key: set_fps_mode(fk)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(fps_modes) - 1 else 0))
                fps_buttons[f_key] = btn

            # B2. Ripping Process Priority row
            row_priority = tk.Frame(card_processing, bg=COLORS["bg_card"])
            row_priority.pack(fill="x", padx=inner_px, pady=row_py)
            row_priority.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_priority.grid_columnconfigure(1, weight=1)

            lbl_priority_title = tk.Label(
                row_priority, text=t('priority.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_priority_title.grid(row=0, column=0, sticky="w")

            priority_btn_frame = tk.Frame(row_priority, bg=COLORS["bg_card"])
            priority_btn_frame.grid(row=0, column=1, sticky="ew")

            priority_buttons = {}
            priorities = [
                ("Low",    t('priority.low')),
                ("Medium", t('priority.medium')),
                ("High",   t('priority.high')),
            ]
            for idx, (p_key, p_label) in enumerate(priorities):
                priority_btn_frame.grid_columnconfigure(idx, weight=1, uniform="priority_btns")
                is_active = (i18n.priority == p_key)
                p_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                p_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                p_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    priority_btn_frame, text=p_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=p_bg, fg=p_fg,
                    highlightbackground=p_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=p_fg if is_active else COLORS["text_primary"],
                    command=lambda pk=p_key: set_priority(pk)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(priorities) - 1 else 0))
                priority_buttons[p_key] = btn

            # B3. DVD Scanner Engine row
            row_dvd_scanner = tk.Frame(card_processing, bg=COLORS["bg_card"])
            row_dvd_scanner.pack(fill="x", padx=inner_px, pady=row_py)

            # B4. Windows Notification switch row
            row_notification = tk.Frame(card_processing, bg=COLORS["bg_card"])
            row_notification.pack(fill="x", padx=inner_px, pady=(row_py, scale_val(6)))
            row_notification.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_notification.grid_columnconfigure(1, weight=1)

            lbl_notification_title = tk.Label(
                row_notification, text=t('notification.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_notification_title.grid(row=0, column=0, sticky="w")

            notification_btn_frame = tk.Frame(row_notification, bg=COLORS["bg_card"])
            notification_btn_frame.grid(row=0, column=1, sticky="ew")

            notification_buttons = {}
            notification_modes = [
                (True,  t('notification.enabled')),
                (False, t('notification.disabled')),
            ]
            for idx, (n_val, n_label) in enumerate(notification_modes):
                notification_btn_frame.grid_columnconfigure(idx, weight=1, uniform="notification_btns")
                is_active = (getattr(i18n, "notification", True) == n_val)
                n_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                n_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                n_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    notification_btn_frame, text=n_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=n_bg, fg=n_fg,
                    highlightbackground=n_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=n_fg if is_active else COLORS["text_primary"],
                    command=lambda nv=n_val: set_notification(nv)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(notification_modes) - 1 else 0))
                notification_buttons[n_val] = btn
            tip_notification = Tooltip(notification_btn_frame, lambda: t('notification.tip'))
            dlg.notification_buttons = notification_buttons
            dlg.tip_notification = tip_notification
            row_dvd_scanner.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_dvd_scanner.grid_columnconfigure(1, weight=1)

            lbl_scanner_title = tk.Label(
                row_dvd_scanner, text=t('dvd_scanner.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_scanner_title.grid(row=0, column=0, sticky="w")

            scanner_btn_frame = tk.Frame(row_dvd_scanner, bg=COLORS["bg_card"])
            scanner_btn_frame.grid(row=0, column=1, sticky="ew")

            scanner_buttons = {}
            scanner_tips = {}
            scanner_modes = [
                ("auto",       t('dvd_scanner.auto'),       lambda: t('dvd_scanner.auto_tip')),
                ("direct_ifo", t('dvd_scanner.direct_ifo'), lambda: t('dvd_scanner.direct_ifo_tip')),
                ("handbrake",  t('dvd_scanner.handbrake'),  lambda: t('dvd_scanner.handbrake_tip')),
            ]
            for idx, (sm_key, sm_label, sm_tip) in enumerate(scanner_modes):
                scanner_btn_frame.grid_columnconfigure(idx, weight=1, uniform="scanner_btns")
                is_active = (getattr(i18n, "dvd_scanner", "auto") == sm_key)
                sm_bg = COLORS["accent"] if is_active else COLORS["bg_panel"]
                sm_fg = COLORS.get("btn_primary_fg", "#FFFFFF") if is_active else COLORS["text_secondary"]
                sm_border = COLORS["accent"] if is_active else COLORS["border"]
                btn = tk.Button(
                    scanner_btn_frame, text=sm_label, font=FONTS["small_bold"] if is_active else FONTS["small"],
                    bg=sm_bg, fg=sm_fg,
                    highlightbackground=sm_border, highlightthickness=1,
                    relief="flat", bd=0, padx=scale_val(2), pady=scale_val(3),
                    cursor="hand2" if not (self._ripping or getattr(self, "_scanning", False)) else "",
                    state="normal" if not (self._ripping or getattr(self, "_scanning", False)) else "disabled",
                    activebackground=COLORS["accent_hover"] if is_active else COLORS["bg_hover"],
                    activeforeground=sm_fg if is_active else COLORS["text_primary"],
                    command=lambda sk=sm_key: set_dvd_scanner(sk)
                )
                btn.grid(row=0, column=idx, sticky="ew", padx=(0, scale_val(4) if idx < len(scanner_modes) - 1 else 0))
                tip = Tooltip(btn, sm_tip)
                scanner_tips[sm_key] = tip
                scanner_buttons[sm_key] = btn
            dlg.scanner_buttons = scanner_buttons
            dlg.scanner_tips = scanner_tips

            # ── Category C: Diagnostics & System Information ──
            card_diagnostics = tk.Frame(
                dlg, bg=COLORS["bg_card"],
                highlightbackground=COLORS["border"],
                highlightthickness=1
            )
            card_diagnostics.pack(fill="x", padx=card_px, pady=card_py)

            lbl_cat_c = tk.Label(
                card_diagnostics, text=f"🛠️  {t('about.cat_diagnostics')}",
                font=FONTS["small_bold"],
                bg=COLORS["bg_card"], fg=COLORS["accent"],
                anchor="w"
            )
            lbl_cat_c.pack(fill="x", padx=inner_px, pady=(scale_val(6), scale_val(4)))

            # C1. Diagnostic Tools Toolbar Row
            row_diag = tk.Frame(card_diagnostics, bg=COLORS["bg_card"])
            row_diag.pack(fill="x", padx=inner_px, pady=row_py)
            row_diag.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)
            row_diag.grid_columnconfigure(1, weight=1)

            lbl_diag_title = tk.Label(
                row_diag, text=t('diagnostics.title'), font=FONTS["small"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_diag_title.grid(row=0, column=0, sticky="nw", pady=(scale_val(4), 0))

            diag_action_box = tk.Frame(row_diag, bg=COLORS["bg_card"])
            diag_action_box.grid(row=0, column=1, sticky="ew")

            btn_action_row = tk.Frame(diag_action_box, bg=COLORS["bg_card"])
            btn_action_row.pack(fill="x")
            btn_action_row.grid_columnconfigure(0, weight=4)
            btn_action_row.grid_columnconfigure(1, weight=5)

            # Secondary neutral action button for Disc Health Check
            is_health_busy = getattr(self, "_health_checking", False)
            health_check_label = t('diagnostics.health_check')
            health_init_text = f"⏳  {t('diagnostics.running_check')}" if is_health_busy else f"🩺  {health_check_label}"

            btn_health_check = tk.Button(
                btn_action_row, text=health_init_text, font=FONTS["small_bold"],
                bg=COLORS["bg_panel"], fg=COLORS["text_primary"] if not (self._ripping or is_health_busy) else COLORS["text_muted"],
                highlightbackground=COLORS["border"], highlightthickness=1,
                relief="flat", bd=0, padx=scale_val(6), pady=scale_val(4),
                cursor="hand2" if not (self._ripping or is_health_busy) else "",
                state="normal" if not (self._ripping or is_health_busy) else "disabled",
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS["text_primary"],
                command=lambda: self._open_health_check(parent_dlg=dlg)
            )
            btn_health_check.grid(row=0, column=0, sticky="ew", padx=(0, scale_val(6)))
            btn_diag_scan = btn_health_check
            dlg.btn_health_check = btn_health_check
            dlg.btn_diag_scan = btn_diag_scan

            def _on_scan_hover(e):
                if btn_health_check.cget("state") == "normal":
                    btn_health_check.configure(bg=COLORS["bg_hover"], highlightbackground=COLORS["accent"])
            def _on_scan_leave(e):
                if btn_health_check.cget("state") == "normal":
                    btn_health_check.configure(bg=COLORS["bg_panel"], highlightbackground=COLORS["border"])
            btn_health_check.bind("<Enter>", _on_scan_hover)
            btn_health_check.bind("<Leave>", _on_scan_leave)

            # Secondary neutral action button for Export Diagnostic Report (.txt)
            btn_export_txt = tk.Button(
                btn_action_row, text=f"📄  {t('diagnostics.export_report')}", font=FONTS["small"],
                bg=COLORS["bg_panel"], fg=COLORS["success"],
                highlightbackground=COLORS["border"], highlightthickness=1,
                relief="flat", bd=0, padx=scale_val(6), pady=scale_val(4),
                cursor="hand2",
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS["success"],
                command=lambda: self._export_diagnostic_report_txt(dlg_parent=dlg)
            )
            btn_export_txt.grid(row=0, column=1, sticky="ew")
            btn_export_zip = btn_export_txt
            dlg.btn_export_txt = btn_export_txt
            dlg.btn_export_zip = btn_export_zip

            def _on_export_hover(e):
                btn_export_txt.configure(bg=COLORS["bg_hover"], highlightbackground=COLORS["success"])
            def _on_export_leave(e):
                btn_export_txt.configure(bg=COLORS["bg_panel"], highlightbackground=COLORS["border"])
            btn_export_txt.bind("<Enter>", _on_export_hover)
            btn_export_txt.bind("<Leave>", _on_export_leave)

            # Descriptive explanatory text under action buttons
            lbl_diag_help = tk.Label(
                diag_action_box, text=t('diagnostics.health_check_tip'), font=FONTS["tiny"],
                bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                wraplength=scale_val(420), justify="left",
                anchor="w"
            )
            lbl_diag_help.pack(fill="x", pady=(scale_val(3), scale_val(2)))
            dlg.lbl_diag_help = lbl_diag_help

            # Subtle divider between action toolbar and dependency entries
            sep_diag = tk.Frame(card_diagnostics, bg=COLORS["border"], height=1)
            sep_diag.pack(fill="x", padx=inner_px, pady=(scale_val(6), scale_val(6)))

            def copy_path_handler(path_to_copy, btn_target, tip_target, orig_tip_text):
                if not path_to_copy:
                    return
                try:
                    dlg.clipboard_clear()
                    dlg.clipboard_append(path_to_copy)
                    dlg.update()
                except Exception:
                    pass
                btn_target.configure(text="✓", fg=COLORS["success"])
                if tip_target:
                    tip_target.text = t('about.copied')
                def _restore_btn():
                    try:
                        if btn_target.winfo_exists():
                            btn_target.configure(text="📋", fg=COLORS["accent"])
                            if tip_target:
                                tip_target.text = orig_tip_text
                    except Exception:
                        pass
                dlg.after(1500, _restore_btn)

            # C2. Dependency Entry 1: FFmpeg
            ff_ready = bool(self._ffmpeg and os.path.isfile(self._ffmpeg))
            ff_status_text = t('about.ready') if ff_ready else t('about.not_found')
            ff_status_color = COLORS["success"] if ff_ready else COLORS["error"]

            ff_header = tk.Frame(card_diagnostics, bg=COLORS["bg_card"])
            ff_header.pack(fill="x", padx=inner_px, pady=(scale_val(2), scale_val(1)))

            lbl_ffmpeg_title = tk.Label(
                ff_header, text=t('about.ffmpeg'), font=FONTS["small_bold"],
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                anchor="w"
            )
            lbl_ffmpeg_title.pack(side="left")

            lbl_ffmpeg_status = tk.Label(
                ff_header,
                text=ff_status_text,
                font=FONTS["small_bold"],
                bg=COLORS["bg_card"],
                fg=ff_status_color,
                anchor="e"
            )
            lbl_ffmpeg_status.pack(side="right")

            ff_path_frame = tk.Frame(
                card_diagnostics, bg=COLORS["bg_panel"],
                highlightbackground=COLORS["border"],
                highlightthickness=1
            )
            ff_path_frame.pack(fill="x", padx=inner_px, pady=(0, scale_val(6)))

            lbl_path_ffmpeg = tk.Label(
                ff_path_frame,
                text=format_path_display(self._ffmpeg),
                font=FONTS["mono"],
                bg=COLORS["bg_panel"],
                fg=COLORS["text_secondary"] if ff_ready else COLORS["text_muted"],
                anchor="w"
            )
            lbl_path_ffmpeg.pack(side="left", fill="x", expand=True, padx=(scale_val(8), scale_val(4)), pady=scale_val(2))
            if ff_ready:
                Tooltip(lbl_path_ffmpeg, self._ffmpeg)

            btn_copy_ffmpeg = tk.Button(
                ff_path_frame,
                text="📋",
                font=FONTS["small"],
                width=3,
                bg=COLORS["bg_hover"],
                fg=COLORS["accent"] if ff_ready else COLORS["text_muted"],
                relief="flat", bd=0, padx=2, pady=1,
                cursor="hand2" if ff_ready else "",
                state="normal" if ff_ready else "disabled",
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS["accent_hover"],
                command=lambda: copy_path_handler(self._ffmpeg, btn_copy_ffmpeg, tip_copy_ffmpeg, t('about.copy_ffmpeg_tip'))
            )
            btn_copy_ffmpeg.pack(side="right", padx=(0, scale_val(4)), pady=scale_val(2))
            tip_copy_ffmpeg = Tooltip(btn_copy_ffmpeg, t('about.copy_ffmpeg_tip'))

            # C3. Dependency Entry 2: HandBrakeCLI
            hb_ready = bool(self._handbrake and os.path.isfile(self._handbrake))
            if hb_ready and not getattr(self, "_handbrake_version", None) and hasattr(dvd_engine, "get_handbrake_version"):
                try:
                    self._handbrake_version = dvd_engine.get_handbrake_version(self._handbrake)
                except Exception:
                    pass

            hb_ver = getattr(self, "_handbrake_version", None)
            hb_status_init = (f"{t('about.ready')} ({hb_ver})" if hb_ver else t('about.ready')) if hb_ready else t('about.not_found')
            hb_status_color = COLORS["success"] if hb_ready else COLORS["error"]

            hb_header = tk.Frame(card_diagnostics, bg=COLORS["bg_card"])
            hb_header.pack(fill="x", padx=inner_px, pady=(scale_val(2), scale_val(1)))

            lbl_hb_title = tk.Label(
                hb_header, text=t('about.handbrake'), font=FONTS["small_bold"],
                bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                anchor="w"
            )
            lbl_hb_title.pack(side="left")

            lbl_hb_status = tk.Label(
                hb_header,
                text=hb_status_init,
                font=FONTS["small_bold"],
                bg=COLORS["bg_card"],
                fg=hb_status_color,
                anchor="e"
            )
            lbl_hb_status.pack(side="right")

            hb_path_frame = tk.Frame(
                card_diagnostics, bg=COLORS["bg_panel"],
                highlightbackground=COLORS["border"],
                highlightthickness=1
            )
            hb_path_frame.pack(fill="x", padx=inner_px, pady=(0, scale_val(8)))

            lbl_path_hb = tk.Label(
                hb_path_frame,
                text=format_path_display(self._handbrake),
                font=FONTS["mono"],
                bg=COLORS["bg_panel"],
                fg=COLORS["text_secondary"] if hb_ready else COLORS["text_muted"],
                anchor="w"
            )
            lbl_path_hb.pack(side="left", fill="x", expand=True, padx=(scale_val(8), scale_val(4)), pady=scale_val(2))
            if hb_ready:
                Tooltip(lbl_path_hb, self._handbrake)

            btn_copy_hb = tk.Button(
                hb_path_frame,
                text="📋",
                font=FONTS["small"],
                width=3,
                bg=COLORS["bg_hover"],
                fg=COLORS["accent"] if hb_ready else COLORS["text_muted"],
                relief="flat", bd=0, padx=2, pady=1,
                cursor="hand2" if hb_ready else "",
                state="normal" if hb_ready else "disabled",
                activebackground=COLORS["bg_hover"],
                activeforeground=COLORS["accent_hover"],
                command=lambda: copy_path_handler(self._handbrake, btn_copy_hb, tip_copy_hb, t('about.copy_hb_tip'))
            )
            btn_copy_hb.pack(side="right", padx=(0, scale_val(4)), pady=scale_val(2))
            tip_copy_hb = Tooltip(btn_copy_hb, t('about.copy_hb_tip'))

            # Responsive path updater on resize
            def update_path_labels(event=None):
                try:
                    pw = max(ff_path_frame.winfo_width(), hb_path_frame.winfo_width())
                    if pw > 60:
                        avail = max(100, pw - scale_val(46))
                        char_w = 8.5 * (FONTS["mono"][1] / 11.0)
                        max_c = max(24, int(avail / char_w))
                        lbl_path_ffmpeg.configure(text=format_path_display(self._ffmpeg, max_len=max_c))
                        lbl_path_hb.configure(text=format_path_display(self._handbrake, max_len=max_c))
                except Exception:
                    pass

            def on_dlg_configure(event):
                if event.widget == dlg:
                    dlg.after_idle(update_path_labels)
            dlg.bind("<Configure>", on_dlg_configure)

            # ── Bounds Calculation & Responsive Geometry ──
            def apply_dialog_geometry(is_initial=False):
                dlg.update_idletasks()
                base_w = scale_val(640)
                base_h = scale_val(850)
                min_w = scale_val(560)
                min_h = scale_val(700)

                req_w = dlg.winfo_reqwidth()
                req_h = dlg.winfo_reqheight()

                dw = max(base_w, req_w)
                dh = max(base_h, req_h + scale_val(10))

                try:
                    mon_x1, mon_y1, mon_x2, mon_y2 = get_monitor_work_area(self if is_initial else dlg)
                    screen_w = mon_x2 - mon_x1
                    screen_h = mon_y2 - mon_y1
                except Exception:
                    mon_x1, mon_y1 = 0, 0
                    mon_x2, mon_y2 = 1920, 1080
                    screen_w = 1920
                    screen_h = 1080

                dw = min(dw, max(min_w, screen_w - 40))
                dh = min(dh, max(min_h, screen_h - 60))

                eff_min_w = min(min_w, dw)
                eff_min_h = min(min_h, dh)
                dlg.minsize(eff_min_w, eff_min_h)

                if is_initial:
                    rx = self.winfo_x()
                    ry = self.winfo_y()
                    rw = self.winfo_width()
                    rh = self.winfo_height()
                    target_x = rx + (rw - dw) // 2
                    target_y = ry + (rh - dh) // 2
                    nx = max(mon_x1, min(mon_x2 - dw, target_x))
                    ny = max(mon_y1, min(mon_y2 - dh, target_y))
                    dlg.geometry(f"{dw}x{dh}+{nx}+{ny}")
                    try:
                        dlg.transient(self)
                    except Exception:
                        pass
                else:
                    try:
                        cur_x = dlg.winfo_x()
                        cur_y = dlg.winfo_y()
                        cur_w = dlg.winfo_width()
                        cur_h = dlg.winfo_height()
                        cx = cur_x + cur_w // 2
                        cy = cur_y + cur_h // 2
                        target_x = cx - dw // 2
                        target_y = cy - dh // 2
                        nx = max(mon_x1, min(mon_x2 - dw, target_x))
                        ny = max(mon_y1, min(mon_y2 - dh, target_y))
                        dlg.geometry(f"{dw}x{dh}+{nx}+{ny}")
                    except Exception:
                        dlg.geometry(f"{dw}x{dh}")

                try:
                    dlg.deiconify()
                except Exception:
                    pass

            apply_dialog_geometry(is_initial=not rebuild)

            def update_dlg_lang():
                dlg.title(t('about.title'))
                lbl_cat_a.configure(text=f"🎨  {t('about.cat_appearance')}")
                lbl_cat_b.configure(text=f"⚙️  {t('about.cat_processing')}")
                lbl_cat_c.configure(text=f"🛠️  {t('about.cat_diagnostics')}")

                lbl_lang_title.configure(text=t('language.title'))
                lbl_appearance_title.configure(text=t('appearance.title'))
                lbl_scale_title.configure(text=t('scale.title'))
                lbl_fps_mode_title.configure(text=t('fps_mode.title'))
                lbl_priority_title.configure(text=t('priority.title'))
                lbl_scanner_title.configure(text=t('dvd_scanner.title'))
                lbl_notification_title.configure(text=t('notification.title'))
                lbl_diag_title.configure(text=t('diagnostics.title'))
                lbl_ffmpeg_title.configure(text=t('about.ffmpeg'))
                lbl_hb_title.configure(text=t('about.handbrake'))

                theme_buttons["system"].configure(text=t('appearance.system'))
                theme_buttons["light"].configure(text=t('appearance.light'))
                theme_buttons["dark"].configure(text=t('appearance.dark'))
                scale_buttons["100%"].configure(text=t('scale.100'))
                scale_buttons["125%"].configure(text=t('scale.125'))
                scale_buttons["150%"].configure(text=t('scale.150'))
                priority_buttons["Low"].configure(text=t('priority.low'))
                priority_buttons["Medium"].configure(text=t('priority.medium'))
                priority_buttons["High"].configure(text=t('priority.high'))
                fps_buttons["Passthrough"].configure(text=t('fps_mode.passthrough'))
                fps_buttons["CFR"].configure(text=t('fps_mode.cfr'))
                scanner_buttons["auto"].configure(text=t('dvd_scanner.auto'))
                scanner_buttons["direct_ifo"].configure(text=t('dvd_scanner.direct_ifo'))
                scanner_buttons["handbrake"].configure(text=t('dvd_scanner.handbrake'))
                for sm_k, tip in scanner_tips.items():
                    tip.text = t(f'dvd_scanner.{sm_k}_tip')
                notification_buttons[True].configure(text=t('notification.enabled'))
                notification_buttons[False].configure(text=t('notification.disabled'))
                tip_notification.text = t('notification.tip')

                is_busy = getattr(self, "_health_checking", False)
                btn_health_check.configure(
                    text=f"⏳  {t('diagnostics.running_check')}" if is_busy else f"🩺  {t('diagnostics.health_check')}",
                    state="disabled" if (self._ripping or is_busy) else "normal"
                )
                btn_export_txt.configure(text=f"📄  {t('diagnostics.export_report')}")
                lbl_diag_help.configure(text=t('diagnostics.health_check_tip'))

                tip_copy_ffmpeg.text = t('about.copy_ffmpeg_tip')
                tip_copy_hb.text = t('about.copy_hb_tip')

                ff_is_ready = bool(self._ffmpeg and os.path.isfile(self._ffmpeg))
                lbl_ffmpeg_status.configure(text=t('about.ready') if ff_is_ready else t('about.not_found'))

                hb_is_ready = bool(self._handbrake and os.path.isfile(self._handbrake))
                hb_curr_ver = getattr(self, "_handbrake_version", None)
                hb_st = (f"{t('about.ready')} ({hb_curr_ver})" if hb_curr_ver else t('about.ready')) if hb_is_ready else t('about.not_found')
                lbl_hb_status.configure(text=hb_st)

                lbl_license.configure(text=t('about.license'))
                btn_close.configure(text=t('about.close'))

                for l_key, btn in lang_buttons.items():
                    is_act = (i18n.lang == l_key)
                    btn.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )
                update_path_labels()
                apply_dialog_geometry(is_initial=False)

            def update_dlg_theme():
                try:
                    dlg.configure(bg=COLORS["bg_panel"])
                except Exception:
                    pass
                try:
                    d_hwnd = ctypes.windll.user32.GetAncestor(dlg.winfo_id(), 2) or dlg.winfo_id()
                    set_window_dark_mode(d_hwnd, i18n.get_effective_theme() == "dark")
                except Exception:
                    pass
                header_frame.configure(bg=COLORS["bg_dark"])
                header_inner.configure(bg=COLORS["bg_dark"])
                lbl_img.configure(bg=COLORS["bg_dark"], fg=COLORS["text_primary"])
                header_text.configure(bg=COLORS["bg_dark"])
                title_row.configure(bg=COLORS["bg_dark"])
                lbl_app_name.configure(bg=COLORS["bg_dark"], fg=COLORS["text_primary"])
                lbl_version.configure(bg=COLORS["bg_dark"], fg=COLORS["accent"])
                lbl_author.configure(bg=COLORS["bg_dark"], fg=COLORS["text_secondary"])
                header_sep.configure(bg=COLORS["border"])

                for c_card in (card_appearance, card_processing, card_diagnostics):
                    c_card.configure(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])

                lbl_cat_a.configure(bg=COLORS["bg_card"], fg=COLORS["accent"])
                lbl_cat_b.configure(bg=COLORS["bg_card"], fg=COLORS["accent"])
                lbl_cat_c.configure(bg=COLORS["bg_card"], fg=COLORS["accent"])

                for r in (row_language, row_appearance, row_scale, row_fps_mode, row_priority, row_dvd_scanner, row_notification, row_diag):
                    r.configure(bg=COLORS["bg_card"])

                for cf in (btn_lang_frame, theme_btn_frame, scale_btn_frame, fps_btn_frame, priority_btn_frame, scanner_btn_frame, notification_btn_frame, diag_action_box, btn_action_row):
                    cf.configure(bg=COLORS["bg_card"])

                for tl in (lbl_lang_title, lbl_appearance_title, lbl_scale_title, lbl_fps_mode_title, lbl_priority_title, lbl_scanner_title, lbl_notification_title, lbl_diag_title):
                    tl.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])

                for btn_dict in (lang_buttons, theme_buttons, scale_buttons, priority_buttons, fps_buttons, scanner_buttons, notification_buttons):
                    for k, btn in btn_dict.items():
                        if btn_dict is lang_buttons: is_act = (i18n.lang == k)
                        elif btn_dict is theme_buttons: is_act = (i18n.theme == k)
                        elif btn_dict is scale_buttons: is_act = (i18n.scale == k)
                        elif btn_dict is priority_buttons: is_act = (i18n.priority == k)
                        elif btn_dict is fps_buttons: is_act = (i18n.fps_mode == k)
                        elif btn_dict is scanner_buttons: is_act = (getattr(i18n, "dvd_scanner", "auto") == k)
                        else: is_act = (getattr(i18n, "notification", True) == k)

                        btn.configure(
                            bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                            fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                            highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                            font=FONTS["small_bold"] if is_act else FONTS["small"],
                            activebackground=COLORS["accent_hover"] if is_act else COLORS["bg_hover"],
                            activeforeground=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_primary"]
                        )

                is_busy = getattr(self, "_health_checking", False)
                btn_health_check.configure(
                    bg=COLORS["bg_panel"],
                    fg=COLORS["text_primary"] if not (self._ripping or is_busy) else COLORS["text_muted"],
                    highlightbackground=COLORS["border"],
                    activebackground=COLORS["bg_hover"],
                    activeforeground=COLORS["text_primary"],
                    state="disabled" if (self._ripping or is_busy) else "normal"
                )
                btn_export_txt.configure(
                    bg=COLORS["bg_panel"], fg=COLORS["success"],
                    highlightbackground=COLORS["border"],
                    activebackground=COLORS["bg_hover"], activeforeground=COLORS["success"]
                )
                lbl_diag_help.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
                lbl_diag_help.configure(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
                sep_diag.configure(bg=COLORS["border"])

                ff_is_ready = bool(self._ffmpeg and os.path.isfile(self._ffmpeg))
                ff_header.configure(bg=COLORS["bg_card"])
                lbl_ffmpeg_title.configure(bg=COLORS["bg_card"], fg=COLORS["text_primary"])
                lbl_ffmpeg_status.configure(
                    bg=COLORS["bg_card"],
                    fg=COLORS["success"] if ff_is_ready else COLORS["error"]
                )
                ff_path_frame.configure(bg=COLORS["bg_panel"], highlightbackground=COLORS["border"])
                lbl_path_ffmpeg.configure(
                    bg=COLORS["bg_panel"],
                    fg=COLORS["text_secondary"] if ff_is_ready else COLORS["text_muted"]
                )
                btn_copy_ffmpeg.configure(
                    bg=COLORS["bg_hover"],
                    fg=COLORS["accent"] if ff_is_ready else COLORS["text_muted"],
                    activebackground=COLORS["bg_hover"],
                    activeforeground=COLORS["accent_hover"]
                )

                hb_is_ready = bool(self._handbrake and os.path.isfile(self._handbrake))
                hb_header.configure(bg=COLORS["bg_card"])
                lbl_hb_title.configure(bg=COLORS["bg_card"], fg=COLORS["text_primary"])
                lbl_hb_status.configure(
                    bg=COLORS["bg_card"],
                    fg=COLORS["success"] if hb_is_ready else COLORS["error"]
                )
                hb_path_frame.configure(bg=COLORS["bg_panel"], highlightbackground=COLORS["border"])
                lbl_path_hb.configure(
                    bg=COLORS["bg_panel"],
                    fg=COLORS["text_secondary"] if hb_is_ready else COLORS["text_muted"]
                )
                btn_copy_hb.configure(
                    bg=COLORS["bg_hover"],
                    fg=COLORS["accent"] if hb_is_ready else COLORS["text_muted"],
                    activebackground=COLORS["bg_hover"],
                    activeforeground=COLORS["accent_hover"]
                )

                footer_frame.configure(bg=COLORS["bg_panel"])
                lbl_license.configure(bg=COLORS["bg_panel"], fg=COLORS["text_secondary"])
                btn_close.configure(
                    bg=COLORS["accent"],
                    fg=COLORS.get("btn_primary_fg", "#FFFFFF"),
                    activebackground=COLORS["accent_hover"],
                    activeforeground=COLORS.get("btn_primary_fg", "#FFFFFF")
                )
                for tip in (tip_copy_ffmpeg, tip_copy_hb, *scanner_tips.values()):
                    if hasattr(tip, "update_theme"):
                        tip.update_theme()
                update_path_labels()
                try:
                    dlg.update_idletasks()
                except Exception:
                    pass

            def update_dlg_scale():
                # 1. Scaled layout tokens
                card_px = scale_val(16)
                card_py = (scale_val(6), 0)
                inner_px = scale_val(14)
                row_py = scale_val(3)
                lbl_col_w = scale_val(148)

                # 2. Header
                header_inner.pack_configure(padx=card_px, pady=scale_val(10))
                header_sep.pack_configure(padx=card_px)
                header_icon = get_header_icon(scale_val(44))
                target_img = getattr(dlg, "lbl_img", lbl_img)
                if header_icon and target_img:
                    target_img.configure(image=header_icon)
                    target_img.image = header_icon
                if target_img:
                    target_img.pack_configure(padx=(0, scale_val(14)))
                lbl_version.pack_configure(padx=(scale_val(8), 0), pady=(scale_val(4), 0))
                lbl_author.pack_configure(pady=(scale_val(1), 0))

                # 3. Cards & categories
                card_appearance.pack_configure(padx=card_px, pady=card_py)
                lbl_cat_a.pack_configure(padx=inner_px, pady=(scale_val(6), scale_val(4)))
                card_processing.pack_configure(padx=card_px, pady=card_py)
                lbl_cat_b.pack_configure(padx=inner_px, pady=(scale_val(6), scale_val(4)))
                card_diagnostics.pack_configure(padx=card_px, pady=card_py)
                lbl_cat_c.pack_configure(padx=inner_px, pady=(scale_val(6), scale_val(4)))

                # 4. Rows in cards (padding & minsize)
                for r in (row_language, row_appearance, row_scale, row_fps_mode, row_priority, row_dvd_scanner, row_notification, row_diag):
                    r.grid_columnconfigure(0, weight=0, minsize=lbl_col_w)

                row_language.pack_configure(padx=inner_px, pady=row_py)
                row_appearance.pack_configure(padx=inner_px, pady=row_py)
                row_scale.pack_configure(padx=inner_px, pady=(row_py, scale_val(6)))
                row_fps_mode.pack_configure(padx=inner_px, pady=row_py)
                row_priority.pack_configure(padx=inner_px, pady=row_py)
                row_dvd_scanner.pack_configure(padx=inner_px, pady=row_py)
                row_notification.pack_configure(padx=inner_px, pady=(row_py, scale_val(6)))
                row_diag.pack_configure(padx=inner_px, pady=row_py)
                lbl_diag_title.grid_configure(pady=(scale_val(4), 0))

                # 5. Segmented buttons padding & spacing
                for btn_group in (lang_buttons, theme_buttons, scale_buttons, fps_buttons, priority_buttons, scanner_buttons, notification_buttons):
                    btn_list = list(btn_group.values())
                    for idx, b in enumerate(btn_list):
                        b.configure(padx=scale_val(2), pady=scale_val(3))
                        b.grid_configure(padx=(0, scale_val(4) if idx < len(btn_list) - 1 else 0))

                # 6. Update scale buttons active/inactive style
                for s_key, btn in scale_buttons.items():
                    is_act = (i18n.scale == s_key)
                    btn.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )

                # 7. Action buttons & diagnostics layout
                btn_health_check.configure(padx=scale_val(6), pady=scale_val(4))
                btn_health_check.grid_configure(padx=(0, scale_val(6)))
                btn_export_txt.configure(padx=scale_val(6), pady=scale_val(4))
                lbl_diag_help.configure(wraplength=scale_val(420))
                lbl_diag_help.pack_configure(pady=(scale_val(3), scale_val(2)))
                sep_diag.pack_configure(padx=inner_px, pady=(scale_val(6), scale_val(6)))

                # 8. Dependency entries
                ff_header.pack_configure(padx=inner_px, pady=(scale_val(2), scale_val(1)))
                ff_path_frame.pack_configure(padx=inner_px, pady=(0, scale_val(6)))
                lbl_path_ffmpeg.pack_configure(padx=(scale_val(8), scale_val(4)), pady=scale_val(2))
                btn_copy_ffmpeg.pack_configure(padx=(0, scale_val(4)), pady=scale_val(2))

                hb_header.pack_configure(padx=inner_px, pady=(scale_val(2), scale_val(1)))
                hb_path_frame.pack_configure(padx=inner_px, pady=(0, scale_val(8)))
                lbl_path_hb.pack_configure(padx=(scale_val(8), scale_val(4)), pady=scale_val(2))
                btn_copy_hb.pack_configure(padx=(0, scale_val(4)), pady=scale_val(2))

                # 9. Footer
                lbl_license.pack_configure(pady=(scale_val(4), 0))
                btn_close.configure(padx=scale_val(36), pady=scale_val(6))
                btn_close.pack_configure(pady=(scale_val(4), scale_val(10)))

                # 10. Geometry & minsize
                apply_dialog_geometry(is_initial=False)

                update_path_labels()

            dlg.update_theme = update_dlg_theme
            dlg.update_lang = update_dlg_lang
            dlg.update_scale = update_dlg_scale

            def set_appearance(mode):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch_theme(mode)
                update_dlg_theme()

            def set_scale(sk):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                if getattr(i18n, "scale", None) == sk:
                    return
                i18n.switch_scale(sk)

            def set_priority(pk):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch_priority(pk)
                for k, b in priority_buttons.items():
                    is_act = (i18n.priority == k)
                    b.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )

            def set_fps_mode(fk):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch_fps_mode(fk)
                for k, b in fps_buttons.items():
                    is_act = (i18n.fps_mode == k)
                    b.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )

            def set_dvd_scanner(sk):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch_dvd_scanner(sk)
                for k, b in scanner_buttons.items():
                    is_act = (getattr(i18n, "dvd_scanner", "auto") == k)
                    b.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )

            def set_notification(nv):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch_notification(nv)
                for k, b in notification_buttons.items():
                    is_act = (getattr(i18n, "notification", True) == k)
                    b.configure(
                        bg=COLORS["accent"] if is_act else COLORS["bg_panel"],
                        fg=COLORS.get("btn_primary_fg", "#FFFFFF") if is_act else COLORS["text_secondary"],
                        highlightbackground=COLORS["accent"] if is_act else COLORS["border"],
                        font=FONTS["small_bold"] if is_act else FONTS["small"]
                    )

            def set_lang(l):
                if self._ripping or getattr(self, "_scanning", False):
                    return
                i18n.switch(l)
                update_dlg_lang()

        build_content(rebuild=False)

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: dlg.destroy())

    def _browse_source(self):
        folder = filedialog.askdirectory(title="Select Disc folder", parent=self)
        if not folder:
            return
        self._vcd_path.set(folder)
        self._detect_label.configure(text=t('drive.detecting'), fg=COLORS["accent"])
        def check_bg():
            check = detect_disc(folder)
            self.after(0, lambda: self._apply_browse_check(folder, check))
        threading.Thread(target=check_bg, daemon=True).start()

    def _apply_browse_check(self, folder, check):
        if check.is_dvd:
            self._source_type = "DVD"
            self._last_non_vcd_drive = None
            self._update_format_visibility_for_source()
            self._log.log(t('log.dvd_found').format(folder=folder), "success")
            self._detect_label.configure(text=t('drive.folder_selected'), fg=COLORS["success"])
            vol_name = get_volume_label(folder)
            disp_name = vol_name or Path(folder).name or folder
            self._drive_lbl.configure(text=f"📀  {disp_name}", fg=COLORS["success"])
            if hasattr(self, "_scan_btn"):
                self._scan_btn.set_text(t('source.scan_dvd'), icon="🔍")
            self.after(300, self._scan_disc)
        elif check.is_vcd:
            self._source_type = "VCD"
            self._last_non_vcd_drive = None
            self._update_format_visibility_for_source()
            self._log.log(t('log.vcd_found').format(folder=folder), "success")
            self._detect_label.configure(text=t('drive.folder_selected'), fg=COLORS["success"])
            vol_name = get_volume_label(folder)
            disp_name = vol_name or Path(folder).name or folder
            self._drive_lbl.configure(text=f"💿  {disp_name}", fg=COLORS["success"])
            if hasattr(self, "_scan_btn"):
                self._scan_btn.set_text(t('source.scan_vcd'), icon="🔍")
            self.after(300, self._scan_disc)
        else:
            self._source_type = "NONE"
            self._update_format_visibility_for_source()
            log_msg = t('log.unsupported_blocked').format(drive=folder, type=check.disc_type)
            self._log.log(log_msg, "warning")
            self._detect_label.configure(text=f"{check.disc_type}", fg=COLORS["warning"])
            self._show_unsupported_disc_dialog(folder, check.disc_type)

    def _on_scan_error(self, title, message):
        """Cleanly reset scan state and show error dialog when a scan fails."""
        self._scanning = False
        self._pause_drive_poll = False
        if hasattr(self, "_scan_btn"):
            self._scan_btn.configure_state(True)
        if hasattr(self, "_scan_progress_frame"):
            self._scan_progress_frame.pack_forget()
        if hasattr(self, "_scan_progress_bar"):
            self._scan_progress_bar.pack_forget()
        self._log.log(f"{title}: {message}", "error")
        messagebox.showerror(title, message, parent=self)

    def _scan_disc(self):
        if getattr(self, "_scanning", False) or self._ripping:
            return

        path = self._vcd_path.get().strip()
        if not path:
            messagebox.showwarning(t('messageboxes.no_source_title'), t('messageboxes.no_source_msg'), parent=self)
            return

        self._scanning = True
        self._pause_drive_poll = True
        if hasattr(self, "_scan_btn"):
            self._scan_btn.configure_state(False)

        self._detect_label.configure(text=t('drive.detecting'), fg=COLORS["accent"])

        def _bg_detect():
            try:
                with dvd_diagnostics.get_drive_io_lock():
                    check = detect_disc(path)
                self.after(0, lambda: self._dispatch_scan_after_detect(path, check))
            except Exception as exc:
                self._pause_drive_poll = False
                self.after(0, lambda err=str(exc): self._on_scan_error("Disc Detection Error", err))

        threading.Thread(target=_bg_detect, daemon=True).start()

    def _dispatch_scan_after_detect(self, path, check):
        if check.is_dvd:
            self._source_type = "DVD"
            self._update_format_visibility_for_source()
            self._scan_dvd(path)
        elif check.is_vcd:
            self._source_type = "VCD"
            self._update_format_visibility_for_source()
            self._scan_vcd_pipeline(path)
        else:
            self._scanning = False
            self._pause_drive_poll = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)
            self._source_type = "NONE"
            self._update_format_visibility_for_source()
            if check.disc_type in ("Empty Drive", "Empty Disc", "Drive Unavailable", "No Disc"):
                self._log.log(f"Drive {path}: {check.disc_type} ({check.details})", "warning")
                self._detect_label.configure(text=f"{check.disc_type}", fg=COLORS["warning"])
                messagebox.showinfo(
                    t('messageboxes.no_files_title'),
                    f"{check.disc_type}: {check.details or 'Please insert a VCD or DVD.'}",
                    parent=self
                )
            else:
                log_msg = t('log.unsupported_blocked').format(drive=path, type=check.disc_type)
                self._log.log(log_msg, "warning")
                self._detect_label.configure(text=f"{check.disc_type}", fg=COLORS["warning"])
                self._show_unsupported_disc_dialog(path, check.disc_type)

    def _scan_vcd(self):
        self._scan_disc()

    def _scan_dvd(self, path):
        if not path:
            self._scanning = False
            self._pause_drive_poll = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)
            messagebox.showwarning(t('messageboxes.no_source_title'), t('messageboxes.no_source_msg'), parent=self)
            return

        self._scanning = True
        self._pause_drive_poll = True
        if hasattr(self, "_scan_btn"):
            self._scan_btn.configure_state(False)

        self._videos.clear()
        self._clear_list()
        dvd_engine.clear_dvdvideo_probe_cache()
        dvd_engine.clear_handbrake_validation_cache()
        self._log.log(t('log.scan_dir').format(path=path), "accent")

        # Initialize persistent diagnostic session for this DVD scan
        diag_session = dvd_diagnostics.DVDScanDiagnosticSession(
            drive_path=path,
            scanner_mode=getattr(i18n, "dvd_scanner", "auto"),
            app_version=APP_VERSION,
            hb_path=self._handbrake,
            ffmpeg_path=self._ffmpeg,
            ffprobe_path=self._ffprobe
        )
        self._current_dvd_diag_session = diag_session

        # Show scan progress bar
        folder_display = get_volume_label(path) or Path(path).name or path
        self._scan_progress_lbl.configure(text=t('content.scan_prog_dvd').format(name=folder_display))
        self._scan_progress_pct.configure(text="0%")
        self._scan_progress_var.set(0)
        self._scan_progress_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._scan_progress_bar.pack(fill="x", padx=8, pady=(0, 8))

        def after_dvd_scan(titles):
            self._scanning = False
            self._pause_drive_poll = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)

            if diag_session:
                if titles:
                    diag_session.complete_session(title_count=len(titles), details=f"Successfully scanned {len(titles)} titles.")
                else:
                    diag_session.fail_session("Scan finished with 0 titles found.")

            if not titles:
                self._scan_progress_frame.pack_forget()
                self._scan_progress_bar.pack_forget()
                self._log.log(t('log.no_vid'), "warning")
                messagebox.showinfo(
                    t('messageboxes.no_files_title'),
                    t('messageboxes.no_files_msg'),
                    parent=self
                )
                return

            total = len(titles)
            self._log.log(t('log.found_files').format(total=total), "info")
            self._video_count_badge.configure(text=t('content.badge_titles').format(n=total))

            for t_item in titles:
                dur_str = format_duration(t_item.get("duration", 0))
                self._log.log(
                    f"  {t_item['filename']}  —  {t_item.get('size_mb', 0)} MB  {dur_str}  [{t_item.get('resolution', '')} {t_item.get('aspect_ratio', '')}]", "info"
                )
                chaps_data = t_item.get("chapters_data", [])
                if chaps_data and len(chaps_data) > 1:
                    for ch in chaps_data:
                        c_n = ch.get("chapter_number", 1)
                        st_s = ch.get("start_str", "0:00")
                        et_s = ch.get("end_str", "")
                        d_s = ch.get("duration_str", "")
                        self._log.log(f"    • Chapter {c_n:02d}: {st_s} → {et_s} ({d_s})", "info")

            # Finish scan progress
            self._scan_progress_var.set(100)
            self._scan_progress_pct.configure(text="100%")
            self._populate_list(titles)
            self.after(600, lambda: (
                self._scan_progress_frame.pack_forget(),
                self._scan_progress_bar.pack_forget()
            ))

        def do_scan_dvd_bg():
            def update_scan_progress(pct: int, stage_desc: str):
                def _apply():
                    if hasattr(self, "_scan_progress_var"):
                        self._scan_progress_var.set(pct)
                    if hasattr(self, "_scan_progress_pct"):
                        self._scan_progress_pct.configure(text=f"{pct}%")
                    if hasattr(self, "_scan_progress_lbl"):
                        base_txt = t('content.scan_prog_dvd').format(name=folder_display)
                        self._scan_progress_lbl.configure(text=f"{base_txt} ({stage_desc})")
                try:
                    self.after(0, _apply)
                except Exception:
                    pass

            try:
                diag_session.set_stage("VALIDATING_PATH", f"Verifying path '{path}'")
                update_scan_progress(10, t('content.scan_stage_validating'))
                if not os.path.isdir(path):
                    diag_session.fail_session(f"Path does not exist: {path}")
                    self._pause_drive_poll = False
                    self.after(0, lambda: self._on_scan_error(
                        t('messageboxes.invalid_path_title'),
                        t('messageboxes.invalid_path_msg').format(path=path)
                    ))
                    return

                # Check encryption
                diag_session.set_stage("CHECKING_ENCRYPTION", "Checking for CSS copy protection")
                update_scan_progress(15, "Checking encryption")
                video_ts_dir = dvd_engine.find_video_ts_dir(path)
                if video_ts_dir:
                    is_enc, enc_reason = dvd_engine.check_dvd_encryption(str(video_ts_dir))
                    if is_enc:
                        diag_session.fail_session(f"Encrypted DVD: {enc_reason}")
                        self._pause_drive_poll = False
                        def handle_enc():
                            self._scanning = False
                            if hasattr(self, "_scan_btn"):
                                self._scan_btn.configure_state(True)
                            self._scan_progress_frame.pack_forget()
                            self._scan_progress_bar.pack_forget()
                            self._log.log(f"Encrypted DVD detected: {enc_reason}", "warning")
                            messagebox.showwarning(
                                t('messageboxes.dvd_encrypted_title'),
                                t('messageboxes.dvd_encrypted_msg'),
                                parent=self
                            )
                        self.after(0, handle_enc)
                        return

                diag_session.set_stage("SCANNING_TITLES", f"Scanning titles using engine: {getattr(i18n, 'dvd_scanner', 'auto')}")
                update_scan_progress(25, t('content.scan_stage_handbrake') if getattr(i18n, 'dvd_scanner', 'auto') != 'direct_ifo' else t('content.scan_stage_ifo'))
                titles = dvd_engine.scan_dvd_titles(
                    path,
                    self._ffmpeg,
                    self._ffprobe,
                    self._handbrake,
                    scanner_mode=getattr(i18n, "dvd_scanner", "auto"),
                    diag_session=diag_session,
                    progress_callback=update_scan_progress
                )
                self.after(0, lambda: after_dvd_scan(titles))
            except Exception as exc:
                if diag_session:
                    diag_session.fail_session(str(exc))
                self._pause_drive_poll = False
                self.after(0, lambda err=str(exc): self._on_scan_error("DVD Scan Error", err))

        threading.Thread(target=do_scan_dvd_bg, daemon=True).start()

    def _scan_vcd_pipeline(self, path=None):
        if not path:
            path = self._vcd_path.get().strip()
        if not path:
            self._scanning = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)
            messagebox.showwarning(t('messageboxes.no_source_title'), t('messageboxes.no_source_msg'), parent=self)
            return

        self._scanning = True
        if hasattr(self, "_scan_btn"):
            self._scan_btn.configure_state(False)

        self._videos.clear()
        self._clear_list()
        self._log.log(t('log.scan_dir').format(path=path), "accent")

        # Show scan progress bar
        self._scan_progress_lbl.configure(text=t('content.scan_prog_folder').format(name=path))
        self._scan_progress_pct.configure(text="0%")
        self._scan_progress_var.set(0)
        self._scan_progress_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._scan_progress_bar.pack(fill="x", padx=8, pady=(0, 8))

        def after_scan(files):
            if not files:
                self._scanning = False
                if hasattr(self, "_scan_btn"):
                    self._scan_btn.configure_state(True)
                self._scan_progress_frame.pack_forget()
                self._scan_progress_bar.pack_forget()
                self._log.log(t('log.no_vid'), "warning")
                messagebox.showinfo(
                    t('messageboxes.no_files_title'),
                    t('messageboxes.no_files_msg'),
                    parent=self
                )
                return

            total = len(files)
            self._log.log(t('log.found_files').format(total=total), "info")
            self._video_count_badge.configure(text=t('content.badge_tracks').format(n=total))

            def probe_all():
                try:
                    infos = []
                    for i, f in enumerate(files):
                        fname = Path(f).name
                        pct = int((i / total) * 100)
                        self.after(0, lambda idx=i, fn=fname, p=pct: (
                            self._scan_progress_lbl.configure(text=t('content.scan_prog_read').format(idx=idx+1, total=total, name=fn)),
                            self._scan_progress_pct.configure(text=f"{p}%"),
                            self._scan_progress_var.set(p)
                        ))
                        if self._ffprobe:
                            info = probe_video(self._ffprobe, f)
                        else:
                            info = {
                                "path":     f,
                                "filename": sanitize_filename(fname),
                                "size_mb":  round(os.path.getsize(f) / 1024**2, 1),
                                "duration": 0, "width": 352, "height": 240,
                                "codec": "MPEG1", "fps": "29 fps", "bitrate": "~1150 kbps",
                            }
                        info["disc_type"] = "VCD"
                        infos.append(info)
                        self.after(0, lambda info_item=info: self._log.log(
                            f"  {info_item['filename']}  —  {info_item['size_mb']} MB  {format_duration(info_item['duration'])}", "info"
                        ))

                    def finish_vcd():
                        self._scanning = False
                        if hasattr(self, "_scan_btn"):
                            self._scan_btn.configure_state(True)
                        self._scan_progress_var.set(100)
                        self._scan_progress_pct.configure(text="100%")
                        self._populate_list(infos)
                        self.after(600, lambda: (
                            self._scan_progress_frame.pack_forget(),
                            self._scan_progress_bar.pack_forget()
                        ))
                    self.after(0, finish_vcd)
                except Exception as exc:
                    self.after(0, lambda err=str(exc): self._on_scan_error("VCD Metadata Read Error", err))

            threading.Thread(target=probe_all, daemon=True).start()

        def do_scan_bg():
            try:
                if not os.path.isdir(path):
                    self.after(0, lambda: self._on_scan_error(
                        t('messageboxes.invalid_path_title'),
                        t('messageboxes.invalid_path_msg').format(path=path)
                    ))
                    return

                folder_display = get_volume_label(path) or Path(path).name or path
                self.after(0, lambda: self._scan_progress_lbl.configure(
                    text=t('content.scan_prog_folder').format(name=folder_display)
                ))

                # Validate disc format - intercept non-VCD discs
                check = is_vcd_disc(path)
                if not check.is_vcd:
                    def handle_non_vcd():
                        self._scanning = False
                        if hasattr(self, "_scan_btn"):
                            self._scan_btn.configure_state(True)
                        self._scan_progress_frame.pack_forget()
                        self._scan_progress_bar.pack_forget()
                        log_msg = t('log.non_vcd_blocked').format(drive=path, type=check.disc_type)
                        if log_msg == 'log.non_vcd_blocked':
                            log_msg = f"Disc detected in drive {path}, type: {check.disc_type}, blocking process."
                        self._log.log(log_msg, "warning")
                        self._show_unsupported_disc_dialog(path, check.disc_type)
                    self.after(0, handle_non_vcd)
                    return

                files = find_dat_files(path)
                if not files:
                    # Fallback: look for any video-like files
                    exts = [".dat", ".mpg", ".mpeg", ".vob", ".mp4", ".avi"]
                    for ext in exts:
                        try:
                            files.extend(str(p) for p in Path(path).rglob(f"*{ext}"))
                        except Exception:
                            pass
                self.after(0, lambda: after_scan(files))
            except Exception as exc:
                self.after(0, lambda err=str(exc): self._on_scan_error("VCD Scan Error", err))

        threading.Thread(target=do_scan_bg, daemon=True).start()

    def _populate_list(self, infos):
        self._videos = infos
        self._cards.clear()
        self._selected_indices.clear()
        self._selected_chapters.clear()
        self._clear_list()

        if self._empty_frame.winfo_exists():
            self._empty_frame.pack_forget()

        for i, info in enumerate(infos):
            card = VideoCard(
                self._list_frame, info, i,
                on_toggle=self._on_card_toggle,
                on_chapter_toggle=self._on_chapter_toggle
            )
            card.pack(fill="x", padx=4, pady=3)
            self._cards.append(card)

        # Auto-select all videos/chapters by default
        self._select_all()
        if self._source_type == "DVD":
            self._log.log(t('log.dvd_loaded').format(total=len(infos)), "success")
            self._video_count_badge.configure(text=t('content.badge_titles').format(n=len(infos)))
        else:
            self._log.log(t('log.loaded').format(total=len(infos)), "success")
            self._video_count_badge.configure(text=t('content.badge_tracks').format(n=len(infos)))

        if hasattr(self, "_detect_label"):
            self._detect_label.configure(text=t('drive.detected'), fg=COLORS["cyan"])

        if self._source_type == "DVD":
            self._dvd_selected_audio_tracks.clear()
            mf_idx = 0
            for idx, v in enumerate(infos):
                if v.get("is_main_feature"):
                    mf_idx = idx
                    break
            self._active_dvd_title_idx = mf_idx
            self._update_audio_track_selector()

    def _clear_list(self):
        for w in self._list_frame.winfo_children():
            if not hasattr(self, "_empty_frame") or w is not self._empty_frame:
                w.destroy()

    def _on_card_toggle(self, index, selected):
        if selected:
            self._selected_indices.add(index)
            if self._source_type == "DVD" and index < len(self._cards):
                card = self._cards[index]
                chaps = card.info.get("chapters_data", [])
                for c in chaps:
                    c_num = int(c.get("chapter_number", 1))
                    self._selected_chapters.discard((index, c_num))
        else:
            self._selected_indices.discard(index)
        self._update_sel_count()

    def _on_chapter_toggle(self, index, chapter_number, selected):
        key = (index, chapter_number)
        if selected:
            self._selected_chapters.add(key)
            self._selected_indices.discard(index)
            if index < len(self._cards):
                self._cards[index].set_title_selected(False)
        else:
            self._selected_chapters.discard(key)
        self._update_sel_count()

    def _on_dvd_mode_change(self):
        pass

    def _select_all(self):
        if self._source_type == "DVD":
            self._selected_indices.clear()
            self._selected_chapters.clear()
            for idx, card in enumerate(self._cards):
                chaps = card.info.get("chapters_data", [])
                if chaps:
                    card.select_all_chapters(notify=False)
                    for c in chaps:
                        c_num = int(c.get("chapter_number", 1))
                        self._selected_chapters.add((idx, c_num))
                else:
                    self._selected_indices.add(idx)
                    card.set_title_selected(True)
                    card.clear_all_chapters(notify=False)
            if self._videos:
                if not (0 <= self._active_dvd_title_idx < len(self._videos)):
                    mf_idx = 0
                    for idx, v in enumerate(self._videos):
                        if v.get("is_main_feature"):
                            mf_idx = idx
                            break
                    self._active_dvd_title_idx = mf_idx
                self._update_audio_track_selector()
        else:
            self._selected_indices = set(range(len(self._videos)))
            for card in self._cards:
                card.set_selected(True)
        self._update_sel_count()

    def _select_none(self):
        self._selected_indices.clear()
        self._selected_chapters.clear()
        for card in self._cards:
            card.set_title_selected(False)
            card.clear_all_chapters(notify=False)
        self._update_sel_count()

    def _is_all_selected(self) -> bool:
        if not self._videos or not self._cards:
            return False
        if self._source_type == "DVD":
            for idx, card in enumerate(self._cards):
                chaps = card.info.get("chapters_data", [])
                if chaps:
                    all_ch_selected = all((idx, int(c.get("chapter_number", 1))) in self._selected_chapters for c in chaps)
                    title_selected = (idx in self._selected_indices)
                    if not (all_ch_selected or title_selected):
                        return False
                else:
                    if idx not in self._selected_indices:
                        return False
            return True
        else:
            return len(self._selected_indices) == len(self._videos) and len(self._videos) > 0

    def _is_none_selected(self) -> bool:
        if not self._videos:
            return False
        return len(self._selected_indices) == 0 and len(self._selected_chapters) == 0

    def _update_sel_count(self):
        all_sel = self._is_all_selected()
        none_sel = self._is_none_selected()

        if hasattr(self, "_sel_all_btn"):
            all_icon = "☑" if all_sel else "☐"
            self._sel_all_btn.set_text(t('selection.all'), icon=all_icon)
            self._sel_all_btn.set_active(all_sel)

        if hasattr(self, "_sel_none_btn"):
            none_icon = "☑" if none_sel else "☐"
            self._sel_none_btn.set_text(t('selection.none'), icon=none_icon)
            self._sel_none_btn.set_active(none_sel)

        if self._source_type == "DVD":
            n_t = len(self._selected_indices)
            n_c = len(self._selected_chapters)
            self._sel_count_lbl.configure(
                text=t('selection.count_dvd_hierarchical').format(titles=n_t, chapters=n_c),
                fg=COLORS["accent"] if (n_t > 0 or n_c > 0) else COLORS["text_muted"]
            )
        else:
            n = len(self._selected_indices)
            total = len(self._videos)
            self._sel_count_lbl.configure(
                text=t('selection.count').format(n=n, total=total),
                fg=COLORS["accent"] if n else COLORS["text_muted"]
            )

    def _choose_output(self):
        folder = filedialog.askdirectory(title="Select output folder", parent=self)
        if folder:
            self._output_folder.set(folder)
            self._log.log(t('log.out_set').format(folder=folder), "info")

    def _update_format_greyout(self):
        """Grey out or enable Video and Audio format options according to output mode."""
        mode = self._output_mode.get()
        if mode not in ("video", "audio", "both"):
            mode = "video"
            self._output_mode.set("video")

        # In "both" mode, enforce valid selections exist in both panels
        if mode == "both":
            if not self._output_format.get() or (self._source_type == "DVD" and self._output_format.get() == "DAT"):
                self._output_format.set("MP4")
            if not self._audio_format.get() or self._audio_format.get() not in AUDIO_FORMATS:
                self._audio_format.set("MP3")

        video_enabled = (mode in ("video", "both"))
        audio_enabled = (mode in ("audio", "both"))

        # ── Video panel greyout / enable ──
        if hasattr(self, "_video_fmt_lbl"):
            self._video_fmt_lbl.configure(
                fg=COLORS["text_secondary"] if video_enabled else COLORS["text_muted"]
            )
        for item in getattr(self, "_fmt_items", []):
            fmt = item.get("fmt", "")
            info = OUTPUT_FORMATS.get(fmt, {"color": COLORS["text_primary"]})
            rb = item.get("rb")
            lbl = item.get("lbl")
            if rb:
                if video_enabled:
                    rb.configure(
                        state="normal",
                        fg=info["color"],
                        activeforeground=info["color"],
                        cursor="hand2"
                    )
                else:
                    rb.configure(
                        state="disabled",
                        fg=COLORS["text_muted"],
                        activeforeground=COLORS["text_muted"],
                        cursor=""
                    )
            if lbl:
                lbl.configure(
                    fg=COLORS["text_secondary"] if video_enabled else COLORS["text_muted"]
                )

        # ── Resolution sub-panel greyout / enable ──
        if hasattr(self, "_res_title_lbl"):
            self._res_title_lbl.configure(
                fg=COLORS["text_secondary"] if video_enabled else COLORS["text_muted"]
            )
        if hasattr(self, "_res_orig_rb"):
            self._res_orig_rb.configure(
                state="normal" if video_enabled else "disabled",
                fg=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                activeforeground=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                disabledforeground=COLORS["text_muted"],
                cursor="hand2" if video_enabled else ""
            )
        if hasattr(self, "_res_1080p_rb"):
            self._res_1080p_rb.configure(
                state="normal" if video_enabled else "disabled",
                fg=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                activeforeground=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                disabledforeground=COLORS["text_muted"],
                cursor="hand2" if video_enabled else ""
            )

        # ── DAT sub-panel greyout / enable ──
        if hasattr(self, "_dat_mode_lbl"):
            self._dat_mode_lbl.configure(
                fg=COLORS["text_secondary"] if video_enabled else COLORS["text_muted"]
            )
        if hasattr(self, "_dat_raw_rb"):
            self._dat_raw_rb.configure(
                state="normal" if video_enabled else "disabled",
                fg=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                activeforeground=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                disabledforeground=COLORS["text_muted"],
                cursor="hand2" if video_enabled else ""
            )
        if hasattr(self, "_dat_mp4_rb"):
            self._dat_mp4_rb.configure(
                state="normal" if video_enabled else "disabled",
                fg=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                activeforeground=COLORS["text_primary"] if video_enabled else COLORS["text_muted"],
                disabledforeground=COLORS["text_muted"],
                cursor="hand2" if video_enabled else ""
            )

        # ── Audio panel greyout / enable ──
        if hasattr(self, "_audio_fmt_lbl"):
            self._audio_fmt_lbl.configure(
                fg=COLORS["text_secondary"] if audio_enabled else COLORS["text_muted"]
            )
        for item in getattr(self, "_audio_items", []):
            afmt = item.get("fmt", "")
            ainfo = AUDIO_FORMATS.get(afmt, {"color": COLORS["text_primary"]})
            rb = item.get("rb")
            lbl = item.get("lbl")
            if rb:
                if audio_enabled:
                    rb.configure(
                        state="normal",
                        fg=ainfo["color"],
                        activeforeground=ainfo["color"],
                        cursor="hand2"
                    )
                else:
                    rb.configure(
                        state="disabled",
                        fg=COLORS["text_muted"],
                        activeforeground=COLORS["text_muted"],
                        cursor=""
                    )
            if lbl:
                lbl.configure(
                    fg=COLORS["text_secondary"] if audio_enabled else COLORS["text_muted"]
                )

        # Update suboption visibility (DAT / Resolution) based on video state
        self._update_format_visibility_for_source()

    def _on_format_change(self):
        self._update_format_greyout()

    def _on_audio_format_change(self):
        pass

    def _on_mode_change(self):
        self._update_format_greyout()

    # ── Ripping logic ─────────────────────────
    def _stop_rip(self):
        if not self._ripping:
            return
        self._cancel_requested = True
        self._taskbar_progress.set_paused()
        self._log.log(t('log.cancel_req'), "warning")
        if self._current_proc and self._current_proc.poll() is None:
            try:
                kill_process_tree(self._current_proc, force=True)
            except Exception:
                pass
        self._stop_btn.configure_state(False)

    def _start_rip(self):
        if self._ripping:
            return

        mode = self._output_mode.get()
        if mode == "audio":
            fmt     = self._audio_format.get()
            fmt_cfg = AUDIO_FORMATS[fmt]
            vid_fmt = None
            aud_fmt = fmt
        elif mode == "both":
            vid_fmt = self._output_format.get()
            if not vid_fmt:
                vid_fmt = "MP4"
                self._output_format.set("MP4")
            fmt     = vid_fmt
            fmt_cfg = OUTPUT_FORMATS.get(vid_fmt, {"ext": f".{vid_fmt.lower()}", "args": []})
            aud_fmt = self._audio_format.get()
            if not aud_fmt or aud_fmt not in AUDIO_FORMATS:
                aud_fmt = "MP3"
                self._audio_format.set("MP3")
        else:
            fmt     = self._output_format.get()
            fmt_cfg = OUTPUT_FORMATS.get(fmt, {"ext": f".{fmt.lower()}", "args": []})
            vid_fmt = fmt
            aud_fmt = None

        is_dvd = (self._source_type == "DVD") or any(v.get("disc_type") == "DVD" for v in self._videos)

        if is_dvd and fmt == "DAT" and mode in ("video", "both"):
            fmt = "MP4"
            vid_fmt = "MP4"
            self._output_format.set("MP4")
            fmt_cfg = OUTPUT_FORMATS["MP4"]

        needs_ffmpeg = is_dvd or (mode in ("audio", "both")) or (fmt not in ("DAT",))
        if needs_ffmpeg and not self._ffmpeg:
            messagebox.showerror(
                t('messageboxes.ffmpeg_req_title'),
                t('messageboxes.ffmpeg_req_msg'),
                parent=self
            )
            return

        # ── DVD Unified Ripping Dispatch (Hierarchical Selection) ──
        if is_dvd:
            title_jobs = [self._videos[i] for i in sorted(self._selected_indices) if i < len(self._videos)]
            chapter_jobs = []
            for (idx, ch_num) in sorted(self._selected_chapters):
                if idx < len(self._videos):
                    t_item = self._videos[idx]
                    for c in t_item.get("chapters_data", []):
                        if int(c.get("chapter_number", 1)) == ch_num:
                            chapter_jobs.append((t_item, c))
                            break

            total_dvd_jobs = len(title_jobs) + len(chapter_jobs)
            if total_dvd_jobs == 0:
                if self._videos:
                    if messagebox.askyesno(
                        t('messageboxes.no_sel_title'),
                        t('messageboxes.no_sel_msg'),
                        parent=self
                    ):
                        self._select_all()
                        title_jobs = [self._videos[i] for i in sorted(self._selected_indices) if i < len(self._videos)]
                        chapter_jobs = []
                        for (idx, ch_num) in sorted(self._selected_chapters):
                            if idx < len(self._videos):
                                t_item = self._videos[idx]
                                for c in t_item.get("chapters_data", []):
                                    if int(c.get("chapter_number", 1)) == ch_num:
                                        chapter_jobs.append((t_item, c))
                                        break
                        total_dvd_jobs = len(title_jobs) + len(chapter_jobs)
                    else:
                        return
                else:
                    messagebox.showwarning(t('messageboxes.no_vid_title'), t('messageboxes.no_vid_msg'), parent=self)
                    return

            out_folder = self._output_folder.get().strip()
            if not out_folder:
                out_folder = filedialog.askdirectory(title="Select output folder", parent=self)
                if not out_folder:
                    return
                self._output_folder.set(out_folder)

            os.makedirs(out_folder, exist_ok=True)

            self._ripping = True
            self._cancel_requested = False
            self._current_proc = None

            self._rip_btn.configure_state(False)
            self._stop_btn.configure_state(True)
            if hasattr(self, "_clear_all_btn"):
                self._clear_all_btn.configure(
                    state="disabled",
                    fg=COLORS["text_muted"],
                    cursor=""
                )
            self._progress_bar.pack(fill="x", padx=8, pady=(0, 8))
            self._progress_var.set(0)
            self._taskbar_progress.set_value(0, 100)
            disp_total = total_dvd_jobs * 2 if mode == "both" else total_dvd_jobs
            disp_fmt = f"{vid_fmt} + {aud_fmt}" if mode == "both" else fmt
            self._log.log(
                t('log.start_ext').format(total=disp_total, fmt=disp_fmt),
                "accent"
            )

            create_title_folder = bool(getattr(self, "_dvd_title_folder_var", None) and self._dvd_title_folder_var.get())
            generate_timeline = bool(getattr(self, "_dvd_timeline_var", None) and self._dvd_timeline_var.get())
            threading.Thread(
                target=self._rip_dvd_unified_thread,
                args=(
                    title_jobs, chapter_jobs, out_folder,
                    vid_fmt if mode == "both" else fmt,
                    self._use_1080p.get(),
                    (mode == "audio"),
                    aud_fmt if mode in ("audio", "both") else fmt,
                    (mode == "both"),
                    create_title_folder,
                    generate_timeline
                ),
                daemon=True
            ).start()
            return

        # ── VCD Ripping Dispatch (Preserved 100%) ──
        selected = sorted(self._selected_indices)
        if not selected:
            if self._videos:
                if messagebox.askyesno(
                    t('messageboxes.no_sel_title'),
                    t('messageboxes.no_sel_msg'),
                    parent=self
                ):
                    self._select_all()
                    selected = list(range(len(self._videos)))
                else:
                    return
            else:
                messagebox.showwarning(t('messageboxes.no_vid_title'), t('messageboxes.no_vid_msg'), parent=self)
                return

        out_folder = self._output_folder.get().strip()
        if not out_folder:
            out_folder = filedialog.askdirectory(title="Select output folder", parent=self)
            if not out_folder:
                return
            self._output_folder.set(out_folder)

        os.makedirs(out_folder, exist_ok=True)
        videos_to_rip = [self._videos[i] for i in selected]

        self._ripping = True
        self._cancel_requested = False
        self._current_proc = None

        self._rip_btn.configure_state(False)
        self._stop_btn.configure_state(True)
        if hasattr(self, "_clear_all_btn"):
            self._clear_all_btn.configure(
                state="disabled",
                fg=COLORS["text_muted"],
                cursor=""
            )
        self._progress_bar.pack(fill="x", padx=8, pady=(0, 8))
        self._progress_var.set(0)
        self._taskbar_progress.set_value(0, 100)
        disp_total = len(videos_to_rip) * 2 if mode == "both" else len(videos_to_rip)
        disp_fmt = f"{vid_fmt} + {aud_fmt}" if mode == "both" else fmt
        self._log.log(
            t('log.start_ext').format(total=disp_total, fmt=disp_fmt),
            "accent"
        )

        threading.Thread(
            target=self._rip_thread,
            args=(
                videos_to_rip, out_folder,
                vid_fmt if mode in ("video", "both") else "MP4",
                fmt_cfg,
                self._use_1080p.get(),
                mode,
                aud_fmt if mode in ("audio", "both") else "MP3"
            ),
            daemon=True
        ).start()

    def _rip_thread(self, videos, out_folder, fmt, fmt_cfg, use_1080p=False, mode="video", audio_fmt="MP3"):
        items = []
        for v in videos:
            if mode == "both":
                items.append({"video": v, "type": "video", "name": f"{v['filename']} (Video)"})
                items.append({"video": v, "type": "audio", "name": f"{v['filename']} (Audio)"})
            elif mode == "audio":
                items.append({"video": v, "type": "audio", "name": v['filename']})
            else:
                items.append({"video": v, "type": "video", "name": v['filename']})

        total   = len(items)
        success = 0
        errors  = 0
        was_cancelled = False
        was_timed_out = False

        # Ensure destination directory exists
        try:
            os.makedirs(out_folder, exist_ok=True)
        except Exception:
            pass

        # Calculate total duration for time-based progress
        total_duration = sum(v.get("duration", 0) for v in videos) * (2 if mode == "both" else 1)
        completed_duration = 0.0

        for i, item in enumerate(items):
            if self._cancel_requested:
                was_cancelled = True
                break

            video = item["video"]
            item_type = item["type"]
            display_name = item["name"]
            raw_stem = Path(video["filename"]).stem
            stem = video.get("custom_stem") or raw_stem
            stem = sanitize_filename(stem, fallback=f"track_{i+1}")

            if item_type == "video":
                # For DAT video: use .dat or .mp4 based on user sub-option
                if fmt == "DAT" and mode in ("video", "both"):
                    out_ext = ".mp4" if self._dat_rename_mp4.get() else ".dat"
                else:
                    out_ext = fmt_cfg["ext"]
            else:
                afmt_cfg = AUDIO_FORMATS.get(audio_fmt, AUDIO_FORMATS["MP3"])
                out_ext = afmt_cfg["ext"]

            out_name = f"{stem}{out_ext}"
            out_path = os.path.join(out_folder, out_name)

            # Avoid overwriting
            if os.path.exists(out_path):
                base, ext = os.path.splitext(out_path)
                out_path  = f"{base}_{int(time.time())}{ext}"
                out_name  = os.path.basename(out_path)

            # Update progress label with current file info
            if total_duration > 0:
                overall_pct = (completed_duration / total_duration) * 100
            else:
                overall_pct = (i / total) * 100 if total > 0 else 0
            self.after(0, lambda d_n=display_name, idx=i, pct=overall_pct: (
                self._progress_lbl.configure(
                    text=t('content.rip_prog_proc').format(idx=idx+1, total=total, name=d_n)
                ),
                self._progress_pct.configure(text=f"{int(pct)}%"),
                self._progress_var.set(pct),
                self._taskbar_progress.set_value(int(pct), 100)
            ))
            self.after(0, lambda d_n=display_name, o_n=os.path.basename(out_path): self._log.log(
                t('log.extracting').format(name=d_n, out=o_n), "info"
            ))

            if item_type == "video" and fmt == "DAT" and mode in ("video", "both"):
                # Direct binary file copy without FFmpeg (with watchdog & queue)
                try:
                    src_path = video["path"]
                    chunk_size = 1024 * 1024  # 1MB chunk
                    file_cancelled = False
                    dat_timed_out = False
                    src_size = os.path.getsize(src_path)
                    video_dur = video.get("duration", 0)
                    bytes_copied = 0

                    chunk_queue = queue.Queue(maxsize=8)
                    stop_reader = threading.Event()

                    def dat_reader():
                        try:
                            with open(src_path, "rb") as fsrc:
                                while not stop_reader.is_set():
                                    buf = fsrc.read(chunk_size)
                                    if not buf:
                                        chunk_queue.put(None)
                                        break
                                    chunk_queue.put(buf)
                        except Exception as read_ex:
                            chunk_queue.put(read_ex)

                    reader_t = threading.Thread(target=dat_reader, daemon=True)
                    reader_t.start()

                    last_heartbeat = time.time()
                    with open(out_path, "wb") as fdst:
                        while True:
                            if self._cancel_requested:
                                stop_reader.set()
                                file_cancelled = True
                                break

                            try:
                                item = chunk_queue.get(timeout=0.2)
                            except queue.Empty:
                                if time.time() - last_heartbeat > DISC_READ_TIMEOUT_SECONDS:
                                    stop_reader.set()
                                    dat_timed_out = True
                                    was_timed_out = True
                                    self.after(0, lambda v=video: self._log.log(
                                        t('log.read_timeout').format(name=v['filename'], timeout=int(DISC_READ_TIMEOUT_SECONDS)),
                                        "warning"
                                    ))
                                    break
                                continue

                            if item is None:
                                break
                            if isinstance(item, Exception):
                                raise item

                            last_heartbeat = time.time()
                            fdst.write(item)
                            bytes_copied += len(item)
                            if src_size > 0 and total_duration > 0:
                                file_progress = (bytes_copied / src_size) * video_dur
                                overall = (completed_duration + file_progress) / total_duration * 100
                                self.after(0, lambda p=overall, idx=i: (
                                    self._progress_var.set(p),
                                    self._progress_pct.configure(text=f"{int(p)}%"),
                                    self._taskbar_progress.set_value(int(p), 100)
                                ))

                    if file_cancelled or self._cancel_requested:
                        was_cancelled = True
                        if os.path.exists(out_path):
                            try:
                                os.remove(out_path)
                            except Exception:
                                pass
                        break

                    if dat_timed_out:
                        # Keep partial file for damaged disc
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                            part_size = round(os.path.getsize(out_path) / 1024**2, 1)
                            self.after(0, lambda n=out_name, s=part_size: self._log.log(
                                t('log.saved_partial').format(name=n, size=s), "warning"
                            ))
                        break

                    size = round(os.path.getsize(out_path) / 1024**2, 1)
                    success += 1
                    completed_duration += video.get("duration", 0)
                    video["last_ripped_video_path"] = out_path
                    self.after(0, lambda n=out_name, s=size: self._log.log(
                        t('log.raw_dat_ok').format(name=n, size=s), "success"
                    ))
                except Exception as e:
                    errors += 1
                    self.after(0, lambda err=str(e): self._log.log(
                        t('log.copy_err').format(err=err), "error"
                    ))
            else:
                # Use FFmpeg to convert/rip video or audio with error tolerance and low priority
                if item_type == "video":
                    ffmpeg_args = list(fmt_cfg["args"])
                    if use_1080p and fmt in ("MP4", "MOV"):
                        # Upscale VCD (352x240 / 352x288) to 1440x1080 (4:3 at 1080p)
                        # using Lanczos for sharpest quality upscale
                        ffmpeg_args = ["-vf", "scale=1440:1080:flags=lanczos"] + ffmpeg_args
                    if fmt in ("MP4", "MOV"):
                        fps_val = "cfr" if getattr(self.i18n, "fps_mode", "Passthrough").upper() == "CFR" else "passthrough"
                        ffmpeg_args = ["-fps_mode", fps_val] + ffmpeg_args
                    input_source = video["path"]
                else:  # audio
                    afmt_cfg = AUDIO_FORMATS.get(audio_fmt, AUDIO_FORMATS["MP3"])
                    ffmpeg_args = list(afmt_cfg["args"])
                    last_vid = video.get("last_ripped_video_path")
                    if last_vid and os.path.exists(last_vid) and not last_vid.lower().endswith(".dat"):
                        input_source = last_vid
                    else:
                        input_source = video["path"]

                cmd = [
                    self._ffmpeg,
                    "-nostdin",
                    "-err_detect", "ignore_err",
                    "-fflags", "+discardcorrupt",
                    "-i", input_source,
                    *ffmpeg_args,
                    "-max_error_rate", "1.0",
                    "-y",
                    out_path
                ]

                try:
                    extra_flags = get_priority_creation_flag(self.i18n.priority)
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=get_subprocess_env(),
                        **get_subprocess_kwargs(extra_flags=extra_flags)
                    )
                    self._current_proc = proc
                    set_process_priority(proc, priority_level=self.i18n.priority, low_io=True)

                    video_dur = video.get("duration", 0)
                    line_queue = queue.Queue()

                    def read_stdout():
                        try:
                            for line in iter(proc.stdout.readline, ''):
                                line_queue.put(line)
                        except Exception:
                            pass
                        finally:
                            try:
                                proc.stdout.close()
                            except Exception:
                                pass
                            line_queue.put(None)

                    reader_t = threading.Thread(target=read_stdout, daemon=True)
                    reader_t.start()

                    last_io_time = time.time()
                    last_progress_time = time.time()
                    last_log_time = 0.0
                    last_seen_frame = -1
                    last_seen_secs = -1.0
                    last_seen_size_kb = -1
                    last_seen_fsize = -1
                    stall_warning_logged = False
                    proc_timed_out = False

                    while True:
                        if self._cancel_requested:
                            kill_process_tree(proc, force=True)
                            break

                        now = time.time()

                        # Monitor active file writing to prevent premature stall detection
                        if out_path and os.path.exists(out_path):
                            try:
                                cur_fsize = os.path.getsize(out_path)
                                if last_seen_fsize < 0:
                                    last_seen_fsize = cur_fsize
                                elif cur_fsize > (last_seen_fsize + 32768):
                                    last_seen_fsize = cur_fsize
                                    last_progress_time = now
                                    if stall_warning_logged:
                                        stall_warning_logged = False
                                        self.after(0, lambda v=video: self._log.log(
                                            f"[Disc Read Notice] Progress resumed on {v['filename']}.", "info"
                                        ))
                            except Exception:
                                pass

                        io_stalled_secs = now - last_io_time
                        prog_stalled_secs = now - last_progress_time

                        stall_warn_threshold = min(15.0, max(0.1, DISC_READ_TIMEOUT_SECONDS * 0.5))
                        if prog_stalled_secs >= stall_warn_threshold and not stall_warning_logged:
                            stall_warning_logged = True
                            frame_info = f" at frame {last_seen_frame}" if last_seen_frame >= 0 else ""
                            self.after(0, lambda v=video, fi=frame_info, ps=int(prog_stalled_secs): self._log.log(
                                f"[Disc Read Notice] Processing paused{fi} on {v['filename']} ({ps}s without progress update; optical drive reading or buffering)...",
                                "warning"
                            ))

                        if io_stalled_secs > DISC_READ_TIMEOUT_SECONDS or prog_stalled_secs > DISC_READ_TIMEOUT_SECONDS:
                            proc_timed_out = True
                            was_timed_out = True
                            stalled_reason = f"stalled at frame {last_seen_frame}" if (last_seen_frame >= 0 and prog_stalled_secs > DISC_READ_TIMEOUT_SECONDS) else "no response"
                            self.after(0, lambda v=video, sr=stalled_reason: self._log.log(
                                f"{t('log.read_timeout').format(name=v['filename'], timeout=int(DISC_READ_TIMEOUT_SECONDS))} ({sr})",
                                "warning"
                            ))
                            terminate_and_kill(proc, graceful_timeout=GRACEFUL_TERMINATE_TIMEOUT)
                            break

                        try:
                            line = line_queue.get(timeout=0.2)
                        except queue.Empty:
                            if proc.poll() is not None:
                                while not line_queue.empty():
                                    rem = line_queue.get_nowait()
                                    if rem is None:
                                        break
                                break
                            continue

                        if line is None:
                            break

                        last_io_time = time.time()
                        line = line.strip()
                        if line and ("frame=" in line or "speed=" in line):
                            frame_match = re.search(r'frame=\s*(\d+)', line)
                            time_match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                            size_match = re.search(r'size=\s*(\d+)kB', line)

                            cur_frame = int(frame_match.group(1)) if frame_match else None
                            cur_secs = None
                            if time_match:
                                h, m, s = time_match.groups()
                                cur_secs = int(h) * 3600 + int(m) * 60 + float(s)
                            cur_size_kb = int(size_match.group(1)) if size_match else None

                            progress_advanced = False
                            if cur_frame is not None and cur_frame > last_seen_frame:
                                last_seen_frame = cur_frame
                                progress_advanced = True
                            if cur_secs is not None and cur_secs > (last_seen_secs + 0.05):
                                last_seen_secs = cur_secs
                                progress_advanced = True
                            if cur_size_kb is not None and cur_size_kb > (last_seen_size_kb + 32):
                                last_seen_size_kb = cur_size_kb
                                progress_advanced = True

                            if progress_advanced:
                                last_progress_time = time.time()
                                if stall_warning_logged:
                                    stall_warning_logged = False
                                    self.after(0, lambda v=video: self._log.log(
                                        f"[Disc Read Notice] Progress resumed on {v['filename']}.", "info"
                                    ))
                                else:
                                    stall_warning_logged = False

                            now = time.time()
                            should_log = (now - last_log_time) >= 1.5
                            if should_log and (now - last_progress_time) < 2.0:
                                last_log_time = now
                                self.after(0, lambda l=line: self._log.log(l, "info"))

                            # Parse time= for fine-grained progress
                            if time_match and video_dur > 0 and total_duration > 0:
                                file_progress = min(cur_secs, video_dur)
                                overall = (completed_duration + file_progress) / total_duration * 100
                                overall = min(overall, 99.9)  # Don't hit 100% until truly done
                                self.after(0, lambda p=overall: (
                                    self._progress_var.set(p),
                                    self._progress_pct.configure(text=f"{int(p)}%"),
                                    self._taskbar_progress.set_value(int(p), 100)
                                ))
                        elif any(err_kw in line.lower() for err_kw in ("error", "corrupt", "invalid")):
                            self.after(0, lambda l=line: self._log.log(l, "warning"))

                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                    self._current_proc = None

                    if self._cancel_requested:
                        was_cancelled = True
                        if os.path.exists(out_path):
                            try:
                                os.remove(out_path)
                            except Exception:
                                pass
                        break

                    if proc_timed_out:
                        # Preserve partially recovered video file
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                            part_size = round(os.path.getsize(out_path) / 1024**2, 1)
                            self.after(0, lambda n=out_name, s=part_size: self._log.log(
                                t('log.saved_partial').format(name=n, size=s), "warning"
                            ))
                        errors += 1
                        completed_duration += video.get("duration", 0)
                        break

                    if proc.returncode == 0:
                        size = round(os.path.getsize(out_path) / 1024**2, 1)
                        success += 1
                        completed_duration += video.get("duration", 0)
                        if item_type == "video":
                            video["last_ripped_video_path"] = out_path
                        self.after(0, lambda n=out_name, s=size: self._log.log(
                            t('log.saved_ok').format(name=n, size=s), "success"
                        ))
                    else:
                        errors += 1
                        completed_duration += video.get("duration", 0)
                        self.after(0, lambda d_n=display_name: self._log.log(
                            t('log.ffmpeg_err').format(name=d_n), "error"
                        ))

                except Exception as e:
                    errors += 1
                    self.after(0, lambda err=str(e): self._log.log(
                        t('log.exc').format(err=err), "error"
                    ))

        # Done
        self.after(0, lambda: self._rip_done(
            total, success, errors, out_folder,
            cancelled=(was_cancelled or self._cancel_requested),
            timed_out=was_timed_out
        ))

    def _rip_dvd_unified_thread(self, title_jobs, chapter_jobs, out_folder, output_format, use_1080p=False, audio_only=False, audio_format="WAV", extract_both=False, create_title_folder=False, generate_timeline=False):
        jobs = []
        for t_item in title_jobs:
            t_base_name = t_item.get("filename") or t_item.get("name") or f"Title {t_item.get('title_number', 1):02d}"
            dur = float(t_item.get("duration", 0.0))
            if extract_both:
                jobs.append({
                    "type": "title",
                    "title": t_item,
                    "chapter": None,
                    "duration": dur,
                    "name": f"{t_base_name} (Video)",
                    "job_mode": "video",
                })
                jobs.append({
                    "type": "title",
                    "title": t_item,
                    "chapter": None,
                    "duration": dur,
                    "name": f"{t_base_name} (Audio)",
                    "job_mode": "audio",
                })
            else:
                jobs.append({
                    "type": "title",
                    "title": t_item,
                    "chapter": None,
                    "duration": dur,
                    "name": t_base_name,
                    "job_mode": "audio" if audio_only else "video",
                })
        for (t_item, c_item) in chapter_jobs:
            t_num = t_item.get("title_number", 1)
            c_num = c_item.get("chapter_number", 1)
            t_stem = t_item.get("custom_stem") or f"Title_{t_num:02d}"
            c_name = c_item.get("custom_stem") or c_item.get("name") or f"Chapter {c_num:02d}"
            ch_base = f"{t_stem} - {c_name}"
            dur = float(c_item.get("duration", 0.0))
            if dur <= 0.0:
                s_t = float(c_item.get("start_time", 0.0))
                e_t = float(c_item.get("end_time", 0.0))
                if e_t > s_t:
                    dur = e_t - s_t
            if extract_both:
                jobs.append({
                    "type": "chapter",
                    "title": t_item,
                    "chapter": c_item,
                    "duration": dur,
                    "name": f"{ch_base} (Video)",
                    "job_mode": "video",
                })
                jobs.append({
                    "type": "chapter",
                    "title": t_item,
                    "chapter": c_item,
                    "duration": dur,
                    "name": f"{ch_base} (Audio)",
                    "job_mode": "audio",
                })
            else:
                jobs.append({
                    "type": "chapter",
                    "title": t_item,
                    "chapter": c_item,
                    "duration": dur,
                    "name": ch_base,
                    "job_mode": "audio" if audio_only else "video",
                })

        # Sort jobs naturally by title number and chapter number
        jobs.sort(key=lambda j: (
            int(j["title"].get("title_number", 1)),
            0 if j["type"] == "title" else int(j["chapter"].get("chapter_number", 1)),
            0 if j.get("job_mode") == "video" else 1
        ))

        total   = len(jobs)
        success = 0
        errors  = 0
        was_cancelled = False
        was_timed_out = False
        ripped_timeline_titles = set()

        try:
            os.makedirs(out_folder, exist_ok=True)
        except Exception:
            pass

        created_folders = set()

        # Calculate effective durations and batch progress spans
        job_durations = []
        for j in jobs:
            d = float(j.get("duration", 0.0))
            if d <= 0.0 and j.get("chapter"):
                c = j["chapter"]
                st = float(c.get("start_time", 0.0))
                et = float(c.get("end_time", 0.0))
                if et > st:
                    d = et - st
            if d <= 0.0 and j.get("title"):
                t_obj = j["title"]
                td = float(t_obj.get("duration", 0.0))
                if td > 0.0:
                    if j.get("type") == "chapter":
                        cc = max(1, int(t_obj.get("chapter_count", 1)))
                        d = td / cc
                    else:
                        d = td
            job_durations.append(max(0.0, d))

        valid_durs = [d for d in job_durations if d > 0.0]
        if valid_durs:
            fallback_dur = sum(valid_durs) / len(valid_durs)
        else:
            fallback_dur = 1.0

        effective_durations = [d if d > 0.0 else fallback_dur for d in job_durations]
        total_eff_dur = sum(effective_durations) if effective_durations else 1.0

        job_spans = []
        acc_dur = 0.0
        for idx, d in enumerate(effective_durations):
            start_pct = (acc_dur / total_eff_dur) * 100.0
            acc_dur += d
            end_pct = 100.0 if (idx == len(effective_durations) - 1) else (acc_dur / total_eff_dur) * 100.0
            job_spans.append((start_pct, end_pct))

        overall_progress_max = 0.0
        completed_duration = 0.0
        dvd_source = self._vcd_path.get().strip()
        if not dvd_source and jobs:
            first_t = jobs[0]["title"]
            vobs = first_t.get("vob_files", [])
            if vobs:
                dvd_source = str(Path(vobs[0]).parent)
            elif first_t.get("path"):
                dvd_source = str(Path(first_t["path"]).parent)

        # Inspect source and perform pre-flight HandBrake validation
        dvd_insp = dvd_engine.inspect_dvd_source(dvd_source)
        if dvd_source and not dvd_insp.is_accessible:
            self.after(0, lambda m=dvd_insp.error_message: self._log.log(
                f"DVD source warning: {m}", "warning"
            ))

        has_potential_hb_job = any(
            (job.get("job_mode") != "audio" and not audio_only and output_format == "MP4")
            for job in jobs
        )
        hb_val_res = None
        hb_disabled_globally = False
        if bool(self._handbrake) and os.path.isfile(self._handbrake) and has_potential_hb_job and dvd_source:
            hb_val_res = dvd_engine.validate_handbrake_source(self._handbrake, dvd_source)
            if not hb_val_res.success:
                hb_disabled_globally = True
                if hb_val_res.error_category == "zero_titles_found":
                    self.after(0, lambda: self._log.log(
                        "HandBrakeCLI scan found 0 valid title(s) on DVD source. Using FFmpeg for extraction.", "info"
                    ))
                else:
                    err_detail = hb_val_res.error_message or "scan failed"
                    self.after(0, lambda d=err_detail: self._log.log(
                        f"HandBrakeCLI pre-flight validation failed ({d}). Using FFmpeg for extraction.", "info"
                    ))
            else:
                self.after(0, lambda p=hb_val_res.working_source_path, n=hb_val_res.title_count: self._log.log(
                    f"HandBrakeCLI validated ({n} titles found using '{p}').", "info"
                ))

        self._last_dvd_progress = 0.0

        def update_dvd_progress_ui(p, status_text=None, lp=None, log_it=False):
            safe_p = max(getattr(self, "_last_dvd_progress", 0.0), p)
            self._last_dvd_progress = safe_p
            self._progress_var.set(safe_p)
            self._progress_pct.configure(text=f"{int(safe_p)}%")
            self._taskbar_progress.set_value(int(safe_p), 100)
            if status_text is not None:
                self._progress_lbl.configure(text=status_text)
            if log_it and lp:
                self._log.log(lp, "info")

        def can_fallback_for_job(title_item, chapter_item):
            if chapter_item:
                return dvd_engine.can_ffmpeg_rip_chapter(self._ffmpeg, dvd_source, title_item, chapter_item)
            return dvd_engine.can_ffmpeg_rip_title(self._ffmpeg, dvd_source, title_item)

        for i, job in enumerate(jobs):
            j_type = job["type"]
            t_item = job["title"]
            c_item = job["chapter"]
            job_name = job["name"]
            j_dur = float(job.get("duration", 0.0))
            job_start_pct, job_end_pct = job_spans[i]
            job_span_pct = max(0.0, job_end_pct - job_start_pct)
            job_eff_dur = effective_durations[i]
            in_job_prog_max = 0.0

            if create_title_folder:
                if t_item.get("custom_stem"):
                    raw_title_name = t_item["custom_stem"]
                else:
                    fname = t_item.get("filename", "")
                    clean_fname = re.sub(r"\s*\(Main Feature\)", "", fname).strip()
                    raw_title_name = clean_fname or f"Title {t_item.get('title_number', 1):02d}"
                title_folder_name = sanitize_filename(raw_title_name, fallback=f"Title_{t_item.get('title_number', 1):02d}")
                job_out_dir = os.path.normpath(os.path.abspath(os.path.join(out_folder, title_folder_name)))
                try:
                    os.makedirs(job_out_dir, exist_ok=True)
                except Exception:
                    pass
                created_folders.add(job_out_dir)
            else:
                job_out_dir = os.path.normpath(os.path.abspath(out_folder))

            if self._cancel_requested:
                was_cancelled = True
                break

            overall_progress_max = max(overall_progress_max, job_start_pct)
            proc_status_msg = t('content.rip_prog_proc').format(idx=i+1, total=total, name=job_name)
            self.after(0, lambda p=overall_progress_max, s=proc_status_msg: update_dvd_progress_ui(p, status_text=s))

            j_mode = job.get("job_mode", "audio" if audio_only else "video")
            is_job_audio = (j_mode == "audio")

            # Resolve audio track mapping for this title
            title_num = int(t_item.get("title_number", 1))

            # Pre-flight chapter timing check: reject zero-duration or invalid chapters before running external processes
            if j_type == "chapter" and c_item is not None:
                c_dur = float(c_item.get("duration", 0.0))
                c_start = float(c_item.get("start_time", 0.0))
                c_end = float(c_item.get("end_time", 0.0))
                if c_dur <= 0.0 and c_end > c_start:
                    c_dur = c_end - c_start
                c_valid = bool(c_item.get("is_valid_timing", True))
                if c_dur <= 0.0 or not c_valid:
                    errors += 1
                    overall_progress_max = max(overall_progress_max, job_end_pct)
                    c_num = int(c_item.get("chapter_number", 1))
                    timing_err = c_item.get("timing_error") or f"duration is {c_dur:.2f}s"
                    err_msg = (
                        f"DVD chapter timing could not be verified. Extraction was skipped to prevent an invalid output file. "
                        f"Title {title_num}, Chapter {c_num} ({timing_err})"
                    )
                    self.after(0, lambda m=err_msg, p=overall_progress_max: (
                        self._log.log(m, "error"),
                        update_dvd_progress_ui(p)
                    ))
                    continue

            raw_tracks = t_item.get("audio_tracks", [])
            selected_track_id = self._dvd_selected_audio_tracks.get(title_num)
            chosen_track = None
            if selected_track_id:
                for trk in raw_tracks:
                    t_id = trk.track_id if isinstance(trk, dvd_engine.DVDAudioTrack) else trk.get("track_id")
                    if t_id == selected_track_id:
                        chosen_track = trk.to_dict() if isinstance(trk, dvd_engine.DVDAudioTrack) else trk
                        break
                if not chosen_track:
                    errors += 1
                    overall_progress_max = max(overall_progress_max, job_end_pct)
                    err_msg = f"Requested audio track '{selected_track_id}' not found for Title {title_num}."
                    self.after(0, lambda m=err_msg, p=overall_progress_max: (
                        self._log.log(m, "error"),
                        update_dvd_progress_ui(p)
                    ))
                    continue
            elif raw_tracks:
                first_trk = raw_tracks[0]
                chosen_track = first_trk.to_dict() if isinstance(first_trk, dvd_engine.DVDAudioTrack) else first_trk

            if is_job_audio and not chosen_track and raw_tracks:
                chosen_track = raw_tracks[0].to_dict() if isinstance(raw_tracks[0], dvd_engine.DVDAudioTrack) else raw_tracks[0]

            if is_job_audio and not chosen_track:
                errors += 1
                overall_progress_max = max(overall_progress_max, job_end_pct)
                err_msg = f"No audio track available for Title {title_num}."
                self.after(0, lambda m=err_msg, p=overall_progress_max: (
                    self._log.log(m, "error"),
                    update_dvd_progress_ui(p)
                ))
                continue

            custom_audio_filename = None
            if is_job_audio and extract_both:
                target_ext = ".wav" if audio_format == "WAV" else ".mp3"
                if chosen_track:
                    lang_name = chosen_track.get("lang_name") or chosen_track.get("raw_lang_name")
                    lang_code = (chosen_track.get("lang") or chosen_track.get("lang_code") or "").lower()
                    trk_num = chosen_track.get("track_number") or chosen_track.get("hb_track_index", 1)
                    if lang_name and lang_name not in ("Unknown", "und", ""):
                        audio_tag = f"{lang_name} Audio"
                    elif lang_code and lang_code not in ("und", "unknown", "qaa", ""):
                        audio_tag = f"{lang_code.upper()} Audio"
                    else:
                        audio_tag = f"Audio Track {trk_num}"
                else:
                    audio_tag = "Audio"

                if j_type == "title":
                    t_stem = t_item.get("custom_stem") or f"Title_{title_num:02d}"
                    custom_audio_filename = f"{t_stem} - {audio_tag}{target_ext}"
                else:
                    t_stem = t_item.get("custom_stem") or f"Title_{title_num:02d}"
                    c_num = int(c_item.get("chapter_number", 1))
                    c_custom = c_item.get("custom_stem") or c_item.get("name") or f"Chapter {c_num:02d}"
                    c_tag = sanitize_filename(c_custom, fallback=f"Chapter_{c_num:02d}")
                    custom_audio_filename = f"{t_stem} - {c_tag} - {audio_tag}{target_ext}"

            can_use_hb = (
                bool(self._handbrake)
                and os.path.isfile(self._handbrake)
                and not is_job_audio
                and output_format == "MP4"
                and not hb_disabled_globally
                and (hb_val_res is not None and hb_val_res.success)
            )

            if can_use_hb:
                map_ok, _, _, _, map_err = dvd_engine.resolve_handbrake_job_mapping(
                    hb_val_res, t_item, c_item, chosen_track
                )
                if not map_ok:
                    can_use_hb = False
                    self.after(0, lambda j_n=job_name, err=map_err: self._log.log(
                        f"HandBrake title/chapter mapping unavailable for {j_n} ({err}). Using FFmpeg fallback.", "info"
                    ))

            run_with_engine = "handbrake" if can_use_hb else "ffmpeg"
            job_done = False
            hb_failure_info = None

            while not job_done:
                temp_concat = None
                out_path = None
                cmd = None
                is_hb = (run_with_engine == "handbrake")

                try:
                    if is_hb:
                        cmd, out_path = dvd_engine.prepare_dvd_handbrake_rip_job(
                            handbrake_path=self._handbrake,
                            dvd_source=dvd_source,
                            title_dict=t_item,
                            chapter_dict=c_item,
                            out_dir=job_out_dir,
                            use_1080p=use_1080p,
                            audio_track=chosen_track,
                            val_res=hb_val_res,
                            fps_mode=getattr(self.i18n, "fps_mode", "Passthrough"),
                        )
                    else:
                        cand_vid = None
                        if is_job_audio and extract_both:
                            cand_vid = (c_item.get("last_ripped_video_path") if c_item else None) or t_item.get("last_ripped_video_path")

                        if cand_vid and os.path.isfile(cand_vid) and os.path.getsize(cand_vid) > 0:
                            cmd, out_path = dvd_engine.prepare_dvd_audio_from_video_job(
                                ffmpeg_path=self._ffmpeg,
                                local_video_path=cand_vid,
                                title_dict=t_item,
                                chapter_dict=c_item,
                                out_dir=job_out_dir,
                                audio_format=audio_format,
                                audio_track=chosen_track,
                                custom_output_filename=custom_audio_filename,
                            )
                        elif j_type == "title":
                            cmd, out_path, temp_concat = dvd_engine.prepare_dvd_rip_job(
                                ffmpeg_path=self._ffmpeg,
                                dvd_source=dvd_source,
                                title_dict=t_item,
                                out_dir=job_out_dir,
                                output_format=output_format,
                                use_1080p=use_1080p,
                                audio_only=is_job_audio,
                                audio_format=audio_format,
                                audio_track=chosen_track,
                                custom_output_filename=custom_audio_filename,
                                fps_mode=getattr(self.i18n, "fps_mode", "Passthrough"),
                            )
                        else:
                            cmd, out_path, temp_concat = dvd_engine.prepare_dvd_chapter_rip_job(
                                ffmpeg_path=self._ffmpeg,
                                dvd_source=dvd_source,
                                title_dict=t_item,
                                chapter_dict=c_item,
                                out_dir=job_out_dir,
                                output_format=output_format,
                                use_1080p=use_1080p,
                                audio_only=is_job_audio,
                                audio_format=audio_format,
                                audio_track=chosen_track,
                                custom_output_filename=custom_audio_filename,
                                fps_mode=getattr(self.i18n, "fps_mode", "Passthrough"),
                            )
                except Exception as prep_ex:
                    prep_str = str(prep_ex)
                    if is_hb and self._ffmpeg and "could not be verified" not in prep_str and "too short" not in prep_str:
                        hb_failure_info = f"HandBrake prep failed ({prep_ex})"
                        self.after(0, lambda e=prep_str: self._log.log(
                            f"HandBrake prep failed ({e}), falling back to FFmpeg...", "warning"
                        ))
                        run_with_engine = "ffmpeg"
                        continue
                    errors += 1
                    overall_progress_max = max(overall_progress_max, job_end_pct)
                    err_msg = t('log.exc').format(err=str(prep_ex))
                    if hb_failure_info:
                        err_msg += f" | [HandBrake failure]: {hb_failure_info}"
                    self.after(0, lambda msg=err_msg, p=overall_progress_max: (
                        self._log.log(msg, "error"),
                        update_dvd_progress_ui(p)
                    ))
                    break

                out_path = os.path.normpath(os.path.abspath(out_path))
                out_basename = os.path.basename(out_path)
                target_final_path = out_path
                target_final_dir = os.path.dirname(target_final_path)
                target_final_stem = Path(target_final_path).stem
                target_final_ext = Path(target_final_path).suffix
                os.makedirs(target_final_dir, exist_ok=True)
                temp_out_path = os.path.normpath(os.path.abspath(os.path.join(
                    target_final_dir, f".tmp_{target_final_stem}_{int(time.time() * 1000)}{target_final_ext}"
                )))

                if os.path.exists(temp_out_path):
                    try:
                        os.remove(temp_out_path)
                    except Exception:
                        pass

                norm_out_lower = out_path.lower()
                cmd = [temp_out_path if (arg is not None and os.path.normpath(os.path.abspath(str(arg))).lower() == norm_out_lower) else arg for arg in cmd if arg is not None]
                cmd = [str(arg) for arg in cmd]
                if temp_out_path not in cmd:
                    if is_hb:
                        for idx_a, a in enumerate(cmd):
                            if a == "-o" and idx_a + 1 < len(cmd):
                                cmd[idx_a + 1] = temp_out_path
                                break
                    elif len(cmd) > 0:
                        cmd[-1] = temp_out_path

                engine_tag = "HandBrakeCLI" if is_hb else "FFmpeg"
                trk_desc = chosen_track.get("display_label", "") if chosen_track else ""
                trk_info = f" [{trk_desc}]" if trk_desc else ""
                cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                if j_type == "chapter" and c_item:
                    c_num = c_item.get("chapter_number", 1)
                    t_num = t_item.get("title_number", 1)
                    s_t = float(c_item.get("start_time", 0.0))
                    d_t = float(c_item.get("duration", 0.0))
                    e_t = float(c_item.get("end_time", s_t + d_t))
                    timing_info = f" [Title {t_num} Ch.{c_num} | Start: {s_t:.1f}s, End: {e_t:.1f}s, Expected: {d_t:.1f}s]"
                    self.after(0, lambda j_n=job_name, o_n=out_basename, eng=engine_tag, t_i=trk_info, tm=timing_info, cs=cmd_str: self._log.log(
                        f"[{eng}]{tm} {t('log.extracting').format(name=j_n, out=o_n)}{t_i} | Command: {cs}", "info"
                    ))
                else:
                    self.after(0, lambda j_n=job_name, o_n=out_basename, eng=engine_tag, t_i=trk_info, cs=cmd_str: self._log.log(
                        f"[{eng}] {t('log.extracting').format(name=j_n, out=o_n)}{t_i} | Command: {cs}", "info"
                    ))

                proc_timed_out = False
                ffmpeg_init_secs = None
                ffmpeg_base_secs = 0.0
                ffmpeg_last_raw_secs = 0.0
                is_finalizing_or_muxing = False
                try:
                    extra_flags = get_priority_creation_flag(self.i18n.priority)
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=get_subprocess_env(),
                        **get_subprocess_kwargs(extra_flags=extra_flags)
                    )
                    self._current_proc = proc
                    set_process_priority(proc, priority_level=self.i18n.priority, low_io=(not is_job_audio))

                    line_queue = queue.Queue()
                    output_tail = collections.deque(maxlen=25)

                    def read_stdout():
                        try:
                            for line in iter(proc.stdout.readline, ''):
                                line_queue.put(line)
                        except Exception:
                            pass
                        finally:
                            try:
                                proc.stdout.close()
                            except Exception:
                                pass
                            line_queue.put(None)

                    reader_t = threading.Thread(target=read_stdout, daemon=True)
                    reader_t.start()

                    last_io_time = time.time()
                    last_progress_time = time.time()
                    last_log_time = 0.0
                    last_seen_frame = -1
                    last_seen_raw_secs = -1.0
                    last_seen_size_kb = -1
                    last_seen_hb_pct = -1.0
                    last_seen_hb_task = -1
                    last_seen_fsize = -1
                    stall_warning_logged = False
                    stall_warn_threshold = min(15.0, max(0.1, DISC_READ_TIMEOUT_SECONDS * 0.5))

                    while True:
                        if self._cancel_requested:
                            kill_process_tree(proc, force=True)
                            break

                        now = time.time()

                        # Monitor active file writing to prevent premature stall detection
                        active_out_file = temp_out_path if (temp_out_path and os.path.exists(temp_out_path)) else (target_final_path if (target_final_path and os.path.exists(target_final_path)) else None)
                        if active_out_file:
                            try:
                                cur_fsize = os.path.getsize(active_out_file)
                                if last_seen_fsize < 0:
                                    last_seen_fsize = cur_fsize
                                elif cur_fsize > (last_seen_fsize + 32768):
                                    last_seen_fsize = cur_fsize
                                    last_progress_time = now
                                    if stall_warning_logged:
                                        stall_warning_logged = False
                                        self.after(0, lambda j_n=job_name: self._log.log(
                                            f"[Disc Read Notice] Progress resumed on {j_n}.", "info"
                                        ))
                            except Exception:
                                pass

                        io_stalled_secs = now - last_io_time
                        prog_stalled_secs = now - last_progress_time
                        effective_timeout = 180.0 if is_finalizing_or_muxing else DISC_READ_TIMEOUT_SECONDS

                        if prog_stalled_secs >= stall_warn_threshold and not stall_warning_logged and not is_finalizing_or_muxing:
                            stall_warning_logged = True
                            frame_info = f" at frame {last_seen_frame}" if last_seen_frame >= 0 else ""
                            self.after(0, lambda j_n=job_name, fi=frame_info, ps=int(prog_stalled_secs): self._log.log(
                                f"[Disc Read Notice] Processing paused{fi} on {j_n} ({ps}s without progress update; optical drive reading or buffering)...",
                                "warning"
                            ))

                        if io_stalled_secs > effective_timeout or prog_stalled_secs > effective_timeout:
                            proc_timed_out = True
                            was_timed_out = True
                            stalled_reason = f"stalled at frame {last_seen_frame}" if (last_seen_frame >= 0 and prog_stalled_secs > effective_timeout) else "no response"
                            self.after(0, lambda j_n=job_name, sr=stalled_reason, to=int(effective_timeout): self._log.log(
                                f"{t('log.read_timeout').format(name=j_n, timeout=to)} ({sr})",
                                "warning"
                            ))
                            terminate_and_kill(proc, graceful_timeout=GRACEFUL_TERMINATE_TIMEOUT)
                            break

                        try:
                            line = line_queue.get(timeout=0.2)
                        except queue.Empty:
                            if proc.poll() is not None:
                                while not line_queue.empty():
                                    rem = line_queue.get_nowait()
                                    if rem is None:
                                        break
                                    rem_s = rem.strip()
                                    if rem_s:
                                        output_tail.append(rem_s)
                                break
                            continue

                        if line is None:
                            break

                        last_io_time = time.time()
                        line = line.strip()
                        if line:
                            output_tail.append(line)

                        if is_hb:
                            hb_match = re.search(r"Encoding:\s+task\s+(\d+)\s+of\s+(\d+),\s+([\d\.]+)\s*%", line)
                            if hb_match:
                                task_idx = max(1, int(hb_match.group(1)))
                                task_total = max(1, int(hb_match.group(2)))
                                cur_pct = float(hb_match.group(3))

                                if task_idx > last_seen_hb_task or cur_pct > (last_seen_hb_pct + 0.01):
                                    last_progress_time = time.time()
                                    last_seen_hb_task = task_idx
                                    last_seen_hb_pct = cur_pct
                                    if stall_warning_logged:
                                        stall_warning_logged = False
                                        self.after(0, lambda j_n=job_name: self._log.log(
                                            f"[Disc Read Notice] Progress resumed on {j_n}.", "info"
                                        ))
                                    else:
                                        stall_warning_logged = False

                                task_frac = ((task_idx - 1) + (cur_pct / 100.0)) / task_total
                                task_frac = max(0.0, min(1.0, task_frac))
                                in_job_prog_max = max(in_job_prog_max, task_frac)

                                if task_frac >= 0.99 and not is_finalizing_or_muxing:
                                    is_finalizing_or_muxing = True
                                    last_progress_time = time.time()
                                    if stall_warning_logged:
                                        stall_warning_logged = False
                                    self.after(0, lambda j_n=job_name: self._log.log(
                                        f"[HandBrakeCLI] Finalizing and muxing media container for {j_n}...", "info"
                                    ))

                                overall = job_start_pct + (in_job_prog_max * job_span_pct)
                                overall = max(overall_progress_max, overall)
                                overall = min(overall, 99.9)
                                overall_progress_max = overall

                                now = time.time()
                                should_log = (now - last_log_time) >= 1.5
                                if should_log:
                                    last_log_time = now
                                self.after(0, lambda p=overall, lp=line, log_it=should_log: update_dvd_progress_ui(
                                    p, lp=lp, log_it=log_it
                                ))
                            elif any(mux_kw in line.lower() for mux_kw in ("muxing", "mux:", "finished work", "work result", "encode done")):
                                is_finalizing_or_muxing = True
                                last_progress_time = time.time()
                                if stall_warning_logged:
                                    stall_warning_logged = False
                            elif any(err_kw in line.lower() for err_kw in ("error", "corrupt", "invalid")):
                                if not any(bdmv in line.lower() for bdmv in ("bdmv\\index.bdmv", "bdmv/index.bdmv", "bdmv\\backup", "bdmv/backup")):
                                    self.after(0, lambda l=line: self._log.log(l, "warning"))
                        else:
                            if line and ("frame=" in line or "speed=" in line or ("size=" in line and "time=" in line)):
                                frame_match = re.search(r'frame=\s*(\d+)', line)
                                time_match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                                size_match = re.search(r'size=\s*(\d+)kB', line)

                                cur_frame = int(frame_match.group(1)) if frame_match else None
                                cur_secs = None
                                if time_match:
                                    h, m, s = time_match.groups()
                                    cur_secs = int(h) * 3600 + int(m) * 60 + float(s)
                                cur_size_kb = int(size_match.group(1)) if size_match else None

                                progress_advanced = False
                                if cur_frame is not None and cur_frame > last_seen_frame:
                                    last_seen_frame = cur_frame
                                    progress_advanced = True
                                if cur_secs is not None and cur_secs > (last_seen_raw_secs + 0.05):
                                    last_seen_raw_secs = cur_secs
                                    progress_advanced = True
                                if cur_size_kb is not None and cur_size_kb > (last_seen_size_kb + 32):
                                    last_seen_size_kb = cur_size_kb
                                    progress_advanced = True

                                if progress_advanced:
                                    last_progress_time = time.time()
                                    if stall_warning_logged:
                                        stall_warning_logged = False
                                        self.after(0, lambda j_n=job_name: self._log.log(
                                            f"[Disc Read Notice] Progress resumed on {j_n}.", "info"
                                        ))
                                    else:
                                        stall_warning_logged = False

                                now = time.time()
                                should_log = (now - last_log_time) >= 1.5
                                if should_log and (now - last_progress_time) < 2.0:
                                    last_log_time = now
                                    self.after(0, lambda l=line: self._log.log(l, "info"))

                                if time_match and job_eff_dur > 0:
                                    raw_secs = cur_secs

                                    if ffmpeg_init_secs is None:
                                        if raw_secs >= job_eff_dur or raw_secs > 5.0:
                                            ffmpeg_init_secs = raw_secs
                                        else:
                                            ffmpeg_init_secs = 0.0
                                        ffmpeg_last_raw_secs = raw_secs

                                    # Detect PTS reset / timestamp jump backwards across cells/VOBs
                                    if raw_secs < (ffmpeg_last_raw_secs - 2.0):
                                        seg_elapsed = max(0.0, ffmpeg_last_raw_secs - ffmpeg_init_secs)
                                        ffmpeg_base_secs += seg_elapsed
                                        ffmpeg_init_secs = raw_secs
                                        ffmpeg_last_raw_secs = raw_secs
                                    else:
                                        ffmpeg_last_raw_secs = max(ffmpeg_last_raw_secs, raw_secs)

                                    cur_seg_elapsed = max(0.0, raw_secs - ffmpeg_init_secs)
                                    total_job_elapsed = ffmpeg_base_secs + cur_seg_elapsed

                                    in_job_frac = min(1.0, max(0.0, total_job_elapsed / job_eff_dur))
                                    in_job_prog_max = max(in_job_prog_max, in_job_frac)

                                    overall = job_start_pct + (in_job_prog_max * job_span_pct)
                                    overall = max(overall_progress_max, overall)
                                    overall = min(overall, 99.9)
                                    overall_progress_max = overall

                                    self.after(0, lambda p=overall: update_dvd_progress_ui(p))
                            elif any(err_kw in line.lower() for err_kw in ("error", "corrupt", "invalid")):
                                self.after(0, lambda l=line: self._log.log(l, "warning"))

                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        terminate_and_kill(proc, graceful_timeout=GRACEFUL_TERMINATE_TIMEOUT)
                    except Exception:
                        pass

                    try:
                        reader_t.join(timeout=5)
                    except Exception:
                        pass

                    self._current_proc = None

                    if temp_concat and os.path.exists(temp_concat):
                        try:
                            os.remove(temp_concat)
                        except Exception:
                            pass

                    if self._cancel_requested:
                        was_cancelled = True
                        if temp_out_path and os.path.exists(temp_out_path):
                            try:
                                os.remove(temp_out_path)
                            except Exception:
                                pass
                        break

                    if proc_timed_out:
                        if temp_out_path and os.path.exists(temp_out_path):
                            try:
                                os.remove(temp_out_path)
                            except Exception:
                                pass

                        can_fb, fb_reason = can_fallback_for_job(t_item, c_item)
                        if is_hb and not self._cancel_requested and can_fb:
                            hb_disabled_globally = True
                            hb_cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                            hb_failure_info = f"HandBrakeCLI stalled/timed out after {int(effective_timeout)}s | Command: {hb_cmd_str}"
                            self.after(0, lambda j_n=job_name, c=hb_cmd_str, to=int(effective_timeout): self._log.log(
                                f"HandBrakeCLI stalled on {j_n} (no progress for {to}s). Falling back to FFmpeg...", "warning"
                            ))
                            run_with_engine = "ffmpeg"
                            continue

                        errors += 1
                        overall_progress_max = max(overall_progress_max, job_end_pct)
                        self.after(0, lambda p=overall_progress_max: update_dvd_progress_ui(p))
                        job_done = True
                        break

                    is_crash, rc_hex, rc_desc = dvd_engine.format_exit_code_info(proc.returncode)
                    if is_crash:
                        self.after(0, lambda eng=engine_tag, rc=proc.returncode, hx=rc_hex, desc=rc_desc: self._log.log(
                            f"[{eng}] Process terminated abnormally with exit code {rc} ({hx}: {desc})", "warning"
                        ))
                    else:
                        self.after(0, lambda eng=engine_tag, rc=proc.returncode: self._log.log(
                            f"[{eng}] Process finished with exit code {rc}", "info"
                        ))

                    candidate_to_validate = None
                    needs_promotion = False
                    if temp_out_path and os.path.exists(temp_out_path) and os.path.getsize(temp_out_path) > 0:
                        candidate_to_validate = temp_out_path
                        needs_promotion = True
                    elif target_final_path and os.path.exists(target_final_path) and os.path.getsize(target_final_path) > 0:
                        candidate_to_validate = target_final_path
                        needs_promotion = False

                    allow_post_crash_validation = (
                        proc.returncode != 0
                        and (is_finalizing_or_muxing or in_job_prog_max >= 0.98 or is_crash)
                        and candidate_to_validate is not None
                        and os.path.exists(candidate_to_validate)
                        and os.path.getsize(candidate_to_validate) > 0
                    )

                    should_validate = (
                        proc.returncode == 0
                        and candidate_to_validate is not None
                        and os.path.getsize(candidate_to_validate) > 0
                    ) or allow_post_crash_validation

                    if should_validate:
                        val_status_msg = f"Validating output media ({out_basename})..."
                        self.after(0, lambda p=overall_progress_max, s=val_status_msg: update_dvd_progress_ui(p, status_text=s))
                        self.after(0, lambda p=candidate_to_validate: self._log.log(
                            f"[{engine_tag}] Validating output media: {p}", "info"
                        ))

                        time.sleep(0.1)

                        expected_fmt = audio_format if is_job_audio else output_format
                        is_valid, val_msg = dvd_engine.validate_ripped_media(
                            ffprobe_path=self._ffprobe,
                            file_path=candidate_to_validate,
                            is_audio_only=is_job_audio,
                            expected_format=expected_fmt,
                            selected_audio_track=chosen_track,
                            expected_duration=j_dur,
                            ffmpeg_path=self._ffmpeg,
                        )
                        if is_valid:
                            if proc.returncode != 0:
                                self.after(0, lambda eng=engine_tag, j_n=job_name, rc=proc.returncode, hx=rc_hex, desc=rc_desc: self._log.log(
                                    f"[{eng} Recovery Notice] Output media for {j_n} passed complete FFprobe stream, codec, and duration validation despite abnormal exit code {rc} ({hx}: {desc}). Recovering output file.",
                                    "warning"
                                ))
                            else:
                                self.after(0, lambda eng=engine_tag, vm=val_msg: self._log.log(
                                    f"[{eng}] {vm}", "info"
                                ))

                            if needs_promotion:
                                try:
                                    if os.path.exists(target_final_path) and target_final_path != candidate_to_validate:
                                        try:
                                            os.remove(target_final_path)
                                        except Exception:
                                            pass
                                    os.replace(candidate_to_validate, target_final_path)
                                except Exception:
                                    try:
                                        shutil.move(candidate_to_validate, target_final_path)
                                    except Exception:
                                        pass

                            out_path = target_final_path
                            size = round(os.path.getsize(target_final_path) / 1024**2, 1)
                            success += 1
                            if not is_job_audio:
                                if j_type == "title":
                                    t_item["last_ripped_video_path"] = target_final_path
                                else:
                                    c_item["last_ripped_video_path"] = target_final_path
                            overall_progress_max = max(overall_progress_max, job_end_pct)
                            self.after(0, lambda p=overall_progress_max: update_dvd_progress_ui(p))
                            self.after(0, lambda n=out_basename, s=size: self._log.log(
                                t('log.saved_ok').format(name=n, size=s), "success"
                            ))
                            job_done = True

                            # DVD Chapter Timeline TXT Generation (only for complete title output)
                            if generate_timeline and j_type == "title":
                                t_key = t_item.get("title_number", i + 1)
                                if t_key not in ripped_timeline_titles:
                                    ripped_timeline_titles.add(t_key)
                                    self._generate_dvd_timeline_file(target_final_path, out_basename)
                        else:
                            if candidate_to_validate and candidate_to_validate != target_final_path and os.path.exists(candidate_to_validate):
                                try:
                                    os.remove(candidate_to_validate)
                                except Exception:
                                    pass

                            if proc.returncode != 0:
                                self.after(0, lambda eng=engine_tag, m=val_msg, rc=proc.returncode, hx=rc_hex: self._log.log(
                                    f"[{eng}] Output media failed validation after exit code {rc} ({hx}): {m}. Incomplete output discarded.",
                                    "warning"
                                ))
                            else:
                                self.after(0, lambda m=val_msg: self._log.log(m, "warning"))

                            can_fb, fb_reason = can_fallback_for_job(t_item, c_item)
                            if is_hb and not self._cancel_requested and can_fb:
                                hb_disabled_globally = True
                                hb_cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                                if proc.returncode != 0:
                                    hb_failure_info = f"Exit code {proc.returncode} ({rc_hex}: {rc_desc}) & validation failed ({val_msg}) | Command: {hb_cmd_str}"
                                    self.after(0, lambda j_n=job_name, rc=proc.returncode, hx=rc_hex, desc=rc_desc, m=val_msg, c=hb_cmd_str: self._log.log(
                                        f"HandBrakeCLI terminated with {hx} ({desc}) for {j_n} and output validation failed ({m}). Command: {c}. Falling back to FFmpeg...", "warning"
                                    ))
                                else:
                                    hb_failure_info = f"HandBrake output validation failed ({val_msg}) | Command: {hb_cmd_str}"
                                    self.after(0, lambda j_n=job_name, m=val_msg, c=hb_cmd_str: self._log.log(
                                        f"HandBrake output validation failed for {j_n} ({m}). Command: {c}. Falling back to FFmpeg...", "warning"
                                    ))
                                run_with_engine = "ffmpeg"
                                continue

                            errors += 1
                            if is_hb:
                                if proc.returncode != 0:
                                    err_msg = f"HandBrake processing error: {job_name} (Exit code {proc.returncode} / {rc_hex}: {rc_desc} | {val_msg})"
                                else:
                                    err_msg = f"HandBrake processing error: {job_name} ({val_msg})"
                                if not can_fb and self._ffmpeg:
                                    err_msg += f" | FFmpeg fallback unavailable: {fb_reason}"
                            else:
                                err_msg = f"{t('log.ffmpeg_err').format(name=job_name)} ({val_msg})"
                                if hb_failure_info:
                                    err_msg += f" | [HandBrake failure]: {hb_failure_info}"
                            self.after(0, lambda msg=err_msg: self._log.log(msg, "error"))
                            job_done = True
                    else:
                        cand_size = os.path.getsize(temp_out_path) if (temp_out_path and os.path.exists(temp_out_path)) else 0
                        if temp_out_path and os.path.exists(temp_out_path):
                            try:
                                os.remove(temp_out_path)
                            except Exception:
                                pass

                        clean_tail = [
                            l for l in output_tail
                            if not any(bdmv in l.lower() for bdmv in ("bdmv\\index.bdmv", "bdmv/index.bdmv", "bdmv\\backup", "bdmv/backup"))
                        ]
                        tail_snippet = " ; ".join(clean_tail[-3:]) if clean_tail else f"Exit code {proc.returncode}"

                        can_fb, fb_reason = can_fallback_for_job(t_item, c_item)
                        if is_hb and not self._cancel_requested and can_fb:
                            hb_disabled_globally = True
                            hb_cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                            hb_failure_info = f"Exit code {proc.returncode} ({rc_hex}: {rc_desc}) [{tail_snippet}] | Command: {hb_cmd_str}"
                            self.after(0, lambda j_n=job_name, rc=proc.returncode, hx=rc_hex, desc=rc_desc, c=hb_cmd_str, snip=tail_snippet: self._log.log(
                                f"HandBrakeCLI terminated with code {rc} ({hx}: {desc}) for {j_n} ({snip}). Command: {c}. Falling back to FFmpeg...", "warning"
                            ))
                            run_with_engine = "ffmpeg"
                            continue

                        errors += 1
                        if is_hb:
                            if proc.returncode == 0 and cand_size > 0 and cand_size < 4096:
                                err_msg = f"HandBrakeCLI output failed: {job_name} (undersized output: {cand_size} bytes)"
                            else:
                                err_msg = f"HandBrakeCLI returned code {proc.returncode} ({rc_hex}: {rc_desc}) for {job_name} ({tail_snippet})"
                            if not can_fb and self._ffmpeg:
                                err_msg += f" | FFmpeg fallback unavailable: {fb_reason}"
                        else:
                            if proc.returncode == 0 and cand_size < 4096:
                                err_msg = f"{t('log.ffmpeg_err').format(name=job_name)} (Empty output produced: {cand_size} bytes)"
                            else:
                                err_msg = f"{t('log.ffmpeg_err').format(name=job_name)} (Exit code {proc.returncode} ({rc_hex}: {rc_desc}): {tail_snippet})"
                            if hb_failure_info:
                                err_msg += f" | [HandBrake failure]: {hb_failure_info}"
                        self.after(0, lambda msg=err_msg: self._log.log(msg, "error"))
                        job_done = True

                except Exception as e:
                    if temp_out_path and os.path.exists(temp_out_path):
                        try:
                            os.remove(temp_out_path)
                        except Exception:
                            pass
                    if temp_concat and os.path.exists(temp_concat):
                        try:
                            os.remove(temp_concat)
                        except Exception:
                            pass

                    can_fb, fb_reason = can_fallback_for_job(t_item, c_item)
                    if is_hb and not self._cancel_requested and can_fb:
                        hb_cmd_str = subprocess.list2cmdline(cmd) if cmd else ""
                        hb_failure_info = f"HandBrakeCLI exception ({e}) | Command: {hb_cmd_str}"
                        self.after(0, lambda err=str(e), c=hb_cmd_str: self._log.log(
                            f"HandBrakeCLI exception ({err}). Command: {c}. Falling back to FFmpeg...", "warning"
                        ))
                        run_with_engine = "ffmpeg"
                        continue

                    errors += 1
                    if is_hb:
                        err_msg = f"HandBrakeCLI exception: {job_name} ({e})"
                        if not can_fb and self._ffmpeg:
                            err_msg += f" | FFmpeg fallback unavailable: {fb_reason}"
                    else:
                        err_msg = t('log.exc').format(err=str(e))
                        if hb_failure_info:
                            err_msg += f" | [HandBrake failure]: {hb_failure_info}"
                    self.after(0, lambda msg=err_msg: self._log.log(msg, "error"))
                    job_done = True

            if not was_cancelled:
                overall_progress_max = max(overall_progress_max, job_end_pct)
                if i == total - 1 and not self._cancel_requested:
                    if success > 0 and errors == 0:
                        overall_progress_max = 100.0
                        self.after(0, lambda: (
                            self._progress_var.set(100),
                            self._progress_pct.configure(text="100%"),
                        ))
                    else:
                        self.after(0, lambda p=overall_progress_max: update_dvd_progress_ui(p))

        effective_done_folder = list(created_folders)[0] if len(created_folders) == 1 else out_folder

        def _finish_rip():
            self._rip_done(
                total, success, errors, effective_done_folder,
                cancelled=(was_cancelled or self._cancel_requested),
                timed_out=was_timed_out
            )

        if threading.current_thread() is threading.main_thread():
            _finish_rip()
        else:
            try:
                self.after(0, _finish_rip)
            except Exception:
                _finish_rip()

    def _generate_dvd_timeline_file(self, media_path: str, media_basename: str):
        """Generates chapter timeline file for the ripped complete title media file."""
        if not self._ffprobe:
            self.after(0, lambda: self._log.log(
                t('log.timeline_ffprobe_missing'), "warning"
            ))
            return

        ok, txt_file, err, count = dvd_engine.generate_chapter_timeline_file(
            ffprobe_path=self._ffprobe,
            media_path=media_path
        )
        if ok and txt_file:
            txt_base = os.path.basename(txt_file)
            self.after(0, lambda tb=txt_base: self._log.log(
                t('log.timeline_done').format(name=tb), "success"
            ))
        else:
            if err and "No chapter metadata" in err:
                self.after(0, lambda mb=media_basename: self._log.log(
                    t('log.timeline_no_chapters').format(name=mb), "warning"
                ))
            else:
                self.after(0, lambda mb=media_basename, e=err: self._log.log(
                    t('log.timeline_failed').format(name=mb, err=e or "Unknown error"), "warning"
                ))

    def _rip_dvd_thread(self, titles, out_folder, output_format, use_1080p=False, audio_only=False, audio_format="WAV", generate_timeline=False):
        """Legacy compatibility wrapper for whole-title DVD ripping."""
        return self._rip_dvd_unified_thread(titles, [], out_folder, output_format, use_1080p, audio_only, audio_format, generate_timeline=generate_timeline)

    def _rip_dvd_chapters_thread(self, chapter_jobs, out_folder, output_format, use_1080p=False, audio_only=False, audio_format="WAV", generate_timeline=False):
        """Legacy compatibility wrapper for chapter-based DVD ripping."""
        return self._rip_dvd_unified_thread([], chapter_jobs, out_folder, output_format, use_1080p, audio_only, audio_format, generate_timeline=generate_timeline)

    def _send_windows_notification(self, total, success, errors, out_folder="", cancelled=False, timed_out=False, hwnd=0):
        """Dispatches a Windows completion notification if enabled in Settings."""
        if not getattr(self.i18n, "notification", True):
            return
        top_hwnd = hwnd or (ctypes.windll.user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id() if sys.platform == "win32" else 0)
        _send_windows_rip_notification(
            app_name=APP_NAME,
            total=total,
            success=success,
            errors=errors,
            out_folder=out_folder,
            cancelled=cancelled,
            timed_out=timed_out,
            lang=self.i18n.lang,
            parent_hwnd=top_hwnd
        )

    def _rip_done(self, total, success, errors, out_folder, cancelled=False, timed_out=False):
        self._ripping = False
        self._current_proc = None
        self._rip_btn.configure_state(True)
        self._stop_btn.configure_state(False)
        dvd_engine.clear_handbrake_validation_cache()
        dvd_engine.clear_dvdvideo_probe_cache()

        # Send Windows notification upon rip completion if enabled
        if not cancelled:
            self._send_windows_notification(
                total=total,
                success=success,
                errors=errors,
                out_folder=out_folder,
                cancelled=cancelled,
                timed_out=timed_out
            )
        if hasattr(self, "_clear_all_btn"):
            self._clear_all_btn.configure(
                state="normal",
                fg=COLORS["text_secondary"],
                cursor="hand2"
            )

        if timed_out:
            self._taskbar_progress.set_paused()
            self._progress_lbl.configure(text=t('messageboxes.timeout_title'))
            self._log.log(t('messageboxes.timeout_msg'), "warning")
            messagebox.showwarning(
                t('messageboxes.timeout_title'),
                t('messageboxes.timeout_msg'),
                parent=self
            )
            self._taskbar_progress.reset()
        elif cancelled:
            self._taskbar_progress.reset()
            self._progress_lbl.configure(text=t('content.rip_prog_stop').format(success=success, total=total))
            self._log.log(t('log.stop_sum').format(success=success), "warning")
            messagebox.showinfo(
                t('messageboxes.stop_title'),
                t('messageboxes.stop_msg').format(success=success, folder=out_folder),
                parent=self
            )
        elif errors == 0:
            self._progress_var.set(100)
            self._progress_lbl.configure(text=t('content.rip_prog_done').format(success=success, total=total))
            self._progress_pct.configure(text="100%")
            self._taskbar_progress.set_value(100, 100)
            self._log.log(
                t('log.done_ok').format(success=success, folder=out_folder),
                "success"
            )
            # Auto-open output folder if checked
            if self._auto_open_folder.get():
                try:
                    os.startfile(out_folder)
                except Exception as e:
                    self._log.log(t('log.open_err').format(err=e), "warning")

            # Only prompt to eject disc
            if messagebox.askyesno(
                t('messageboxes.eject_title'),
                t('messageboxes.eject_msg').format(success=success),
                parent=self
            ):
                self._eject_disc()
            self._taskbar_progress.reset()
        else:
            self._taskbar_progress.set_error()
            self._log.log(
                t('log.done_err').format(errors=errors, success=success, folder=out_folder),
                "warning"
            )
            messagebox.showwarning(
                t('messageboxes.err_title'),
                t('messageboxes.err_msg').format(success=success, errors=errors),
                parent=self
            )
            self._taskbar_progress.reset()

    # ── Canvas scroll helpers ─────────────────
    def _on_list_configure(self, _):
        if getattr(self, "_list_cfg_job", None):
            try:
                self.after_cancel(self._list_cfg_job)
            except Exception:
                pass
        def _apply_bbox():
            self._list_cfg_job = None
            if hasattr(self, "_canvas") and self._canvas.winfo_exists():
                self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._list_cfg_job = self.after(16, _apply_bbox)

    def _on_canvas_configure(self, event):
        if getattr(self, "_last_canvas_width", None) == event.width:
            return
        self._last_canvas_width = event.width
        if getattr(self, "_canvas_resize_job", None):
            try:
                self.after_cancel(self._canvas_resize_job)
            except Exception:
                pass
            self._canvas_resize_job = None

        # Immediate sync if canvas_window is uninitialized (0 or <=1) so layout renders without blank frames
        if hasattr(self, "_canvas") and self._canvas.winfo_exists() and hasattr(self, "_canvas_window"):
            try:
                cur_item_w = int(float(self._canvas.itemcget(self._canvas_window, "width")))
            except Exception:
                cur_item_w = 0
            if cur_item_w <= 1 and event.width > 1:
                try:
                    self._canvas.itemconfig(self._canvas_window, width=event.width)
                except Exception:
                    pass

        def _apply():
            self._canvas_resize_job = None
            if hasattr(self, "_canvas") and self._canvas.winfo_exists() and hasattr(self, "_canvas_window"):
                try:
                    w = self._canvas.winfo_width()
                    if w > 1:
                        self._last_canvas_width = w
                        self._canvas.itemconfig(self._canvas_window, width=w)
                except Exception:
                    pass
        self._canvas_resize_job = self.after(16, _apply)

    def _on_mousewheel(self, event):
        self._on_global_mousewheel(event)

    def _on_global_mousewheel(self, event):
        """Global mousewheel scroll handler: scrolls only the canvas under the mouse pointer."""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            widget = None
        if not widget:
            return
        w = widget
        while w:
            if isinstance(w, tk.Canvas) and getattr(w, "_can_scroll", False):
                w.yview_scroll(-1 * (event.delta // 120), "units")
                return "break"
            w = getattr(w, "master", None)

    # ── Unsupported Disc Dialog ───────────────
    def _show_unsupported_disc_dialog(self, drive_path, disc_type):
        """Show modal dialog warning user that the detected disc is not a VCD."""
        if getattr(self, "_unsupported_dlg_open", False):
            return
        self._unsupported_dlg_open = True

        dlg = tk.Toplevel(self)
        dlg.withdraw()
        dlg.title(t('messageboxes.unsupported_disc_title'))
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.resizable(False, False)
        self._set_window_icon(dlg)

        def on_close():
            self._unsupported_dlg_open = False
            try:
                dlg.destroy()
            except Exception:
                pass

        dlg.protocol("WM_DELETE_WINDOW", on_close)

        content = tk.Frame(dlg, bg=COLORS["bg_panel"], padx=scale_val(24), pady=scale_val(20))
        content.pack(fill="both", expand=True)

        # Top row: warning icon + title & type badge
        top_row = tk.Frame(content, bg=COLORS["bg_panel"])
        top_row.pack(fill="x", pady=(0, scale_val(10)))

        icon_lbl = tk.Label(
            top_row, text="⚠", font=FONTS["title"],
            bg=COLORS["bg_panel"], fg=COLORS["warning"]
        )
        icon_lbl.pack(side="left", padx=(0, scale_val(14)), anchor="n")

        title_col = tk.Frame(top_row, bg=COLORS["bg_panel"])
        title_col.pack(side="left", fill="x", expand=True)

        t_lbl = tk.Label(
            title_col, text=t('messageboxes.unsupported_disc_title'),
            font=FONTS["subhead"], bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
            anchor="w"
        )
        t_lbl.pack(anchor="w")

        clean_drive = drive_path.rstrip("\\") if drive_path else ""
        badge_text = f"Drive: {clean_drive}  •  Format: {disc_type}"
        badge_lbl = tk.Label(
            title_col, text=badge_text,
            font=FONTS["small"], bg=COLORS["accent_dim"], fg=COLORS["text_primary"],
            padx=scale_val(8), pady=scale_val(2)
        )
        badge_lbl.pack(anchor="w", pady=(scale_val(4), 0))

        # Message body
        msg_lbl = tk.Label(
            content, text=t('messageboxes.unsupported_disc_msg'),
            font=FONTS["body"], bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
            wraplength=scale_val(420), justify="left", anchor="w"
        )
        msg_lbl.pack(fill="x", pady=(0, 16))

        # Button row
        btn_row = tk.Frame(content, bg=COLORS["bg_panel"])
        btn_row.pack(fill="x", side="bottom")

        def do_eject():
            on_close()
            self._eject_disc(drive_path)

        def do_ok():
            on_close()

        # Eject Disc button (accent color)
        btn_eject = tk.Button(
            btn_row, text=f"⏏  {t('messageboxes.btn_eject')}",
            font=FONTS["body"], bg=COLORS["accent"],
            fg=COLORS["text_primary"], relief="flat", bd=0,
            padx=18, pady=7, cursor="hand2",
            activebackground=COLORS["accent_hover"],
            activeforeground=COLORS["text_primary"],
            command=do_eject
        )
        btn_eject.pack(side="right", padx=(8, 0))

        # OK button (card style)
        btn_ok = tk.Button(
            btn_row, text=t('messageboxes.btn_ok'),
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["text_primary"], relief="flat", bd=0,
            padx=20, pady=7, cursor="hand2",
            activebackground=COLORS["bg_hover"],
            activeforeground=COLORS["text_primary"],
            command=do_ok
        )
        btn_ok.pack(side="right")

        dlg.bind("<Return>", lambda e: do_ok())
        dlg.bind("<Escape>", lambda e: do_ok())

        position_window_on_parent(dlg, self, width=scale_val(480), height=scale_val(240))
        dlg.grab_set()

    def _clear_all_action(self):
        """Clear loaded video files list and reset progress indicators."""
        if self._ripping:
            self._stop_rip()

        if getattr(self, "_scanning", False):
            self._scanning = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)

        self._videos.clear()
        self._cards.clear()
        self._selected_indices.clear()
        self._selected_chapters.clear()
        self._dvd_selected_audio_tracks.clear()
        self._active_dvd_title_idx = 0
        self._batch_base_name = "Track"

        self._clear_list()
        if hasattr(self, "_empty_frame") and self._empty_frame.winfo_exists():
            self._empty_frame.pack(fill="both", expand=True, pady=100)

        self._video_count_badge.configure(text=t('content.badge_empty'))
        self._update_sel_count()

        # Reset main ripping progress
        self._progress_var.set(0)
        self._progress_lbl.configure(text="")
        self._progress_pct.configure(text="")
        self._progress_bar.pack_forget()

        # Reset scan progress if active
        if hasattr(self, "_scan_progress_var"):
            self._scan_progress_var.set(0)
        if hasattr(self, "_scan_progress_lbl"):
            self._scan_progress_lbl.configure(text="")
        if hasattr(self, "_scan_progress_pct"):
            self._scan_progress_pct.configure(text="")
        if hasattr(self, "_scan_progress_frame"):
            self._scan_progress_frame.pack_forget()
        if hasattr(self, "_scan_progress_bar"):
            self._scan_progress_bar.pack_forget()

        # Reset Windows taskbar progress
        if hasattr(self, "_taskbar_progress"):
            self._taskbar_progress.reset()

        self._log.log(t('log.cleared_all'), "info")

    # ── Drive eject & Reset ───────────────────
    def _clear_disc_info(self):
        """Reset and clear all scanned disc tracks and drive info UI."""
        if getattr(self, "_scanning", False):
            self._scanning = False
            if hasattr(self, "_scan_btn"):
                self._scan_btn.configure_state(True)

        self._taskbar_progress.reset()
        self._videos.clear()
        self._cards.clear()
        self._selected_indices.clear()
        self._selected_chapters.clear()
        self._dvd_selected_audio_tracks.clear()
        self._active_dvd_title_idx = 0
        self._vcd_path.set("")
        self._batch_base_name = "Track"
        self._last_non_vcd_drive = None
        self._last_disc_vol_name = None
        self._source_type = "NONE"
        self._source_disc_type = ""
        self._update_format_visibility_for_source()
        dvd_engine.clear_handbrake_validation_cache()
        dvd_engine.clear_dvdvideo_probe_cache()

        self._clear_list()
        if hasattr(self, "_empty_frame") and self._empty_frame.winfo_exists():
            self._empty_frame.pack(fill="both", expand=True, pady=100)

        self._drive_lbl.configure(text=t('header.no_disc'), fg=COLORS["text_muted"])
        self._detect_icon.configure(text="💿")
        self._detect_label.configure(text=t('drive.insert_vcd'), fg=COLORS["text_muted"])
        self._detected_drive_lbl.configure(text="")
        self._video_count_badge.configure(text=t('content.badge_empty'))
        self._sel_count_lbl.configure(text=t('selection.count').format(n=0, total=0))

        self._log.log(t('log.cleared'), "info")

    def _eject_disc(self, drive_to_eject=None):
        """Eject the disc from the detected or specified optical drive."""
        if self._ripping:
            busy_msg = t('messageboxes.eject_busy_msg')
            if busy_msg == 'messageboxes.eject_busy_msg':
                busy_msg = "Ripping is currently in progress. Are you sure you want to stop ripping and eject the disc?"
            if not messagebox.askyesno(
                t('header.title'),
                busy_msg,
                parent=self
            ):
                return
            self._stop_rip()

        # Determine drive letter
        drive_letter = None
        target = drive_to_eject or self._vcd_path.get()
        if target and len(target) >= 2 and target[1] == ':':
            drive_letter = target[0].upper()
        else:
            # Try to find an optical drive
            cd_drives = get_cd_drives()
            if cd_drives:
                drive_letter = cd_drives[0][0].upper()
        
        if not drive_letter:
            messagebox.showinfo(t('messageboxes.no_drive_title'), t('messageboxes.no_drive_msg'), parent=self)
            return
        
        self._log.log(t('messageboxes.ejecting').format(drive=drive_letter), "info")
        
        def do_eject_bg():
            ejected = False
            # Strategy 1: Win32 DeviceIoControl with volume dismount (most reliable)
            try:
                import ctypes
                from ctypes import wintypes
                GENERIC_READ = 0x80000000
                GENERIC_WRITE = 0x40000000
                FILE_SHARE_READ = 0x00000001
                FILE_SHARE_WRITE = 0x00000002
                OPEN_EXISTING = 3
                FSCTL_LOCK_VOLUME = 0x00090018
                FSCTL_DISMOUNT_VOLUME = 0x00090020
                IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808
                FSCTL_UNLOCK_VOLUME = 0x0009001C
                INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
                
                handle = ctypes.windll.kernel32.CreateFileW(
                    f"\\\\.\\{drive_letter}:",
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None
                )
                if handle == INVALID_HANDLE_VALUE:
                    handle = ctypes.windll.kernel32.CreateFileW(
                        f"\\\\.\\{drive_letter}:",
                        GENERIC_READ,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None
                    )
                if handle != INVALID_HANDLE_VALUE:
                    bytes_returned = wintypes.DWORD(0)
                    # Dismount volume first so Windows cache is dropped
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_LOCK_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_DISMOUNT_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    result = ctypes.windll.kernel32.DeviceIoControl(
                        handle, IOCTL_STORAGE_EJECT_MEDIA,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle, FSCTL_UNLOCK_VOLUME,
                        None, 0, None, 0,
                        ctypes.byref(bytes_returned), None
                    )
                    ctypes.windll.kernel32.CloseHandle(handle)
                    if result:
                        ejected = True
                        self.after(0, lambda: self._log.log(t('log.eject_win32').format(drive=drive_letter), "success"))
            except Exception as e:
                self.after(0, lambda err=e: self._log.log(t('log.eject_win32_fail').format(err=err), "warning"))
            
            # Strategy 2: PowerShell Shell.Application COM
            if not ejected:
                try:
                    ps_cmd = (
                        f"(New-Object -ComObject Shell.Application)"
                        f".Namespace(17).ParseName('{drive_letter}:').InvokeVerb('Eject')"
                    )
                    proc = subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                         "-Command", ps_cmd],
                        env=get_subprocess_env(),
                        capture_output=True,
                        **get_subprocess_kwargs()
                    )
                    if proc.returncode == 0:
                        ejected = True
                        self.after(0, lambda: self._log.log(t('log.eject_ps').format(drive=drive_letter), "success"))
                    else:
                        raise RuntimeError(proc.stderr.strip() if proc.stderr else "Eject verb failed")
                except Exception as e:
                    self.after(0, lambda err=e: (
                        self._log.log(t('log.eject_ps_fail').format(err=err), "error"),
                        messagebox.showwarning(
                            t('messageboxes.eject_fail_title'),
                            t('messageboxes.eject_fail_msg').format(drive=drive_letter, err=err),
                            parent=self
                        )
                    ))
            
            # Force Windows kernel cache invalidation and volume dismount for drive
            flush_optical_drive_cache(f"{drive_letter}:\\")

            # Always clear disc info and reset non-VCD state on UI thread
            self.after(0, self._clear_disc_info)

        threading.Thread(target=do_eject_bg, daemon=True).start()

    def _set_window_icon(self, window):
        """Set app icon on a Tk or Toplevel window using the multi-resolution CompactDisc.ico and sync title bar dark mode."""
        set_window_icon(window)

    def _batch_rename(self):
        """Open a batch rename dialog for all scanned files (supporting both DVD titles/chapters and VCD tracks)."""
        if not self._videos:
            messagebox.showinfo(t('batch.no_files_title'), t('batch.no_files_msg'), parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.withdraw()
        self._batch_rename_dialog = dlg
        _focus_job = [None]

        def _on_dlg_destroy(event):
            if event.widget == dlg:
                setattr(self, "_batch_rename_dialog", None)
                if _focus_job[0]:
                    try:
                        dlg.after_cancel(_focus_job[0])
                    except Exception:
                        pass
                    _focus_job[0] = None

        dlg.bind("<Destroy>", _on_dlg_destroy)
        dlg.title(t('batch.title'))
        dlg.configure(bg=COLORS["bg_panel"])
        self._set_window_icon(dlg)

        # Title
        tk.Label(
            dlg, text=t('batch.header'),
            font=FONTS["heading"], bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"]
        ).pack(padx=24, pady=(20, 4), anchor="w")

        tk.Label(
            dlg, text=t('batch.inst'),
            font=FONTS["body"], bg=COLORS["bg_panel"],
            fg=COLORS["text_secondary"]
        ).pack(padx=24, pady=(0, 8), anchor="w")

        # ── Sequential Numbering Section ──────────────────
        seq_frame = tk.Frame(dlg, bg=COLORS["bg_card"],
                             highlightbackground=COLORS["border"], highlightthickness=1)
        seq_frame.pack(fill="x", padx=24, pady=(0, 10))

        seq_enabled = tk.BooleanVar(value=self._batch_seq_enabled)
        base_var = tk.StringVar(value=self._batch_base_name)
        start_var = tk.StringVar(value=self._batch_start_index)

        def _save_batch_state(*_):
            self._batch_seq_enabled = seq_enabled.get()
            self._batch_base_name = base_var.get()
            self._batch_start_index = start_var.get()

        seq_enabled.trace_add("write", _save_batch_state)
        base_var.trace_add("write", _save_batch_state)
        start_var.trace_add("write", _save_batch_state)

        # Checkbox row
        seq_chk = tk.Checkbutton(
            seq_frame, text=t('batch.seq_enable'),
            variable=seq_enabled,
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["accent"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"], selectcolor=COLORS["bg_dark"],
            cursor="hand2"
        )
        seq_chk.pack(anchor="w", padx=12, pady=(10, 6))

        # Config row (Base Name + Start Index)
        cfg_row = tk.Frame(seq_frame, bg=COLORS["bg_card"])
        cfg_row.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(cfg_row, text=t('batch.seq_base'), font=FONTS["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=(0, 4))
        base_ent = tk.Entry(cfg_row, textvariable=base_var, font=FONTS["body"],
                            bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                            insertbackground=COLORS["accent"], relief="flat",
                            bd=4, width=14)
        base_ent.pack(side="left", padx=(0, 14))

        tk.Label(cfg_row, text=t('batch.seq_start'), font=FONTS["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=(0, 4))
        start_ent = tk.Entry(cfg_row, textvariable=start_var, font=FONTS["body"],
                             bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                             insertbackground=COLORS["accent"], relief="flat",
                             bd=4, width=5)
        start_ent.pack(side="left")

        # ── Collect Items (Unified VCD / DVD) ─────────────
        batch_items = []
        if self._source_type == "DVD":
            for t_idx, v in enumerate(self._videos):
                t_num = v.get("title_number", t_idx + 1)
                t_stem = v.get("custom_stem") or f"Title_{t_num:02d}"
                batch_items.append({
                    "type": "title",
                    "title_idx": t_idx,
                    "chapter_num": None,
                    "tag": t('batch.tag_title'),
                    "label": t('batch.title_item').format(n=t_num),
                    "current_stem": t_stem,
                    "target": v,
                })
                for ch in v.get("chapters_data", []):
                    c_num = int(ch.get("chapter_number", 1))
                    c_stem = ch.get("custom_stem") or ch.get("name") or f"Chapter {c_num:02d}"
                    batch_items.append({
                        "type": "chapter",
                        "title_idx": t_idx,
                        "chapter_num": c_num,
                        "tag": t('batch.tag_chapter'),
                        "label": f"  T{t_num:02d} Ch {c_num:02d}:",
                        "current_stem": c_stem,
                        "target": ch,
                        "parent_title": v,
                    })
        else:
            for i, info in enumerate(self._videos):
                current_stem = info.get("custom_stem", Path(info["filename"]).stem)
                batch_items.append({
                    "type": "track",
                    "title_idx": i,
                    "chapter_num": None,
                    "tag": t('batch.tag_track'),
                    "label": t('batch.track').format(n=i + 1),
                    "current_stem": current_stem,
                    "target": info,
                })

        # ── Scrollable file list ──────────────────────────
        scroll_frame = tk.Frame(dlg, bg=COLORS["bg_panel"])
        scroll_frame.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        canvas = tk.Canvas(scroll_frame, bg=COLORS["bg_panel"], highlightthickness=0)
        canvas._can_scroll = True
        vsb = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=COLORS["bg_panel"])
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width) if canvas.find_all() else None)

        total = len(batch_items)
        pad_width = 3 if total > 99 else 2

        entry_vars = []       # full-name entries (manual mode)
        suffix_vars = []      # suffix entries (seq mode)
        preview_labels = []   # live preview labels
        manual_widgets = []   # (tag_lbl, trk_lbl, name_ent)
        seq_widgets = []      # (tag_lbl, num_lbl, suf_lbl, suf_ent)
        row_widgets = []      # row Frame widgets for auto-scroll

        def _scroll_to_row(idx):
            try:
                if idx < 0 or idx >= len(row_widgets):
                    return
                r = row_widgets[idx]
                inner.update_idletasks()
                canvas.update_idletasks()
                r_y = r.winfo_y()
                r_h = r.winfo_height()
                canv_h = canvas.winfo_height()
                bbox = canvas.bbox("all")
                if not bbox or canv_h <= 0:
                    return
                total_h = bbox[3] - bbox[1]
                if total_h <= canv_h:
                    return
                yview = canvas.yview()
                vis_top = yview[0] * total_h
                vis_bot = vis_top + canv_h
                r_bot = r_y + r_h
                if r_bot > vis_bot:
                    new_top = min(total_h - canv_h, r_bot - canv_h + scale_val(12))
                    canvas.yview_moveto(max(0.0, new_top / total_h))
                elif r_y < vis_top:
                    new_top = max(0, r_y - scale_val(12))
                    canvas.yview_moveto(min(1.0, new_top / total_h))
            except Exception:
                pass

        def _on_enter_track(event, idx):
            if not seq_enabled.get():
                if idx + 1 < total:
                    next_ent = manual_widgets[idx + 1][2]
                    next_ent.focus_set()
                    next_ent.selection_range(0, 'end')
                    next_ent.icursor('end')
                    _scroll_to_row(idx + 1)
                else:
                    if hasattr(dlg, "_apply_btn") and dlg._apply_btn:
                        dlg._apply_btn.focus_set()
            else:
                if idx + 1 < total:
                    next_ent = seq_widgets[idx + 1][3]
                    next_ent.focus_set()
                    next_ent.selection_range(0, 'end')
                    next_ent.icursor('end')
                    _scroll_to_row(idx + 1)
                else:
                    if hasattr(dlg, "_apply_btn") and dlg._apply_btn:
                        dlg._apply_btn.focus_set()
            return "break"

        def _on_shift_enter_track(event, idx):
            if not seq_enabled.get():
                if idx > 0:
                    prev_ent = manual_widgets[idx - 1][2]
                    prev_ent.focus_set()
                    prev_ent.selection_range(0, 'end')
                    prev_ent.icursor('end')
                    _scroll_to_row(idx - 1)
            else:
                if idx > 0:
                    prev_ent = seq_widgets[idx - 1][3]
                    prev_ent.focus_set()
                    prev_ent.selection_range(0, 'end')
                    prev_ent.icursor('end')
                    _scroll_to_row(idx - 1)
                else:
                    start_ent.focus_set()
                    start_ent.selection_range(0, 'end')
                    start_ent.icursor('end')
            return "break"

        def _on_enter_base(event):
            start_ent.focus_set()
            start_ent.selection_range(0, 'end')
            start_ent.icursor('end')
            return "break"

        def _on_enter_start(event):
            if seq_widgets:
                first_suf = seq_widgets[0][3]
                first_suf.focus_set()
                first_suf.selection_range(0, 'end')
                first_suf.icursor('end')
                _scroll_to_row(0)
            else:
                if hasattr(dlg, "_apply_btn") and dlg._apply_btn:
                    dlg._apply_btn.focus_set()
            return "break"

        base_ent.bind("<Return>", _on_enter_base)
        start_ent.bind("<Return>", _on_enter_start)

        for i, item in enumerate(batch_items):
            row = tk.Frame(inner, bg=COLORS["bg_card"],
                           highlightbackground=COLORS["border"], highlightthickness=1)
            row.pack(fill="x", pady=3)
            row_widgets.append(row)

            # Type tag badge: [Title] cyan, [Chapter] accent, [Track] cyan
            tag_color = COLORS["cyan"] if item["type"] in ("title", "track") else COLORS["accent"]
            tag_lbl = tk.Label(
                row, text=item["tag"],
                font=FONTS["small_bold"], bg=COLORS["bg_card"],
                fg=tag_color, width=9, anchor="w"
            )

            # Item label
            trk_lbl = tk.Label(
                row, text=item["label"],
                font=FONTS["badge"], bg=COLORS["bg_card"],
                fg=COLORS["text_primary"], width=13, anchor="w"
            )

            # Manual entry
            name_var = tk.StringVar(value=item["current_stem"])
            entry_vars.append(name_var)
            name_ent = tk.Entry(
                row, textvariable=name_var, font=FONTS["body"],
                bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                insertbackground=COLORS["accent"], relief="flat", bd=4, width=20
            )
            name_ent.bind("<Return>", lambda e, idx=i: _on_enter_track(e, idx))
            name_ent.bind("<Shift-Return>", lambda e, idx=i: _on_shift_enter_track(e, idx))
            name_ent.bind("<FocusIn>", lambda e, idx=i: _scroll_to_row(idx))
            manual_widgets.append((tag_lbl, trk_lbl, name_ent))

            # Sequential mode widgets
            try:
                start_idx = int(start_var.get())
            except ValueError:
                start_idx = 1
            num_text = str(start_idx + i).zfill(pad_width)
            num_lbl = tk.Label(
                row, text=num_text,
                font=FONTS["badge"], bg=COLORS["bg_card"],
                fg=COLORS["cyan"], width=5
            )
            suf_lbl = tk.Label(
                row, text=t('batch.seq_suffix'),
                font=FONTS["small"], bg=COLORS["bg_card"],
                fg=COLORS["text_muted"]
            )
            suf_var = tk.StringVar(value="")
            suffix_vars.append(suf_var)
            suf_ent = tk.Entry(
                row, textvariable=suf_var, font=FONTS["body"],
                bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                insertbackground=COLORS["accent"], relief="flat", bd=4, width=16
            )
            suf_ent.bind("<Return>", lambda e, idx=i: _on_enter_track(e, idx))
            suf_ent.bind("<Shift-Return>", lambda e, idx=i: _on_shift_enter_track(e, idx))
            suf_ent.bind("<FocusIn>", lambda e, idx=i: _scroll_to_row(idx))
            seq_widgets.append((tag_lbl, num_lbl, suf_lbl, suf_ent))

            # Live preview label
            prev_lbl = tk.Label(
                row, text="",
                font=FONTS["mono"], bg=COLORS["bg_card"],
                fg=COLORS["text_secondary"], anchor="w", width=26
            )
            prev_lbl.pack(side="right", padx=(6, 12), pady=6)
            preview_labels.append(prev_lbl)

        def _update_previews(*_):
            """Recalculate sequential numbers and live preview for each item."""
            try:
                start_idx = int(start_var.get())
            except ValueError:
                start_idx = 1
            base = base_var.get().strip()
            pw = 3 if total > 99 else 2
            is_seq = seq_enabled.get()

            for i in range(total):
                num_str = str(start_idx + i).zfill(pw)
                seq_widgets[i][1].configure(text=num_str)

                if is_seq:
                    suf = suffix_vars[i].get().strip()
                    if base and suf:
                        p_stem = f"{base} {num_str} - {suf}"
                    elif base:
                        p_stem = f"{base} {num_str}"
                    elif suf:
                        p_stem = f"{num_str} - {suf}"
                    else:
                        p_stem = num_str
                else:
                    p_stem = entry_vars[i].get().strip() or batch_items[i]["current_stem"]

                clean = sanitize_filename(p_stem, fallback=f"Item_{i+1}")
                preview_labels[i].configure(text=f"→ {clean}")

        def _toggle_mode(*_):
            """Switch between manual and sequential layouts."""
            is_seq = seq_enabled.get()
            cur_focus = None
            try:
                cur_focus = dlg.focus_get()
            except Exception:
                pass
            active_idx = None
            for idx in range(total):
                if cur_focus in (manual_widgets[idx][2], seq_widgets[idx][3]):
                    active_idx = idx
                    break

            for i in range(total):
                tag_m, trk_lbl, name_ent = manual_widgets[i]
                tag_s, num_lbl, suf_lbl, suf_ent = seq_widgets[i]
                # Hide all first
                for w in (tag_m, trk_lbl, name_ent, tag_s, num_lbl, suf_lbl, suf_ent):
                    w.pack_forget()

                if is_seq:
                    tag_s.pack(side="left", padx=(10, 4), pady=6)
                    num_lbl.pack(side="left", padx=(0, 6), pady=6)
                    suf_lbl.pack(side="left", padx=(0, 4), pady=6)
                    suf_ent.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)
                else:
                    tag_m.pack(side="left", padx=(10, 4), pady=6)
                    trk_lbl.pack(side="left", padx=(0, 6), pady=6)
                    name_ent.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)

            state = "normal" if is_seq else "disabled"
            base_ent.configure(state=state)
            start_ent.configure(state=state)
            _update_previews()

            if active_idx is not None:
                try:
                    if is_seq:
                        seq_widgets[active_idx][3].focus_set()
                        seq_widgets[active_idx][3].selection_range(0, 'end')
                    else:
                        manual_widgets[active_idx][2].focus_set()
                        manual_widgets[active_idx][2].selection_range(0, 'end')
                except Exception:
                    pass

        # Wire live preview triggers
        seq_enabled.trace_add("write", _toggle_mode)
        base_var.trace_add("write", _update_previews)
        start_var.trace_add("write", _update_previews)
        for var in entry_vars:
            var.trace_add("write", _update_previews)
        for var in suffix_vars:
            var.trace_add("write", _update_previews)

        # Initialize in manual mode
        _toggle_mode()

        # ── Button row ────────────────────────────────────
        btn_row = tk.Frame(dlg, bg=COLORS["bg_panel"])
        btn_row.pack(fill="x", padx=24, pady=(4, 20))

        def apply_all():
            is_seq = seq_enabled.get()
            base = base_var.get().strip()
            try:
                start_idx = int(start_var.get())
            except ValueError:
                start_idx = 1
            pw = 3 if total > 99 else 2

            for i, item in enumerate(batch_items):
                if is_seq:
                    num_str = str(start_idx + i).zfill(pw)
                    suffix = suffix_vars[i].get().strip()
                    if base and suffix:
                        raw_stem = f"{base} {num_str} - {suffix}"
                    elif base:
                        raw_stem = f"{base} {num_str}"
                    elif suffix:
                        raw_stem = f"{num_str} - {suffix}"
                    else:
                        raw_stem = num_str
                else:
                    raw_stem = entry_vars[i].get().strip()

                fallback_prefix = "Title" if item["type"] == "title" else ("Chapter" if item["type"] == "chapter" else "Track")
                clean_stem = sanitize_filename(raw_stem, fallback=f"{fallback_prefix}_{i+1}")

                if item["type"] in ("title", "track"):
                    item["target"]["custom_stem"] = clean_stem
                    card_idx = item["title_idx"]
                    if card_idx < len(self._cards):
                        self._cards[card_idx]._filename_lbl.configure(text=f"📼  {clean_stem}")
                elif item["type"] == "chapter":
                    item["target"]["custom_stem"] = clean_stem
                    item["target"]["name"] = clean_stem
                    card_idx = item["title_idx"]
                    c_num = item["chapter_num"]
                    if card_idx < len(self._cards):
                        self._cards[card_idx].update_chapter_name_display(c_num, clean_stem)

            self._log.log(t('log.batch_renamed').format(total=total), "success")
            dlg.destroy()

        apply_btn = tk.Button(
            btn_row, text=t('batch.apply_all'),
            font=FONTS["body"], bg=COLORS["accent"],
            fg=COLORS["text_primary"], relief="flat", bd=0,
            padx=20, pady=8, cursor="hand2",
            command=apply_all
        )
        apply_btn.pack(side="left", padx=(0, 8))
        apply_btn.bind("<Return>", lambda e: apply_all())
        dlg._apply_btn = apply_btn

        cancel_btn = tk.Button(
            btn_row, text=t('batch.cancel'),
            font=FONTS["body"], bg=COLORS["bg_card"],
            fg=COLORS["text_muted"], relief="flat", bd=0,
            padx=20, pady=8, cursor="hand2",
            command=dlg.destroy
        )
        cancel_btn.pack(side="left")
        cancel_btn.bind("<Return>", lambda e: dlg.destroy())
        dlg._cancel_btn = cancel_btn

        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg._manual_widgets = manual_widgets
        dlg._seq_widgets = seq_widgets
        dlg._base_ent = base_ent
        dlg._start_ent = start_ent
        dlg._seq_enabled = seq_enabled
        dlg._entry_vars = entry_vars
        dlg._suffix_vars = suffix_vars
        dlg._scroll_to_row = _scroll_to_row
        dlg._on_enter_track = _on_enter_track
        dlg._on_shift_enter_track = _on_shift_enter_track

        def _focus_initial():
            try:
                if seq_enabled.get():
                    base_ent.focus_set()
                    base_ent.selection_range(0, 'end')
                    base_ent.icursor('end')
                elif manual_widgets:
                    manual_widgets[0][2].focus_set()
                    manual_widgets[0][2].selection_range(0, 'end')
                    manual_widgets[0][2].icursor('end')
            except Exception:
                pass

        _focus_job[0] = dlg.after(60, _focus_initial)

        position_window_on_parent(
            dlg, self,
            width=scale_val(760),
            height=scale_val(600),
            min_w=scale_val(600),
            min_h=scale_val(480)
        )
        dlg.grab_set()

    # ── FFmpeg warning ────────────────────────
    def _show_ffmpeg_warning(self):
        self._log.log(
            t('log.ffmpeg_dl'), "error"
        )
        self._log.log(
            t('log.ffmpeg_hint'), "warning"
        )

    def _toggle_console(self):
        """Show or hide the console log window."""
        if self._log_window.state() == "withdrawn" or self._log_window.state() == "iconic":
            if not getattr(self, "_log_window_positioned", False):
                position_window_on_parent(
                    self._log_window, self,
                    width=scale_val(700), height=scale_val(400)
                )
                self._log_window_positioned = True
            else:
                self._log_window.deiconify()
            self._log_window.lift()
        else:
            self._log_window.withdraw()

    def _refresh_ui(self):
        self.title(t('header.title'))
        self._title_lbl.configure(text=t('header.title'))
        self._console_btn.configure(text=t('header.console'))
        if hasattr(self, "_clear_all_btn"):
            self._clear_all_btn.configure(text=t('header.clear_all'))
        if hasattr(self, "_clear_all_tip"):
            self._clear_all_tip.text = t('header.clear_all_tip')
        self._about_btn.configure(text=t('header.about'))
        self._batch_rename_btn.configure(text=t('header.batch_rename'))
        self._eject_btn.configure(text=t('header.eject_disc'))
        
        d = self._vcd_path.get()
        if d:
            drive_letter = d[0].upper()
            if self._videos:
                self._detect_label.configure(text=t('drive.detected'), fg=COLORS["cyan"])
            elif self._source_type == "DVD":
                self._detect_label.configure(text=t('drive.detect_dvd'), fg=COLORS["success"])
            elif self._source_type == "VCD":
                self._detect_label.configure(text=t('drive.detect_vcd'), fg=COLORS["success"])
            else:
                self._detect_label.configure(text=t('drive.detect_disc'), fg=COLORS["success"])

            if self._source_type == "DVD":
                self._drive_lbl.configure(text=t('header.dvd_on').format(drive=drive_letter))
                self._scan_btn.set_text(t('source.scan_dvd'), icon="🔍")
            elif self._source_type == "VCD":
                self._drive_lbl.configure(text=t('header.vcd_on').format(drive=drive_letter))
                self._scan_btn.set_text(t('source.scan_vcd'), icon="🔍")
            else:
                self._drive_lbl.configure(text=t('header.disc_on').format(drive=drive_letter))
                self._scan_btn.set_text(t('source.scan'), icon="🔍")
            self._detected_drive_lbl.configure(text=t('drive.drive_label').format(drive=drive_letter))
        else:
            self._drive_lbl.configure(text=t('header.no_disc'))
            self._detect_label.configure(text=t('drive.insert_disc'))
            self._scan_btn.set_text(t('source.scan'), icon="🔍")
            
        self._source_section_lbl.configure(text=t('source.title'))
        self._browse_btn.set_text(t('source.browse'), icon="📁")
        
        self._sel_section_lbl.configure(text=t('selection.title'))
        if hasattr(self, "_dvd_mode_title_rb"):
            self._dvd_mode_title_rb.configure(text=t('selection.mode_title'))
        if hasattr(self, "_dvd_mode_chaps_rb"):
            self._dvd_mode_chaps_rb.configure(text=t('selection.mode_chapters'))
        self._update_sel_count()
        
        self._format_section_lbl.configure(text=t('format.title'))
        self._video_mode_rb.configure(text=t('format.video_mode'))
        self._audio_mode_rb.configure(text=t('format.audio_mode'))
        if hasattr(self, "_both_mode_rb"):
            self._both_mode_rb.configure(text=t('format.both_mode'))
        self._video_fmt_lbl.configure(text=t('format.video_lbl'))
        self._audio_fmt_lbl.configure(text=t('format.audio_lbl'))
        
        for fmt, lbl in self._fmt_desc_lbls.items():
            lbl.configure(text=t(f"format.{fmt.lower()}_desc"))
        for fmt, lbl in self._audio_desc_lbls.items():
            lbl.configure(text=t(f"format.{fmt.lower()}_desc"))
            
        self._dat_mode_lbl.configure(text=t('format.dat_mode_lbl'))
        self._dat_raw_rb.configure(text=t('format.dat_raw'))
        self._dat_mp4_rb.configure(text=t('format.dat_mp4'))
        self._res_title_lbl.configure(text=t('format.res_title'))
        self._res_orig_rb.configure(text=t('format.res_orig'))
        self._res_1080p_rb.configure(text=t('format.res_1080p'))

        if hasattr(self, "_audio_track_lbl"):
            self._audio_track_lbl.configure(text=t('format.audio_track_lbl'))
        if hasattr(self, "_target_title_lbl"):
            self._target_title_lbl.configure(text=t('format.target_title_lbl'))
        if hasattr(self, "_update_audio_track_selector"):
            self._update_audio_track_selector()

        if hasattr(self, "_update_format_greyout"):
            self._update_format_greyout()
        
        self._output_section_lbl.configure(text=t('output.title'))
        self._choose_folder_btn.set_text(t('output.choose'), icon="💾")
        if hasattr(self, "_dvd_title_folder_chk"):
            self._dvd_title_folder_chk.configure(text=t('output.dvd_title_folder'))
        self._auto_open_chk.configure(text=t('output.auto_open'))
        if hasattr(self, "_dvd_timeline_chk"):
            self._dvd_timeline_chk.configure(text=t('output.dvd_timeline'))
        
        self._rip_btn.set_text(t('rip.start'), icon="⚡")
        self._stop_btn.set_text(t('rip.stop'), icon="⏹")
        
        self._content_title.configure(text=t('content.title'))
        total = len(self._videos)
        if total == 0:
            self._video_count_badge.configure(text=t('content.badge_empty'))
        elif self._source_type == "DVD":
            self._video_count_badge.configure(text=t('content.badge_titles').format(n=total))
        else:
            self._video_count_badge.configure(text=t('content.badge_tracks').format(n=total))
            
        if hasattr(self, "_empty_title_lbl") and self._empty_title_lbl.winfo_exists():
            self._empty_title_lbl.configure(text=t('content.empty_title'))
            self._empty_sub_lbl.configure(text=t('content.empty_sub'))
            
        self._console_title_lbl.configure(text=t('console.title'))
        self._console_clear_btn.configure(text=t('console.clear'))
        self._log_window.title(f"{t('console.title').strip()} — {t('header.title')}")
        if hasattr(self, "_about_dialog") and self._about_dialog and self._about_dialog.winfo_exists():
            if hasattr(self._about_dialog, "update_lang"):
                self._about_dialog.update_lang()

    def destroy(self):
        if getattr(self, "_stale_check_job", None):
            try:
                self.after_cancel(self._stale_check_job)
            except Exception:
                pass
            self._stale_check_job = None
        if getattr(self, "_poll_job", None):
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if getattr(i18n, "_scale_cb", None) == self._on_scale_changed:
            i18n.set_scale_callback(None)
        if getattr(i18n, "_theme_cb", None) == self._on_theme_changed:
            i18n.set_theme_callback(None)
        try:
            super().destroy()
        except Exception:
            pass

    def on_close(self):
        try:
            self._taskbar_progress.reset()
        except Exception:
            pass
        try:
            if hasattr(self, "i18n") and self.i18n:
                self.i18n._save_config()
        except Exception:
            pass
        self._log_window.destroy()
        if self._poll_job:
            self.after_cancel(self._poll_job)
        if getattr(self, "_stale_check_job", None):
            try:
                self.after_cancel(self._stale_check_job)
            except Exception:
                pass
        release_single_instance_lock()
        self.destroy()


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Single-instance lock check — executed before initializing heavy GUI
    if not acquire_single_instance_lock():
        activate_existing_window()
        sys.exit(0)

    app = VCDRipperApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
