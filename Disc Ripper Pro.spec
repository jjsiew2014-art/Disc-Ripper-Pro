# -*- mode: python ; coding: utf-8 -*-
import os

spec_dir = os.path.abspath(SPECPATH)

a = Analysis(
    [os.path.join(spec_dir, 'vcd_ripper.py')],
    pathex=[spec_dir],
    binaries=[],
    datas=[
        (os.path.join(spec_dir, 'CompactDisc.ico'), '.'),
        (os.path.join(spec_dir, 'CompactDisc.png'), '.'),
        (os.path.join(spec_dir, 'en.json'), '.'),
        (os.path.join(spec_dir, 'zh-CN.json'), '.'),
    ],
    hiddenimports=['PIL._tkinter_finder', 'dvd_engine', 'disc_detector'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Disc Ripper Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(spec_dir, 'CompactDisc.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Disc Ripper Pro',
)
