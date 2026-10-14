# Disc Ripper Pro

<p align="center">
  <img src="CompactDisc.png" alt="Disc Ripper Pro Logo" width="128"/>
</p>

<p align="center">
  <strong>A modern, high-performance optical disc extraction & conversion suite for Windows</strong><br/>
  Effortlessly extract, convert, and preserve video tracks and movies from <strong>VCD</strong> and <strong>DVD-Video</strong> discs — featuring a sleek adaptive UI, chapter-level precision, multi-audio selection, and zero-fuss automation.
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2.0.0-6C63FF?style=flat-square"/>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows_7_--_11_(64--bit)-blue?style=flat-square"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square"/>
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-F59E0B?style=flat-square"/>
  <img alt="Engine" src="https://img.shields.io/badge/engine-HandBrakeCLI_%2B_FFmpeg-EF4444?style=flat-square"/>
</p>

---

## 🌟 Highlights

- **VCD & DVD Dual Pipeline**: Unified, intelligent disc scanner that detects optical media automatically.
- **HandBrakeCLI + FFmpeg Hybrid DVD Engine**: Ultra-fast, progressive DVD title and chapter transcoding powered by HandBrakeCLI, with automatic fallback to FFmpeg IFO stream parsing.
- **Chapter-Level Ripping & Timeline Generation**: Rip entire DVD titles or select individual chapters directly from collapsible cards. Automatically generate microsecond-accurate `.txt` chapter timeline files via bundled FFprobe.
- **Comprehensive Audio Track Selection**: Discover all audio streams (AC-3, DTS, LPCM, MPEG Audio, 5.1 multichannel) with language metadata and per-title selection persistence across both video and audio-only extraction modes.
- **Deep Software Optimizations**: Background subprocess execution with zero command-prompt window popups, instantaneous dark/light theme switching, 100%/125%/150% UI scaling with rock-solid window maximize/restore layout stability, and configurable process CPU priority.

---

## ✨ Features Breakdown

### 📀 DVD Pipeline Features

| Feature | Description |
|---|---|
| 🚀 **Hybrid Dual Engine** | High-performance title discovery and progressive ripping via **HandBrakeCLI**, seamlessly backed by **FFmpeg / IFO parsing** fallback if HandBrakeCLI is unavailable. |
| 📑 **Hierarchical Title & Chapter Ripping** | All chapters are expanded by default in interactive cards. Rip the complete title (`_FULL`), select specific chapters, or extract individual chapters without cumbersome mode switching. |
| ⏱ **Chapter Timeline File (.txt)** | Optional automatic timeline export (`Generate Chapter Timeline File (.txt)`) creating a companion text file (e.g., `Title_01_FULL_Chapter_Timeline.txt`) with exact timestamps and formatted FFprobe command. |
| 🎧 **Full Audio Track Selection** | Complete discovery of all audio tracks per title (track number, language, codec, channel layout such as Stereo or 5.1 Surround). Supports explicit stream mapping across MP4, MOV, MPG, WAV, MP3, and dual Video+Audio modes. |
| 📁 **DVD Title Output Subfolders** | Optional **Create folder with DVD title** automatically organizes ripped titles and chapters into neat disc-title subfolders. |
| 🔄 **Hierarchical Selection Logic** | One-click **ALL** selects all titles and all chapters simultaneously; **None** deselects all. Individual checkboxes update parent counts reactively. |
| 🛠 **MPEG Timestamp & Sync Hardening** | Robust handling of MPEG-2 PCR/PTS timeline discontinuities, dropped frames, and audio-video drift prevention for old or scratched discs. |

### 💿 VCD Pipeline Features

| Feature | Description |
|---|---|
| ⚡ **Direct Raw DAT Copy** | Extract raw `.dat` MPEG-1 video tracks directly from VCD discs without re-encoding — transfers at maximum optical drive read speed. |
| 🎞 **Video Conversion** | Convert DAT tracks to modern **MP4** (H.264 + AAC), **MOV**, or standard **MPG** containers. |
| 📐 **1080p Resolution Upscale** | High-quality Lanczos upscaling to 1080p (1440×1080 for 4:3 aspect ratio, 1920×1080 for 16:9). |

### 🎵 Export Modes & Audio Formats

| Feature | Description |
|---|---|
| 🎬 **Video Mode** | Export video with audio in MP4, MOV, MPG, or DAT formats. |
| 🎧 **Audio Only Mode** | Extract pristine soundtrack audio directly into **WAV** (lossless PCM) or **MP3** (high-bitrate). |
| 🔀 **Video and Audio Dual Mode** | Simultaneously produce both the video file and a standalone audio track in a single extraction pass. |
| 🎨 **Smart Greyout Layout** | Resolution and video-specific options gracefully transition to a greyed-out disabled state when Audio Only is active, preventing distracting UI reflows. |

### ⚡ Software Optimizations & UX Enhancements

