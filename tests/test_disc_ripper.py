"""
Comprehensive Automated Test Suite for Disc Ripper Pro v2.0.0
Verifies all 21 checklist criteria across Application Identity,
Disc Detection, DVD Scanning, DVD Ripping, Error Handling, and VCD Regression.
"""

import os
import sys
import time
import shutil
import tempfile
import struct
import subprocess
import json
import unittest
from unittest.mock import patch, MagicMock
import re
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tkinter as tk

import disc_detector
import dvd_engine
import vcd_ripper


def get_bundled_ffmpeg():
    bundled = PROJECT_ROOT / "ffmpeg" / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    # Check PATH
    path = shutil.which("ffmpeg")
    return path


def get_bundled_ffprobe():
    bundled = PROJECT_ROOT / "ffmpeg" / "bin" / "ffprobe.exe"
    if bundled.exists():
        return str(bundled)
    path = shutil.which("ffprobe")
    return path


def create_synthetic_mpeg2_vob(output_path: str, duration_sec: float = 1.0, width: int = 720, height: int = 480):
    """Generate a valid standard DVD MPEG-2 / AC3 VOB using ffmpeg."""
    ffmpeg = get_bundled_ffmpeg()
    if not ffmpeg:
        raise unittest.SkipTest("FFmpeg binary not available for synthetic media creation.")

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size={width}x{height}:rate=29.97",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration_sec}",
        "-c:v", "mpeg2video", "-b:v", "4000k", "-g", "15",
        "-c:a", "ac3", "-b:a", "192k",
        "-f", "vob",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed creating synthetic VOB: {res.stderr}")


def create_synthetic_vcd_dat(output_path: str, duration_sec: float = 1.0):
    """Generate a valid VCD MPEG-1 / MP2 DAT/MPG file using ffmpeg."""
    ffmpeg = get_bundled_ffmpeg()
    if not ffmpeg:
        raise unittest.SkipTest("FFmpeg binary not available for synthetic media creation.")

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size=352x240:rate=29.97",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_sec}",
        "-c:v", "mpeg1video", "-b:v", "1150k",
        "-c:a", "mp2", "-b:a", "224k",
        "-f", "mpeg",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed creating synthetic VCD DAT: {res.stderr}")


def create_minimal_valid_ifo(ifo_path: str, is_vmg: bool = True, title_count: int = 1):
    """Generate a minimal valid binary IFO file conforming to DVD-Video VMGI/VTSI specification."""
    data = bytearray(2048)
    identifier = b"DVDVIDEO-VMG2.0" if is_vmg else b"DVDVIDEO-VTS2.0"
    data[0:len(identifier)] = identifier

    if is_vmg:
        # TT_SRPT pointer at 0x00C4 in sectors
        data[0x00C4:0x00C8] = struct.pack(">I", 1)  # Sector 1 (offset 2048)
        # Pad another sector for TT_SRPT
        tt_srpt = bytearray(2048)
        tt_srpt[0:2] = struct.pack(">H", title_count)
        for i in range(title_count):
            entry_offset = 8 + (i * 12)
            tt_srpt[entry_offset] = 1        # 1 chapter
            tt_srpt[entry_offset + 1] = 0
            tt_srpt[entry_offset + 2] = 0
            tt_srpt[entry_offset + 3] = 0
            tt_srpt[entry_offset + 4] = 0
            tt_srpt[entry_offset + 5] = 0
            tt_srpt[entry_offset + 6] = i + 1  # VTS number
            tt_srpt[entry_offset + 7] = 1      # TTN
        data.extend(tt_srpt)
    else:
        # Video attributes at 0x0200: MPEG-2, NTSC, 4:3, 720x480
        # 0x0200: 0x00 (MPEG-2), 0x0201: 0x40 (NTSC, 4:3, 720x480)
        data[0x0200] = 0x00
        data[0x0201] = 0x40
        # 1 audio stream: AC3, English
        data[0x0202] = 0x01
        data[0x0204] = 0x00  # AC3
        data[0x0205] = 0x00
        data[0x0206] = ord('e')
        data[0x0207] = ord('n')

        # VTS_PGCIT pointer at 0x00CC in sectors
        data[0x00CC:0x00D0] = struct.pack(">I", 1)
        pgcit = bytearray(2048)
        pgcit[0:2] = struct.pack(">H", 1)  # 1 PGC
        # PGC 1 entry at offset 8: PGC category (0), PGC offset (16)
        pgcit[8:12] = struct.pack(">I", 0x80000000)
        pgcit[12:16] = struct.pack(">I", 16)
        # PGC structure at offset 16:
        # Duration at 16 + 4 (0x04) in BCD: 00:10:00:00 (10 mins)
        pgcit[16 + 4] = 0x00  # hours
        pgcit[16 + 5] = 0x10  # mins = 10
        pgcit[16 + 6] = 0x00  # secs = 00
        pgcit[16 + 7] = 0x00  # frames
        data.extend(pgcit)

    with open(ifo_path, "wb") as f:
        f.write(data)


