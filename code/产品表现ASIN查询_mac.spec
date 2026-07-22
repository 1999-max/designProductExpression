# -*- mode: python ; coding: utf-8 -*-
# macOS 专用 spec 文件：生成 产品表现ASIN查询.app
# 使用方法：在 macOS 上运行 pyinstaller 产品表现ASIN查询_mac.spec


a = Analysis(
    ['product_query_app_mapped.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\productData\\designProductExpression\\store_asin_mapping.json', '.')],
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
    a.binaries,
    a.datas,
    [],
    name='产品表现ASIN查询',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

app = BUNDLE(
    exe,
    name='产品表现ASIN查询.app',
    icon=None,
    bundle_identifier=None,
    info_plist={
        'NSHighResolutionCapable': True,
    },
)
