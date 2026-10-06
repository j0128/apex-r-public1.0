# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

_shared = os.path.normpath(os.path.join(SPECPATH, '..', 'shared'))
hiddenimports = ['yfinance', 'pandas', 'numpy', 'pytz', 'yaml', 'universe_builder', 'config_io', 'strategy_presets', 'apex_core', 'locked_book', 'book_store', 'bootstrap', 'curl_cffi', 'matplotlib.backends.backend_tkagg']
hiddenimports += collect_submodules('yfinance')
hiddenimports += collect_submodules('curl_cffi')
# 市場簡報子套件以延後 import 載入，需明示讓 PyInstaller 收錄
hiddenimports += collect_submodules('briefing')

_briefing_data = os.path.join(_shared, 'briefing', 'data')

a = Analysis(
    ['monitor_gui.py'],
    pathex=[_shared],
    binaries=[],
    datas=[
        ('config.yaml', '.'),
        (os.path.join(_briefing_data, 'sector_groups.yaml'), 'briefing/data'),
        (os.path.join(_briefing_data, 'ticker_aliases.yaml'), 'briefing/data'),
    ],
    hiddenimports=hiddenimports,
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
    name='Apex-R-4.0',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Apex-R-4.0',
)