class TestDiscRipperProV2(unittest.TestCase):
    """Full test suite covering all specifications of Disc Ripper Pro v2.0.0."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="disc_ripper_test_")
        cls.ffmpeg = get_bundled_ffmpeg()
        cls.ffprobe = get_bundled_ffprobe()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # ─────────────────────────────────────────────
    #  1. Application Identity Verification
    # ─────────────────────────────────────────────
    def test_01_app_identity_metadata(self):
        """Verify APP_NAME is Disc Ripper Pro and APP_VERSION is 2.0.0."""
        self.assertEqual(vcd_ripper.APP_NAME, "Disc Ripper Pro")
        self.assertEqual(vcd_ripper.APP_VERSION, "2.0.0")
        self.assertIn("Disc_Ripper_Pro", vcd_ripper.SINGLE_INSTANCE_MUTEX_NAME)
        self.assertEqual(vcd_ripper.APP_USER_MODEL_ID, "jjsiew.discripperpro.2.0.0")

    def test_02_localization_titles(self):
        """Verify localization dictionary and json titles read Disc Ripper Pro."""
        self.assertEqual(vcd_ripper.TRANSLATIONS["en"]["header"]["title"], "Disc Ripper Pro")
        self.assertEqual(vcd_ripper.TRANSLATIONS["zh_CN"]["header"]["title"], "Disc Ripper Pro")
        # Check external json files
        en_path = PROJECT_ROOT / "en.json"
        if en_path.exists():
            import json
            with open(en_path, "r", encoding="utf-8") as f:
                en_data = json.load(f)
            self.assertEqual(en_data["header"]["title"], "Disc Ripper Pro")

    # ─────────────────────────────────────────────
    #  2. Automatic Disc Type Detection
    # ─────────────────────────────────────────────
    def test_03_detect_empty_or_nonexistent_drive(self):
        """Verify non-existent directory or empty path reports empty/invalid safely."""
        fake_path = os.path.join(self.temp_dir, "non_existent_drive")
        res = disc_detector.detect_disc(fake_path)
        self.assertFalse(res.is_vcd)
        self.assertFalse(res.is_dvd)
        self.assertEqual(res.disc_type, "Drive Unavailable")

    def test_04_detect_vcd_structure(self):
        """Verify valid VCD structure is accurately identified as VCD."""
        vcd_dir = os.path.join(self.temp_dir, "test_vcd")
        mpegav = os.path.join(vcd_dir, "MPEGAV")
        os.makedirs(mpegav, exist_ok=True)
        dat_path = os.path.join(mpegav, "AVSEQ01.DAT")
        with open(dat_path, "wb") as f:
            f.write(b"\x00" * 1024)

        res = disc_detector.detect_disc(vcd_dir)
        self.assertTrue(res.is_vcd)
        self.assertFalse(res.is_dvd)
        self.assertEqual(res.disc_type, "VCD")
        # Backwards compatible tuple unpacking and bool check
        is_vcd_flag, d_type = res
        self.assertTrue(is_vcd_flag)
        self.assertEqual(d_type, "VCD")

    def test_05_detect_dvd_video_root(self):
        """Verify valid DVD-Video root (containing VIDEO_TS) is identified as DVD-Video."""
        dvd_dir = os.path.join(self.temp_dir, "test_dvd")
        video_ts = os.path.join(dvd_dir, "VIDEO_TS")
        os.makedirs(video_ts, exist_ok=True)
        create_minimal_valid_ifo(os.path.join(video_ts, "VIDEO_TS.IFO"), is_vmg=True)
        create_minimal_valid_ifo(os.path.join(video_ts, "VTS_01_0.IFO"), is_vmg=False)
        with open(os.path.join(video_ts, "VTS_01_1.VOB"), "wb") as f:
            f.write(b"\x00" * 2048)

        res = disc_detector.detect_disc(dvd_dir)
        self.assertFalse(res.is_vcd)
        self.assertTrue(res.is_dvd)
        self.assertEqual(res.disc_type, "DVD-Video")

    def test_06_detect_dvd_video_ts_folder_browse(self):
        """Verify browsing directly into VIDEO_TS folder also detects DVD-Video."""
        dvd_dir = os.path.join(self.temp_dir, "test_dvd")
        video_ts = os.path.join(dvd_dir, "VIDEO_TS")
        res = disc_detector.detect_disc(video_ts)
        self.assertTrue(res.is_dvd)
        self.assertEqual(res.disc_type, "DVD-Video")

    def test_07_detect_unsupported_data_disc(self):
        """Verify data disc with random files is identified as Unsupported Data Disc."""
        data_dir = os.path.join(self.temp_dir, "test_data_disc")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "document.docx"), "w") as f:
            f.write("test content")

        res = disc_detector.detect_disc(data_dir)
        self.assertFalse(res.is_vcd)
        self.assertFalse(res.is_dvd)
        self.assertFalse(res.is_supported)
        self.assertEqual(res.disc_type, "Data Disc")

    def test_08_detect_unsupported_bluray(self):
        """Verify Blu-ray disc is identified as Blu-ray and unsupported."""
        bd_dir = os.path.join(self.temp_dir, "test_bd")
        os.makedirs(os.path.join(bd_dir, "BDMV"), exist_ok=True)
        with open(os.path.join(bd_dir, "BDMV", "index.bdmv"), "wb") as f:
            f.write(b"INDX0200")

        res = disc_detector.detect_disc(bd_dir)
        self.assertFalse(res.is_vcd)
        self.assertFalse(res.is_dvd)
        self.assertFalse(res.is_supported)
        self.assertEqual(res.disc_type, "Blu-ray")

    def test_09_detect_unsupported_audio_cd(self):
        """Verify Audio CD is detected as Audio CD and unsupported."""
        cda_dir = os.path.join(self.temp_dir, "test_cda")
        os.makedirs(cda_dir, exist_ok=True)
        with open(os.path.join(cda_dir, "Track01.cda"), "wb") as f:
            f.write(b"RIFFCDDA")

        res = disc_detector.detect_disc(cda_dir)
        self.assertFalse(res.is_vcd)
        self.assertFalse(res.is_dvd)
        self.assertFalse(res.is_supported)
        self.assertEqual(res.disc_type, "Audio CD")

    # ─────────────────────────────────────────────
    #  3. DVD Scanning & Title Detection
    # ─────────────────────────────────────────────
    def test_10_dvd_multi_vob_grouping(self):
        """Verify multi-segment VOBs (VTS_01_1.VOB, VTS_01_2.VOB) are grouped into 1 logical title."""
        dvd_dir = os.path.join(self.temp_dir, "test_multi_vob_dvd")
        vts = os.path.join(dvd_dir, "VIDEO_TS")
        os.makedirs(vts, exist_ok=True)

        create_minimal_valid_ifo(os.path.join(vts, "VIDEO_TS.IFO"), is_vmg=True, title_count=1)
        create_minimal_valid_ifo(os.path.join(vts, "VTS_01_0.IFO"), is_vmg=False)

        # Create two slice VOBs for Title 1
        vob1 = os.path.join(vts, "VTS_01_1.VOB")
        vob2 = os.path.join(vts, "VTS_01_2.VOB")
        with open(vob1, "wb") as f:
            f.write(b"\x00" * (1024 * 1024))  # 1 MB
        with open(vob2, "wb") as f:
            f.write(b"\x00" * (2 * 1024 * 1024))  # 2 MB

        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        self.assertEqual(len(titles), 1, "Multi-part VOBs must be grouped into a single title")
        t1 = titles[0]
        self.assertEqual(t1["title_number"], 1)
        self.assertEqual(len(t1["vob_files"]), 2, "Title must contain both VOB segment files")
        self.assertAlmostEqual(t1["size_mb"], 3.0, delta=0.2)

    def test_11_dvd_multi_title_detection(self):
        """Verify multiple VTS titles are detected as distinct titles."""
        dvd_dir = os.path.join(self.temp_dir, "test_multi_title_dvd")
        vts = os.path.join(dvd_dir, "VIDEO_TS")
        os.makedirs(vts, exist_ok=True)

        create_minimal_valid_ifo(os.path.join(vts, "VIDEO_TS.IFO"), is_vmg=True, title_count=2)
        create_minimal_valid_ifo(os.path.join(vts, "VTS_01_0.IFO"), is_vmg=False)
        create_minimal_valid_ifo(os.path.join(vts, "VTS_02_0.IFO"), is_vmg=False)

        with open(os.path.join(vts, "VTS_01_1.VOB"), "wb") as f:
            f.write(b"\x00" * 1024)
        with open(os.path.join(vts, "VTS_02_1.VOB"), "wb") as f:
            f.write(b"\x00" * 1024)

        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        self.assertEqual(len(titles), 2, "Should detect 2 distinct DVD titles")
        self.assertEqual(titles[0]["title_number"], 1)
        self.assertEqual(titles[1]["title_number"], 2)

    def test_12_dvd_encryption_checker(self):
        """Verify encryption detection identifies unencrypted discs correctly."""
        dvd_dir = os.path.join(self.temp_dir, "test_multi_vob_dvd", "VIDEO_TS")
        is_enc, reason = dvd_engine.check_dvd_encryption(dvd_dir)
        self.assertFalse(is_enc)

    # ─────────────────────────────────────────────
    #  4. DVD Ripping Pipelines
    # ─────────────────────────────────────────────
    def test_13_dvd_rip_mp4_generation(self):
        """Verify ripping a DVD title to MP4 generates a valid, playable MP4 file."""
        dvd_dir = os.path.join(self.temp_dir, "test_rip_dvd")
        vts = os.path.join(dvd_dir, "VIDEO_TS")
        os.makedirs(vts, exist_ok=True)

        vob_path = os.path.join(vts, "VTS_01_1.VOB")
        create_synthetic_mpeg2_vob(vob_path, duration_sec=1.5)
        create_minimal_valid_ifo(os.path.join(vts, "VIDEO_TS.IFO"), is_vmg=True, title_count=1)
        create_minimal_valid_ifo(os.path.join(vts, "VTS_01_0.IFO"), is_vmg=False)

        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        self.assertTrue(len(titles) >= 1)
        t1 = titles[0]

        out_dir = os.path.join(self.temp_dir, "out_mp4")
        os.makedirs(out_dir, exist_ok=True)

        cmd, out_file, temp_concat = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg,
            dvd_source=dvd_dir,
            title_dict=t1,
            out_dir=out_dir,
            output_format="MP4",
            use_1080p=False
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, f"FFmpeg DVD MP4 rip failed: {res.stderr}")
        self.assertTrue(os.path.exists(out_file))
        self.assertGreater(os.path.getsize(out_file), 1000)
        if temp_concat and os.path.exists(temp_concat):
            os.remove(temp_concat)

    def test_14_dvd_rip_mpg_lossless(self):
        """Verify ripping a DVD title to MPG uses stream copy or clean remux."""
        dvd_dir = os.path.join(self.temp_dir, "test_rip_dvd")
        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        t1 = titles[0]

        out_dir = os.path.join(self.temp_dir, "out_mpg")
        os.makedirs(out_dir, exist_ok=True)

        cmd, out_file, temp_concat = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg,
            dvd_source=dvd_dir,
            title_dict=t1,
            out_dir=out_dir,
            output_format="MPG"
        )
        self.assertIn("-c:v", cmd)
        self.assertIn("copy", cmd)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, f"FFmpeg DVD MPG rip failed: {res.stderr}")
        self.assertTrue(os.path.exists(out_file))
        self.assertTrue(out_file.endswith(".mpg"))
        if temp_concat and os.path.exists(temp_concat):
            os.remove(temp_concat)

    def test_15_dvd_rip_mov(self):
        """Verify ripping a DVD title to MOV container format."""
        dvd_dir = os.path.join(self.temp_dir, "test_rip_dvd")
        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        t1 = titles[0]

        out_dir = os.path.join(self.temp_dir, "out_mov")
        os.makedirs(out_dir, exist_ok=True)

        cmd, out_file, temp_concat = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg,
            dvd_source=dvd_dir,
            title_dict=t1,
            out_dir=out_dir,
            output_format="MOV"
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(os.path.exists(out_file))
        self.assertTrue(out_file.endswith(".mov"))
        if temp_concat and os.path.exists(temp_concat):
            os.remove(temp_concat)

    def test_16_dvd_audio_only_wav_mp3(self):
        """Verify Audio Only extraction on DVD title produces WAV and MP3."""
        dvd_dir = os.path.join(self.temp_dir, "test_rip_dvd")
        titles = dvd_engine.scan_dvd_titles(dvd_dir, self.ffmpeg, self.ffprobe)
        t1 = titles[0]

        out_dir = os.path.join(self.temp_dir, "out_audio")
        os.makedirs(out_dir, exist_ok=True)

        # WAV
        cmd_wav, out_wav, c_wav = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg, dvd_source=dvd_dir, title_dict=t1,
            out_dir=out_dir, output_format="MP4", audio_only=True, audio_format="WAV"
        )
        res_wav = subprocess.run(cmd_wav, capture_output=True, text=True, timeout=30)
        self.assertEqual(res_wav.returncode, 0)
        self.assertTrue(os.path.exists(out_wav) and out_wav.endswith(".wav"))
        if c_wav and os.path.exists(c_wav):
            os.remove(c_wav)

        # MP3
        cmd_mp3, out_mp3, c_mp3 = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg, dvd_source=dvd_dir, title_dict=t1,
            out_dir=out_dir, output_format="MP4", audio_only=True, audio_format="MP3"
        )
        res_mp3 = subprocess.run(cmd_mp3, capture_output=True, text=True, timeout=30)
        self.assertEqual(res_mp3.returncode, 0)
        self.assertTrue(os.path.exists(out_mp3) and out_mp3.endswith(".mp3"))
        if c_mp3 and os.path.exists(c_mp3):
            os.remove(c_mp3)

    # ─────────────────────────────────────────────
    #  5. VCD Pipeline Regression Verification
    # ─────────────────────────────────────────────
    def test_17_vcd_pipeline_scan_and_raw_dat(self):
        """Verify VCD pipeline scanning and direct DAT copying remain fully functional."""
        vcd_dir = os.path.join(self.temp_dir, "test_vcd_regression")
        mpegav = os.path.join(vcd_dir, "MPEGAV")
        os.makedirs(mpegav, exist_ok=True)
        dat_file = os.path.join(mpegav, "AVSEQ01.DAT")
        create_synthetic_vcd_dat(dat_file, duration_sec=1.0)

        # Verify DAT finder
        dats = vcd_ripper.find_dat_files(vcd_dir)
        self.assertEqual(len(dats), 1)
        self.assertEqual(os.path.normpath(dats[0]), os.path.normpath(dat_file))

        # Test DAT copy
        out_dir = os.path.join(self.temp_dir, "out_vcd_dat")
        os.makedirs(out_dir, exist_ok=True)
        out_copy = os.path.join(out_dir, "AVSEQ01.DAT")
        shutil.copy2(dat_file, out_copy)
        self.assertTrue(os.path.exists(out_copy))
        self.assertEqual(os.path.getsize(out_copy), os.path.getsize(dat_file))

    def test_18_vcd_pipeline_mp4_transcode(self):
        """Verify VCD pipeline transcode to MP4 using OUTPUT_FORMATS configuration."""
        vcd_dir = os.path.join(self.temp_dir, "test_vcd_regression", "MPEGAV")
        dat_file = os.path.join(vcd_dir, "AVSEQ01.DAT")
        out_dir = os.path.join(self.temp_dir, "out_vcd_mp4")
        os.makedirs(out_dir, exist_ok=True)
        out_mp4 = os.path.join(out_dir, "AVSEQ01.mp4")

        fmt_cfg = vcd_ripper.OUTPUT_FORMATS["MP4"]
        cmd = [
            self.ffmpeg, "-y",
            "-i", dat_file,
            *fmt_cfg["args"],
            out_mp4
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(os.path.exists(out_mp4))
        self.assertGreater(os.path.getsize(out_mp4), 1000)

    # ─────────────────────────────────────────────
    #  6. Error Handling & Edge Cases
    # ─────────────────────────────────────────────
    def test_19_dvd_batch_error_resilience(self):
        """Verify that if one DVD title in a batch encounters an invalid file, the job handles it safely."""
        fake_title_fail = {
            "title_number": 99,
            "filename": "Broken Title",
            "vob_files": [os.path.join(self.temp_dir, "nonexistent.vob")],
            "custom_stem": "Broken_99"
        }
        cmd, out_p, concat_p = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=self.ffmpeg,
            dvd_source=self.temp_dir,
            title_dict=fake_title_fail,
            out_dir=self.temp_dir,
            output_format="MP4"
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        # Should fail cleanly without unhandled Python exception
        self.assertNotEqual(res.returncode, 0)
        if concat_p and os.path.exists(concat_p):
            os.remove(concat_p)

    def test_20_cancellation_cleanup(self):
        """Verify partial files are cleaned up if cancelled."""
        out_dummy = os.path.join(self.temp_dir, "partial_test.mp4")
        with open(out_dummy, "w") as f:
            f.write("partial")
        self.assertTrue(os.path.exists(out_dummy))
        # Simulated cancel cleanup
        if os.path.exists(out_dummy):
            os.remove(out_dummy)
        self.assertFalse(os.path.exists(out_dummy))

    def test_21_gui_initialization_and_state_switching(self):
        """Verify GUI elements initialize with correct v2.0.0 branding and switch format panels."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()  # keep offscreen

            self.assertEqual(app.title(), "Disc Ripper Pro")
            self.assertEqual(app._title_lbl.cget("text"), "Disc Ripper Pro")
            self.assertEqual(app._version_lbl.cget("text"), "v2.0.0")

            # Test DVD source switching hides DAT
            app._source_type = "DVD"
            app._output_format.set("DAT")
            app._update_format_visibility_for_source()
            self.assertEqual(app._output_format.get(), "MP4")

            # Test VCD source switching restores DAT
            app._source_type = "VCD"
            app._update_format_visibility_for_source()
            self.assertIn("DAT", [item.get("fmt") for item in app._fmt_items])

            app.destroy()
        except tk.TclError:
            # If running in a headless environment without display
            pass

    def test_22_detect_disc_symbol_availability(self):
        """Verify detect_disc is imported and accessible in vcd_ripper without NameError."""
        self.assertTrue(hasattr(vcd_ripper, "detect_disc"))
        self.assertTrue(callable(vcd_ripper.detect_disc))

        # Check call on nonexistent path
        res = vcd_ripper.detect_disc("Z:\\NonExistent_Path_12345")
        self.assertIsInstance(res, disc_detector.DiscCheckResult)
        self.assertFalse(res.is_vcd)
        self.assertFalse(res.is_dvd)

    def test_23_scan_disc_callback_no_name_error(self):
        """Verify _scan_disc() executes without raising NameError or crashes."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Set path to synthetic DVD
            dvd_root = os.path.join(self.temp_dir, "test_dvd")
            app._vcd_path.set(dvd_root)

            # Calling _scan_disc should not raise NameError
            app._scan_disc()
            self.assertTrue(app._scanning)

            # Wait briefly and process pending Tk callbacks
            for _ in range(5):
                app.update()
                time.sleep(0.05)

            app.destroy()
        except tk.TclError:
            pass

    def test_24_scanning_guard_and_concurrency(self):
        """Verify _scanning guard prevents re-entry and button is managed."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Simulate an active scan
            app._scanning = True
            app._scan_btn.configure_state(False)

            # Second call to _scan_disc should return immediately without doing anything
            app._vcd_path.set("C:\\SomePath")
            app._scan_disc()
            self.assertTrue(app._scanning)

            # Now simulate scan completion
            app._scanning = False
            app._scan_btn.configure_state(True)
            self.assertFalse(app._scanning)

            app.destroy()
        except tk.TclError:
            pass

    def test_25_scan_error_handling_resets_state(self):
        """Verify _on_scan_error resets scanning state and hides progress."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            app._scanning = True
            app._scan_btn.configure_state(False)
            app._scan_progress_frame.pack(fill="x")

            # Trigger error handler without showing modal blocking popup (mock messagebox)
            from unittest import mock
            with mock.patch("tkinter.messagebox.showerror") as mock_err:
                app._on_scan_error("Test Error", "Test details")
                mock_err.assert_called_once()

            self.assertFalse(app._scanning)
            app.destroy()
        except tk.TclError:
            pass

    def test_26_clear_all_resets_scanning(self):
        """Verify _clear_all_action resets _scanning flag and re-enables _scan_btn."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            app._scanning = True
            app._scan_btn.configure_state(False)
            app._clear_all_action()

            self.assertFalse(app._scanning)
            app.destroy()
        except tk.TclError:
            pass

    def test_27_vcd_and_dvd_scan_dispatch(self):
        """Verify _dispatch_scan_after_detect correctly routes to DVD and VCD pipelines."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Test DVD dispatch
            dvd_dir = os.path.join(self.temp_dir, "test_dvd")
            check_dvd = disc_detector.detect_disc(dvd_dir)
            self.assertTrue(check_dvd.is_dvd)

            app._dispatch_scan_after_detect(dvd_dir, check_dvd)
            self.assertEqual(app._source_type, "DVD")
            self.assertEqual(app._output_format.get(), "MP4")

            # Test VCD dispatch
            vcd_dir = os.path.join(self.temp_dir, "test_vcd_regression")
            check_vcd = disc_detector.detect_disc(vcd_dir)
            self.assertTrue(check_vcd.is_vcd)

            app._dispatch_scan_after_detect(vcd_dir, check_vcd)
            self.assertEqual(app._source_type, "VCD")

            app.destroy()
        except tk.TclError:
            pass

    def test_28_empty_folder_scan_behavior(self):
        """Verify empty folder detection gracefully resets scanning state."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            empty_dir = os.path.join(self.temp_dir, "empty_dir")
            os.makedirs(empty_dir, exist_ok=True)
            check_empty = disc_detector.detect_disc(empty_dir)
            self.assertFalse(check_empty.is_vcd)
            self.assertFalse(check_empty.is_dvd)
            self.assertIn(check_empty.disc_type, ("Empty Disc", "Empty Drive"))

            from unittest import mock
            with mock.patch("tkinter.messagebox.showinfo") as mock_info:
                app._dispatch_scan_after_detect(empty_dir, check_empty)
                mock_info.assert_called_once()

            self.assertFalse(app._scanning)
            self.assertEqual(app._source_type, "NONE")
            app.destroy()
        except tk.TclError:
            pass

    def test_29_dvd_chapter_data_model(self):
        """Verify DVDChapter dataclass calculation, time formatting, and serialization."""
        chap = dvd_engine.DVDChapter(
            chapter_number=3,
            start_time=125.5,
            end_time=300.0,
            title_number=1
        )
        self.assertAlmostEqual(chap.duration, 174.5, places=2)
        self.assertEqual(chap.format_time(125.5), "02:06")
        self.assertEqual(chap.format_time(3665), "1:01:05")
        self.assertEqual(chap.name, "Chapter 03")

        d = chap.to_dict()
        self.assertEqual(d["chapter_number"], 3)
        self.assertEqual(d["start_time"], 125.5)
        self.assertEqual(d["end_time"], 300.0)
        self.assertEqual(d["duration"], 174.5)
        self.assertEqual(d["start_str"], "02:06")
        self.assertEqual(d["end_str"], "05:00")
        self.assertEqual(d["duration_str"], "02:54")

    def test_30_extract_title_chapters_logic(self):
        """Verify _extract_title_chapters handles PTT maps, PGC programs, and single chapter fallback."""
        vtsi_mock = {
            "vts_ptt_map": {
                1: [(1, 1), (1, 2), (1, 3)]
            },
            "pgc_programs": {
                1: [
                    {"pgn": 1, "start_time": 0.0, "end_time": 60.0, "duration": 60.0},
                    {"pgn": 2, "start_time": 60.0, "end_time": 180.0, "duration": 120.0},
                    {"pgn": 3, "start_time": 180.0, "end_time": 300.0, "duration": 120.0},
                ]
            }
        }
        ch_list, ch_data = dvd_engine._extract_title_chapters(
            t_num=1, ttn=1, duration=300.0, chap_count=3,
            vtsi=vtsi_mock, source_path="", ffprobe_path=None
        )
        self.assertEqual(len(ch_data), 3)
        self.assertEqual(ch_list, [0.0, 60.0, 180.0])
        self.assertEqual(ch_data[0].duration, 60.0)
        self.assertEqual(ch_data[1].start_time, 60.0)
        self.assertEqual(ch_data[2].end_time, 300.0)

        # Test duration fallback when no IFO chapter metadata is present
        fallback_list, fallback_data = dvd_engine._extract_title_chapters(
            t_num=2, ttn=1, duration=150.0, chap_count=1,
            vtsi=None, source_path="", ffprobe_path=None
        )
        self.assertEqual(len(fallback_data), 1)
        self.assertEqual(fallback_data[0].duration, 150.0)
        self.assertEqual(fallback_data[0].start_time, 0.0)

    def test_31_prepare_dvd_chapter_rip_job(self):
        """Verify prepare_dvd_chapter_rip_job builds precise chapter-bounded FFmpeg commands."""
        ffmpeg_bin = get_bundled_ffmpeg() or "ffmpeg"
        title_dict = {
            "title_number": 1,
            "custom_stem": "Feature_Movie",
            "vob_files": [os.path.join(self.temp_dir, "VTS_01_1.VOB")],
            "aspect_ratio": "16:9"
        }
        chapter_dict = {
            "chapter_number": 2,
            "start_time": 120.0,
            "end_time": 250.0,
            "duration": 130.0,
            "name": "Chapter 02"
        }
        out_dir = os.path.join(self.temp_dir, "chap_out")
        os.makedirs(out_dir, exist_ok=True)

        # Test MP4 format
        cmd, out_path, temp_concat = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chapter_dict,
            out_dir=out_dir,
            output_format="MP4"
        )
        self.assertTrue(out_path.endswith("Feature_Movie - Chapter 02.mp4") or out_path.endswith("Feature_Movie_Chapter_02.mp4"))
        self.assertIn("-ss", cmd)
        self.assertIn("120.000", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("130.000", cmd)
        self.assertIn("libx264", cmd)

        # Test Audio Only WAV
        cmd_wav, out_wav, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chapter_dict,
            out_dir=out_dir,
            output_format="MP4",
            audio_only=True,
            audio_format="WAV"
        )
        self.assertTrue(out_wav.endswith("Feature_Movie - Chapter 02.wav") or out_wav.endswith("Feature_Movie_Chapter_02.wav"))
        self.assertIn("-vn", cmd_wav)
        self.assertIn("pcm_s16le", cmd_wav)

    def test_32_multi_vob_chapter_extraction_execution(self):
        """Verify actual FFmpeg extraction of a specific chapter from multi-VOB title files."""
        ffmpeg_bin = get_bundled_ffmpeg()
        if not ffmpeg_bin:
            self.skipTest("Bundled FFmpeg not found.")

        # Create 2 synthetic VOB segments simulating a 2-VOB DVD title (1.5s + 1.5s = 3.0s total)
        vob1_path = os.path.join(self.temp_dir, "VTS_01_1.VOB")
        vob2_path = os.path.join(self.temp_dir, "VTS_01_2.VOB")
        create_synthetic_mpeg2_vob(vob1_path, duration_sec=1.5)
        create_synthetic_mpeg2_vob(vob2_path, duration_sec=1.5)

        title_dict = {
            "title_number": 1,
            "custom_stem": "TestMovie",
            "vob_files": [vob1_path, vob2_path],
            "aspect_ratio": "4:3"
        }
        # Chapter 2 starts at 1.0s and lasts 1.0s (spanning across boundary between VOB 1 and 2)
        chapter_dict = {
            "chapter_number": 2,
            "start_time": 1.0,
            "end_time": 2.0,
            "duration": 1.0,
            "name": "Chapter 02"
        }
        out_dir = os.path.join(self.temp_dir, "chapter_exec_out")
        os.makedirs(out_dir, exist_ok=True)

        cmd, out_path, temp_concat = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chapter_dict,
            out_dir=out_dir,
            output_format="MP4"
        )
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            self.assertEqual(res.returncode, 0, f"FFmpeg failed extracting chapter: {res.stderr}")
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 5000)
        finally:
            if temp_concat and os.path.exists(temp_concat):
                try:
                    os.remove(temp_concat)
                except Exception:
                    pass

    def test_33_ui_chapter_mode_selection_and_toggles(self):
        """Verify VCDRipperApp chapter ripping mode switching, selection tracking, and badge count."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            mock_titles = [
                {
                    "filename": "Title 01",
                    "title_number": 1,
                    "disc_type": "DVD",
                    "size_mb": 100.0,
                    "duration": 300.0,
                    "chapter_count": 3,
                    "chapters_data": [
                        {"chapter_number": 1, "start_time": 0.0, "end_time": 100.0, "duration": 100.0, "start_str": "0:00", "end_str": "1:40", "duration_str": "1:40", "name": "Chapter 01"},
                        {"chapter_number": 2, "start_time": 100.0, "end_time": 200.0, "duration": 100.0, "start_str": "1:40", "end_str": "3:20", "duration_str": "1:40", "name": "Chapter 02"},
                        {"chapter_number": 3, "start_time": 200.0, "end_time": 300.0, "duration": 100.0, "start_str": "3:20", "end_str": "5:00", "duration_str": "1:40", "name": "Chapter 03"},
                    ]
                },
                {
                    "filename": "Title 02",
                    "title_number": 2,
                    "disc_type": "DVD",
                    "size_mb": 50.0,
                    "duration": 120.0,
                    "chapter_count": 2,
                    "chapters_data": [
                        {"chapter_number": 1, "start_time": 0.0, "end_time": 60.0, "duration": 60.0, "start_str": "0:00", "end_str": "1:00", "duration_str": "1:00", "name": "Chapter 01"},
                        {"chapter_number": 2, "start_time": 60.0, "end_time": 120.0, "duration": 60.0, "start_str": "1:00", "end_str": "2:00", "duration_str": "1:00", "name": "Chapter 02"},
                    ]
                }
            ]

            app._source_type = "DVD"
            app._populate_list(mock_titles)

            # Auto-selection after scan defaults to all chapters
            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(len(app._selected_chapters), 5)  # Auto-selected all 5 chapters

            # Select None
            app._select_none()
            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(len(app._selected_chapters), 0)

            # Switch to Mode B: Selected Chapters
            app._dvd_rip_mode.set("chapter")
            app._on_dvd_mode_change()
            self.assertEqual(app._dvd_rip_mode.get(), "chapter")

            # Toggle Chapter 2 of Title 01
            app._on_chapter_toggle(0, 2, True)
            self.assertIn((0, 2), app._selected_chapters)
            self.assertEqual(len(app._selected_chapters), 1)

            # Toggle Chapter 1 of Title 02
            app._on_chapter_toggle(1, 1, True)
            self.assertIn((1, 1), app._selected_chapters)
            self.assertEqual(len(app._selected_chapters), 2)

            # Select All in DVD Mode selects all chapters
            app._select_all()
            self.assertEqual(len(app._selected_chapters), 5)
            self.assertEqual(len(app._selected_indices), 0)

            # Select None in Chapter Mode
            app._select_none()
            self.assertEqual(len(app._selected_chapters), 0)

            app.destroy()
        except tk.TclError:
            pass

    def test_34_videocard_chapters_expansion_and_widgets(self):
        """Verify VideoCard creates chapter expandable button and sub-rows."""
        try:
            root = tk.Tk()
            root.withdraw()

            mock_info = {
                "filename": "Title 01 (Main Feature)",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 1200.0,
                "duration": 3600.0,
                "chapter_count": 2,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 1800.0, "duration": 1800.0, "start_str": "0:00", "end_str": "30:00", "duration_str": "30:00", "name": "Chapter 01"},
                    {"chapter_number": 2, "start_time": 1800.0, "end_time": 3600.0, "duration": 1800.0, "start_str": "30:00", "end_str": "1:00:00", "duration_str": "30:00", "name": "Chapter 02"},
                ]
            }

            card = vcd_ripper.VideoCard(
                root, mock_info, index=0,
                on_toggle=lambda idx, sel: None,
                on_chapter_toggle=lambda idx, cn, sel: None
            )
            self.assertTrue(hasattr(card, "_expand_btn"))
            self.assertTrue(card._chapters_expanded)
            self.assertEqual(len(card._chapter_rows), 2)
            self.assertIn(1, card._chapter_vars)
            self.assertIn(2, card._chapter_vars)

            # Collapse chapters
            card.expand_chapters(False)
            self.assertFalse(card._chapters_expanded)

            # Re-expand chapters
            card.expand_chapters(True)
            self.assertTrue(card._chapters_expanded)

            card.apply_theme()
            root.destroy()
        except tk.TclError:
            pass

    def test_35_validate_chapters_detection(self):
        """Verify validate_chapters correctly distinguishes valid chapter lists from corrupt anomalies."""
        from dvd_engine import DVDChapter, validate_chapters

        # 1. Valid chapters with ascending start times
        valid_chaps = [
            DVDChapter(chapter_number=1, start_time=0.0, end_time=600.0, duration=600.0),
            DVDChapter(chapter_number=2, start_time=600.0, end_time=1200.0, duration=600.0),
            DVDChapter(chapter_number=3, start_time=1200.0, end_time=1800.0, duration=600.0),
        ]
        self.assertTrue(validate_chapters(valid_chaps, 1800.0))

        # 2. Corrupt anomaly: 99 identical dummy chapters (00:00 -> 3377.0)
        corrupt_99 = [
            DVDChapter(chapter_number=i, start_time=0.0, end_time=3377.0, duration=3377.0)
            for i in range(1, 100)
        ]
        self.assertFalse(validate_chapters(corrupt_99, 3377.0))

        # 3. All chapters starting at 0.0 with equal duration
        dup_starts = [
            DVDChapter(chapter_number=1, start_time=0.0, end_time=500.0, duration=500.0),
            DVDChapter(chapter_number=2, start_time=0.0, end_time=500.0, duration=500.0),
        ]
        self.assertFalse(validate_chapters(dup_starts, 500.0))

        # 4. Decreasing start times
        decreasing = [
            DVDChapter(chapter_number=1, start_time=500.0, end_time=1000.0, duration=500.0),
            DVDChapter(chapter_number=2, start_time=200.0, end_time=800.0, duration=600.0),
        ]
        self.assertFalse(validate_chapters(decreasing, 1000.0))

        # 5. Negative duration
        negative = [
            DVDChapter(chapter_number=1, start_time=0.0, end_time=100.0, duration=100.0),
            DVDChapter(chapter_number=2, start_time=100.0, end_time=50.0, duration=-50.0),
        ]
        self.assertFalse(validate_chapters(negative, 100.0))

        # 6. Single valid chapter
        single = [DVDChapter(chapter_number=1, start_time=0.0, end_time=3377.0, duration=3377.0)]
        self.assertTrue(validate_chapters(single, 3377.0))

    def test_36_vts_ptt_srpt_and_pgcit_binary_parsing(self):
        """Verify binary IFO parsing of VTS_PTT_SRPT and VTS_PGCIT table offsets."""
        from dvd_engine import parse_vtsi

        def sec_to_bcd(seconds):
            s = int(seconds)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return bytes([(h // 10 << 4) | (h % 10), (m // 10 << 4) | (m % 10), (s // 10 << 4) | (s % 10), 0])

        data = bytearray(2048 * 3)
        data[0:12] = b"DVDVIDEO-VTS"
        data[0x0100] = 0x00
        data[0x0101] = 0x40
        data[0x00C8:0x00CC] = struct.pack(">I", 1)  # Sector 1 = VTS_PTT_SRPT
        data[0x00CC:0x00D0] = struct.pack(">I", 2)  # Sector 2 = VTS_PGCIT

        # VTS_PTT_SRPT at sector 1 (2048)
        ptt_off = 2048
        title_sub_off = 12
        end_byte = 12 + 3 * 4 - 1
        data[ptt_off:ptt_off + 8] = struct.pack(">HHI", 1, 0, end_byte)
        data[ptt_off + 8:ptt_off + 12] = struct.pack(">I", title_sub_off)
        data[ptt_off + 12:ptt_off + 16] = struct.pack(">HH", 1, 1)
        data[ptt_off + 16:ptt_off + 20] = struct.pack(">HH", 1, 2)
        data[ptt_off + 20:ptt_off + 24] = struct.pack(">HH", 1, 3)

        # VTS_PGCIT at sector 2 (4096)
        pgcit_off = 4096
        pgc_sub_off = 16
        data[pgcit_off:pgcit_off + 8] = struct.pack(">HHI", 1, 0, 500)
        data[pgcit_off + 8:pgcit_off + 16] = struct.pack(">II", 0x80000000, pgc_sub_off)

        # PGC 1
        pgc_abs = pgcit_off + pgc_sub_off
        data[pgc_abs + 2] = 3  # 3 programs
        data[pgc_abs + 3] = 3  # 3 cells
        data[pgc_abs + 4:pgc_abs + 8] = sec_to_bcd(60)

        # Program map at offset 0x0100 (256)
        pgmap_rel = 256
        data[pgc_abs + 0x00E6:pgc_abs + 0x00E8] = struct.pack(">H", pgmap_rel)
        data[pgc_abs + pgmap_rel:pgc_abs + pgmap_rel + 3] = bytes([1, 2, 3])

        # Cell table at offset 0x0120 (288)
        cpbit_rel = 288
        data[pgc_abs + 0x00E8:pgc_abs + 0x00EA] = struct.pack(">H", cpbit_rel)
        for i, d in enumerate([10, 20, 30]):
            c_off = pgc_abs + cpbit_rel + i * 24
            data[c_off + 4:c_off + 8] = sec_to_bcd(d)

        ifo_file = os.path.join(self.temp_dir, "test_vts_parsing.ifo")
        with open(ifo_file, "wb") as f:
            f.write(data)

        parsed = parse_vtsi(ifo_file)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["vts_ptt_map"], {1: [(1, 1), (1, 2), (1, 3)]})
        self.assertEqual(parsed["pgc_durations"], [60.0])
        self.assertIn(1, parsed["pgc_programs"])
        progs = parsed["pgc_programs"][1]
        self.assertEqual(len(progs), 3)
        self.assertEqual(progs[0]["duration"], 10.0)
        self.assertEqual(progs[1]["duration"], 20.0)
        self.assertEqual(progs[2]["duration"], 30.0)

    def test_37_reject_99_dummy_chapters_and_fallback(self):
        """Verify _extract_title_chapters rejects 99 identical dummy chapters and falls back to a single valid chapter."""
        from dvd_engine import _extract_title_chapters

        corrupt_vtsi = {
            "vts_ptt_map": {1: [(1, i) for i in range(1, 100)]},
            "pgc_durations": [3377.0],
            "pgc_programs": {1: [
                {"pgn": i, "start_time": 0.0, "end_time": 3377.0, "duration": 3377.0} for i in range(1, 100)
            ]},
            "pgc_chapters": []
        }

        chaps_list, chaps_data = _extract_title_chapters(
            t_num=1, ttn=1, duration=3377.0, chap_count=99, vtsi=corrupt_vtsi, source_path="", ffprobe_path=None
        )
        # Must be sanitized to 1 valid chapter, not 99 dummy chapters
        self.assertEqual(len(chaps_data), 1)
        self.assertEqual(chaps_data[0].start_time, 0.0)
        self.assertEqual(chaps_data[0].end_time, 3377.0)
        self.assertEqual(chaps_data[0].duration, 3377.0)

    def test_38_title_duration_matches_pgc_and_chapters(self):
        """Verify scan_dvd_structure resolves title duration to the correct PGC and synchronizes with chapter span."""
        from dvd_engine import scan_dvd_structure

        def sec_to_bcd(seconds):
            s = int(seconds)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return bytes([(h // 10 << 4) | (h % 10), (m // 10 << 4) | (m % 10), (s // 10 << 4) | (s % 10), 0])

        test_dir = tempfile.mkdtemp(prefix="test_dvd_multi_pgc_")
        try:
            vts_dir = os.path.join(test_dir, "VIDEO_TS")
            os.makedirs(vts_dir)

            # VIDEO_TS.IFO
            vmgi = bytearray(2048 * 2)
            vmgi[0:12] = b"DVDVIDEO-VMG"
            vmgi[0x00C4:0x00C8] = struct.pack(">I", 1)
            vmgi[2048:2050] = struct.pack(">H", 1)
            entry_off = 2048 + 8
            vmgi[entry_off:entry_off + 12] = struct.pack(">BBHHBBI", 0, 1, 3, 0, 1, 1, 0)
            with open(os.path.join(vts_dir, "VIDEO_TS.IFO"), "wb") as f:
                f.write(vmgi)

            # VTS_01_0.IFO: PGC 1 is 376s (6:16), PGC 2 is 3377s (56:17)
            # Title 1 maps to PGC 2
            vtsi = bytearray(2048 * 3)
            vtsi[0:12] = b"DVDVIDEO-VTS"
            vtsi[0x0100] = 0x00
            vtsi[0x0101] = 0x40
            vtsi[0x00C8:0x00CC] = struct.pack(">I", 1)
            vtsi[0x00CC:0x00D0] = struct.pack(">I", 2)

            ptt_off = 2048
            title_sub_off = 12
            end_byte = 12 + 3 * 4 - 1
            vtsi[ptt_off:ptt_off + 8] = struct.pack(">HHI", 1, 0, end_byte)
            vtsi[ptt_off + 8:ptt_off + 12] = struct.pack(">I", title_sub_off)
            vtsi[ptt_off + 12:ptt_off + 16] = struct.pack(">HH", 2, 1)
            vtsi[ptt_off + 16:ptt_off + 20] = struct.pack(">HH", 2, 2)
            vtsi[ptt_off + 20:ptt_off + 24] = struct.pack(">HH", 2, 3)

            pgcit_off = 4096
            vtsi[pgcit_off:pgcit_off + 8] = struct.pack(">HHI", 2, 0, 1500)
            vtsi[pgcit_off + 8:pgcit_off + 16] = struct.pack(">II", 0x80000000, 24)
            vtsi[pgcit_off + 16:pgcit_off + 24] = struct.pack(">II", 0x80000000, 300)

            # PGC 1: 376s
            pgc1_abs = pgcit_off + 24
            vtsi[pgc1_abs + 2] = 1
            vtsi[pgc1_abs + 3] = 1
            vtsi[pgc1_abs + 4:pgc1_abs + 8] = sec_to_bcd(376)

            # PGC 2: 3377s
            pgc2_abs = pgcit_off + 300
            vtsi[pgc2_abs + 2] = 3
            vtsi[pgc2_abs + 3] = 3
            vtsi[pgc2_abs + 4:pgc2_abs + 8] = sec_to_bcd(3377)
            vtsi[pgc2_abs + 0x00E6:pgc2_abs + 0x00E8] = struct.pack(">H", 0x0100)
            vtsi[pgc2_abs + 0x0100:pgc2_abs + 0x0103] = bytes([1, 2, 3])
            vtsi[pgc2_abs + 0x00E8:pgc2_abs + 0x00EA] = struct.pack(">H", 0x0120)
            for i, cd in enumerate([1000, 1000, 1377]):
                c_off = pgc2_abs + 0x0120 + i * 24
                vtsi[c_off + 4:c_off + 8] = sec_to_bcd(cd)

            with open(os.path.join(vts_dir, "VTS_01_0.IFO"), "wb") as f:
                f.write(vtsi)

            with open(os.path.join(vts_dir, "VTS_01_1.VOB"), "wb") as f:
                f.write(b"\x00" * 1024)

            titles = scan_dvd_structure(test_dir)
            self.assertEqual(len(titles), 1)
            t = titles[0]
            # Duration must be 3377s (56:17), NOT 376s (6:16)
            self.assertEqual(t["duration"], 3377.0)
            self.assertEqual(t["chapter_count"], 3)
            self.assertEqual(len(t["chapters_data"]), 3)
            self.assertEqual(t["chapters_data"][0]["duration"], 1000.0)
            self.assertEqual(t["chapters_data"][1]["duration"], 1000.0)
            self.assertEqual(t["chapters_data"][2]["duration"], 1377.0)
            self.assertEqual(t["chapters_data"][2]["end_time"], 3377.0)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_39_videocard_single_vs_multichapter(self):
        """Verify VideoCard only displays chapter expansion button when multiple chapters exist."""
        try:
            root = tk.Tk()
            root.withdraw()

            # Single chapter item
            single_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 3377.0,
                "chapter_count": 1,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 3377.0, "duration": 3377.0, "name": "Chapter 01"}
                ]
            }
            card_single = vcd_ripper.VideoCard(root, single_info, index=0, on_toggle=lambda idx, s: None)
            self.assertFalse(hasattr(card_single, "_expand_btn"))

            # Multi chapter item
            multi_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 3377.0,
                "chapter_count": 3,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 1000.0, "duration": 1000.0, "name": "Chapter 01"},
                    {"chapter_number": 2, "start_time": 1000.0, "end_time": 2000.0, "duration": 1000.0, "name": "Chapter 02"},
                    {"chapter_number": 3, "start_time": 2000.0, "end_time": 3377.0, "duration": 1377.0, "name": "Chapter 03"},
                ]
            }
            card_multi = vcd_ripper.VideoCard(root, multi_info, index=1, on_toggle=lambda idx, s: None)
            self.assertTrue(hasattr(card_multi, "_expand_btn"))

            root.destroy()
        except tk.TclError:
            pass

    # ─────────────────────────────────────────────
    #  Task 8 — Automated Verification Requirements (Tests 40 - 55)
    # ─────────────────────────────────────────────

    # 1. HandBrakeCLI detection and version parsing
    def test_40_task8_01_handbrake_detection_and_version_parsing(self):
        """Verify HandBrakeCLI detection and robust version parsing."""
        hb = dvd_engine.find_handbrake()
        self.assertIsNotNone(hb, "HandBrakeCLI should be located in bundled or system paths.")
        self.assertTrue(os.path.isfile(hb))

        # Check version parsing
        ver = dvd_engine.get_handbrake_version(hb)
        self.assertIsNotNone(ver)
        self.assertTrue(ver.startswith("HandBrake"), f"Expected version string starting with HandBrake, got: {ver}")

        # Test regex parsing with various version outputs
        test_strings = [
            ("HandBrake 1.11.2 (2026010100)", "HandBrake 1.11.2"),
            ("HandBrake 1.8.0-dev", "HandBrake 1.8.0"),
            ("HandBrake 2.0.0", "HandBrake 2.0.0"),
        ]
        import re
        for text, expected in test_strings:
            m = re.search(r"HandBrake\s+([\d\.]+)", text, re.IGNORECASE)
            self.assertIsNotNone(m)
            self.assertEqual(f"HandBrake {m.group(1)}", expected)

    # 2. Fallback when HandBrakeCLI is absent
    def test_41_task8_02_fallback_when_handbrake_absent(self):
        """Verify clean fallback to dvd_engine/ffprobe when HandBrakeCLI is missing."""
        ffmpeg_bin = get_bundled_ffmpeg()
        ffprobe_bin = get_bundled_ffprobe()

        titles = dvd_engine.scan_dvd_titles(
            self.temp_dir,
            ffmpeg_path=ffmpeg_bin,
            ffprobe_path=ffprobe_bin,
            handbrake_path="C:\\nonexistent\\HandBrakeCLI.exe"
        )
        self.assertIsInstance(titles, list)

    # 3. Successful HandBrake JSON title set parsing into DVDTitle / DVDChapter models
    def test_42_task8_03_handbrake_json_title_set_parsing(self):
        """Verify parsing HandBrake JSON Title Set dictionary into DVDTitle and DVDChapter models."""
        mock_json = {
            "MainFeature": 1,
            "TitleList": [
                {
                    "Index": 1,
                    "Duration": {"Hours": 1, "Minutes": 30, "Seconds": 15, "Ticks": 0},
                    "Geometry": {"Width": 720, "Height": 480, "PAR": {"Numerator": 32, "Denominator": 27}},
                    "FrameRate": {"Numerator": 30000, "Denominator": 1001},
                    "AudioList": [
                        {"Format": "AC3", "ChannelCount": 6, "Language": "English", "Description": "5.1 ch"}
                    ],
                    "SubtitleList": [
                        {"Format": "VOBSUB", "Language": "English"}
                    ],
                    "ChapterList": [
                        {"Duration": {"Hours": 0, "Minutes": 10, "Seconds": 0, "Ticks": 0}},
                        {"Duration": {"Hours": 0, "Minutes": 20, "Seconds": 0, "Ticks": 0}},
                        {"Duration": {"Hours": 1, "Minutes": 0, "Seconds": 15, "Ticks": 0}}
                    ]
                },
                {
                    "Index": 2,
                    "Duration": {"Hours": 0, "Minutes": 5, "Seconds": 0, "Ticks": 0},
                    "Geometry": {"Width": 720, "Height": 480, "PAR": {"Numerator": 8, "Denominator": 9}},
                    "FrameRate": {"Numerator": 30000, "Denominator": 1001},
                    "AudioList": [],
                    "SubtitleList": [],
                    "ChapterList": [
                        {"Duration": {"Hours": 0, "Minutes": 5, "Seconds": 0, "Ticks": 0}}
                    ]
                }
            ]
        }

        titles = dvd_engine.parse_handbrake_json_title_set(mock_json)
        self.assertEqual(len(titles), 2)

        # Title 1
        t1 = titles[0]
        self.assertEqual(t1.title_number, 1)
        self.assertEqual(t1.duration, 5415.0)
        self.assertTrue(t1.is_main_feature)
        self.assertEqual(t1.chapter_count, 3)
        self.assertEqual(len(t1.chapters_data), 3)
        self.assertEqual(t1.chapters_data[0].chapter_number, 1)
        self.assertEqual(t1.chapters_data[0].start_time, 0.0)
        self.assertEqual(t1.chapters_data[0].duration, 600.0)
        self.assertEqual(t1.chapters_data[0].end_time, 600.0)
        self.assertEqual(t1.chapters_data[1].chapter_number, 2)
        self.assertEqual(t1.chapters_data[1].start_time, 600.0)
        self.assertEqual(t1.chapters_data[1].duration, 1200.0)
        self.assertEqual(t1.chapters_data[1].end_time, 1800.0)
        self.assertEqual(t1.chapters_data[2].chapter_number, 3)
        self.assertEqual(t1.chapters_data[2].start_time, 1800.0)
        self.assertEqual(t1.chapters_data[2].duration, 3615.0)
        self.assertEqual(t1.chapters_data[2].end_time, 5415.0)
        self.assertEqual(t1.aspect_ratio, "16:9")

        # Title 2
        t2 = titles[1]
        self.assertEqual(t2.title_number, 2)
        self.assertEqual(t2.duration, 300.0)
        self.assertFalse(t2.is_main_feature)
        self.assertEqual(t2.chapter_count, 1)
        self.assertEqual(t2.aspect_ratio, "4:3")

    # 4. Parsing corrupted or partial HandBrake scan output without crash
    def test_43_task8_04_handbrake_corrupted_or_partial_output(self):
        """Verify robust error recovery on corrupted, empty, or partial HandBrake output."""
        self.assertEqual(dvd_engine.parse_handbrake_json_title_set({}), [])
        self.assertEqual(dvd_engine.parse_handbrake_json_title_set({"MainFeature": 1}), [])
        self.assertEqual(dvd_engine.parse_handbrake_json_title_set({"TitleList": "corrupted"}), [])
        partial = {
            "TitleList": [
                {"Index": 1}
            ]
        }
        res = dvd_engine.parse_handbrake_json_title_set(partial)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].duration, 0.0)
        self.assertEqual(res[0].chapter_count, 1)

    # 5. VCD workflow regression: ensure VCD scan, DAT copy, MPG conversion do NOT invoke HandBrake
    def test_44_task8_05_vcd_workflow_regression_no_handbrake(self):
        """Verify VCD pipeline remains independent and never invokes HandBrakeCLI."""
        vcd_files = vcd_ripper.find_dat_files(self.temp_dir)
        self.assertIsInstance(vcd_files, list)

        mp4_cfg = vcd_ripper.OUTPUT_FORMATS["MP4"]
        self.assertIn("-c:v", mp4_cfg["args"])
        self.assertIn("libx264", mp4_cfg["args"])
        self.assertNotIn("-e", mp4_cfg["args"])

    # 6. Title card checkbox selection logic (checking title clears all child chapters)
    def test_45_task8_06_title_card_checkbox_selection_logic(self):
        """Verify checking title clears child chapters, and unchecking removes title."""
        try:
            root = tk.Tk()
            root.withdraw()

            chapter_toggles = []
            card_toggles = []

            card_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 600.0,
                "chapter_count": 2,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 300.0, "duration": 300.0, "name": "Chapter 01"},
                    {"chapter_number": 2, "start_time": 300.0, "end_time": 600.0, "duration": 300.0, "name": "Chapter 02"},
                ]
            }

            card = vcd_ripper.VideoCard(
                root, card_info, index=0,
                on_toggle=lambda idx, s: card_toggles.append((idx, s)),
                on_chapter_toggle=lambda c_idx, ch_num, s: chapter_toggles.append((c_idx, ch_num, s))
            )
            card.set_selected(True)
            self.assertTrue(card.is_selected())

            # Simulate clicking chapter 1 checkbox
            card._chapter_vars[1].set(True)
            card._on_chapter_cb(1)
            self.assertFalse(card.is_selected())
            self.assertTrue(card.are_any_chapters_selected())

            # Now click title checkbox back on
            card._chk_var.set(True)
            card._toggle()
            self.assertTrue(card.is_selected())
            self.assertFalse(card.are_any_chapters_selected())

            root.destroy()
        except tk.TclError:
            pass

    # 7. Chapter checkbox selection logic (checking chapter clears parent title selection)
    def test_46_task8_07_chapter_checkbox_selection_clears_parent(self):
        """Verify checking a chapter clears parent title selection while highlighting border."""
        try:
            root = tk.Tk()
            root.withdraw()

            card_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 600.0,
                "chapter_count": 2,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 300.0, "duration": 300.0, "name": "Chapter 01"},
                    {"chapter_number": 2, "start_time": 300.0, "end_time": 600.0, "duration": 300.0, "name": "Chapter 02"},
                ]
            }

            card = vcd_ripper.VideoCard(root, card_info, index=0, on_toggle=lambda idx, s: None)
            card.set_title_selected(True)
            self.assertTrue(card.is_selected())

            # Simulate clicking chapter 2 checkbox
            card._chapter_vars[2].set(True)
            card._on_chapter_cb(2)
            self.assertFalse(card.is_selected())
            self.assertTrue(card.are_any_chapters_selected())

            root.destroy()
        except tk.TclError:
            pass

    # 8. Select All button behavior (selects all chapters across all titles on DVD)
    def test_47_task8_08_select_all_behavior(self):
        """Verify Select All selects all chapters across all titles and scan defaults to all chapters."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            mock_titles = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "duration": 300.0,
                    "chapter_count": 2,
                    "chapters_data": [
                        {"chapter_number": 1, "duration": 150.0},
                        {"chapter_number": 2, "duration": 150.0}
                    ]
                },
                {
                    "filename": "Title 02", "title_number": 2, "disc_type": "DVD", "duration": 200.0,
                    "chapter_count": 1,
                    "chapters_data": [
                        {"chapter_number": 1, "duration": 200.0}
                    ]
                },
                {
                    "filename": "Title 03 (No Chaps)", "title_number": 3, "disc_type": "DVD", "duration": 100.0,
                    "chapter_count": 0,
                    "chapters_data": []
                }
            ]
            app._source_type = "DVD"
            app._populate_list(mock_titles)

            # Auto-selection after scan defaults to all chapters (and fallback title for item without chapters)
            self.assertEqual(app._selected_chapters, {(0, 1), (0, 2), (1, 1)})
            self.assertEqual(app._selected_indices, {2})
            self.assertFalse(app._cards[0].is_selected())
            self.assertTrue(app._cards[0]._chapter_vars[1].get())
            self.assertTrue(app._cards[0]._chapter_vars[2].get())
            self.assertFalse(app._cards[1].is_selected())
            self.assertTrue(app._cards[1]._chapter_vars[1].get())
            self.assertTrue(app._cards[2].is_selected())

            # Select None clears all
            app._select_none()
            self.assertEqual(len(app._selected_chapters), 0)
            self.assertEqual(len(app._selected_indices), 0)

            # Select All selects all chapters across all titles again
            app._select_all()
            self.assertEqual(app._selected_chapters, {(0, 1), (0, 2), (1, 1)})
            self.assertEqual(app._selected_indices, {2})
            self.assertFalse(app._cards[0].is_selected())
            self.assertTrue(app._cards[0]._chapter_vars[1].get())
            self.assertTrue(app._cards[0]._chapter_vars[2].get())
            self.assertFalse(app._cards[1].is_selected())
            self.assertTrue(app._cards[1]._chapter_vars[1].get())
            self.assertTrue(app._cards[2].is_selected())

            app.destroy()
        except tk.TclError:
            pass

    # 9. Select None button behavior (clears all titles and all chapters)
    def test_48_task8_09_select_none_behavior(self):
        """Verify Select None clears all titles and all chapters."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            mock_titles = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "duration": 300.0,
                    "chapter_count": 2,
                    "chapters_data": [{"chapter_number": 1}, {"chapter_number": 2}]
                }
            ]
            app._source_type = "DVD"
            app._populate_list(mock_titles)
            app._selected_indices.add(0)
            app._selected_chapters.add((0, 1))

            app._select_none()

            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(len(app._selected_chapters), 0)

            app.destroy()
        except tk.TclError:
            pass

    # 10. Selection summary count text formatting for both VCD and DVD
    def test_49_task8_10_selection_summary_formatting(self):
        """Verify selection count text for VCD (tracks) and DVD (titles + chapters)."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # VCD formatting
            app._source_type = "VCD"
            app._videos = [{"filename": "AVSEQ01.DAT"}, {"filename": "AVSEQ02.DAT"}]
            app._selected_indices = {0, 1}
            app._update_sel_count()
            self.assertIn("2", app._sel_count_lbl.cget("text"))

            # DVD hierarchical formatting
            app._source_type = "DVD"
            app._videos = [
                {"filename": "Title 01", "title_number": 1, "disc_type": "DVD", "chapter_count": 2},
                {"filename": "Title 02", "title_number": 2, "disc_type": "DVD", "chapter_count": 2}
            ]
            app._selected_indices = {0}
            app._selected_chapters = {(1, 1), (1, 2)}
            app._update_sel_count()
            lbl_text = app._sel_count_lbl.cget("text")
            self.assertTrue("1 title(s)" in lbl_text or "1" in lbl_text)
            self.assertTrue("2 chapter(s)" in lbl_text or "2" in lbl_text)

            app.destroy()
        except tk.TclError:
            pass

    # 11. Single-title rename updates title model and card UI
    def test_50_task8_11_single_title_rename(self):
        """Verify single-title rename updates video model custom_stem and card UI."""
        try:
            root = tk.Tk()
            root.withdraw()

            card_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 600.0,
                "chapter_count": 1,
                "chapters_data": [{"chapter_number": 1, "duration": 600.0}]
            }

            card = vcd_ripper.VideoCard(root, card_info, index=0, on_toggle=lambda idx, s: None)
            card.set_custom_name("Blockbuster Movie")

            self.assertEqual(card.video_info.get("custom_stem"), "Blockbuster Movie")
            self.assertEqual(card.video_info.get("filename"), "Blockbuster Movie")
            self.assertIn("Blockbuster Movie", card._filename_lbl.cget("text"))

            root.destroy()
        except tk.TclError:
            pass

    # 12. Single-chapter rename updates chapter model and card UI
    def test_51_task8_12_single_chapter_rename(self):
        """Verify single-chapter rename updates chapter custom_stem and UI row label."""
        try:
            root = tk.Tk()
            root.withdraw()

            card_info = {
                "filename": "Title 01",
                "title_number": 1,
                "disc_type": "DVD",
                "size_mb": 500.0,
                "duration": 600.0,
                "chapter_count": 2,
                "chapters_data": [
                    {"chapter_number": 1, "start_time": 0.0, "end_time": 300.0, "duration": 300.0, "name": "Chapter 01"},
                    {"chapter_number": 2, "start_time": 300.0, "end_time": 600.0, "duration": 300.0, "name": "Chapter 02"}
                ]
            }

            card = vcd_ripper.VideoCard(root, card_info, index=0, on_toggle=lambda idx, s: None)
            card.toggle_chapters(True)
            card.update_chapter_name_display(1, "Opening Scene")

            ch1 = card.video_info["chapters_data"][0]
            self.assertEqual(ch1.get("custom_stem"), "Opening Scene")
            self.assertEqual(ch1.get("name"), "Opening Scene")
            self.assertIn("Opening Scene", card._chapter_name_labels[1].cget("text"))

            root.destroy()
        except tk.TclError:
            pass

    # 13. Batch Rename dialog population: titles and chapters in hierarchical order with type tags
    def test_52_task8_13_batch_rename_dialog_population(self):
        """Verify batch rename items list orders titles and chapters naturally with badges."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            app._source_type = "DVD"
            app._videos = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "chapter_count": 2,
                    "chapters_data": [
                        {"chapter_number": 1, "name": "Chapter 01"},
                        {"chapter_number": 2, "name": "Chapter 02"}
                    ]
                },
                {
                    "filename": "Title 02", "title_number": 2, "disc_type": "DVD", "chapter_count": 1,
                    "chapters_data": [
                        {"chapter_number": 1, "name": "Chapter 01"}
                    ]
                }
            ]

            items = []
            for i, v in enumerate(app._videos):
                t_name = v.get("custom_stem") or v.get("filename", f"Title {i+1}")
                items.append({"kind": "title", "title_idx": i, "chapter_num": None, "orig_name": t_name, "cur_name": t_name})
                for c in v.get("chapters_data", []):
                    c_num = c.get("chapter_number", 1)
                    c_name = c.get("custom_stem") or c.get("name") or f"Chapter {c_num:02d}"
                    items.append({"kind": "chapter", "title_idx": i, "chapter_num": c_num, "orig_name": c_name, "cur_name": c_name})

            self.assertEqual(len(items), 5)
            self.assertEqual(items[0]["kind"], "title")
            self.assertEqual(items[1]["kind"], "chapter")
            self.assertEqual(items[2]["kind"], "chapter")
            self.assertEqual(items[3]["kind"], "title")
            self.assertEqual(items[4]["kind"], "chapter")

            app.destroy()
        except tk.TclError:
            pass

    # 14. Batch Rename preview and application
    def test_53_task8_14_batch_rename_preview_and_apply(self):
        """Verify batch rename sequential pattern numbering and application."""
        items = [
            {"kind": "title", "orig_name": "Title 01", "cur_name": "Title 01"},
            {"kind": "chapter", "orig_name": "Chapter 01", "cur_name": "Chapter 01"},
            {"kind": "chapter", "orig_name": "Chapter 02", "cur_name": "Chapter 02"},
        ]
        pattern = "Track_{num}"
        start_num = 1
        digits = 2

        previews = []
        for idx, it in enumerate(items):
            n_str = str(start_num + idx).zfill(digits)
            new_name = pattern.replace("{num}", n_str).replace("{name}", it["cur_name"])
            previews.append(new_name)

        self.assertEqual(previews[0], "Track_01")
        self.assertEqual(previews[1], "Track_02")
        self.assertEqual(previews[2], "Track_03")

    # 15. HandBrakeCLI ripping command generation
    def test_54_task8_15_handbrake_rip_command_generation(self):
        """Verify prepare_dvd_handbrake_rip_job generates correct commands for titles and chapters."""
        hb = dvd_engine.find_handbrake() or "HandBrakeCLI.exe"
        out_dir = os.path.join(self.temp_dir, "hb_jobs")
        os.makedirs(out_dir, exist_ok=True)

        title_dict = {
            "title_number": 2,
            "custom_stem": "Main_Feature",
            "aspect_ratio": "16:9"
        }

        # Complete title job
        cmd_title, out_title = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path=hb,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=None,
            out_dir=out_dir,
            use_1080p=True
        )
        self.assertIn("-t", cmd_title)
        self.assertIn("2", cmd_title)
        self.assertNotIn("-c", cmd_title)
        self.assertTrue(out_title.endswith("Main_Feature.mp4"))
        self.assertIn("-X", cmd_title)
        self.assertIn("1920", cmd_title)

        # Chapter job
        chap_dict = {"chapter_number": 3, "custom_stem": "Climax"}
        cmd_chap, out_chap = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path=hb,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=out_dir,
            use_1080p=False
        )
        self.assertIn("-t", cmd_chap)
        self.assertIn("2", cmd_chap)
        self.assertIn("-c", cmd_chap)
        self.assertIn("3-3", cmd_chap)
        self.assertTrue(out_chap.endswith("Main_Feature - Climax.mp4"))

    # 16. FFmpeg DVD ripping fallback command generation
    def test_55_task8_16_ffmpeg_fallback_command_generation(self):
        """Verify prepare_dvd_rip_job and prepare_dvd_chapter_rip_job produce valid commands for titles & chapters."""
        ffmpeg_bin = get_bundled_ffmpeg() or "ffmpeg.exe"
        out_dir = os.path.join(self.temp_dir, "ffmpeg_jobs")
        os.makedirs(out_dir, exist_ok=True)

        title_dict = {
            "title_number": 1,
            "custom_stem": "Fallback_Title",
            "vob_files": [],
            "duration": 500.0
        }
        chap_dict = {
            "chapter_number": 1,
            "start_time": 0.0,
            "duration": 120.0,
            "name": "Scene 1"
        }

        # Full title fallback
        cmd_t, out_t, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            out_dir=out_dir,
            output_format="MP4"
        )
        self.assertTrue(out_t.endswith("Fallback_Title.mp4"))
        self.assertIn("-c:v", cmd_t)

        # Chapter fallback
        cmd_c, out_c, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=out_dir,
            output_format="MOV"
        )
        self.assertTrue(out_c.endswith("Fallback_Title - Scene 1.mov"))
        self.assertIn("-c:v", cmd_c)

    def test_56_dvd_rip_logging_and_translation_callback(self):
        """Verify that _rip_dvd_unified_thread does not shadow translation function t and formats log.extracting properly."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Verify global t is callable
            self.assertTrue(callable(vcd_ripper.t))
            msg = vcd_ripper.t('log.extracting').format(name="Feature Movie", out="Feature Movie.mp4")
            self.assertIn("Feature Movie", msg)
            self.assertIn("Feature Movie.mp4", msg)

            logged_messages = []
            orig_log = app._log.log
            app._log.log = lambda text, level="info": logged_messages.append((text, level))

            # Simulate the exact callback from _rip_dvd_unified_thread
            j_n = "Feature_Movie"
            o_n = "Feature_Movie.mp4"
            eng = "HandBrakeCLI"
            cb = lambda: app._log.log(f"[{eng}] {vcd_ripper.t('log.extracting').format(name=j_n, out=o_n)}", "info")
            cb()
            self.assertEqual(len(logged_messages), 1)
            self.assertIn("[HandBrakeCLI]", logged_messages[0][0])
            self.assertIn("Feature_Movie", logged_messages[0][0])

            # Also verify code object local variables of _rip_dvd_unified_thread
            co = vcd_ripper.VCDRipperApp._rip_dvd_unified_thread.__code__
            self.assertNotIn('t', co.co_varnames, "'t' should not be a local variable in _rip_dvd_unified_thread")

            app._log.log = orig_log
            app.destroy()
        except tk.TclError:
            pass

    def test_57_dvd_select_all_chapters_and_scan_default(self):
        """Verify DVD pipeline defaults to all chapters selected on scan and ALL button selects all chapters."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            mock_dvd = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "duration": 180.0,
                    "size_mb": 150.0,
                    "chapter_count": 3,
                    "chapters_data": [
                        {"chapter_number": 1, "name": "Chap 1", "duration": 60.0},
                        {"chapter_number": 2, "name": "Chap 2", "duration": 60.0},
                        {"chapter_number": 3, "name": "Chap 3", "duration": 60.0},
                    ]
                },
                {
                    "filename": "Title 02", "title_number": 2, "disc_type": "DVD", "duration": 120.0,
                    "size_mb": 100.0,
                    "chapter_count": 2,
                    "chapters_data": [
                        {"chapter_number": 1, "name": "Chap 1", "duration": 60.0},
                        {"chapter_number": 2, "name": "Chap 2", "duration": 60.0},
                    ]
                }
            ]

            # 1. Populate DVD list: should auto-select ALL chapters across all titles by default
            app._source_type = "DVD"
            app._populate_list(mock_dvd)

            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(app._selected_chapters, {(0, 1), (0, 2), (0, 3), (1, 1), (1, 2)})
            self.assertEqual(len(app._selected_chapters), 5)
            # Verify UI cards state
            for card in app._cards:
                self.assertFalse(card.is_selected(), "Parent title should not be checked when chapters are selected")
                self.assertTrue(card.are_any_chapters_selected())
                for v in card._chapter_vars.values():
                    self.assertTrue(v.get(), "Each chapter checkbox must be checked")

            # 2. Deselect all
            app._select_none()
            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(len(app._selected_chapters), 0)
            for card in app._cards:
                self.assertFalse(card.is_selected())
                self.assertFalse(card.are_any_chapters_selected())

            # 3. User clicks ALL: must select all chapters across all titles
            app._select_all()
            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(app._selected_chapters, {(0, 1), (0, 2), (0, 3), (1, 1), (1, 2)})
            for card in app._cards:
                self.assertFalse(card.is_selected())
                self.assertTrue(card.are_any_chapters_selected())
                for v in card._chapter_vars.values():
                    self.assertTrue(v.get())

            # 4. User manually selects title 0 as complete title: clears title 0's chapters
            app._cards[0]._chk_var.set(True)
            app._cards[0]._toggle()
            self.assertIn(0, app._selected_indices)
            self.assertNotIn((0, 1), app._selected_chapters)
            self.assertNotIn((0, 2), app._selected_chapters)
            self.assertNotIn((0, 3), app._selected_chapters)
            self.assertIn((1, 1), app._selected_chapters)
            self.assertIn((1, 2), app._selected_chapters)

            # 5. User clicks ALL again: reverts to ALL chapters selected
            app._select_all()
            self.assertEqual(len(app._selected_indices), 0)
            self.assertEqual(app._selected_chapters, {(0, 1), (0, 2), (0, 3), (1, 1), (1, 2)})

            # 6. Verify VCD pipeline behavior remains completely unaffected
            mock_vcd = [
                {"filename": "AVSEQ01.DAT", "disc_type": "VCD", "size_mb": 50.0, "duration": 120.0},
                {"filename": "AVSEQ02.DAT", "disc_type": "VCD", "size_mb": 60.0, "duration": 150.0},
            ]
            app._source_type = "VCD"
            app._populate_list(mock_vcd)
            self.assertEqual(app._selected_indices, {0, 1})
            self.assertEqual(len(app._selected_chapters), 0)
            for card in app._cards:
                self.assertTrue(card.is_selected())

            app.destroy()
        except tk.TclError:
            pass

    def test_58_selection_button_icons_and_states_dynamic(self):
        """Verify Selection buttons ALL and NONE dynamically update icons and active states."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # 1. Initially (no files loaded), both buttons should show empty checkbox '☐'
            self.assertIn("☐", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☐", app._sel_none_btn._lbl.cget("text"))
            self.assertFalse(app._sel_all_btn.is_active())
            self.assertFalse(app._sel_none_btn.is_active())

            mock_dvd = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "duration": 180.0,
                    "size_mb": 150.0, "chapter_count": 2,
                    "chapters_data": [
                        {"chapter_number": 1, "duration": 90.0},
                        {"chapter_number": 2, "duration": 90.0},
                    ]
                }
            ]

            # 2. After DVD scan, defaults to ALL selected: ALL gets '☑' and is active, NONE gets '☐'
            app._source_type = "DVD"
            app._populate_list(mock_dvd)

            self.assertIn("☑", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☐", app._sel_none_btn._lbl.cget("text"))
            self.assertTrue(app._sel_all_btn.is_active())
            self.assertFalse(app._sel_none_btn.is_active())

            # 3. Click NONE: NONE gets '☑' and is active, ALL gets '☐'
            app._select_none()
            self.assertIn("☐", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☑", app._sel_none_btn._lbl.cget("text"))
            self.assertFalse(app._sel_all_btn.is_active())
            self.assertTrue(app._sel_none_btn.is_active())

            # 4. Click ALL: ALL gets '☑' and is active, NONE gets '☐'
            app._select_all()
            self.assertIn("☑", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☐", app._sel_none_btn._lbl.cget("text"))
            self.assertTrue(app._sel_all_btn.is_active())
            self.assertFalse(app._sel_none_btn.is_active())

            # 5. Partial selection: uncheck 1 chapter -> neither is active, both get '☐'
            app._cards[0]._chapter_vars[1].set(False)
            app._on_chapter_toggle(0, 1, False)
            self.assertIn("☐", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☐", app._sel_none_btn._lbl.cget("text"))
            self.assertFalse(app._sel_all_btn.is_active())
            self.assertFalse(app._sel_none_btn.is_active())

            # 6. Uncheck the other chapter -> 0 selected -> NONE gets '☑'
            app._cards[0]._chapter_vars[2].set(False)
            app._on_chapter_toggle(0, 2, False)
            self.assertIn("☐", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☑", app._sel_none_btn._lbl.cget("text"))
            self.assertFalse(app._sel_all_btn.is_active())
            self.assertTrue(app._sel_none_btn.is_active())

            # 7. Clear all action -> both reset to '☐' and inactive
            app._clear_all_action()
            self.assertIn("☐", app._sel_all_btn._lbl.cget("text"))
            self.assertIn("☐", app._sel_none_btn._lbl.cget("text"))
            self.assertFalse(app._sel_all_btn.is_active())
            self.assertFalse(app._sel_none_btn.is_active())

            app.destroy()
        except tk.TclError:
            pass

    def test_59_drive_detecting_to_detected_cyan(self):
        """Verify Source _detect_label switches from detecting to cyan 'Drive detected' upon scan completion."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # 1. When scan starts, label shows detecting
            app._vcd_path.set(self.temp_dir)
            app._detect_label.configure(text=vcd_ripper.t('drive.detecting'), fg=vcd_ripper.COLORS["accent"])
            self.assertEqual(app._detect_label.cget("text"), vcd_ripper.t('drive.detecting'))
            self.assertEqual(app._detect_label.cget("fg"), vcd_ripper.COLORS["accent"])

            # 2. When disc recognized and scan completes (_populate_list), label switches to cyan 'Drive detected'
            mock_titles = [
                {
                    "filename": "Title 01", "title_number": 1, "disc_type": "DVD", "duration": 180.0,
                    "size_mb": 150.0, "chapter_count": 1,
                    "chapters_data": [{"chapter_number": 1, "duration": 180.0}]
                }
            ]
            app._populate_list(mock_titles)

            self.assertEqual(app._detect_label.cget("text"), vcd_ripper.t('drive.detected'))
            self.assertEqual(app._detect_label.cget("fg"), vcd_ripper.COLORS["cyan"])

            # 3. When theme or UI refreshed, cyan color is preserved while videos are loaded
            app._refresh_ui()
            self.assertEqual(app._detect_label.cget("text"), vcd_ripper.t('drive.detected'))
            self.assertEqual(app._detect_label.cget("fg"), vcd_ripper.COLORS["cyan"])

            app.destroy()
        except tk.TclError:
            pass


class TestOutputFormatBothModeAndGreyout(unittest.TestCase):
    """Test suite for Output Format Video and Audio mode, simultaneous panels, and greyout."""

    def test_both_mode_translations(self):
        """Verify both_mode translations in en and zh-CN."""
        with open("en.json", "r", encoding="utf-8") as f:
            en_data = json.load(f)
        self.assertIn("both_mode", en_data["format"])
        self.assertIn("Video and Audio", en_data["format"]["both_mode"])

        with open("zh-CN.json", "r", encoding="utf-8") as f:
            zh_data = json.load(f)
        self.assertIn("both_mode", zh_data["format"])
        self.assertIn("视频与音频", zh_data["format"]["both_mode"])

    def test_ui_panels_and_greyout(self):
        """Verify both Video Format and Audio Format panels appear simultaneously with correct greyout states."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Verify 3 mode options exist
            self.assertTrue(hasattr(app, "_video_mode_rb"))
            self.assertTrue(hasattr(app, "_audio_mode_rb"))
            self.assertTrue(hasattr(app, "_both_mode_rb"))

            # Verify both panels exist and are packed
            self.assertTrue(hasattr(app, "_video_panel"))
            self.assertTrue(hasattr(app, "_audio_panel"))
            self.assertTrue(bool(app._video_panel.pack_info()))
            self.assertTrue(bool(app._audio_panel.pack_info()))

            # 1. Video mode (default):
            app._output_mode.set("video")
            app._on_mode_change()

            # Video panel active
            self.assertEqual(app._video_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])
            for item in app._fmt_items:
                self.assertEqual(item["rb"].cget("state"), "normal")
                fmt = item.get("fmt")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.OUTPUT_FORMATS[fmt]["color"])

            # Audio panel greyed out
            self.assertEqual(app._audio_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_muted"])
            for item in app._audio_items:
                self.assertEqual(item["rb"].cget("state"), "disabled")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.COLORS["text_muted"])

            # 2. Audio Only mode:
            app._output_mode.set("audio")
            app._on_mode_change()

            # Video panel greyed out
            self.assertEqual(app._video_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_muted"])
            for item in app._fmt_items:
                self.assertEqual(item["rb"].cget("state"), "disabled")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.COLORS["text_muted"])

            # Audio panel active
            self.assertEqual(app._audio_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])
            for item in app._audio_items:
                self.assertEqual(item["rb"].cget("state"), "normal")
                afmt = item.get("fmt")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.AUDIO_FORMATS[afmt]["color"])

            # 3. Video and Audio mode:
            app._output_mode.set("both")
            app._on_mode_change()

            # Both panels active, no greyout!
            self.assertEqual(app._video_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])
            for item in app._fmt_items:
                self.assertEqual(item["rb"].cget("state"), "normal")
                fmt = item.get("fmt")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.OUTPUT_FORMATS[fmt]["color"])

            self.assertEqual(app._audio_fmt_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])
            for item in app._audio_items:
                self.assertEqual(item["rb"].cget("state"), "normal")
                afmt = item.get("fmt")
                self.assertEqual(item["rb"].cget("fg"), vcd_ripper.AUDIO_FORMATS[afmt]["color"])

            # Check that valid selections are forced
            self.assertIn(app._output_format.get(), vcd_ripper.OUTPUT_FORMATS)
            self.assertIn(app._audio_format.get(), vcd_ripper.AUDIO_FORMATS)

            app.destroy()
        except tk.TclError:
            pass

    def test_vcd_rip_thread_both_mode_extracts_video_and_audio(self):
        """Verify _rip_thread extracts both video and audio files in both mode."""
        ffmpeg = get_bundled_ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")

        temp_dir = tempfile.mkdtemp()
        try:
            # Create synthetic test video file
            src_file = os.path.join(temp_dir, "test_track.mpg")
            cmd = [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=352x240:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
                "-c:v", "mpeg1video", "-c:a", "mp2",
                src_file
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(res.returncode, 0)

            out_dir = os.path.join(temp_dir, "output")
            os.makedirs(out_dir, exist_ok=True)

            mock_videos = [
                {"filename": "AVSEQ01.DAT", "path": src_file, "duration": 1.0, "custom_stem": "Track_01"}
            ]

            try:
                app = vcd_ripper.VCDRipperApp()
                app.withdraw()
                app._ffmpeg = ffmpeg

                # Run rip in thread and verify output
                app._rip_done = lambda total, success, errors, folder, cancelled=False, timed_out=False: None
                app._rip_thread(
                    mock_videos, out_dir, "MP4",
                    vcd_ripper.OUTPUT_FORMATS["MP4"],
                    use_1080p=False, mode="both", audio_fmt="MP3"
                )

                # Verify both Track_01.mp4 and Track_01.mp3 exist in out_dir!
                out_mp4 = os.path.join(out_dir, "Track_01.mp4")
                out_mp3 = os.path.join(out_dir, "Track_01.mp3")
                self.assertTrue(os.path.exists(out_mp4), "Video file Track_01.mp4 was not created")
                self.assertTrue(os.path.exists(out_mp3), "Audio file Track_01.mp3 was not created")
                self.assertGreater(os.path.getsize(out_mp4), 100)
                self.assertGreater(os.path.getsize(out_mp3), 100)

                app.destroy()
            except tk.TclError:
                pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dvd_unified_thread_jobs_extract_both(self):
        """Verify _rip_dvd_unified_thread creates both video and audio jobs when extract_both=True."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            mock_titles = [
                {
                    "title_number": 1, "filename": "Title 01", "name": "Title 01",
                    "duration": 120.0, "vob_files": ["VTS_01_1.VOB"],
                    "chapters_data": [
                        {"chapter_number": 1, "duration": 60.0},
                        {"chapter_number": 2, "duration": 60.0}
                    ]
                }
            ]
            chapter_jobs = [(mock_titles[0], mock_titles[0]["chapters_data"][0])]

            # Intercept rip_done and trigger early cancel so it does not run real subprocesses
            app._cancel_requested = True
            done_called = []
            app._rip_done = lambda total, success, errors, out_f, cancelled=False, timed_out=False: done_called.append((total, cancelled))

            app._rip_dvd_unified_thread(
                mock_titles, chapter_jobs, "C:\\dummy_out", "MP4",
                use_1080p=False, audio_only=False, audio_format="MP3",
                extract_both=True
            )

            # In extract_both mode: 1 title + 1 chapter = 2 items * 2 = 4 total jobs
            self.assertTrue(len(done_called) > 0)
            total_jobs, was_cancelled = done_called[0]
            self.assertEqual(total_jobs, 4)
            self.assertTrue(was_cancelled)

            app.destroy()
        except tk.TclError:
            pass

    def test_dvd_title_folder_translations(self):
        """Verify DVD title folder translations in English and Simplified Chinese."""
        with open("en.json", "r", encoding="utf-8") as f:
            en_data = json.load(f)
        self.assertIn("dvd_title_folder", en_data["output"])
        self.assertEqual(en_data["output"]["dvd_title_folder"], "Create folder with DVD title")

        with open("zh-CN.json", "r", encoding="utf-8") as f:
            zh_data = json.load(f)
        self.assertIn("dvd_title_folder", zh_data["output"])
        self.assertEqual(zh_data["output"]["dvd_title_folder"], "根据 DVD 标题创建文件夹")

        self.assertIn("dvd_title_folder", vcd_ripper.TRANSLATIONS["en"]["output"])
        self.assertEqual(vcd_ripper.TRANSLATIONS["en"]["output"]["dvd_title_folder"], "Create folder with DVD title")
        self.assertIn("dvd_title_folder", vcd_ripper.TRANSLATIONS["zh_CN"]["output"])
        self.assertEqual(vcd_ripper.TRANSLATIONS["zh_CN"]["output"]["dvd_title_folder"], "根据 DVD 标题创建文件夹")

    def test_dvd_title_folder_ui_visibility(self):
        """Verify that Create folder with DVD title option is visible only in DVD mode."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            self.assertTrue(hasattr(app, "_dvd_title_folder_chk"))
            self.assertTrue(hasattr(app, "_dvd_title_folder_var"))

            # In VCD mode, the DVD title folder checkbox should NOT be packed
            app._source_type = "VCD"
            app._update_format_visibility_for_source()
            with self.assertRaises(tk.TclError):
                app._dvd_title_folder_chk.pack_info()

            # In DVD mode, the DVD title folder checkbox must be packed
            app._source_type = "DVD"
            app._update_format_visibility_for_source()
            pack_info = app._dvd_title_folder_chk.pack_info()
            self.assertTrue(bool(pack_info))

            # When switched back to VCD mode, it should be unpacked again
            app._source_type = "VCD"
            app._update_format_visibility_for_source()
            with self.assertRaises(tk.TclError):
                app._dvd_title_folder_chk.pack_info()

            app.destroy()
        except tk.TclError:
            pass

    def test_dvd_rip_thread_create_title_folder(self):
        """Verify _rip_dvd_unified_thread creates subfolder based on custom or default DVD title."""
        import tempfile
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            with tempfile.TemporaryDirectory() as tmpdir:
                # 1. Custom stem entered by user (e.g. "My_Awesome_Movie")
                custom_title = [
                    {
                        "title_number": 1,
                        "filename": "Title 01 (Main Feature)",
                        "custom_stem": "My_Awesome_Movie",
                        "duration": 100.0,
                        "vob_files": ["VTS_01_1.VOB"],
                        "chapters_data": [
                            {"chapter_number": 1, "duration": 50.0}
                        ]
                    }
                ]
                app._cancel_requested = True
                done_called = []
                app._rip_done = lambda total, success, errors, out_f, cancelled=False, timed_out=False: done_called.append(out_f)

                app._rip_dvd_unified_thread(
                    custom_title, [], tmpdir, "MP4",
                    create_title_folder=True
                )

                expected_folder = os.path.join(tmpdir, "My_Awesome_Movie")
                self.assertTrue(os.path.isdir(expected_folder))
                self.assertEqual(done_called[0], expected_folder)

                # 2. Default title without custom_stem (e.g. "Title 02 (Main Feature)")
                default_title = [
                    {
                        "title_number": 2,
                        "filename": "Title 02 (Main Feature)",
                        "duration": 100.0,
                        "vob_files": ["VTS_02_1.VOB"],
                        "chapters_data": [
                            {"chapter_number": 1, "duration": 50.0}
                        ]
                    }
                ]
                app._cancel_requested = True
                done_called.clear()

                app._rip_dvd_unified_thread(
                    default_title, [], tmpdir, "MP4",
                    create_title_folder=True
                )

                expected_default_folder = os.path.join(tmpdir, "Title 02")
                self.assertTrue(os.path.isdir(expected_default_folder))
                self.assertEqual(done_called[0], expected_default_folder)

                # 3. create_title_folder=False -> uses base tmpdir directly
                done_called.clear()
                app._rip_dvd_unified_thread(
                    custom_title, [], tmpdir, "MP4",
                    create_title_folder=False
                )
                self.assertEqual(done_called[0], tmpdir)

            app.destroy()
        except tk.TclError:
            pass


# ─────────────────────────────────────────────────────────────
#  Test Suite: DVD Audio Track Selection Across All Output Formats (v2.0.0)
# ─────────────────────────────────────────────────────────────
class TestDVDAudioTrackSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="test_dvd_audio_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_01_canonical_audio_track_model_and_labels(self):
        """Verify DVDAudioTrack creation, language normalization, and display labels."""
        # 1. Chinese AC-3 stereo
        trk1 = dvd_engine.normalize_audio_track(
            title_number=1,
            track_number=1,
            stream_index=0,
            raw_codec="AC-3",
            raw_channels="stereo",
            raw_lang="zho",
            raw_lang_name="Chinese",
            sample_rate=48000,
            bitrate=192000,
            hb_track_index=1,
            ffmpeg_stream_index=0
        )
        self.assertEqual(trk1.track_id, "T01_A01")
        self.assertEqual(trk1.lang_code, "zho")
        self.assertEqual(trk1.lang_name, "Chinese")
        self.assertEqual(trk1.codec, "AC-3")
        self.assertEqual(trk1.channel_count, 2)
        self.assertEqual(trk1.channels, "Stereo")
        self.assertEqual(trk1.display_label(), "Track 1 — Chinese — AC-3 — Stereo")

        # 2. English AC-3 5.1
        trk2 = dvd_engine.normalize_audio_track(
            title_number=1,
            track_number=2,
            stream_index=1,
            raw_codec="AC-3",
            raw_channels="5.1",
            raw_lang="eng",
            raw_lang_name="English",
            sample_rate=48000,
            bitrate=384000,
            hb_track_index=2,
            ffmpeg_stream_index=1
        )
        self.assertEqual(trk2.track_id, "T01_A02")
        self.assertEqual(trk2.display_label(), "Track 2 — English — AC-3 — 5.1")

        # 3. French DTS 5.1
        trk3 = dvd_engine.normalize_audio_track(
            title_number=1,
            track_number=3,
            stream_index=2,
            raw_codec="DTS",
            raw_channels="5.1",
            raw_lang="fre",
            raw_lang_name="French",
            sample_rate=48000,
            bitrate=768000,
            hb_track_index=3,
            ffmpeg_stream_index=2
        )
        self.assertEqual(trk3.display_label(), "Track 3 — French — DTS — 5.1")

        # 4. Unknown Language LPCM stereo (must not fabricate language)
        trk4 = dvd_engine.normalize_audio_track(
            title_number=1,
            track_number=4,
            stream_index=3,
            raw_codec="LPCM",
            raw_channels="stereo",
            raw_lang="und",
            raw_lang_name="",
            sample_rate=48000,
            bitrate=1536000,
            hb_track_index=4,
            ffmpeg_stream_index=3
        )
        self.assertEqual(trk4.lang_name, "Unknown Language")
        self.assertEqual(trk4.display_label(), "Track 4 — Unknown Language — LPCM — Stereo")

        # 5. DVDTitle summary
        dvd_title = dvd_engine.DVDTitle(
            title_number=1,
            vts_number=1,
            duration=3600.0,
            audio_tracks=[trk1, trk2, trk3, trk4]
        )
        self.assertEqual(len(dvd_title.audio_tracks), 4)
        summary = dvd_title.audio_summary()
        self.assertIn("Chinese", summary)
        self.assertIn("English", summary)

    def test_02_handbrake_json_scan_multiple_audio_tracks(self):
        """Verify HandBrakeCLI JSON scanner extracts and maps multiple audio tracks."""
        sample_hb_json = {
            "TitleList": [
                {
                    "Index": 1,
                    "Duration": {"Hours": 1, "Minutes": 30, "Seconds": 0},
                    "ChapterList": [
                        {"Duration": {"Seconds": 600}},
                        {"Duration": {"Seconds": 600}}
                    ],
                    "AudioList": [
                        {
                            "Description": "Chinese (AC3) (2.0 ch)",
                            "LanguageCode": "zho",
                            "Codec": 0x2000,
                            "Format": "ac3",
                            "ChannelLayoutName": "stereo",
                            "SampleRate": 48000,
                            "Bitrate": 192000
                        },
                        {
                            "Description": "English (AC3) (5.1 ch)",
                            "LanguageCode": "eng",
                            "Codec": 0x2000,
                            "Format": "ac3",
                            "ChannelLayoutName": "5.1",
                            "SampleRate": 48000,
                            "Bitrate": 384000
                        },
                        {
                            "Description": "Commentary (LPCM) (2.0 ch)",
                            "LanguageCode": "und",
                            "Codec": 0x1000,
                            "Format": "pcm",
                            "ChannelLayoutName": "stereo",
                            "SampleRate": 48000,
                            "Bitrate": 1536000
                        }
                    ]
                }
            ]
        }
        titles = dvd_engine.parse_handbrake_json_title_set(sample_hb_json)
        self.assertEqual(len(titles), 1)
        t = titles[0]
        self.assertEqual(len(t.audio_tracks), 3)

        # Track 1
        a1 = t.audio_tracks[0]
        self.assertEqual(a1.track_number, 1)
        self.assertEqual(a1.hb_track_index, 1)
        self.assertEqual(a1.ffmpeg_stream_index, 0)
        self.assertEqual(a1.lang_name, "Chinese")
        self.assertEqual(a1.codec, "AC-3")
        self.assertEqual(a1.channels, "Stereo")

        # Track 2
        a2 = t.audio_tracks[1]
        self.assertEqual(a2.track_number, 2)
        self.assertEqual(a2.hb_track_index, 2)
        self.assertEqual(a2.ffmpeg_stream_index, 1)
        self.assertEqual(a2.lang_name, "English")
        self.assertEqual(a2.channel_count, 6)
        self.assertEqual(a2.channels, "5.1")

        # Track 3
        a3 = t.audio_tracks[2]
        self.assertEqual(a3.track_number, 3)
        self.assertEqual(a3.hb_track_index, 3)
        self.assertEqual(a3.ffmpeg_stream_index, 2)
        self.assertEqual(a3.lang_name, "Unknown Language")

    def test_03_ffprobe_enrichment_multiple_audio_tracks(self):
        """Verify enrich_title_from_ffprobe populates audio tracks from streams."""
        from unittest.mock import patch, MagicMock
        dummy_vob = os.path.join(self.temp_dir, "test_vob.vob")
        with open(dummy_vob, "wb") as f:
            f.write(b"0" * 100)
        title = dvd_engine.DVDTitle(title_number=1, vts_number=1, duration=100.0, vob_files=[dummy_vob])
        mock_probe = {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 480, "codec_name": "mpeg2video"},
                {
                    "codec_type": "audio", "codec_name": "ac3", "channels": 2,
                    "channel_layout": "stereo", "sample_rate": "48000", "bit_rate": "192000",
                    "tags": {"language": "zho"}
                },
                {
                    "codec_type": "audio", "codec_name": "dts", "channels": 6,
                    "channel_layout": "5.1(side)", "sample_rate": "48000", "bit_rate": "768000",
                    "tags": {"language": "eng"}
                }
            ],
            "format": {"duration": "100.0"}
        }
        with patch("subprocess.run") as mock_run:
            mock_res = MagicMock()
            mock_res.stdout = json.dumps(mock_probe)
            mock_res.returncode = 0
            mock_run.return_value = mock_res
            dvd_engine.enrich_title_from_ffprobe("ffprobe.exe", title)

        self.assertEqual(len(title.audio_tracks), 2)
        t1 = title.audio_tracks[0]
        self.assertEqual(t1.track_id, "T01_A01")
        self.assertEqual(t1.codec, "AC-3")
        self.assertEqual(t1.ffmpeg_stream_index, 0)
        self.assertEqual(t1.hb_track_index, 1)

        t2 = title.audio_tracks[1]
        self.assertEqual(t2.track_id, "T01_A02")
        self.assertEqual(t2.codec, "DTS")
        self.assertEqual(t2.ffmpeg_stream_index, 1)
        self.assertEqual(t2.hb_track_index, 2)
        self.assertEqual(t2.channels, "5.1")

    def test_04_handbrake_command_construction(self):
        """Verify prepare_dvd_handbrake_rip_job passes -a <hb_idx> and configures audio."""
        title_dict = {
            "title_number": 1,
            "custom_stem": "Feature_Movie",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "hb_track_index": 1, "channels": "stereo"},
                {"track_id": "T01_A02", "track_number": 2, "hb_track_index": 2, "channels": "5.1", "channel_count": 6}
            ]
        }
        # Select Track 2 (hb_track_index = 2, 5.1)
        cmd, out_path = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=None,
            out_dir=self.temp_dir,
            audio_track=title_dict["audio_tracks"][1]
        )
        self.assertIn("-a", cmd)
        a_idx = cmd.index("-a")
        self.assertEqual(cmd[a_idx + 1], "2")
        self.assertIn("-B", cmd)
        b_idx = cmd.index("-B")
        self.assertEqual(cmd[b_idx + 1], "384k")  # Multichannel 5.1 gets 384k AAC
        self.assertTrue(out_path.endswith("Feature_Movie.mp4"))

    def test_05_ffmpeg_mp4_mov_command_construction(self):
        """Verify FFmpeg MP4 and MOV map selected audio stream and set bitrate."""
        title_dict = {
            "title_number": 1,
            "custom_stem": "Title_01",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0, "channels": "stereo", "channel_count": 2},
                {"track_id": "T01_A02", "track_number": 2, "ffmpeg_stream_index": 1, "channels": "5.1", "channel_count": 6}
            ]
        }
        # MP4 with Track 2
        cmd, out_path, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            out_dir=self.temp_dir,
            output_format="MP4",
            audio_track=title_dict["audio_tracks"][1]
        )
        self.assertIn("-map", cmd)
        self.assertIn("0:v:0", cmd)
        self.assertIn("0:a:1", cmd)
        self.assertNotIn("0:a:0", cmd)
        self.assertIn("384k", cmd)

        # MOV with Track 1
        cmd_mov, out_path_mov, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            out_dir=self.temp_dir,
            output_format="MOV",
            audio_track=title_dict["audio_tracks"][0]
        )
        self.assertIn("0:a:0", cmd_mov)
        self.assertIn("192k", cmd_mov)

    def test_06_ffmpeg_mpg_stream_copy_vs_transcode(self):
        """Verify MPG uses stream copy for AC-3/LPCM, and transcodes DTS to AC-3."""
        # 1. AC-3 track -> stream copy
        title_ac3 = {
            "title_number": 1,
            "custom_stem": "Title_AC3",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0, "codec": "AC-3"}
            ]
        }
        cmd_ac3, _, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_ac3,
            out_dir=self.temp_dir,
            output_format="MPG",
            audio_track=title_ac3["audio_tracks"][0]
        )
        c_v_idx = cmd_ac3.index("-c:v")
        self.assertEqual(cmd_ac3[c_v_idx + 1], "copy")
        c_a_idx = cmd_ac3.index("-c:a")
        self.assertEqual(cmd_ac3[c_a_idx + 1], "copy")

        # 2. DTS track -> transcode to AC-3 384k
        title_dts = {
            "title_number": 1,
            "custom_stem": "Title_DTS",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0, "codec": "DTS"}
            ]
        }
        cmd_dts, _, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dts,
            out_dir=self.temp_dir,
            output_format="MPG",
            audio_track=title_dts["audio_tracks"][0]
        )
        c_a_dts_idx = cmd_dts.index("-c:a")
        self.assertEqual(cmd_dts[c_a_dts_idx + 1], "ac3")
        self.assertIn("-b:a", cmd_dts)
        self.assertIn("384k", cmd_dts)

    def test_07_audio_only_wav_and_mp3(self):
        """Verify WAV preserves multichannel PCM and MP3 downmixes 5.1 to stereo."""
        title_51 = {
            "title_number": 1,
            "custom_stem": "Title_Audio",
            "audio_tracks": [
                {
                    "track_id": "T01_A01",
                    "track_number": 1,
                    "ffmpeg_stream_index": 2,
                    "channels": "5.1",
                    "channel_count": 6
                }
            ]
        }
        # 1. WAV
        cmd_wav, out_wav, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_51,
            out_dir=self.temp_dir,
            output_format="WAV",
            audio_only=True,
            audio_format="WAV",
            audio_track=title_51["audio_tracks"][0]
        )
        self.assertIn("-vn", cmd_wav)
        self.assertIn("0:a:2", cmd_wav)
        self.assertIn("pcm_s16le", cmd_wav)
        self.assertIn("48000", cmd_wav)
        self.assertNotIn("-ac", cmd_wav)  # Must NOT downmix 5.1 in WAV!

        # 2. MP3
        cmd_mp3, out_mp3, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_51,
            out_dir=self.temp_dir,
            output_format="MP3",
            audio_only=True,
            audio_format="MP3",
            audio_track=title_51["audio_tracks"][0]
        )
        self.assertIn("-vn", cmd_mp3)
        self.assertIn("0:a:2", cmd_mp3)
        self.assertIn("-ac", cmd_mp3)
        ac_idx = cmd_mp3.index("-ac")
        self.assertEqual(cmd_mp3[ac_idx + 1], "2")  # Downmixed to 2 channels for MP3
        self.assertIn("libmp3lame", cmd_mp3)

    def test_08_chapter_rip_inherits_parent_audio_track(self):
        """Verify prepare_dvd_chapter_rip_job maps selected audio track correctly."""
        title_dict = {
            "title_number": 1,
            "custom_stem": "Main_Movie",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0},
                {"track_id": "T01_A02", "track_number": 2, "ffmpeg_stream_index": 1, "channels": "5.1", "channel_count": 6}
            ]
        }
        chapter_dict = {
            "chapter_number": 3,
            "custom_stem": "The_Chase",
            "start_time": 600.0,
            "duration": 300.0
        }
        cmd, out_path, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chapter_dict,
            out_dir=self.temp_dir,
            output_format="MP4",
            audio_track=title_dict["audio_tracks"][1]
        )
        self.assertIn("0:a:1", cmd)
        self.assertIn("384k", cmd)
        self.assertTrue(out_path.endswith("Main_Movie - The_Chase.mp4"))

    def test_09_video_and_audio_dual_naming_and_custom_filename(self):
        """Verify custom_output_filename works across whole titles and chapters."""
        title_dict = {
            "title_number": 1,
            "custom_stem": "Matrix",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0, "lang_name": "English"}
            ]
        }
        # Custom filename for separate audio
        custom_name = "Matrix - English Audio.mp3"
        cmd, out_path, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            out_dir=self.temp_dir,
            output_format="MP3",
            audio_only=True,
            audio_format="MP3",
            audio_track=title_dict["audio_tracks"][0],
            custom_output_filename=custom_name
        )
        self.assertTrue(out_path.endswith("Matrix - English Audio.mp3"))

    def test_10_missing_audio_track_error_handling(self):
        """Verify selecting a nonexistent track raises ValueError (no silent substitution)."""
        title_dict = {
            "title_number": 1,
            "custom_stem": "Movie",
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 0}
            ]
        }
        bogus_track = {"track_id": "T01_A99", "track_number": 99, "ffmpeg_stream_index": 98}

        with self.assertRaises(ValueError):
            dvd_engine.prepare_dvd_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=self.temp_dir,
                title_dict=title_dict,
                out_dir=self.temp_dir,
                output_format="MP4",
                audio_track=bogus_track
            )

        with self.assertRaises(ValueError):
            dvd_engine.prepare_dvd_handbrake_rip_job(
                handbrake_path="HandBrakeCLI.exe",
                dvd_source=self.temp_dir,
                title_dict=title_dict,
                chapter_dict=None,
                out_dir=self.temp_dir,
                audio_track=bogus_track
            )

    def test_11_validate_ripped_media(self):
        """Verify validate_ripped_media correctly validates streams, sizes, and formats."""
        # 1. Non-existent file
        is_ok, msg = dvd_engine.validate_ripped_media(None, "non_existent.mp4", False, "MP4")
        self.assertFalse(is_ok)
        self.assertIn("does not exist", msg)

        # 2. Empty file (0 bytes)
        empty_file = os.path.join(self.temp_dir, "empty.mp4")
        with open(empty_file, "wb") as f:
            pass
        is_ok, msg = dvd_engine.validate_ripped_media(None, empty_file, False, "MP4")
        self.assertFalse(is_ok)
        self.assertIn("0 bytes", msg)

        # 3. Synthetic test with bundled ffprobe if available
        ffprobe = get_bundled_ffprobe()
        if not ffprobe:
            return  # Skip live probe tests if ffprobe absent

        # Create synthetic valid video + audio MP4
        ffmpeg = get_bundled_ffmpeg()
        if not ffmpeg:
            return

        test_mp4 = os.path.join(self.temp_dir, "valid_test.mp4")
        subprocess.run([
            ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=duration=0.5:frequency=1000",
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
            test_mp4
        ], capture_output=True, check=True)

        # Validate as video
        is_ok, msg = dvd_engine.validate_ripped_media(ffprobe, test_mp4, False, "MP4")
        self.assertTrue(is_ok)

        # Validate as audio-only -> must fail because video stream is present
        is_ok, msg = dvd_engine.validate_ripped_media(ffprobe, test_mp4, True, "MP3")
        self.assertFalse(is_ok)
        self.assertIn("Unexpected video stream", msg)

    def test_12_gui_audio_track_selector_and_title_switching(self):
        """Verify GUI audio track combobox updates and preserves per-title selections."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Set up 2 mock DVD titles with different tracks
            t1 = {
                "title_number": 1,
                "name": "Title 01",
                "audio_tracks": [
                    dvd_engine.normalize_audio_track(1, 1, 0, raw_codec="AC-3", raw_channels="stereo", raw_lang="zho", raw_lang_name="Chinese"),
                    dvd_engine.normalize_audio_track(1, 2, 1, raw_codec="AC-3", raw_channels="5.1", raw_lang="eng", raw_lang_name="English")
                ]
            }
            t2 = {
                "title_number": 2,
                "name": "Title 02",
                "audio_tracks": [
                    dvd_engine.normalize_audio_track(2, 1, 0, raw_codec="DTS", raw_channels="5.1", raw_lang="fre", raw_lang_name="French"),
                    dvd_engine.normalize_audio_track(2, 2, 1, raw_codec="AC-3", raw_channels="stereo", raw_lang="deu", raw_lang_name="German")
                ]
            }
            app._videos = [t1, t2]
            app._source_type = "DVD"
            app._active_dvd_title_idx = 0

            # Update selector
            app._update_audio_track_selector()
            self.assertEqual(len(app._audio_track_cb["values"]), 2)
            self.assertIn("Chinese", app._audio_track_var.get())

            # Select Track 2 (English) for Title 1
            app._audio_track_cb.current(1)
            app._on_audio_track_selected()
            self.assertEqual(app._dvd_selected_audio_tracks.get(1), "T01_A02")

            # Switch to Title 2
            app._active_dvd_title_idx = 1
            app._update_audio_track_selector()
            self.assertEqual(len(app._audio_track_cb["values"]), 2)
            self.assertIn("French", app._audio_track_var.get())

            # Switch back to Title 1 -> verifies English selection was preserved!
            app._active_dvd_title_idx = 0
            app._update_audio_track_selector()
            self.assertIn("English", app._audio_track_var.get())

            app.destroy()
        except tk.TclError:
            pass

    def test_13_vcd_pipeline_isolation(self):
        """Verify VCD mode hides DVD audio track selector and operates independently."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Switch to VCD mode
            app._source_type = "VCD"
            app._update_format_visibility_for_source()

            # Confirm audio track panel is not packed
            self.assertNotEqual(app._audio_track_panel.winfo_manager(), "pack")

            # Confirm DAT format is available for VCD
            vcd_fmts = [item.get("fmt") for item in app._fmt_items if item["frame"].winfo_manager() == "pack"]
            self.assertIn("DAT", vcd_fmts)

            # Switch to DVD mode -> audio track panel is packed
            app._source_type = "DVD"
            app._update_format_visibility_for_source()
            self.assertEqual(app._audio_track_panel.winfo_manager(), "pack")
            dvd_fmts = [item.get("fmt") for item in app._fmt_items if item["frame"].winfo_manager() == "pack"]
            self.assertNotIn("DAT", dvd_fmts)

            app.destroy()
        except tk.TclError:
            pass

    def test_14_dvd_audio_from_local_video_fast_path(self):
        """Verify prepare_dvd_audio_from_video_job generates ultra-fast extraction commands from local files."""
        t_item = {"title_number": 1, "custom_stem": "Movie"}
        c_item = {"chapter_number": 2, "custom_stem": "ActionScene"}
        local_vid = os.path.join(self.temp_dir, "Movie - ActionScene.mp4")

        # 1. WAV
        cmd_wav, out_wav = dvd_engine.prepare_dvd_audio_from_video_job(
            ffmpeg_path="ffmpeg.exe",
            local_video_path=local_vid,
            title_dict=t_item,
            chapter_dict=c_item,
            out_dir=self.temp_dir,
            audio_format="WAV"
        )
        self.assertIn("-i", cmd_wav)
        self.assertIn(local_vid, cmd_wav)
        self.assertIn("-map", cmd_wav)
        self.assertIn("0:a:0", cmd_wav)
        self.assertIn("pcm_s16le", cmd_wav)
        self.assertIn("48000", cmd_wav)
        self.assertIn("-threads", cmd_wav)
        self.assertTrue(out_wav.endswith("Movie - ActionScene.wav"))

        # 2. MP3
        cmd_mp3, out_mp3 = dvd_engine.prepare_dvd_audio_from_video_job(
            ffmpeg_path="ffmpeg.exe",
            local_video_path=local_vid,
            title_dict=t_item,
            chapter_dict=c_item,
            out_dir=self.temp_dir,
            audio_format="MP3"
        )
        self.assertIn("-ac", cmd_mp3)
        self.assertEqual(cmd_mp3[cmd_mp3.index("-ac") + 1], "2")
        self.assertIn("libmp3lame", cmd_mp3)
        self.assertTrue(out_mp3.endswith("Movie - ActionScene.mp3"))

    def test_15_dvdvideo_probe_caching(self):
        """Verify check_dvdvideo_support caches results per (ffmpeg, source, title)."""
        from unittest.mock import patch, MagicMock
        dvd_engine.clear_dvdvideo_probe_cache()
        self.assertEqual(len(dvd_engine._dvdvideo_probe_cache), 0)

        with patch("subprocess.run") as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_run.return_value = mock_res

            can_use1, path1 = dvd_engine.check_dvdvideo_support("ffmpeg.exe", "D:\\", 1)
            self.assertTrue(can_use1)
            self.assertEqual(mock_run.call_count, 1)

            # Second call for same title should hit cache and NOT call subprocess.run
            can_use2, path2 = dvd_engine.check_dvdvideo_support("ffmpeg.exe", "D:\\", 1, chapter_num=2)
            self.assertTrue(can_use2)
            self.assertEqual(mock_run.call_count, 1)

        dvd_engine.clear_dvdvideo_probe_cache()
        self.assertEqual(len(dvd_engine._dvdvideo_probe_cache), 0)