| Feature | Description |
|---|---|
| 🪟 **Zero Console Window Flashes** | All background operations (FFmpeg, FFprobe, HandBrakeCLI, PowerShell eject) utilize Win32 `CREATE_NO_WINDOW`, eliminating command prompt popups on Windows. |
| 🌓 **Adaptive Theme System** | Seamlessly toggle between **System** (follows Windows Dark/Light mode), **Light Mode**, and **Dark Mode**. Color palettes, headers, cards, and modal dialogs refresh cleanly with high contrast. |
| 🔍 **Multi-DPI Interface Scaling** | Presets for **100%**, **125%**, and **150%** UI scaling. Engineered with strict sidebar docking and dynamic canvas reflow to ensure zero dead margins when maximizing or restoring the window. |
| 🏎 **Ripping Process Priority** | Configurable CPU scheduling in Settings: **Low**, **Medium**, or **High** (default). Keeps heavy ripping jobs fast while leaving system multitasking responsive. |
| 🎞 **Ripping FPS Mode** | Choose between **Passthrough** (default, preserves original frame rate) and **CFR** (constant frame rate) for maximum device compatibility. |
| ✏ **Individual & Batch Renaming** | Direct `✏` rename buttons on every Title and Chapter card. Includes a sequential **Batch Rename** tool supporting custom prefix, start index, and suffixes. |
| 📊 **Real-Time Progress & Taskbar Sync** | Unified, smooth progress tracking displaying current track/chapter progress alongside total job percentage, mirrored directly on the Windows taskbar icon. |
| 🖱 **Global MouseWheel Scrolling** | Hover over any scrollable view (source options, track list, right sidebar, console log) to scroll immediately without clicking to focus. |
| 🔒 **Single-Instance Mutex** | Windows system-level mutex prevents duplicate instances from launching; re-launching brings the active window to the foreground. |
| ⏏ **Optical Drive Ejection** | Multi-strategy safe disc ejection utilizing Win32 `DeviceIoControl` (IOCTL_STORAGE_EJECT_MEDIA) and PowerShell fallback. |
| 🌐 **Bilingual Localization** | Instant, runtime language switching between **English** and **简体中文 (Simplified Chinese)**. |

---

## 🖥 System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| **Operating System** | Windows 7 SP1 (64-bit) | Windows 10 / 11 (64-bit) |
| **Processor** | Dual-core x86-64 CPU | Quad-core Intel Core i5 / AMD Ryzen or better |
| **Memory (RAM)** | 512 MB | 2 GB or more |
| **Disk Space** | ~200 MB for app & tools | 10+ GB free space for ripped video files |
| **Optical Drive** | DVD-ROM / CD-ROM drive | High-speed internal or USB 3.0 external drive |
| **Python** *(source only)* | Python 3.9+ | Python 3.11+ (bundled in portable build) |

---

## 🚀 Getting Started

### Option A: Portable Release (Recommended — No Installation Required)

1. Download **`Disc_Ripper_Pro_Portable_v2.0.0.zip`** from the [Releases](../../releases) directory.
2. Extract the archive to any folder on your computer.
3. Double-click **`Disc Ripper Pro.exe`** to run.
4. *Note: Keep the bundled `_internal\` and `ffmpeg\` folders alongside `Disc Ripper Pro.exe`.*

### Option B: Run from Source

#### 1. Clone or Download the Repository

```bash
git clone https://github.com/jjsiew2014-art/vcd-ripper-pro.git
cd vcd-ripper-pro
```

#### 2. Install Dependencies

```bash
pip install -r requirements.txt
```
*(Dependencies: `Pillow` for high-resolution graphics and UI icons)*

#### 3. Setup FFmpeg

If FFmpeg is not installed on your system PATH, download it automatically:

```bash
python setup_ffmpeg.py
```
Or place `ffmpeg.exe` and `ffprobe.exe` into a local `ffmpeg/bin/` folder.

#### 4. Launch Application

```bash
python vcd_ripper.py
```
Or double-click `launch.bat`.

---

## 📖 Usage Guide

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [💿 Logo] Disc Ripper Pro v2.0.0               [⏏ Eject] [✏ Rename] [⚙ Settings] [Log] │  <- Header
├───────────────────┬────────────────────────────────────────────────┬───────────────────┤
│ SOURCE & SEL      │ VIDEO FILES LIST                               │ EXPORT CONTROLS   │
│                   │                                                │                   │
│ 💿 Disc Auto-Detect│ 📼 Title 01 (DVD-Video, 01:45:12, 720×480) ✏  │ Output Format:    │
│    [Scan Disc]    │    ├─ ☑ Chapter 01 (00:00 → 05:20) ✏           │ (•) Video         │
│                   │    ├─ ☑ Chapter 02 (05:20 → 12:45) ✏           │ ( ) Audio Only    │
│ Selection:        │    └─ ☑ Chapter 03 (12:45 → 24:10) ✏           │ ( ) Video + Audio │
│    [☑ ALL] [☐ NONE]│                                                │                   │
│                   │ 📼 Title 02 (DVD-Video, 00:25:00) ✏            │ Format: MP4 / MOV │
│                   │    └─ ☑ Chapter 01 ...                         │ [⚡ Start Ripping] │
└───────────────────┴────────────────────────────────────────────────┴───────────────────┘
```

