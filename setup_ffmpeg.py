"""
setup_ffmpeg.py  —  Helper script to download FFmpeg automatically (Windows)
Run this once if you don't have FFmpeg installed.
"""

import urllib.request
import zipfile
import os
import sys
import shutil
import ctypes

FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

DEST = os.path.join(os.path.dirname(__file__), "ffmpeg", "bin")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def download_ffmpeg():
    print("=" * 56)
    print("  FFmpeg Auto-Installer for Disc Ripper Pro")
    print("=" * 56)
    print()

    # Check if already present
    if shutil.which("ffmpeg"):
        print("✓  FFmpeg is already in your PATH – nothing to do.")
        return

    if os.path.isfile(os.path.join(DEST, "ffmpeg.exe")):
        print("✓  FFmpeg already exists in:", DEST)
        return

    zip_path = os.path.join(os.path.dirname(__file__), "_ffmpeg_tmp.zip")

    print(f"Downloading FFmpeg from:\n  {FFMPEG_URL}\n")
    print("This may take a few minutes (~80 MB)…")

    try:
        def reporthook(count, block_size, total_size):
            if total_size > 0:
                pct = min(100, int(count * block_size * 100 / total_size))
                bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
                sys.stdout.write(f"\r  [{bar}] {pct}%")
                sys.stdout.flush()

        urllib.request.urlretrieve(FFMPEG_URL, zip_path, reporthook)
        print("\n\nExtracting…")

        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            # Find ffmpeg.exe and ffprobe.exe inside the zip
            os.makedirs(DEST, exist_ok=True)
            for member in names:
                if member.endswith("ffmpeg.exe") or member.endswith("ffprobe.exe"):
                    basename = os.path.basename(member)
                    with z.open(member) as src, open(
                        os.path.join(DEST, basename), "wb"
                    ) as dst:
                        shutil.copyfileobj(src, dst)
                    print(f"  Extracted: {basename}")

        os.remove(zip_path)
        print(f"\n✓  FFmpeg installed to:\n   {DEST}")
        print("\nYou can now launch Disc Ripper Pro.")

    except Exception as e:
        print(f"\n✗  Error: {e}")
        print("\nPlease download FFmpeg manually:")
        print("  https://ffmpeg.org/download.html")
        print(f"\nThen place ffmpeg.exe and ffprobe.exe in:\n  {DEST}")

    input("\nPress Enter to exit…")


if __name__ == "__main__":
    download_ffmpeg()