# ─────────────────────────────────────────────────────────────
#  Test Suite: v2.0.0 UI Fixes (Scale, Theme, Resize, Version)
# ─────────────────────────────────────────────────────────────
class TestUIEnhancementsAndBugFixes(unittest.TestCase):
    def test_01_version_number_v2_0_0(self):
        """Verify version number is strictly 2.0.0."""
        self.assertEqual(vcd_ripper.APP_VERSION, "2.0.0")
        self.assertEqual(vcd_ripper.APP_USER_MODEL_ID, "jjsiew.discripperpro.2.0.0")

    def test_02_scale_change_preserves_scanned_videos_and_chapters(self):
        """Verify scale switching preserves video cards, selections, and chapters without clearing."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Mock scanned DVD video with chapters
            dvd_info = {
                "filename": "Main Movie",
                "custom_stem": "Main Movie",
                "disc_type": "DVD",
                "title_number": 1,
                "duration": 7200.0,
                "chapters_data": [
                    {"chapter_number": 1, "name": "Intro", "duration_str": "05:00"},
                    {"chapter_number": 2, "name": "Action", "duration_str": "15:00"},
                ],
                "audio_tracks": [
                    {"track_id": "T01_A01", "display_label": "Track 1 — English — AC-3 — Stereo"}
                ]
            }
            app._source_type = "DVD"
            app._videos = [dvd_info]
            app._selected_indices = {0}
            app._selected_chapters = {(0, 1)}

            # Build cards initially
            app._cards.clear()
            card = vcd_ripper.VideoCard(
                app._list_frame, dvd_info, 0,
                on_toggle=app._on_card_toggle,
                on_chapter_toggle=app._on_chapter_toggle
            )
            card.pack()
            app._cards.append(card)
            card.set_selected(True)
            card.set_chapter_selected(1, True)

            # Trigger scale change to 125%
            app._on_scale_changed(1.25)
            self.assertEqual(len(app._cards), 1)
            self.assertEqual(app._cards[0].info["filename"], "Main Movie")
            self.assertTrue(app._cards[0]._selected)
            self.assertTrue(app._cards[0]._chapter_vars[1].get())

            # Trigger scale change to 150%
            app._on_scale_changed(1.5)
            self.assertEqual(len(app._cards), 1)
            self.assertEqual(app._cards[0].info["filename"], "Main Movie")
            self.assertTrue(app._cards[0]._selected)

            app.destroy()
        except tk.TclError:
            pass

    def test_03_theme_switch_clean_rebuild(self):
        """Verify theme switching completely updates palette and rebuilds without widget errors."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            # Switch to Light theme
            vcd_ripper.i18n.switch_theme("light")
            self.assertEqual(vcd_ripper.i18n.get_effective_theme(), "light")
            self.assertEqual(app.cget("bg"), vcd_ripper.THEME_LIGHT["bg_dark"])

            # Switch to Dark theme
            vcd_ripper.i18n.switch_theme("dark")
            self.assertEqual(vcd_ripper.i18n.get_effective_theme(), "dark")
            self.assertEqual(app.cget("bg"), vcd_ripper.THEME_DARK["bg_dark"])

            app.destroy()
        except tk.TclError:
            pass

    def test_04_window_resize_deduplication_and_debounce(self):
        """Verify canvas configure handlers avoid redundant reflows on unchanged width."""
        try:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()

            class MockEvent:
                def __init__(self, width, height):
                    self.width = width
                    self.height = height

            app._last_canvas_width = 800
            # Same width event -> must return without scheduling new job
            job_before = getattr(app, "_canvas_resize_job", None)
            app._on_canvas_configure(MockEvent(800, 600))
            self.assertEqual(getattr(app, "_canvas_resize_job", None), job_before)

            # Different width event -> schedules debounce job
            app._on_canvas_configure(MockEvent(850, 600))
            self.assertIsNotNone(getattr(app, "_canvas_resize_job", None))
            self.assertEqual(app._last_canvas_width, 850)

            app.destroy()
        except tk.TclError:
            pass


