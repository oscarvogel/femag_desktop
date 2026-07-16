from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = collect_submodules("pyqt5libs")
datas = collect_data_files("pyqt5libs")
datas += [("../app/ui/assets/branding", "app/ui/assets/branding")]


a = Analysis(
    ["../app/demo_entrypoint.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FEMAG Desktop DEMO",
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
    icon="../app/ui/assets/branding/femag.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FEMAG Desktop DEMO",
)
