from PyInstaller.utils.hooks import collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("pymysql")
hiddenimports += collect_submodules("dotenv")


a = Analysis(
    ["../app/managerial_summary_entrypoint.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "PyQt5"],
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
    name="FEMAG_Managerial_Summary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon="../app/ui/assets/branding/femag.ico",
)