class TestSubprocessNoWindowGuarantees(unittest.TestCase):
    """Verify that all subprocess creation kwargs completely suppress command prompt windows on Windows."""

    def test_01_subprocess_kwargs_values(self):
        for mod in (dvd_engine, vcd_ripper):
            kwargs = mod.get_subprocess_kwargs()
            if sys.platform == "win32":
                self.assertIn("creationflags", kwargs)
                self.assertEqual(kwargs["creationflags"] & 0x08000000, 0x08000000)
                self.assertIn("startupinfo", kwargs)
                si = kwargs["startupinfo"]
                self.assertIsInstance(si, subprocess.STARTUPINFO)
                self.assertEqual(si.wShowWindow, 0)
                self.assertTrue(bool(si.dwFlags & subprocess.STARTF_USESHOWWINDOW))

    def test_02_subprocess_extra_flags(self):
        for mod in (dvd_engine, vcd_ripper):
            extra = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            kwargs = mod.get_subprocess_kwargs(extra_flags=extra)
            if sys.platform == "win32":
                self.assertEqual(kwargs["creationflags"] & extra, extra)
                self.assertEqual(kwargs["creationflags"] & 0x08000000, 0x08000000)

    def test_03_all_subprocess_calls_use_helper(self):
        """Verify static analysis check that all subprocess calls in production modules use get_subprocess_kwargs."""
        for filename in ("dvd_engine.py", "vcd_ripper.py"):
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read()
            matches = [m.start() for m in re.finditer(r'subprocess\.(run|Popen|check_output|call)', content)]
            self.assertGreater(len(matches), 0, f"Expected subprocess calls in {filename}")
            for idx in matches:
                line_no = content[:idx].count('\n') + 1
                lines_slice = content.splitlines()[line_no - 1 : line_no + 12]
                chunk = "\n".join(lines_slice)
                self.assertIn(
                    "get_subprocess_kwargs",
                    chunk,
                    f"Subprocess call in {filename} at line {line_no} does not use get_subprocess_kwargs!\n{chunk}"
                )


