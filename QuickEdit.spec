# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['quickedit.py'],
    pathex=[],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.'), ('mpv.exe', '.'), ('nvdaControllerClient64.dll', '.')],
    datas=[('runtime', 'runtime')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_tk314.py'],
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
    name='QuickEdit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='QuickEdit',
)
