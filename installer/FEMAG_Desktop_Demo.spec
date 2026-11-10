from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
)


hiddenimports = collect_submodules("pyqt5libs")
datas = collect_data_files("pyqt5libs")
datas += [("../app/ui/assets/branding", "app/ui/assets/branding")]
datas += [("../app/build_demo_version.py", "app/build_demo_version.py")]

# Precarga con IA (#913) desde foto o PDF.
pdfium_datas, pdfium_binaries, pdfium_hidden = collect_all("pypdfium2")
raw_datas, raw_binaries, raw_hidden = collect_all("pypdfium2_raw")
datas += pdfium_datas + raw_datas
binaries = pdfium_binaries + raw_binaries
hiddenimports += pdfium_hidden + raw_hidden


a = Analysis(
    ["../app/demo_entrypoint.py"],
    pathex=[".."],
    binaries=binaries,
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