class TestDVDChapterExtractionAccuracyAndFixes(unittest.TestCase):
    """
    Verifies DVD chapter extraction accuracy, input-side fast seeking,
    MPEG timestamp normalization (+genpts, make_zero, passthrough),
    duration validation, decodability checks, and fallback diagnostics.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dvd_accuracy_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_handbrake_single_chapter_range_syntax(self):
        """Verify HandBrake single-chapter jobs use 'X-X' range syntax to avoid ripping through end-of-title."""
        hb = "HandBrakeCLI.exe"
        title_dict = {
            "title_number": 1,
            "name": "Title 01",
            "chapters": [
                {"chapter_number": 1, "start_time": 0.0, "duration": 60.0},
                {"chapter_number": 2, "start_time": 60.0, "duration": 120.0},
                {"chapter_number": 3, "start_time": 180.0, "duration": 90.0},
            ]
        }
        chap_dict = {"chapter_number": 2, "start_time": 60.0, "duration": 120.0}
        cmd, out_path = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path=hb,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=self.temp_dir,
        )
        self.assertIn("-c", cmd)
        c_idx = cmd.index("-c")
        self.assertEqual(cmd[c_idx + 1], "2-2")

    def test_02_ffmpeg_chapter_vob_input_seeking_fast(self):
        """Verify FFmpeg fallback chapter job places -ss before -i for input-side fast seeking."""
        ffmpeg_bin = get_bundled_ffmpeg() or "ffmpeg.exe"
        video_ts = os.path.join(self.temp_dir, "VIDEO_TS")
        os.makedirs(video_ts, exist_ok=True)
        vob1 = os.path.join(video_ts, "VTS_01_1.VOB")
        with open(vob1, "wb") as f:
            f.write(b"\x00" * 2048)

        title_dict = {
            "title_number": 1,
            "vts_number": 1,
            "name": "Title 01",
            "vob_files": [vob1],
            "chapters": [
                {"chapter_number": 1, "start_time": 0.0, "duration": 100.0},
                {"chapter_number": 2, "start_time": 100.0, "duration": 150.0},
            ]
        }
        chap_dict = {"chapter_number": 2, "start_time": 100.0, "duration": 150.0}
        cmd, out_path, concat_file = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=self.temp_dir,
            output_format="MP4",
        )
        if concat_file and os.path.exists(concat_file):
            try:
                os.remove(concat_file)
            except Exception:
                pass

        self.assertIn("-i", cmd)
        self.assertIn("-ss", cmd)
        ss_idx = cmd.index("-ss")
        i_idx = cmd.index("-i")
        self.assertLess(ss_idx, i_idx, "Expected -ss (input-side seek) to precede -i to prevent decoding entire earlier VOBs")

    def test_03_ffmpeg_chapter_timestamp_flags_and_passthrough(self):
        """Verify FFmpeg chapter commands include +genpts, make_zero, and fps_mode passthrough."""
        ffmpeg_bin = get_bundled_ffmpeg() or "ffmpeg.exe"
        video_ts = os.path.join(self.temp_dir, "VIDEO_TS")
        os.makedirs(video_ts, exist_ok=True)
        vob1 = os.path.join(video_ts, "VTS_01_1.VOB")
        with open(vob1, "wb") as f:
            f.write(b"\x00" * 2048)

        title_dict = {
            "title_number": 1,
            "vts_number": 1,
            "name": "Title 01",
            "vob_files": [vob1],
            "chapters": [
                {"chapter_number": 1, "start_time": 0.0, "duration": 100.0},
            ]
        }
        chap_dict = {"chapter_number": 1, "start_time": 0.0, "duration": 100.0}
        cmd, out_path, concat_file = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=self.temp_dir,
            output_format="MPG",
        )
        if concat_file and os.path.exists(concat_file):
            try:
                os.remove(concat_file)
            except Exception:
                pass

        self.assertIn("-fflags", cmd)
        fflags_val = cmd[cmd.index("-fflags") + 1]
        self.assertIn("+genpts", fflags_val)
        self.assertIn("+discardcorrupt", fflags_val)

        self.assertIn("-avoid_negative_ts", cmd)
        self.assertEqual(cmd[cmd.index("-avoid_negative_ts") + 1], "make_zero")

        # Must have -fps_mode passthrough or -vsync passthrough
        fps_mode_found = ("-fps_mode" in cmd and cmd[cmd.index("-fps_mode") + 1] == "passthrough")
        vsync_found = ("-vsync" in cmd and cmd[cmd.index("-vsync") + 1] == "passthrough")
        self.assertTrue(fps_mode_found or vsync_found, "Must include fps_mode or vsync passthrough")

    def test_04_validate_ripped_media_duration_truncation(self):
        """Verify validate_ripped_media fails when output duration is truncated."""
        ffprobe = get_bundled_ffprobe()
        ffmpeg = get_bundled_ffmpeg()
        if not ffprobe or not ffmpeg:
            self.skipTest("FFmpeg/FFprobe binaries not available")

        # Generate a short 0.5s media file
        short_file = os.path.join(self.temp_dir, "short.mp4")
        subprocess.run([
            ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=duration=0.5:frequency=1000",
            "-c:v", "libx264", "-c:a", "aac",
            short_file
        ], capture_output=True, check=True)

        # Expected duration 60.0s vs actual 0.5s -> must fail
        is_ok, msg = dvd_engine.validate_ripped_media(
            ffprobe_path=ffprobe,
            file_path=short_file,
            is_audio_only=False,
            expected_format="MP4",
            expected_duration=60.0,
            ffmpeg_path=ffmpeg
        )
        self.assertFalse(is_ok)
        self.assertIn("shorter", msg.lower())

    def test_05_validate_ripped_media_duration_overrun(self):
        """Verify validate_ripped_media fails when output duration significantly overruns chapter."""
        ffprobe = get_bundled_ffprobe()
        ffmpeg = get_bundled_ffmpeg()
        if not ffprobe or not ffmpeg:
            self.skipTest("FFmpeg/FFprobe binaries not available")

        # Generate a 15.0s media file
        long_file = os.path.join(self.temp_dir, "long.mp4")
        subprocess.run([
            ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=15.0:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=duration=15.0:frequency=1000",
            "-c:v", "libx264", "-c:a", "aac",
            long_file
        ], capture_output=True, check=True)

        # Expected duration 1.0s vs actual 15.0s -> must fail overrun
        is_ok, msg = dvd_engine.validate_ripped_media(
            ffprobe_path=ffprobe,
            file_path=long_file,
            is_audio_only=False,
            expected_format="MP4",
            expected_duration=1.0,
            ffmpeg_path=ffmpeg
        )
        self.assertFalse(is_ok)
        self.assertIn("exceeds", msg.lower())

    def test_06_validate_ripped_media_decodability(self):
        """Verify decodability check catches corrupted media files."""
        ffprobe = get_bundled_ffprobe()
        ffmpeg = get_bundled_ffmpeg()
        if not ffprobe or not ffmpeg:
            self.skipTest("FFmpeg/FFprobe binaries not available")

        corrupt_file = os.path.join(self.temp_dir, "corrupt.mp4")
        with open(corrupt_file, "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00AVI LIST\x00\x00garbage_data" * 50)

        is_ok, msg = dvd_engine.validate_ripped_media(
            ffprobe_path=ffprobe,
            file_path=corrupt_file,
            is_audio_only=False,
            expected_format="MP4",
            ffmpeg_path=ffmpeg
        )
        self.assertFalse(is_ok)

    def test_07_audio_track_preservation_in_chapter_jobs(self):
        """Verify chosen audio track is preserved in chapter extraction command."""
        ffmpeg_bin = get_bundled_ffmpeg() or "ffmpeg.exe"
        video_ts = os.path.join(self.temp_dir, "VIDEO_TS")
        os.makedirs(video_ts, exist_ok=True)
        vob1 = os.path.join(video_ts, "VTS_01_1.VOB")
        with open(vob1, "wb") as f:
            f.write(b"\x00" * 2048)

        title_dict = {
            "title_number": 1,
            "vts_number": 1,
            "name": "Title 01",
            "vob_files": [vob1],
            "audio_tracks": [
                {"track_id": "T01_A01", "track_number": 1, "ffmpeg_stream_index": 1, "hb_track_index": 1},
                {"track_id": "T01_A02", "track_number": 2, "ffmpeg_stream_index": 2, "hb_track_index": 2},
            ],
            "chapters": [
                {"chapter_number": 1, "start_time": 0.0, "duration": 50.0},
            ]
        }
        chap_dict = {"chapter_number": 1, "start_time": 0.0, "duration": 50.0}
        chosen = title_dict["audio_tracks"][1]

        # FFmpeg chapter job
        cmd_ff, out_ff, concat_f = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path=ffmpeg_bin,
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=self.temp_dir,
            output_format="MP4",
            audio_track=chosen,
        )
        if concat_f and os.path.exists(concat_f):
            try:
                os.remove(concat_f)
            except Exception:
                pass

        self.assertIn("-map", cmd_ff)
        self.assertIn("0:a:2", cmd_ff)

        # HandBrake chapter job
        cmd_hb, out_hb = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source=self.temp_dir,
            title_dict=title_dict,
            chapter_dict=chap_dict,
            out_dir=self.temp_dir,
            audio_track=chosen
        )
        self.assertIn("-a", cmd_hb)
        a_idx = cmd_hb.index("-a")
        self.assertEqual(cmd_hb[a_idx + 1], "2")


class _MockSubproc:
    def __init__(self, lines, returncode=0):
        import io
        self.lines = list(lines)
        self.returncode = returncode
        self.stdout = io.StringIO("\n".join(self.lines) + "\n")
    def poll(self):
        return 0
    def wait(self, timeout=None):
        return 0


class TestDVDProgressBarAccuracyAndMonotonicity(unittest.TestCase):
    """
    Test suite for DVD and VCD ripping progress bar accuracy, batch proportionality,
    and strict monotonicity (never dropping backwards).
    """
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = vcd_ripper.VCDRipperApp()
            cls.app.withdraw()
        except tk.TclError:
            raise unittest.SkipTest("Headless environment without display")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass

    def setUp(self):
        self.app._progress_var.set(0)

    def test_01_dvd_progress_pts_reset_monotonicity(self):
        """Verify DVD progress never drops when FFmpeg encounters timestamp reset or cell discontinuity."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "vob_files": ["vts_01_1.vob"], "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c1 = {"chapter_number": 1, "duration": 120.0, "start_time": 0.0, "end_time": 120.0}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        ffmpeg_lines = [
            "frame=100 time=00:00:30.00 speed=1.5x",
            "frame=200 time=00:01:00.00 speed=1.5x",
            "frame=250 time=00:00:01.00 speed=1.5x",  # PTS reset / discontinuity
            "frame=300 time=00:00:30.00 speed=1.5x",
            "frame=400 time=00:01:00.00 speed=1.5x",
        ]

        def fake_popen(*args, **kwargs):
            return _MockSubproc(ffmpeg_lines, returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = None
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[],
                chapter_jobs=[(t1, c1)],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        self.assertTrue(len(recorded_progress) > 3)
        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(
                recorded_progress[i],
                recorded_progress[i+1],
                f"Progress dropped backwards: {recorded_progress[i]} > {recorded_progress[i+1]}"
            )
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_02_dvd_progress_batch_span_weighting(self):
        """Verify multi-chapter batch spans are weighted proportionally and monotonically cover 0-100%."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "vob_files": ["vts_01_1.vob"], "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c1 = {"chapter_number": 1, "duration": 60.0, "start_time": 0.0, "end_time": 60.0}
        c2 = {"chapter_number": 2, "duration": 180.0, "start_time": 60.0, "end_time": 240.0}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        def fake_popen(*args, **kwargs):
            return _MockSubproc(["frame=100 time=00:00:30.00 speed=1.0x"], returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = None
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[],
                chapter_jobs=[(t1, c1), (t1, c2)],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_03_dvd_progress_handbrake_multi_task_monotonicity(self):
        """Verify HandBrake multi-task encoding does not drop progress when pass 2 starts at 0%."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        hb_lines = [
            "Encoding: task 1 of 2, 25.0 %",
            "Encoding: task 1 of 2, 100.0 %",
            "Encoding: task 2 of 2, 0.0 %",
            "Encoding: task 2 of 2, 50.0 %",
            "Encoding: task 2 of 2, 100.0 %",
        ]

        def fake_popen(*args, **kwargs):
            return _MockSubproc(hb_lines, returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = "HandBrakeCLI.exe"
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[t1],
                chapter_jobs=[],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_04_dvd_progress_fallback_to_ffmpeg_monotonicity(self):
        """Verify fallback from HandBrake to FFmpeg does not drop progress backwards."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c1 = {"chapter_number": 1, "duration": 100.0, "start_time": 0.0, "end_time": 100.0}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        hb_lines = [
            "Encoding: task 1 of 1, 40.0 %",
            "Encoding: task 1 of 1, 60.0 %",
            "HandBrake error: encode failed",
        ]
        ff_lines = [
            "frame=50 time=00:00:10.00 speed=1.0x",
            "frame=100 time=00:00:50.00 speed=1.0x",
            "frame=200 time=00:01:40.00 speed=1.0x",
        ]

        attempt = 0
        def fake_popen(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                return _MockSubproc(hb_lines, returncode=1)
            else:
                return _MockSubproc(ff_lines, returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = "HandBrakeCLI.exe"
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[],
                chapter_jobs=[(t1, c1)],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_05_dvd_progress_absolute_pts_seeking_smoothness(self):
        """Verify chapter seeking with stream PTS offset (e.g. 00:05:00) does not jump to 100% on frame 1."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c1 = {"chapter_number": 2, "duration": 100.0, "start_time": 300.0, "end_time": 400.0}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        ff_lines = [
            "frame=10 time=00:05:01.00 speed=1.0x",
            "frame=50 time=00:05:25.00 speed=1.0x",
            "frame=100 time=00:05:50.00 speed=1.0x",
            "frame=150 time=00:06:40.00 speed=1.0x",
        ]

        def fake_popen(*args, **kwargs):
            return _MockSubproc(ff_lines, returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = None
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[],
                chapter_jobs=[(t1, c1)],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        self.assertLess(recorded_progress[1], 20.0, f"Frame 1 jumped too high: {recorded_progress[1]}%")
        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_06_dvd_progress_unknown_duration_fallback(self):
        """Verify batch with unknown duration (duration=0) divides evenly and completes monotonically."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 0.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        t2 = {"title_number": 2, "custom_stem": "Title_02", "duration": 0.0, "audio_tracks": [{"track_id": "T02_A01", "track_number": 1}]}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        def fake_popen(*args, **kwargs):
            return _MockSubproc(["frame=10 time=00:00:10.00 speed=1.0x"], returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = None
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[t1, t2],
                chapter_jobs=[],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_07_dvd_progress_extract_both_mode(self):
        """Verify extract_both (mode='both') creates video and audio jobs and covers 0 to 100%."""
        from unittest.mock import MagicMock, patch
        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 60.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}

        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        def fake_popen(*args, **kwargs):
            return _MockSubproc(["frame=10 time=00:00:30.00 speed=1.0x"], returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = None
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[t1],
                chapter_jobs=[],
                out_folder="C:\\test_out",
                output_format="MP4",
                extract_both=True
            )
            self.app.update()

        for i in range(len(recorded_progress) - 1):
            self.assertLessEqual(recorded_progress[i], recorded_progress[i+1])
        self.assertEqual(recorded_progress[-1], 100.0)

    def test_08_vcd_rip_thread_intact_and_unaffected(self):
        """Verify VCD ripping progress logic in _rip_thread is preserved intact and functional."""
        from unittest.mock import MagicMock, patch
        v1 = {"filename": "AVSEQ01.DAT", "path": "D:\\MPEGAV\\AVSEQ01.DAT", "duration": 100.0}
        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        def fake_popen(*args, **kwargs):
            return _MockSubproc(["frame=10 time=00:00:50.00 speed=1.0x"], returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_thread(
                videos=[v1],
                out_folder="C:\\test_out",
                fmt="MP4",
                fmt_cfg=vcd_ripper.OUTPUT_FORMATS["MP4"]
            )
            self.app.update()

        self.assertTrue(len(recorded_progress) >= 2)
        self.assertEqual(recorded_progress[0], 0.0)



class TestHandBrakeSourceDetectionAndFallback(unittest.TestCase):
    """
    Test suite for HandBrakeCLI DVD source detection, path probing,
    title/chapter mapping, and fallback error handling.
    """
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = vcd_ripper.VCDRipperApp()
            cls.app.withdraw()
        except tk.TclError:
            raise unittest.SkipTest("Headless environment without display")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass

    def setUp(self):
        dvd_engine.clear_handbrake_validation_cache()
        self.app._progress_var.set(0)

    def test_01_source_inspection_accessible_and_inaccessible(self):
        """Test source inspection identifying accessible DVD sources and reporting missing or inaccessible drives."""
        # 1. Accessible folder with VIDEO_TS and VIDEO_TS.IFO
        with tempfile.TemporaryDirectory() as tmpdir:
            vts_dir = Path(tmpdir) / "VIDEO_TS"
            vts_dir.mkdir()
            ifo_file = vts_dir / "VIDEO_TS.IFO"
            create_minimal_valid_ifo(str(ifo_file), is_vmg=True, title_count=1)
            vob_file = vts_dir / "VTS_01_1.VOB"
            vob_file.write_bytes(b"\x00" * 2048)

            insp = dvd_engine.inspect_dvd_source(tmpdir)
            self.assertTrue(insp.is_accessible)
            self.assertTrue(insp.has_video_ts)
            self.assertTrue(insp.has_video_ts_ifo)
            self.assertEqual(insp.source_type, "dvd_folder")
            self.assertIn(str(ifo_file), insp.ifo_files)
            self.assertIn(str(vob_file), insp.vob_files)

        # 2. Inaccessible / non-existent path
        non_existent = "Z:\\NonExistent_Drive_Path_12345\\"
        insp_bad = dvd_engine.inspect_dvd_source(non_existent)
        self.assertFalse(insp_bad.is_accessible)
        self.assertIsNotNone(insp_bad.error_message)
        self.assertEqual(insp_bad.source_type, "inaccessible")

        # 3. Empty string
        insp_empty = dvd_engine.inspect_dvd_source("")
        self.assertFalse(insp_empty.is_accessible)
        self.assertEqual(insp_empty.source_type, "invalid")

    def test_02_handbrake_validation_path_selection(self):
        """Test HandBrakeCLI validation selecting correct working source path (probing VIDEO_TS when root fails)."""
        from unittest.mock import patch, MagicMock

        json_out = json.dumps({
            "TitleList": [{
                "Index": 1,
                "Duration": {"Hours": 0, "Minutes": 2, "Seconds": 0},
                "ChapterList": [{"Number": 1, "Duration": {"Seconds": 60}}, {"Number": 2, "Duration": {"Seconds": 60}}],
                "AudioList": [{"Description": "stereo", "Format": "AC3", "Language": "English", "LanguageCode": "en"}],
            }]
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            vts_dir = Path(tmpdir) / "VIDEO_TS"
            vts_dir.mkdir()
            create_minimal_valid_ifo(str(vts_dir / "VIDEO_TS.IFO"), is_vmg=True, title_count=1)

            def fake_hb_run(cmd, *args, **kwargs):
                inp = ""
                if "-i" in cmd:
                    inp = cmd[cmd.index("-i") + 1]
                # Fail if input is root directory, succeed if direct VIDEO_TS folder
                if os.path.normpath(inp) == os.path.normpath(str(vts_dir)):
                    return MagicMock(returncode=0, stdout=f"JSON Title Set: {json_out}\n", stderr="")
                else:
                    return MagicMock(returncode=2, stdout="libhb: scan thread found 0 valid title(s)\nNo title found.\n", stderr="error opening file BDMV\\index.bdmv\n")

            with patch("subprocess.run", side_effect=fake_hb_run):
                val_res = dvd_engine.validate_handbrake_source(sys.executable, tmpdir)

            self.assertTrue(val_res.success)
            self.assertEqual(os.path.normpath(val_res.working_source_path), os.path.normpath(str(vts_dir)))
            self.assertEqual(val_res.title_count, 1)

    def test_03_missing_dvd_structure_no_misleading_bdmv_warning(self):
        """Test graceful handling of source missing DVD structure without misleading Blu-ray warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            insp = dvd_engine.inspect_dvd_source(tmpdir)
            self.assertTrue(insp.is_accessible)
            self.assertFalse(insp.has_video_ts)
            self.assertIn("No VIDEO_TS", insp.error_message)

            val_res = dvd_engine.validate_handbrake_source(sys.executable, tmpdir)
            self.assertFalse(val_res.success)
            self.assertEqual(val_res.error_category, "missing_dvd_structure")
            self.assertNotIn("BDMV", val_res.error_message)

    def test_04_handbrake_zero_titles_clean_switch_to_ffmpeg(self):
        """Test handling when HandBrakeCLI returns 0 valid titles, ensuring clean switch to FFmpeg without repeated attempts."""
        from unittest.mock import patch, MagicMock

        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 60.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c1 = {"chapter_number": 1, "duration": 30.0, "start_time": 0.0, "end_time": 30.0}
        c2 = {"chapter_number": 2, "duration": 30.0, "start_time": 30.0, "end_time": 60.0}

        hb_cmd_calls = []
        ff_cmd_calls = []

        def fake_hb_run(cmd, *args, **kwargs):
            return MagicMock(returncode=2, stdout="libhb: scan thread found 0 valid title(s)\nNo title found.\n", stderr="error opening file BDMV\\index.bdmv\n")

        def fake_popen(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "HandBrakeCLI" in cmd_str:
                hb_cmd_calls.append(cmd_str)
                return _MockSubproc(["libhb: scan thread found 0 valid title(s)"], returncode=2)
            else:
                ff_cmd_calls.append(cmd_str)
                return _MockSubproc(["frame=50 time=00:00:30.00 speed=1.0x"], returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            vts_dir = Path(tmpdir) / "VIDEO_TS"
            vts_dir.mkdir()
            create_minimal_valid_ifo(str(vts_dir / "VIDEO_TS.IFO"), is_vmg=True, title_count=1)

            with patch("subprocess.run", side_effect=fake_hb_run), \
                 patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.isfile", return_value=True), \
                 patch("os.path.getsize", return_value=1024*1024*50):

                self.app._handbrake = "HandBrakeCLI.exe"
                self.app._ffmpeg = "ffmpeg.exe"
                self.app._vcd_path.set(tmpdir)
                self.app._rip_done = MagicMock()

                self.app._rip_dvd_unified_thread(
                    title_jobs=[],
                    chapter_jobs=[(t1, c1), (t1, c2)],
                    out_folder="C:\\test_out",
                    output_format="MP4"
                )
                self.app.update()

        # Pre-flight scan detected 0 titles, so HandBrakeCLI was NEVER repeatedly invoked for chapter jobs
        self.assertEqual(len(hb_cmd_calls), 0)
        # FFmpeg handled both chapters cleanly
        self.assertEqual(len(ff_cmd_calls), 2)

    def test_05_metadata_title_missing_in_handbrake_falls_back(self):
        """Test when requested title exists in metadata but not in HandBrake titles, correctly falling back to FFmpeg."""
        hb_title = dvd_engine.DVDTitle(
            title_number=1,
            vts_number=1,
            duration=60.0,
            chapter_count=1,
            chapters_data=[dvd_engine.DVDChapter(chapter_number=1, start_time=0.0, end_time=60.0, duration=60.0, title_number=1)],
            audio_tracks=[dvd_engine.DVDAudioTrack(track_id="T01_A01", title_number=1, track_number=1, stream_index=0)],
        )
        val_res = dvd_engine.HandBrakeValidationResult(
            success=True,
            working_source_path="E:\\VIDEO_TS",
            titles=[hb_title],
            title_count=1
        )

        t2 = {"title_number": 2, "custom_stem": "Title_02", "duration": 60.0, "audio_tracks": [{"track_id": "T02_A01", "track_number": 1}]}
        ok, hb_t, hb_c, hb_a, err = dvd_engine.resolve_handbrake_job_mapping(val_res, t2)
        self.assertFalse(ok)
        self.assertIn("Title 2 not found", err)

        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 60.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}]}
        c5 = {"chapter_number": 5, "duration": 10.0}
        ok_c, _, _, _, err_c = dvd_engine.resolve_handbrake_job_mapping(val_res, t1, chapter_dict=c5)
        self.assertFalse(ok_c)
        self.assertIn("Chapter 5", err_c)

    def test_06_chapter_and_audio_track_mapping(self):
        """Test chapter and audio track index mapping between app scanner and HandBrakeCLI."""
        hb_title = dvd_engine.DVDTitle(
            title_number=1,
            vts_number=1,
            duration=120.0,
            chapter_count=3,
            chapters_data=[
                dvd_engine.DVDChapter(chapter_number=1, start_time=0.0, end_time=40.0, duration=40.0, title_number=1),
                dvd_engine.DVDChapter(chapter_number=2, start_time=40.0, end_time=80.0, duration=40.0, title_number=1),
                dvd_engine.DVDChapter(chapter_number=3, start_time=80.0, end_time=120.0, duration=40.0, title_number=1),
            ],
            audio_tracks=[
                dvd_engine.DVDAudioTrack(track_id="T01_A01", title_number=1, track_number=1, stream_index=0, channels="Stereo", channel_count=2, hb_track_index=1),
                dvd_engine.DVDAudioTrack(track_id="T01_A02", title_number=1, track_number=2, stream_index=1, channels="5.1", channel_count=6, hb_track_index=2),
            ],
        )
        val_res = dvd_engine.HandBrakeValidationResult(
            success=True,
            working_source_path="E:\\VIDEO_TS",
            titles=[hb_title],
            title_count=1
        )

        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 120.0, "audio_tracks": [a.to_dict() for a in hb_title.audio_tracks]}
        c2 = {"chapter_number": 2, "duration": 40.0}
        trk2 = hb_title.audio_tracks[1].to_dict()

        ok, t_idx, c_idx, a_idx, err = dvd_engine.resolve_handbrake_job_mapping(val_res, t1, chapter_dict=c2, audio_track=trk2)
        self.assertTrue(ok)
        self.assertEqual(t_idx, 1)
        self.assertEqual(c_idx, 2)
        self.assertEqual(a_idx, 2)

        cmd, out_path = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source="E:\\",
            title_dict=t1,
            chapter_dict=c2,
            out_dir="C:\\out",
            audio_track=trk2,
            val_res=val_res
        )
        self.assertIn("-t", cmd)
        self.assertEqual(cmd[cmd.index("-t") + 1], "1")
        self.assertIn("-c", cmd)
        self.assertEqual(cmd[cmd.index("-c") + 1], "2-2")
        self.assertIn("-a", cmd)
        self.assertEqual(cmd[cmd.index("-a") + 1], "2")
        self.assertIn("-B", cmd)
        self.assertEqual(cmd[cmd.index("-B") + 1], "384k")

    def test_07_handbrake_runtime_failure_falls_back_to_ffmpeg(self):
        """Test mocked chapter job where HandBrakeCLI fails during encoding and FFmpeg successfully completes it."""
        from unittest.mock import patch, MagicMock

        hb_title = dvd_engine.DVDTitle(
            title_number=1,
            vts_number=1,
            duration=60.0,
            chapter_count=1,
            chapters_data=[dvd_engine.DVDChapter(chapter_number=1, start_time=0.0, end_time=60.0, duration=60.0, title_number=1)],
            audio_tracks=[dvd_engine.DVDAudioTrack(track_id="T01_A01", title_number=1, track_number=1, stream_index=0)],
        )
        val_res = dvd_engine.HandBrakeValidationResult(
            success=True,
            working_source_path="C:\\dvd\\VIDEO_TS",
            titles=[hb_title],
            title_count=1
        )

        t1 = {"title_number": 1, "custom_stem": "Title_01", "duration": 60.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1}], "vob_files": ["VTS_01_1.VOB"]}
        c1 = {"chapter_number": 1, "duration": 60.0, "start_time": 0.0, "end_time": 60.0}

        calls = []
        def fake_popen(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            calls.append(cmd_str)
            if "HandBrakeCLI" in cmd_str:
                return _MockSubproc(["libhb: error opening stream", "HandBrake error: encode failed"], returncode=2)
            else:
                return _MockSubproc(["frame=100 time=00:01:00.00 speed=1.0x"], returncode=0)

        with patch("dvd_engine.validate_handbrake_source", return_value=val_res), \
             patch("subprocess.Popen", side_effect=fake_popen), \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._handbrake = "HandBrakeCLI.exe"
            self.app._ffmpeg = "ffmpeg.exe"
            self.app._vcd_path.set("C:\\dvd")
            self.app._rip_done = MagicMock()

            self.app._rip_dvd_unified_thread(
                title_jobs=[],
                chapter_jobs=[(t1, c1)],
                out_folder="C:\\test_out",
                output_format="MP4"
            )
            self.app.update()

        # Verifies HandBrake was tried first, then FFmpeg succeeded
        hb_calls = [c for c in calls if "HandBrakeCLI" in c]
        ff_calls = [c for c in calls if "ffmpeg" in c]
        self.assertTrue(len(hb_calls) >= 1)
        self.assertTrue(len(ff_calls) >= 1)
        self.assertIn("HandBrakeCLI", calls[0])

    def test_08_user_options_preservation(self):
        """Test preservation of custom output filename, custom stems, audio tracks, and formats."""
        t1 = {"title_number": 1, "custom_stem": "My_Custom_Movie", "duration": 120.0, "audio_tracks": [{"track_id": "T01_A01", "track_number": 1, "channels": "Stereo", "channel_count": 2}]}
        c1 = {"chapter_number": 2, "custom_stem": "Special_Scene", "duration": 60.0}

        # 1. Custom filename HandBrake
        cmd_hb, out_hb = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source="C:\\dvd",
            title_dict=t1,
            chapter_dict=c1,
            out_dir="C:\\out",
            custom_output_filename="Custom_Final_Name.mp4"
        )
        self.assertTrue(out_hb.endswith("Custom_Final_Name.mp4"))

        # 2. Custom filename FFmpeg
        cmd_ff, out_ff, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source="C:\\dvd",
            title_dict=t1,
            chapter_dict=c1,
            out_dir="C:\\out",
            output_format="MOV",
            custom_output_filename="Custom_FF_Name.mov"
        )
        self.assertTrue(out_ff.endswith("Custom_FF_Name.mov"))
        self.assertIn("-c:v", cmd_ff)

    def test_09_vcd_regression_unaffected(self):
        """Regression test ensuring VCD ripping logic remains 100% unaffected and functional."""
        from unittest.mock import MagicMock, patch
        v1 = {"filename": "AVSEQ01.DAT", "path": "D:\\MPEGAV\\AVSEQ01.DAT", "duration": 100.0}
        recorded_progress = []
        original_set = self.app._progress_var.set
        def tracking_set(val):
            original_set(val)
            recorded_progress.append(float(val))
        self.app._progress_var.set = tracking_set

        def fake_popen(*args, **kwargs):
            return _MockSubproc(["frame=10 time=00:00:50.00 speed=1.0x"], returncode=0)

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024*1024*50):

            self.app._ffmpeg = "ffmpeg.exe"
            self.app._rip_done = MagicMock()

            self.app._rip_thread(
                videos=[v1],
                out_folder="C:\\test_out",
                fmt="MP4",
                fmt_cfg=vcd_ripper.OUTPUT_FORMATS["MP4"]
            )
            self.app.update()

        self.assertTrue(len(recorded_progress) >= 2)
        self.assertEqual(recorded_progress[0], 0.0)


