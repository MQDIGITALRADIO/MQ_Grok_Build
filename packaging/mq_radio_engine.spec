# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for MQRadioEngine (run on macOS in CI).
# From repo root: pyinstaller packaging/mq_radio_engine.spec

from pathlib import Path

block_cipher = None
root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(root / 'mq_radio' / 'desktop_launch.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / 'migrations'), 'migrations'),
        (str(root / 'mq_radio' / 'web' / 'static'), 'mq_radio/web/static'),
    ],
    hiddenimports=[
        'mq_radio',
        'mq_radio.cli',
        'mq_radio.cli.main',
        'mq_radio.config',
        'mq_radio.db',
        'mq_radio.db.connection',
        'mq_radio.engine',
        'mq_radio.engine.mock_engine',
        'mq_radio.engine.base',
        'mq_radio.library',
        'mq_radio.library.scanner',
        'mq_radio.living_log',
        'mq_radio.living_log.service',
        'mq_radio.music_director',
        'mq_radio.music_director.seed',
        'mq_radio.scheduler',
        'mq_radio.scheduler.generator',
        'mq_radio.scheduler.rules',
        'mq_radio.web',
        'mq_radio.web.app',
        'mq_radio.enums',
        'mq_radio.desktop_launch',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MQRadioEngine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MQRadioEngine',
)