1. **Insert Disc & Detect**:
   - Insert a VCD or DVD into your optical drive. Disc Ripper Pro automatically identifies the disc format and triggers a scan.
   - Alternatively, click **Browse Folder** to target a local folder containing a VCD structure or a DVD `VIDEO_TS` directory.
2. **Review Titles & Chapters**:
   - For DVDs, titles are listed with duration, resolution, audio streams, and chapters.
   - Expand or collapse chapters as desired. Check or uncheck individual chapters to extract only specific segments.
   - Click the **✏** button on any title or chapter to assign a custom output filename, or use **Batch Rename** in the header.
3. **Configure Export Settings**:
   - In the right sidebar, choose your output format (**MP4**, **MOV**, **MPG**, or raw **DAT** for VCD).
   - If ripping audio, select **Audio Only** (**WAV** or **MP3**), or choose **Video and Audio** to rip both simultaneously.
   - For DVDs with multiple languages, select the desired **Audio Track** from the dropdown.
   - *(Optional)* Check **Create folder with DVD title** to organize files automatically.
   - *(Optional)* Check **Generate Chapter Timeline File (.txt)** for companion timestamp files.
4. **Start Ripping**:
   - Click **⚡ Start Ripping**. Progress is shown on-screen and on the Windows taskbar.
   - You can stop an ongoing rip at any time by clicking **⏹ Stop Ripping**.

---

## ⚙ Application Settings & Customization

Click the **⚙ Setting** button in the top-right header to configure:

- **Appearance**: Toggle between **System** (syncs with Windows), **Light Mode**, and **Dark Mode**.
- **Interface Scaling**: Choose **100%**, **125%**, or **150%** scaling for optimal readability across 1080p, 2K, and 4K displays.
- **Ripping Process Priority**: Adjust CPU scheduling priority (**Low**, **Medium**, **High**) to balance transcoding speed with system multitasking.
- **Ripping FPS Mode**: Select **Passthrough** (recommended for native frame timing) or **CFR** (constant frame rate).
- **Language**: Switch instantly between **English (EN)** and **简体中文 (中)**.

---

## 🗂 Project Structure

```
Disc Ripper Pro/
├── vcd_ripper.py          # Main GUI application, pipeline orchestration & state management
├── dvd_engine.py          # DVD parsing, HandBrakeCLI & FFmpeg/IFO transcoding engine
├── disc_detector.py       # Optical drive media type detection & drive inspection
├── CompactDisc.png        # Application logo
├── CompactDisc.ico        # Multi-resolution Windows application icon
├── en.json                # English translation catalog
├── zh-CN.json             # Simplified Chinese translation catalog
├── config.json            # User preferences persistence (theme, scale, priority, fps)
├── launch.bat             # Quick launcher script
├── build.bat              # PyInstaller automated packaging script
├── setup_ffmpeg.py        # FFmpeg automatic download utility
├── requirements.txt       # Python package dependencies
├── Disc Ripper Pro.spec   # PyInstaller build specification
├── tests/                 # Automated test suite (152+ unit and regression tests)
│   └── test_disc_ripper.py
└── ffmpeg/
    └── bin/
        ├── ffmpeg.exe     # Multimedia encoding/decoding engine
        └── ffprobe.exe    # Stream analysis & chapter inspection tool
```

---

## 🔧 Building from Source

To create the standalone portable release:

```bash
# 1. Install build requirements
pip install pyinstaller pillow

# 2. Compile executable using spec
pyinstaller --noconfirm "Disc Ripper Pro.spec"

# 3. Or run the automated build script
build.bat
```

The resulting standalone executable will be located in `dist/Disc Ripper Pro/`, and packaged into `Release/Disc_Ripper_Pro_Portable_v2.0.0.zip`.

---

## 🧪 Testing & Reliability

Disc Ripper Pro includes a comprehensive automated test suite with **152+ tests** covering:
- DVD and VCD auto-detection and fallback routing
- HandBrakeCLI & FFmpeg title discovery and chapter timestamp extraction
- Multi-audio stream mapping and 5.1 channel retention
- Chapter timeline `.txt` file generation and FFprobe parameter formatting
- Zero-console-window subprocess creation flag guarantees
- Dynamic layout stability across 100%, 125%, and 150% DPI scaling under maximize and restore operations
- Theme and language runtime switching integrity

Run the test suite with:

```bash
python -m unittest discover -s tests
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

Developed with passion by **jjsiew2014-art**. Free to use, modify, and distribute.