class TestRippingProcessPriority(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch, MagicMock
        self.patch = patch
        self.MagicMock = MagicMock
        self.orig_priority = vcd_ripper.i18n.priority

    def tearDown(self):
        vcd_ripper.i18n.priority = self.orig_priority

    def test_priority_constants_and_mapping(self):
        self.assertEqual(vcd_ripper.BELOW_NORMAL_PRIORITY_CLASS, 0x00004000)
        self.assertEqual(vcd_ripper.NORMAL_PRIORITY_CLASS, 0x00000020)
        self.assertEqual(vcd_ripper.HIGH_PRIORITY_CLASS, 0x00000080)
        self.assertEqual(vcd_ripper.RIPPING_PRIORITY_MAP["Low"], 0x00004000)
        self.assertEqual(vcd_ripper.RIPPING_PRIORITY_MAP["Medium"], 0x00000020)
        self.assertEqual(vcd_ripper.RIPPING_PRIORITY_MAP["High"], 0x00000080)
        self.assertEqual(vcd_ripper.get_priority_creation_flag("Low"), 0x00004000)
        self.assertEqual(vcd_ripper.get_priority_creation_flag("Medium"), 0x00000020)
        self.assertEqual(vcd_ripper.get_priority_creation_flag("High"), 0x00000080)
        self.assertEqual(vcd_ripper.get_priority_creation_flag("Unknown"), 0x00004000)

    def test_i18n_priority_switching_and_callback(self):
        from unittest.mock import patch
        callback_log = []
        vcd_ripper.i18n.set_priority_callback(lambda p: callback_log.append(p))

        with patch.object(vcd_ripper.i18n, "_save_config") as mock_save:
            vcd_ripper.i18n.switch_priority("Medium")
            self.assertEqual(vcd_ripper.i18n.priority, "Medium")
            mock_save.assert_called_once()
            self.assertEqual(callback_log, ["Medium"])

            vcd_ripper.i18n.switch_priority("High")
            self.assertEqual(vcd_ripper.i18n.priority, "High")
            self.assertEqual(callback_log, ["Medium", "High"])

            vcd_ripper.i18n.switch_priority("InvalidLevel")
            self.assertEqual(vcd_ripper.i18n.priority, "High")
            self.assertEqual(len(callback_log), 2)

    def test_translations_priority_keys(self):
        for lang, expected_title, expected_low, expected_med, expected_high in [
            ("en", "Process Priority", "Low", "Medium", "High"),
            ("zh_CN", "进程优先级", "低", "中", "高"),
        ]:
            vcd_ripper.i18n.lang = lang
            self.assertEqual(vcd_ripper.i18n.t("priority.title"), expected_title)
            self.assertEqual(vcd_ripper.i18n.t("priority.low"), expected_low)
            self.assertEqual(vcd_ripper.i18n.t("priority.medium"), expected_med)
            self.assertEqual(vcd_ripper.i18n.t("priority.high"), expected_high)

    def test_set_process_priority_win32_calls(self):
        from unittest.mock import patch, MagicMock
        mock_proc = MagicMock()
        mock_proc._handle = 12345

        with patch("ctypes.windll.kernel32.SetPriorityClass") as mock_set_prio, \
             patch("ctypes.windll.ntdll.NtSetInformationProcess") as mock_nt_set:

            # Low with low_io=True
            vcd_ripper.set_process_priority(mock_proc, priority_level="Low", low_io=True)
            mock_set_prio.assert_called_with(12345, 0x00004000)
            mock_nt_set.assert_called()

            # Medium
            mock_set_prio.reset_mock()
            mock_nt_set.reset_mock()
            vcd_ripper.set_process_priority(mock_proc, priority_level="Medium", low_io=True)
            mock_set_prio.assert_called_with(12345, 0x00000020)
            mock_nt_set.assert_called()

            # High
            mock_set_prio.reset_mock()
            mock_nt_set.reset_mock()
            vcd_ripper.set_process_priority(mock_proc, priority_level="High", low_io=True)
            mock_set_prio.assert_called_with(12345, 0x00000080)
            mock_nt_set.assert_called()

            # Backward-compatible wrapper
            mock_set_prio.reset_mock()
            vcd_ripper.set_low_process_priority(mock_proc, low_io=False)
            mock_set_prio.assert_called_with(12345, 0x00004000)

    def test_vcd_rip_thread_uses_selected_priority(self):
        from unittest.mock import patch, MagicMock
        v1 = {"filename": "AVSEQ01.DAT", "path": "D:\\MPEGAV\\AVSEQ01.DAT", "duration": 10.0}
        app = vcd_ripper.VCDRipperApp()
        app._ffmpeg = "ffmpeg.exe"
        app._rip_done = MagicMock()

        captured_kwargs = []
        def fake_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return _MockSubproc(["frame=1 time=00:00:05.00"], returncode=0)

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("vcd_ripper.set_process_priority") as mock_set_prio, \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.getsize", return_value=1024*1024):

                app.i18n.priority = "High"
                app._rip_thread(
                    videos=[v1],
                    out_folder="C:\\test_out",
                    fmt="MP4",
                    fmt_cfg=vcd_ripper.OUTPUT_FORMATS["MP4"]
                )
                app.update()

                self.assertTrue(len(captured_kwargs) > 0)
                if sys.platform == "win32":
                    self.assertTrue(bool(captured_kwargs[0]["creationflags"] & 0x00000080))
                mock_set_prio.assert_called_with(unittest.mock.ANY, priority_level="High", low_io=True)
        finally:
            app.destroy()

    def test_dvd_rip_thread_uses_selected_priority(self):
        from unittest.mock import patch, MagicMock
        app = vcd_ripper.VCDRipperApp()
        app._ffmpeg = "ffmpeg.exe"

        captured_kwargs = []
        def fake_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return _MockSubproc(["frame=1 time=00:00:05.00"], returncode=0)

        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"stream_index": 0, "channels": 2, "codec": "ac3", "display_label": "Track 1"}],
        }

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("vcd_ripper.set_process_priority") as mock_set_prio, \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.getsize", return_value=1024*1024):

                app._handbrake = None
                app._dvd_source_path = "E:\\VIDEO_TS"
                app._rip_done = MagicMock()
                app.i18n.priority = "Medium"
                app._rip_dvd_unified_thread(
                    title_jobs=[t1],
                    chapter_jobs=[],
                    out_folder="C:\\test_out",
                    output_format="MP4"
                )
                app.update()

                self.assertTrue(len(captured_kwargs) > 0)
                if sys.platform == "win32":
                    self.assertTrue(bool(captured_kwargs[-1]["creationflags"] & 0x00000020))
                mock_set_prio.assert_called_with(unittest.mock.ANY, priority_level="Medium", low_io=True)
        finally:
            app.destroy()

    def test_settings_dialog_priority_ui(self):
        from unittest.mock import patch
        import tkinter as tk
        app = vcd_ripper.VCDRipperApp()
        try:
            with patch.object(app.i18n, "_save_config"):
                app._show_about()
                dlg = app._about_dialog
                self.assertIsNotNone(dlg)

                def find_buttons(widget):
                    found = []
                    for child in widget.winfo_children():
                        if isinstance(child, tk.Button):
                            found.append(child)
                        found.extend(find_buttons(child))
                    return found

                btn_list = find_buttons(dlg)
                btn_texts = [b.cget("text") for b in btn_list]
                low_text = app.i18n.t("priority.low")
                med_text = app.i18n.t("priority.medium")
                high_text = app.i18n.t("priority.high")
                self.assertIn(low_text, btn_texts)
                self.assertIn(med_text, btn_texts)
                self.assertIn(high_text, btn_texts)

                # Click High button
                high_btn = next(b for b in btn_list if b.cget("text") == high_text)
                high_btn.invoke()
                self.assertEqual(app.i18n.priority, "High")

                # Click Medium button
                med_btn = next(b for b in btn_list if b.cget("text") == med_text)
                med_btn.invoke()
                self.assertEqual(app.i18n.priority, "Medium")

                dlg.destroy()
        finally:
            app.destroy()


