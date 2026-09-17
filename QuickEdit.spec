# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

pedalboard_datas, pedalboard_binaries, pedalboard_hiddenimports = collect_all('pedalboard')
websocket_datas, websocket_binaries, websocket_hiddenimports = collect_all('websockets')
boto3_datas, boto3_binaries, boto3_hiddenimports = collect_all('boto3')
botocore_datas, botocore_binaries, botocore_hiddenimports = collect_all('botocore')


a = Analysis(
    ['quickedit.py'],
    pathex=['.builddeps'],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.'), ('mpv.exe', '.'), ('nvdaControllerClient64.dll', '.'), *pedalboard_binaries, *websocket_binaries, *boto3_binaries, *botocore_binaries],
    datas=[('runtime', 'runtime'), *pedalboard_datas, *websocket_datas, *boto3_datas, *botocore_datas],
    hiddenimports=pedalboard_hiddenimports + websocket_hiddenimports + boto3_hiddenimports + botocore_hiddenimports,
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
