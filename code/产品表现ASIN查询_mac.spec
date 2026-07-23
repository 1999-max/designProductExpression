# -*- mode: python ; coding: utf-8 -*-
# macOS 专用 spec 文件：生成 产品表现ASIN查询.app
# 使用方法：在 macOS 上运行 pyinstaller 产品表现ASIN查询_mac.spec
# 注意：macOS .app 必须使用 onedir 模式，不能用 onefile

import os

# 自动定位 store_asin_mapping.json（兼容 macOS 和 Windows）
_script_dir = os.path.abspath(SPECPATH)
_mapping_file = os.path.join(os.path.dirname(_script_dir), 'store_asin_mapping.json')
if not os.path.exists(_mapping_file):
    _mapping_file = os.path.join(_script_dir, 'store_asin_mapping.json')

a = Analysis(
    ['product_query_app_mapped.py'],
    pathex=[],
    binaries=[],
    datas=[(_mapping_file, '.')],
    hiddenimports=[],
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
    name='产品表现ASIN查询',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='产品表现ASIN查询',
)

app = BUNDLE(
    coll,
    name='产品表现ASIN查询.app',
    icon=None,
    bundle_identifier=None,
    info_plist={
        'NSHighResolutionCapable': True,
    },
)