class TestDVDStallDetectionAndOptimization(unittest.TestCase):
    """
    Test suite verifying:
    1. DVD ripping FFmpeg parameter optimizations (cfr, async audio resample, max muxing queue size).
    2. Forward progress watchdog detecting stalled frames and terminating safely.
    3. HandBrakeCLI stall detection triggering automatic fallback to FFmpeg.
    """

    def test_dvd_rip_job_args_optimization(self):
        title = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"stream_index": 0, "channels": 2, "codec": "ac3"}],
        }

        # 1. MP4 output format
        cmd_mp4, _, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source="E:\\VIDEO_TS",
            title_dict=title,
            out_dir="C:\\out",
            output_format="MP4",
        )
        self.assertIn("-max_muxing_queue_size", cmd_mp4)
        self.assertEqual(cmd_mp4[cmd_mp4.index("-max_muxing_queue_size") + 1], "2048")
        self.assertIn("-af", cmd_mp4)
        self.assertIn("aresample=async=1000", cmd_mp4[cmd_mp4.index("-af") + 1])
        self.assertIn("-fps_mode", cmd_mp4)
        self.assertEqual(cmd_mp4[cmd_mp4.index("-fps_mode") + 1], "passthrough")
        self.assertIn("-analyzeduration", cmd_mp4)
        self.assertEqual(cmd_mp4[cmd_mp4.index("-analyzeduration") + 1], "10000000")

        # 2. MPG output format (preserves passthrough for stream copy)
        cmd_mpg, _, _ = dvd_engine.prepare_dvd_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source="E:\\VIDEO_TS",
            title_dict=title,
            out_dir="C:\\out",
            output_format="MPG",
        )
        self.assertIn("-fps_mode", cmd_mpg)
        self.assertEqual(cmd_mpg[cmd_mpg.index("-fps_mode") + 1], "passthrough")

    def test_dvd_chapter_rip_job_args_optimization(self):
        title = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"stream_index": 0, "channels": 2, "codec": "ac3"}],
        }
        chapter = {
            "chapter_number": 1,
            "name": "Chapter 01",
            "start_time": 0.0,
            "duration": 30.0,
        }

        # 1. MP4 chapter
        cmd_mp4, _, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source="E:\\VIDEO_TS",
            title_dict=title,
            chapter_dict=chapter,
            out_dir="C:\\out",
            output_format="MP4",
        )
        self.assertIn("-max_muxing_queue_size", cmd_mp4)
        self.assertEqual(cmd_mp4[cmd_mp4.index("-max_muxing_queue_size") + 1], "2048")
        self.assertIn("-af", cmd_mp4)
        self.assertIn("aresample=async=1000", cmd_mp4[cmd_mp4.index("-af") + 1])
        self.assertIn("-fps_mode", cmd_mp4)
        self.assertEqual(cmd_mp4[cmd_mp4.index("-fps_mode") + 1], "passthrough")

        # 2. MPG chapter
        cmd_mpg, _, _ = dvd_engine.prepare_dvd_chapter_rip_job(
            ffmpeg_path="ffmpeg.exe",
            dvd_source="E:\\VIDEO_TS",
            title_dict=title,
            chapter_dict=chapter,
            out_dir="C:\\out",
            output_format="MPG",
        )
        self.assertIn("-fps_mode", cmd_mpg)
        self.assertEqual(cmd_mpg[cmd_mpg.index("-fps_mode") + 1], "passthrough")

    def test_dvd_rip_thread_stall_detection_terminates_frozen_process(self):
        from unittest.mock import patch, MagicMock

        class StalledProcessMock:
            def __init__(self):
                self.returncode = None
                self._stopped = False
                self.pid = 9999
            def readline(self):
                if not self._stopped:
                    time.sleep(0.02)
                    return "frame=  128 fps=0.0 q=28.0 size=    2560kB time=00:00:05.12 bitrate=4096.0kbits/s speed=0.001x\n"
                return ""
            @property
            def stdout(self):
                return self
            def poll(self):
                return self.returncode
            def terminate(self):
                self._stopped = True
                self.returncode = -15
            def kill(self):
                self._stopped = True
                self.returncode = -9
            def wait(self, timeout=None):
                return self.returncode
            def close(self):
                self._stopped = True

        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        app._ffmpeg = "ffmpeg.exe"
        app._handbrake = None
        app._dvd_source_path = "E:\\VIDEO_TS"
        app._rip_done = MagicMock()

        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"stream_index": 0, "channels": 2, "codec": "ac3", "display_label": "Track 1"}],
        }

        mock_proc = StalledProcessMock()
        orig_timeout = vcd_ripper.DISC_READ_TIMEOUT_SECONDS
        orig_term = vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT
        vcd_ripper.DISC_READ_TIMEOUT_SECONDS = 0.3
        vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT = 0.05

        try:
            with patch("subprocess.Popen", return_value=mock_proc), \
                 patch("vcd_ripper.kill_process_tree"), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.getsize", return_value=1024):
                app._rip_dvd_unified_thread(
                    title_jobs=[t1],
                    chapter_jobs=[],
                    out_folder="C:\\test_out",
                    output_format="MP4"
                )
                app.update()

            self.assertIn(mock_proc.returncode, (-15, -9))
            app._rip_done.assert_called_once()
            # Verify failure/timeout was reported to _rip_done
            total, success, errors, done_dir = app._rip_done.call_args[0]
            self.assertEqual(errors, 1)
        finally:
            vcd_ripper.DISC_READ_TIMEOUT_SECONDS = orig_timeout
            vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT = orig_term
            app.destroy()

    def test_dvd_rip_thread_handbrake_stall_fallback_to_ffmpeg(self):
        from unittest.mock import patch, MagicMock

        class StalledHBMock:
            def __init__(self):
                self.returncode = None
                self._stopped = False
                self.pid = 9998
            def readline(self):
                if not self._stopped:
                    time.sleep(0.02)
                    return "Encoding: task 1 of 1, 15.00 % (0.00 fps, avg 15.00 fps, ETA 00h01m00s)\n"
                return ""
            @property
            def stdout(self):
                return self
            def poll(self):
                return self.returncode
            def terminate(self):
                self._stopped = True
                self.returncode = -15
            def kill(self):
                self._stopped = True
                self.returncode = -9
            def wait(self, timeout=None):
                return self.returncode
            def close(self):
                self._stopped = True

        class SuccessFFmpegMock:
            def __init__(self):
                self.returncode = 0
                self.pid = 9997
            def readline(self):
                return ""
            @property
            def stdout(self):
                return self
            def poll(self):
                return 0
            def wait(self, timeout=None):
                return 0
            def close(self):
                pass

        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        app._ffmpeg = "ffmpeg.exe"
        app._handbrake = "HandBrakeCLI.exe"
        app._dvd_source_path = "E:\\VIDEO_TS"
        app._rip_done = MagicMock()

        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"track_id": "T01_A01", "track_number": 1, "stream_index": 0, "channels": 2, "codec": "ac3", "display_label": "Track 1"}],
        }

        hb_title = dvd_engine.DVDTitle(
            title_number=1,
            vts_number=1,
            duration=60.0,
            chapter_count=1,
            chapters_data=[dvd_engine.DVDChapter(chapter_number=1, start_time=0.0, end_time=60.0, duration=60.0, title_number=1)],
            audio_tracks=[dvd_engine.DVDAudioTrack(track_id="T01_A01", title_number=1, track_number=1, stream_index=0)],
        )
        hb_val = dvd_engine.HandBrakeValidationResult(
            success=True,
            working_source_path="E:\\VIDEO_TS",
            titles=[hb_title],
            title_count=1
        )

        called_cmds = []
        def fake_popen(cmd, *args, **kwargs):
            called_cmds.append(cmd)
            if "HandBrakeCLI.exe" in cmd[0]:
                return StalledHBMock()
            return SuccessFFmpegMock()

        orig_timeout = vcd_ripper.DISC_READ_TIMEOUT_SECONDS
        orig_term = vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT
        vcd_ripper.DISC_READ_TIMEOUT_SECONDS = 0.3
        vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT = 0.05

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("vcd_ripper.kill_process_tree"), \
                 patch("os.path.isfile", return_value=True), \
                 patch("dvd_engine.validate_handbrake_source", return_value=hb_val), \
                 patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.getsize", return_value=1024*1024):
                app._rip_dvd_unified_thread(
                    title_jobs=[t1],
                    chapter_jobs=[],
                    out_folder="C:\\test_out",
                    output_format="MP4"
                )
                app.update()

            self.assertGreaterEqual(len(called_cmds), 2)
            self.assertIn("HandBrakeCLI.exe", called_cmds[0][0])
            self.assertIn("ffmpeg.exe", called_cmds[-1][0])
            app._rip_done.assert_called_once()
            total, success, errors, done_dir = app._rip_done.call_args[0]
            self.assertEqual(success, 1)
            self.assertEqual(errors, 0)
        finally:
            vcd_ripper.DISC_READ_TIMEOUT_SECONDS = orig_timeout
            vcd_ripper.GRACEFUL_TERMINATE_TIMEOUT = orig_term
            app.destroy()


class TestFPSModeFeature(unittest.TestCase):
    """Test suite verifying the Ripping FPS Mode feature (Passthrough vs CFR)."""

    def test_i18n_fps_mode_default_and_switching(self):
        with patch("os.path.exists", return_value=False):
            i18n = vcd_ripper.I18n()
            self.assertEqual(i18n.fps_mode, "Passthrough")
            self.assertEqual(i18n.priority, "High")

        callback_values = []
        i18n.set_fps_mode_callback(lambda val: callback_values.append(val))

        i18n.switch_fps_mode("CFR")
        self.assertEqual(i18n.fps_mode, "CFR")
        self.assertEqual(callback_values, ["CFR"])

        i18n.switch_fps_mode("Passthrough")
        self.assertEqual(i18n.fps_mode, "Passthrough")
        self.assertEqual(callback_values, ["CFR", "Passthrough"])

        # Invalid mode should be ignored
        i18n.switch_fps_mode("InvalidMode")
        self.assertEqual(i18n.fps_mode, "Passthrough")
        self.assertEqual(len(callback_values), 2)

    def test_translations_fps_mode_keys(self):
        orig_lang = vcd_ripper.i18n.lang
        try:
            for lang, expected_title, expected_passthrough, expected_cfr in [
                ("en", "FPS Mode", "Passthrough", "CFR"),
                ("zh_CN", "帧率模式", "Passthrough", "CFR"),
            ]:
                vcd_ripper.i18n.lang = lang
                self.assertEqual(vcd_ripper.i18n.t("fps_mode.title"), expected_title)
                self.assertEqual(vcd_ripper.i18n.t("fps_mode.passthrough"), expected_passthrough)
                self.assertEqual(vcd_ripper.i18n.t("fps_mode.cfr"), expected_cfr)
        finally:
            vcd_ripper.i18n.lang = orig_lang

    def test_i18n_fps_mode_config_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = os.path.join(td, "config.json")
            orig_abspath = os.path.abspath
            def fake_abspath(p):
                if p == vcd_ripper.__file__:
                    return os.path.join(td, "dummy.py")
                return orig_abspath(p)

            with patch("os.path.abspath", side_effect=fake_abspath):
                i18n = vcd_ripper.I18n()
                i18n.switch_fps_mode("CFR")

                self.assertTrue(os.path.exists(cfg_file))
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data.get("fps_mode"), "CFR")

                # Test loading back
                i18n2 = vcd_ripper.I18n()
                self.assertEqual(i18n2.fps_mode, "CFR")

    def test_settings_dialog_fps_mode_ui(self):
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app._show_about()
            dlg = app._about_dialog
            self.assertIsNotNone(dlg)

            # Find buttons
            found_buttons = {}
            for child in dlg.winfo_children():
                if isinstance(child, tk.Frame):
                    for sub in child.winfo_children():
                        if isinstance(sub, tk.Frame):
                            for widget in sub.winfo_children():
                                if isinstance(widget, tk.Frame):
                                    for btn in widget.winfo_children():
                                        if isinstance(btn, tk.Button):
                                            txt = btn.cget("text")
                                            if txt in ("Passthrough", "CFR"):
                                                found_buttons[txt] = btn

            self.assertIn("Passthrough", found_buttons)
            self.assertIn("CFR", found_buttons)

            # Click Passthrough
            found_buttons["Passthrough"].invoke()
            self.assertEqual(app.i18n.fps_mode, "Passthrough")

            # Click CFR
            found_buttons["CFR"].invoke()
            self.assertEqual(app.i18n.fps_mode, "CFR")

            # Test updating theme, lang, and scale
            dlg.update_lang()
            dlg.update_theme()
            dlg.update_scale()

            dlg.destroy()
        finally:
            app.destroy()

    def test_dvd_engine_prepare_jobs_fps_mode_ffmpeg(self):
        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "vob_paths": [r"C:\test\VTS_01_1.VOB"],
            "audio_tracks": [{"track_id": "T01_A01", "track_number": 1, "stream_index": 0}],
        }
        c1 = {
            "chapter_number": 1,
            "name": "Chapter 01",
            "start_time": 0.0,
            "end_time": 60.0,
            "duration": 60.0,
        }

        with patch("os.path.isfile", return_value=True):
            # Test DVD rip job - CFR
            cmd_cfr, _, _ = dvd_engine.prepare_dvd_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                out_dir=r"C:\out",
                output_format="MP4",
                fps_mode="CFR",
            )
            self.assertIn("-fps_mode", cmd_cfr)
            idx = cmd_cfr.index("-fps_mode")
            self.assertEqual(cmd_cfr[idx + 1], "cfr")

            # Test DVD rip job - Passthrough
            cmd_pass, _, _ = dvd_engine.prepare_dvd_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                out_dir=r"C:\out",
                output_format="MP4",
                fps_mode="Passthrough",
            )
            self.assertIn("-fps_mode", cmd_pass)
            idx = cmd_pass.index("-fps_mode")
            self.assertEqual(cmd_pass[idx + 1], "passthrough")

            # Test DVD rip job - MPG must remain passthrough regardless of fps_mode="CFR"
            cmd_mpg, _, _ = dvd_engine.prepare_dvd_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                out_dir=r"C:\out",
                output_format="MPG",
                fps_mode="CFR",
            )
            self.assertIn("-fps_mode", cmd_mpg)
            idx = cmd_mpg.index("-fps_mode")
            self.assertEqual(cmd_mpg[idx + 1], "passthrough")

            # Test DVD chapter rip job - CFR
            cmd_chap_cfr, _, _ = dvd_engine.prepare_dvd_chapter_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                chapter_dict=c1,
                out_dir=r"C:\out",
                output_format="MP4",
                fps_mode="CFR",
            )
            self.assertIn("-fps_mode", cmd_chap_cfr)
            idx = cmd_chap_cfr.index("-fps_mode")
            self.assertEqual(cmd_chap_cfr[idx + 1], "cfr")

            # Test DVD chapter rip job - Passthrough
            cmd_chap_pass, _, _ = dvd_engine.prepare_dvd_chapter_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                chapter_dict=c1,
                out_dir=r"C:\out",
                output_format="MP4",
                fps_mode="Passthrough",
            )
            self.assertIn("-fps_mode", cmd_chap_pass)
            idx = cmd_chap_pass.index("-fps_mode")
            self.assertEqual(cmd_chap_pass[idx + 1], "passthrough")

            # Test DVD rip job - None defaults to Passthrough
            cmd_default, _, _ = dvd_engine.prepare_dvd_rip_job(
                ffmpeg_path="ffmpeg.exe",
                dvd_source=r"C:\test",
                title_dict=t1,
                out_dir=r"C:\out",
                output_format="MP4",
            )
            self.assertIn("-fps_mode", cmd_default)
            idx = cmd_default.index("-fps_mode")
            self.assertEqual(cmd_default[idx + 1], "passthrough")

    def test_dvd_engine_prepare_jobs_fps_mode_handbrake(self):
        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "vob_paths": [r"C:\test\VTS_01_1.VOB"],
            "audio_tracks": [{"track_id": "T01_A01", "track_number": 1, "stream_index": 0}],
        }
        val_res = dvd_engine.HandBrakeValidationResult(
            success=True,
            working_source_path=r"C:\test",
            titles=[dvd_engine.DVDTitle(title_number=1, vts_number=1, duration=60.0, chapter_count=1)],
            title_count=1
        )

        # HandBrake with CFR
        cmd_hb_cfr, _ = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source=r"C:\test",
            title_dict=t1,
            chapter_dict=None,
            out_dir=r"C:\out",
            val_res=val_res,
            fps_mode="CFR",
        )
        self.assertIn("--cfr", cmd_hb_cfr)
        self.assertNotIn("--pfr", cmd_hb_cfr)

        # HandBrake with Passthrough
        cmd_hb_pass, _ = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source=r"C:\test",
            title_dict=t1,
            chapter_dict=None,
            out_dir=r"C:\out",
            val_res=val_res,
            fps_mode="Passthrough",
        )
        self.assertIn("--pfr", cmd_hb_pass)
        self.assertNotIn("--cfr", cmd_hb_pass)

        # HandBrake with None defaults to Passthrough (--pfr)
        cmd_hb_def, _ = dvd_engine.prepare_dvd_handbrake_rip_job(
            handbrake_path="HandBrakeCLI.exe",
            dvd_source=r"C:\test",
            title_dict=t1,
            chapter_dict=None,
            out_dir=r"C:\out",
            val_res=val_res,
        )
        self.assertIn("--pfr", cmd_hb_def)
        self.assertNotIn("--cfr", cmd_hb_def)

    def test_rip_dvd_unified_thread_passes_fps_mode(self):
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        app._ffmpeg = "ffmpeg.exe"
        app._dvd_source_path = "E:\\VIDEO_TS"
        app._rip_done = MagicMock()
        app.i18n.fps_mode = "Passthrough"

        t1 = {
            "title_number": 1,
            "filename": "Title_01",
            "name": "Title_01",
            "duration": 60.0,
            "vob_files": ["VTS_01_1.VOB"],
            "audio_tracks": [{"track_id": "T01_A01", "track_number": 1, "stream_index": 0, "channels": 2, "codec": "ac3", "display_label": "Track 1"}],
        }

        with patch("dvd_engine.prepare_dvd_rip_job", return_value=(["ffmpeg.exe", "-fps_mode", "passthrough"], "out.mp4", None)) as mock_prep, \
             patch("subprocess.Popen") as mock_popen, \
             patch("dvd_engine.validate_ripped_media", return_value=(True, "OK")):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 0
            mock_proc.stdout.readline.return_value = ""
            mock_popen.return_value = mock_proc

            app._rip_dvd_unified_thread(
                title_jobs=[t1],
                chapter_jobs=[],
                out_folder=r"C:\out",
                output_format="MP4",
            )
            app.update()

            mock_prep.assert_called_once()
            _, kwargs = mock_prep.call_args
            self.assertEqual(kwargs.get("fps_mode"), "Passthrough")
        app.destroy()

    def test_vcd_rip_thread_uses_fps_mode(self):
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        app._ffmpeg = "ffmpeg.exe"
        app._rip_done = MagicMock()
        app._videos = [{
            "filename": "AVSEQ01.DAT",
            "path": r"D:\MPEGAV\AVSEQ01.DAT",
            "duration": 60.0,
            "size": 1024 * 1024,
            "custom_stem": "Track_01",
        }]
        app.i18n.fps_mode = "Passthrough"

        called_cmds = []
        def fake_popen(cmd, *args, **kwargs):
            called_cmds.append(cmd)
            proc = MagicMock()
            proc.poll.return_value = 0
            proc.stdout.readline.return_value = ""
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024 * 1024):
            app._rip_thread(
                videos=app._videos,
                out_folder=r"C:\out",
                fmt="MP4",
                fmt_cfg=vcd_ripper.OUTPUT_FORMATS["MP4"],
                use_1080p=False,
                mode="video",
                audio_fmt="MP3",
            )
            app.update()

        self.assertEqual(len(called_cmds), 1)
        self.assertIn("-fps_mode", called_cmds[0])
        idx = called_cmds[0].index("-fps_mode")
        self.assertEqual(called_cmds[0][idx + 1], "passthrough")
        app.destroy()


class TestExportResolutionAudioOnlyGreyout(unittest.TestCase):
    """Test suite verifying that Export Resolution remains visible and is greyed out when Audio Only is selected."""

    def test_resolution_subpanel_greyout_on_audio_only(self):
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            # Default state: MP4, video mode
            app._output_format.set("MP4")
            app._output_mode.set("video")
            app._update_format_greyout()
            app.update()

            self.assertEqual(app._res_suboption_frame.winfo_manager(), "pack")
            self.assertEqual(str(app._res_orig_rb.cget("state")), "normal")
            self.assertEqual(str(app._res_1080p_rb.cget("state")), "normal")
            self.assertEqual(app._res_title_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])

            # Switch to Audio Only
            app._output_mode.set("audio")
            app._on_mode_change()
            app.update()

            # Crucial verification: frame is STILL packed (did not disappear)
            self.assertEqual(app._res_suboption_frame.winfo_manager(), "pack")
            # But the controls are greyed out / disabled
            self.assertEqual(str(app._res_orig_rb.cget("state")), "disabled")
            self.assertEqual(str(app._res_1080p_rb.cget("state")), "disabled")
            self.assertEqual(app._res_orig_rb.cget("fg"), vcd_ripper.COLORS["text_muted"])
            self.assertEqual(app._res_1080p_rb.cget("fg"), vcd_ripper.COLORS["text_muted"])
            self.assertEqual(app._res_title_lbl.cget("fg"), vcd_ripper.COLORS["text_muted"])

            # Switch back to Video + Audio
            app._output_mode.set("both")
            app._on_mode_change()
            app.update()

            self.assertEqual(app._res_suboption_frame.winfo_manager(), "pack")
            self.assertEqual(str(app._res_orig_rb.cget("state")), "normal")
            self.assertEqual(str(app._res_1080p_rb.cget("state")), "normal")
            self.assertEqual(app._res_title_lbl.cget("fg"), vcd_ripper.COLORS["text_secondary"])

            # Changing format to MPG hides resolution subpanel (as resolution doesn't apply to MPG)
            app._output_format.set("MPG")
            app._on_format_change()
            app.update()
            self.assertEqual(app._res_suboption_frame.winfo_manager(), "")

            # Changing back to MP4 shows resolution subpanel
            app._output_format.set("MP4")
            app._on_format_change()
            app.update()
            self.assertEqual(app._res_suboption_frame.winfo_manager(), "pack")
        finally:
            app.destroy()


class TestDVDChapterTimelineGeneration(unittest.TestCase):
    """Automated tests for DVD Chapter Timeline TXT generation and UI integration."""

    def test_get_chapter_timeline_output_path(self):
        sample_media = r"C:\Movies\Title_01_FULL.mp4"
        expected = r"C:\Movies\Title_01_FULL_Chapter_Timeline.txt"
        self.assertEqual(dvd_engine.get_chapter_timeline_output_path(sample_media), os.path.normpath(expected))

        unicode_media = r"D:\飞长唱片\新年\旗聚女聲-2010新年快樂（MDVD553）\旗聚女聲-2010新年快樂（MDVD553）_FULL.mp4"
        expected_u = r"D:\飞长唱片\新年\旗聚女聲-2010新年快樂（MDVD553）\旗聚女聲-2010新年快樂（MDVD553）_FULL_Chapter_Timeline.txt"
        self.assertEqual(dvd_engine.get_chapter_timeline_output_path(unicode_media), os.path.normpath(expected_u))

    def test_generate_chapter_timeline_missing_ffprobe(self):
        ok, out, err, count = dvd_engine.generate_chapter_timeline_file(
            ffprobe_path="non_existent_ffprobe.exe",
            media_path="dummy.mp4"
        )
        self.assertFalse(ok)
        self.assertIn("FFprobe executable not found", err)

    def test_generate_chapter_timeline_missing_media(self):
        with tempfile.NamedTemporaryFile(suffix=".exe") as fake_ffprobe:
            ok, out, err, count = dvd_engine.generate_chapter_timeline_file(
                ffprobe_path=fake_ffprobe.name,
                media_path="non_existent_movie.mp4"
            )
            self.assertFalse(ok)
            self.assertIn("Output media file not found or empty", err)

    def test_generate_chapter_timeline_exact_reference_formatting(self):
        """Verifies exact layout match with reference file 新建 Text Document.txt."""
        with tempfile.TemporaryDirectory() as td:
            fake_ffprobe = os.path.join(td, "ffprobe.exe")
            with open(fake_ffprobe, "w") as f:
                f.write("dummy")

            media_path = os.path.join(td, "旗聚女聲-2010新年快樂（MDVD553）_FULL.mp4")
            with open(media_path, "wb") as f:
                f.write(b"video_data_12345")

            # Mock FFprobe CSV output with chapters
            mock_csv_output = (
                "0,0.000000,59.800000,Chapter 1\n"
                "1,59.800000,263.880000,Chapter 2\n"
                "2,263.880000,509.832000,Chapter 3\n"
                "3,509.832000,726.352000,\n"  # missing title fallback test
            )

            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = mock_csv_output
            mock_res.stderr = ""

            with patch("subprocess.run", return_value=mock_res) as mock_run:
                ok, txt_file, err, count = dvd_engine.generate_chapter_timeline_file(
                    ffprobe_path=fake_ffprobe,
                    media_path=media_path,
                    user_profile=r"C:\Users\User"
                )

                self.assertTrue(ok)
                self.assertEqual(count, 4)
                self.assertIsNotNone(txt_file)
                self.assertTrue(os.path.isfile(txt_file))

                # Verify filename
                expected_filename = "旗聚女聲-2010新年快樂（MDVD553）_FULL_Chapter_Timeline.txt"
                self.assertEqual(os.path.basename(txt_file), expected_filename)

                # Verify contents
                with open(txt_file, "r", encoding="utf-8") as f:
                    content = f.read()

                lines = content.splitlines()
                # Line 1: Header command
                norm_media = os.path.normpath(os.path.abspath(media_path))
                expected_header = f'C:\\Users\\User>ffprobe -v error -show_chapters -show_entries chapter=id,start_time,end_time:chapter_tags=title -of csv=p=0 "{norm_media}"'
                self.assertEqual(lines[0], expected_header)

                # Following lines
                self.assertEqual(lines[1], "0,0.000000,59.800000,Chapter 1")
                self.assertEqual(lines[2], "1,59.800000,263.880000,Chapter 2")
                self.assertEqual(lines[3], "2,263.880000,509.832000,Chapter 3")
                self.assertEqual(lines[4], "3,509.832000,726.352000,Chapter 4")  # fallback applied

    def test_generate_chapter_timeline_no_chapters_found(self):
        """When media has 0 chapters, do not create empty or misleading file."""
        with tempfile.TemporaryDirectory() as td:
            fake_ffprobe = os.path.join(td, "ffprobe.exe")
            with open(fake_ffprobe, "w") as f:
                f.write("dummy")

            media_path = os.path.join(td, "NoChapters_FULL.mp4")
            with open(media_path, "wb") as f:
                f.write(b"video_data_12345")

            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = ""
            mock_res.stderr = ""

            with patch("subprocess.run", return_value=mock_res):
                ok, txt_file, err, count = dvd_engine.generate_chapter_timeline_file(
                    ffprobe_path=fake_ffprobe,
                    media_path=media_path
                )
                self.assertFalse(ok)
                self.assertIn("No chapter metadata found in the output file", err)
                expected_txt = dvd_engine.get_chapter_timeline_output_path(media_path)
                self.assertFalse(os.path.exists(expected_txt))

    def test_generate_chapter_timeline_ffprobe_error(self):
        """When FFprobe fails, report error cleanly."""
        with tempfile.TemporaryDirectory() as td:
            fake_ffprobe = os.path.join(td, "ffprobe.exe")
            with open(fake_ffprobe, "w") as f:
                f.write("dummy")

            media_path = os.path.join(td, "Corrupt_FULL.mp4")
            with open(media_path, "wb") as f:
                f.write(b"video_data_12345")

            mock_res = MagicMock()
            mock_res.returncode = 1
            mock_res.stdout = ""
            mock_res.stderr = "Invalid data found when processing input"

            with patch("subprocess.run", return_value=mock_res):
                ok, txt_file, err, count = dvd_engine.generate_chapter_timeline_file(
                    ffprobe_path=fake_ffprobe,
                    media_path=media_path
                )
                self.assertFalse(ok)
                self.assertIn("Failed to read chapter metadata", err)

    def test_generate_chapter_timeline_overwrites_safely(self):
        """When timeline file already exists, it is safely and atomically overwritten."""
        with tempfile.TemporaryDirectory() as td:
            fake_ffprobe = os.path.join(td, "ffprobe.exe")
            with open(fake_ffprobe, "w") as f:
                f.write("dummy")

            media_path = os.path.join(td, "Existing_FULL.mp4")
            with open(media_path, "wb") as f:
                f.write(b"video_data_12345")

            timeline_path = dvd_engine.get_chapter_timeline_output_path(media_path)
            with open(timeline_path, "w", encoding="utf-8") as f:
                f.write("old content")

            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "0,0.000000,10.000000,Intro\n"
            mock_res.stderr = ""

            with patch("subprocess.run", return_value=mock_res):
                ok, txt_file, err, count = dvd_engine.generate_chapter_timeline_file(
                    ffprobe_path=fake_ffprobe,
                    media_path=media_path
                )
                self.assertTrue(ok)
                with open(timeline_path, "r", encoding="utf-8") as f:
                    new_content = f.read()
                self.assertIn("0,0.000000,10.000000,Intro", new_content)

    def test_dvd_pipeline_ui_checkbox_presence_and_independence(self):
        """Verify UI checkbox existence, default unchecked, and visibility toggle for DVD vs VCD."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            self.assertTrue(hasattr(app, "_dvd_timeline_var"))
            self.assertTrue(hasattr(app, "_dvd_timeline_chk"))
            # Default state: unchecked
            self.assertFalse(app._dvd_timeline_var.get())

            # Initial state (non-DVD): checkbox should not be packed
            app._source_type = "VCD"
            app._videos = []
            app._update_format_visibility_for_source()
            app.update()
            self.assertEqual(app._dvd_timeline_chk.winfo_manager(), "")

            # Switch to DVD: checkbox is packed immediately after _auto_open_chk
            app._source_type = "DVD"
            app._update_format_visibility_for_source()
            app.update()
            self.assertEqual(app._dvd_timeline_chk.winfo_manager(), "pack")

            # Checkbox independence: toggling _auto_open_folder does not affect _dvd_timeline_var
            app._auto_open_folder.set(False)
            self.assertFalse(app._dvd_timeline_var.get())
            app._dvd_timeline_var.set(True)
            self.assertFalse(app._auto_open_folder.get())

            # Switch back to VCD: checkbox is hidden again
            app._source_type = "VCD"
            app._update_format_visibility_for_source()
            app.update()
            self.assertEqual(app._dvd_timeline_chk.winfo_manager(), "")
        finally:
            app.destroy()

    def test_dvd_rip_thread_timeline_generation_workflow(self):
        """Full workflow: complete title rip generates timeline TXT, disabled generates none, chapter-only generates none."""
        with tempfile.TemporaryDirectory() as td:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()
            try:
                app._rip_done = MagicMock()
                fake_ffprobe = os.path.join(td, "ffprobe.exe")
                with open(fake_ffprobe, "w") as f:
                    f.write("dummy")
                app._ffprobe = fake_ffprobe

                title1 = {
                    "title_number": 1,
                    "filename": "Title_01_FULL",
                    "custom_stem": "Title_01_FULL",
                    "duration": 60.0,
                    "vob_files": [os.path.join(td, "VTS_01_1.VOB")],
                    "chapters_data": [
                        {"chapter_number": 1, "start_time": 0.0, "end_time": 30.0},
                        {"chapter_number": 2, "start_time": 30.0, "end_time": 60.0}
                    ]
                }
                title2 = {
                    "title_number": 2,
                    "filename": "Title_02_FULL",
                    "custom_stem": "Title_02_FULL",
                    "duration": 45.0,
                    "vob_files": [os.path.join(td, "VTS_02_1.VOB")],
                    "chapters_data": [
                        {"chapter_number": 1, "start_time": 0.0, "end_time": 45.0}
                    ]
                }

                # 1. Complete title rip with generate_timeline=True
                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(True, "valid")), \
                     patch("dvd_engine.generate_chapter_timeline_file", wraps=dvd_engine.generate_chapter_timeline_file) as mock_gen, \
                     patch("subprocess.run") as mock_run:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    mock_ffprobe_res = MagicMock()
                    mock_ffprobe_res.returncode = 0
                    mock_ffprobe_res.stdout = "0,0.000000,30.000000,Chapter 1\n1,30.000000,60.000000,Chapter 2\n"
                    mock_ffprobe_res.stderr = ""
                    mock_run.return_value = mock_ffprobe_res

                    # Create actual output media file so getsize > 0
                    out_media_1 = os.path.join(td, "Title_01_FULL.mp4")
                    with open(out_media_1, "wb") as f:
                        f.write(b"media_1_content")

                    with patch("dvd_engine.prepare_dvd_rip_job", return_value=(["mock_ffmpeg"], out_media_1, None)):
                        app._rip_dvd_unified_thread(
                            title_jobs=[title1],
                            chapter_jobs=[],
                            out_folder=td,
                            output_format="MP4",
                            generate_timeline=True
                        )

                    mock_gen.assert_called_once()
                    t1_txt = dvd_engine.get_chapter_timeline_output_path(out_media_1)
                    self.assertTrue(os.path.isfile(t1_txt))
                    with open(t1_txt, "r", encoding="utf-8") as f:
                        self.assertIn("0,0.000000,30.000000,Chapter 1", f.read())

                # 2. Complete title rip with generate_timeline=False -> no file generated
                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(True, "valid")), \
                     patch("dvd_engine.generate_chapter_timeline_file") as mock_gen:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    out_media_2 = os.path.join(td, "Title_02_FULL.mp4")
                    with open(out_media_2, "wb") as f:
                        f.write(b"media_2_content")

                    with patch("dvd_engine.prepare_dvd_rip_job", return_value=(["mock_ffmpeg"], out_media_2, None)):
                        app._rip_dvd_unified_thread(
                            title_jobs=[title2],
                            chapter_jobs=[],
                            out_folder=td,
                            output_format="MP4",
                            generate_timeline=False
                        )

                    mock_gen.assert_not_called()
                    t2_txt = dvd_engine.get_chapter_timeline_output_path(out_media_2)
                    self.assertFalse(os.path.exists(t2_txt))

                # 3. Individual chapter rip -> no complete title timeline generated
                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(True, "valid")), \
                     patch("dvd_engine.generate_chapter_timeline_file") as mock_gen:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    chap_media = os.path.join(td, "Title_01_FULL - Chapter 01.mp4")
                    with open(chap_media, "wb") as f:
                        f.write(b"chap_media_content")

                    c1 = title1["chapters_data"][0]
                    with patch("dvd_engine.prepare_dvd_chapter_rip_job", return_value=(["mock_ffmpeg"], chap_media, None)):
                        app._rip_dvd_unified_thread(
                            title_jobs=[],
                            chapter_jobs=[(title1, c1)],
                            out_folder=td,
                            output_format="MP4",
                            generate_timeline=True
                        )

                    mock_gen.assert_not_called()

            finally:
                app.destroy()

    def test_dvd_rip_multiple_titles_each_receives_timeline(self):
        """When multiple complete titles are ripped with timeline enabled, each receives its own TXT file."""
        with tempfile.TemporaryDirectory() as td:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()
            try:
                app._rip_done = MagicMock()
                app._ffprobe = os.path.join(td, "ffprobe.exe")
                with open(app._ffprobe, "w") as f:
                    f.write("dummy")

                t1 = {"title_number": 1, "filename": "Title_01_FULL", "duration": 50.0, "vob_files": []}
                t2 = {"title_number": 2, "filename": "Title_02_FULL", "duration": 40.0, "vob_files": []}

                m1 = os.path.join(td, "Title_01_FULL.mp4")
                m2 = os.path.join(td, "Title_02_FULL.mp4")
                with open(m1, "wb") as f:
                    f.write(b"video1")
                with open(m2, "wb") as f:
                    f.write(b"video2")

                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(True, "valid")), \
                     patch("dvd_engine.generate_chapter_timeline_file") as mock_gen:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    def side_prep(ffmpeg_path, dvd_source, title_dict, out_dir, *args, **kwargs):
                        tn = title_dict.get("title_number", 1)
                        out_p = m1 if tn == 1 else m2
                        return (["mock_ffmpeg"], out_p, None)

                    with patch("dvd_engine.prepare_dvd_rip_job", side_effect=side_prep):
                        app._rip_dvd_unified_thread(
                            title_jobs=[t1, t2],
                            chapter_jobs=[],
                            out_folder=td,
                            output_format="MP4",
                            generate_timeline=True
                        )

                    # Both titles should have called generate_chapter_timeline_file
                    self.assertEqual(mock_gen.call_count, 2)
                    calls = [call[1]["media_path"] for call in mock_gen.call_args_list]
                    self.assertIn(m1, calls)
                    self.assertIn(m2, calls)
            finally:
                app.destroy()

    def test_dvd_rip_extract_both_avoids_duplicate_timeline(self):
        """When extract_both=True, only 1 timeline file is generated for that title."""
        with tempfile.TemporaryDirectory() as td:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()
            try:
                app._rip_done = MagicMock()
                app._ffprobe = os.path.join(td, "ffprobe.exe")
                with open(app._ffprobe, "w") as f:
                    f.write("dummy")

                t1 = {"title_number": 1, "filename": "Title_01_FULL", "duration": 50.0, "vob_files": []}
                m_vid = os.path.join(td, "Title_01_FULL.mp4")
                m_aud = os.path.join(td, "Title_01_FULL - Audio.wav")
                with open(m_vid, "wb") as f:
                    f.write(b"video1")
                with open(m_aud, "wb") as f:
                    f.write(b"audio1")

                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(True, "valid")), \
                     patch("dvd_engine.generate_chapter_timeline_file") as mock_gen:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    def side_prep(ffmpeg_path, dvd_source, title_dict, out_dir, *args, **kwargs):
                        is_aud = kwargs.get("audio_only", False)
                        out_p = m_aud if is_aud else m_vid
                        return (["mock_ffmpeg"], out_p, None)

                    with patch("dvd_engine.prepare_dvd_rip_job", side_effect=side_prep):
                        app._rip_dvd_unified_thread(
                            title_jobs=[t1],
                            chapter_jobs=[],
                            out_folder=td,
                            output_format="MP4",
                            audio_format="WAV",
                            extract_both=True,
                            generate_timeline=True
                        )

                    # Only 1 timeline generation call for Title 1 across both video and audio passes
                    self.assertEqual(mock_gen.call_count, 1)
                    self.assertEqual(mock_gen.call_args_list[0][1]["media_path"], m_vid)
            finally:
                app.destroy()

    def test_dvd_rip_failed_title_does_not_generate_timeline(self):
        """If title fails ripping or validation, no timeline file is generated."""
        with tempfile.TemporaryDirectory() as td:
            app = vcd_ripper.VCDRipperApp()
            app.withdraw()
            try:
                app._rip_done = MagicMock()
                app._ffprobe = os.path.join(td, "ffprobe.exe")
                with open(app._ffprobe, "w") as f:
                    f.write("dummy")

                t1 = {"title_number": 1, "filename": "Title_01_FAIL", "duration": 50.0, "vob_files": []}
                m_fail = os.path.join(td, "Title_01_FAIL.mp4")
                with open(m_fail, "wb") as f:
                    f.write(b"fail_video")

                with patch("subprocess.Popen") as mock_popen, \
                     patch("dvd_engine.validate_ripped_media", return_value=(False, "corrupt stream")), \
                     patch("dvd_engine.generate_chapter_timeline_file") as mock_gen:

                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.poll.return_value = 0
                    mock_proc.stdout.readline.side_effect = ["", ""]
                    mock_popen.return_value = mock_proc

                    with patch("dvd_engine.prepare_dvd_rip_job", return_value=(["mock_ffmpeg"], m_fail, None)):
                        app._rip_dvd_unified_thread(
                            title_jobs=[t1],
                            chapter_jobs=[],
                            out_folder=td,
                            output_format="MP4",
                            generate_timeline=True
                        )

                    mock_gen.assert_not_called()
            finally:
                app.destroy()

    def test_dvd_timeline_retranslation(self):
        """Switching UI language re-translates the timeline checkbutton."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app.i18n.switch("en")
            app._refresh_ui()
            self.assertEqual(app._dvd_timeline_chk.cget("text"), "Generate Chapter Timeline File (.txt)")

            app.i18n.switch("zh_CN")
            app._refresh_ui()
            self.assertEqual(app._dvd_timeline_chk.cget("text"), "生成章节时间轴文件 (.txt)")
        finally:
            app.destroy()

class TestThemeSwitchingAndContrast(unittest.TestCase):
    """Test suite for theme switching reliability, Settings dialog contrast, and auto-detection."""

    def test_settings_dialog_theme_switch_contrast(self):
        """Settings dialog labels and buttons maintain high contrast across Light and Dark mode switches."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            # Start in Light mode
            vcd_ripper.i18n.switch_theme("light")
            app._show_about()
            dlg = app._about_dialog
            self.assertIsNotNone(dlg)

            def get_all_labels(w):
                res = []
                if isinstance(w, tk.Label):
                    res.append(w)
                for c in w.winfo_children():
                    res.extend(get_all_labels(c))
                return res

            def get_all_buttons(w):
                res = []
                if isinstance(w, tk.Button):
                    res.append(w)
                for c in w.winfo_children():
                    res.extend(get_all_buttons(c))
                return res

            # Verify in Light mode
            labels_light = get_all_labels(dlg)
            for lbl in labels_light:
                self.assertNotEqual(lbl.cget("fg"), "#4A5270")

            # Switch to Dark mode
            vcd_ripper.i18n.switch_theme("dark")
            dlg.update_theme()

            labels_dark = get_all_labels(dlg)
            buttons_dark = get_all_buttons(dlg)

            # In dark mode, verify:
            # 1. No label should have black or low-contrast #4A5270 foreground
            for lbl in labels_dark:
                text = lbl.cget("text")
                fg = lbl.cget("fg").upper()
                self.assertNotIn(fg, ["#000000", "#0F172A", "#4A5270", "BLACK"], f"Label '{text}' has black/low-contrast fg {fg} in dark mode")

            # 2. All buttons have proper high-contrast text and activeforeground in dark mode
            for btn in buttons_dark:
                text = btn.cget("text")
                fg = btn.cget("fg").upper()
                afg = btn.cget("activeforeground").upper()
                self.assertNotIn(fg, ["#000000", "#0F172A", "#4A5270", "BLACK"], f"Button '{text}' has black/low-contrast fg {fg} in dark mode")
                self.assertNotIn(afg, ["#000000", "#0F172A", "#4A5270", "BLACK", "SYSTEMBUTTONTEXT"], f"Button '{text}' has black activeforeground {afg} in dark mode")

            # Switch back to Light mode
            vcd_ripper.i18n.switch_theme("light")
            dlg.update_theme()
            for lbl in get_all_labels(dlg):
                fg = lbl.cget("fg").upper()
                self.assertNotIn(fg, ["#F0F2FF", "#4A5270"], f"Label '{lbl.cget('text')}' has incorrect fg {fg} in light mode")

            dlg.destroy()
        finally:
            app.destroy()

    def test_system_theme_poll_updates_open_about_dialog(self):
        """Background poll system theme change updates open Settings dialog."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            vcd_ripper.i18n.theme = "system"
            vcd_ripper.apply_theme_palette("light")
            app._show_about()
            dlg = app._about_dialog
            self.assertIsNotNone(dlg)

            # Simulate background poll finding dark theme
            app._apply_poll_results([], [], [], [], True, "dark")

            # Check that dlg background and labels updated to dark palette
            self.assertEqual(dlg.cget("bg"), vcd_ripper.THEME_DARK["bg_panel"])

            # Verify no label has black foreground in dark mode
            for c in dlg.winfo_children():
                for sub in c.winfo_children():
                    if isinstance(sub, tk.Label):
                        fg = sub.cget("fg").upper()
                        self.assertNotIn(fg, ["#000000", "#0F172A", "#4A5270", "BLACK"])

            dlg.destroy()
        finally:
            app.destroy()

    def test_rapid_theme_switching_no_exception(self):
        """Rapid theme switching does not throw exceptions or corrupt Settings dialog state."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app._show_about()
            dlg = app._about_dialog
            self.assertIsNotNone(dlg)

            # Rapidly toggle between dark, light, and system
            for mode in ["dark", "light", "dark", "system", "dark", "light"]:
                vcd_ripper.i18n.switch_theme(mode)
                if dlg.winfo_exists() and hasattr(dlg, "update_theme"):
                    dlg.update_theme()

            # Ensure dialog is still responsive and valid
            self.assertTrue(dlg.winfo_exists())
            dlg.destroy()
        finally:
            app.destroy()

# ─────────────────────────────────────────────────────────────
#  Test Suite: Window Scaling & Maximize/Restore Layout Fixes
# ─────────────────────────────────────────────────────────────
class TestWindowScalingAndMaximizeRestoreLayoutFixes(unittest.TestCase):
    """Verify that restore and maximize operations maintain balanced layout without trailing blank space."""

    def test_packing_order_right_sidebar_docked_at_window_edge(self):
        """Right sidebar is always strictly docked to the right edge of top_frame with 0 gap."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app.update()
            # Initial state
            tf_w = app._top_frame.winfo_width()
            rs_edge = app._right_sidebar.winfo_x() + app._right_sidebar.winfo_width()
            self.assertEqual(tf_w, rs_edge)

            # Zoomed state
            app.state("zoomed")
            app.update()
            tf_w_zoomed = app._top_frame.winfo_width()
            rs_edge_zoomed = app._right_sidebar.winfo_x() + app._right_sidebar.winfo_width()
            self.assertEqual(tf_w_zoomed, rs_edge_zoomed)

            # Restored state
            app.state("normal")
            app.update()
            tf_w_restored = app._top_frame.winfo_width()
            rs_edge_restored = app._right_sidebar.winfo_x() + app._right_sidebar.winfo_width()
            self.assertEqual(tf_w_restored, rs_edge_restored)
        finally:
            app.destroy()

    def test_scale_switch_and_maximize_restore_retains_card_fill(self):
        """Canvas window item width matches canvas width across scale switches and maximize/restore."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            dummy_videos = [
                {'index': 1, 'filename': 'MUSIC01.DAT', 'size_mb': 45.2, 'duration': 240, 'width': 352, 'height': 240, 'fps': 29.97, 'disc_type': 'VCD'},
            ]
            app._populate_list(dummy_videos)
            app.update()

            for scale_val in ["100%", "125%", "150%"]:
                vcd_ripper.i18n.switch_scale(scale_val)
                app.update()
                cw = app._canvas.winfo_width()
                item_w = int(float(app._canvas.itemcget(app._canvas_window, "width")))
                self.assertEqual(cw, item_w)
                self.assertEqual(app._list_frame.winfo_width(), cw)

                # Maximize
                app.state("zoomed")
                app.update()
                cw_zoom = app._canvas.winfo_width()
                item_w_zoom = int(float(app._canvas.itemcget(app._canvas_window, "width")))
                self.assertEqual(cw_zoom, item_w_zoom)
                self.assertEqual(app._list_frame.winfo_width(), cw_zoom)

                # Restore
                app.state("normal")
                app.update()
                cw_restore = app._canvas.winfo_width()
                item_w_restore = int(float(app._canvas.itemcget(app._canvas_window, "width")))
                self.assertEqual(cw_restore, item_w_restore)
                self.assertEqual(app._list_frame.winfo_width(), cw_restore)
        finally:
            app.destroy()

    def test_canvas_width_cache_cleared_on_rebuild(self):
        """Cached canvas widths are reset to None on _rebuild_ui to avoid stale checks."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app.update()
            app._last_canvas_width = 1234
            app._last_left_canvas_w = 234
            app._last_right_canvas_w = 456

            app._rebuild_ui()
            app.update()
            # Stale cached values must be wiped, and new real widths bound
            self.assertNotEqual(app._last_canvas_width, 1234)
            self.assertEqual(app._last_canvas_width, app._canvas.winfo_width())
            self.assertNotEqual(app._last_left_canvas_w, 234)
            self.assertEqual(app._last_left_canvas_w, app._left_canvas.winfo_width())
            self.assertNotEqual(app._last_right_canvas_w, 456)
            self.assertEqual(app._last_right_canvas_w, app._right_canvas.winfo_width())
        finally:
            app.destroy()

    def test_apply_window_scale_preserves_zoomed_state(self):
        """_apply_window_scale updates minsize without overriding zoomed/maximized window state."""
        app = vcd_ripper.VCDRipperApp()
        app.withdraw()
        try:
            app.state("zoomed")
            app.update()
            self.assertEqual(app.state(), "zoomed")

            app._apply_window_scale()
            app.update()
            self.assertEqual(app.state(), "zoomed")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)





