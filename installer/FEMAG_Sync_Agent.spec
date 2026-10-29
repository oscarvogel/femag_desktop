# Agente de sincronizacion FEMAG (#804).
#
# Es un ejecutable de consola independiente del escritorio y del servidor web.
# No usa PyQt: solo peewee, PyMySQL, dotenv y los modelos/servicios de sync.

a = Analysis(
    ["../app/jobs/sync_agent.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=["pymysql", "dotenv"],
    excludes=[
        "pytest",
        "tkinter",
        "PyQt5",
        "pyqt5libs",
        "matplotlib",
        "numpy",
        "reportlab",
        "PIL",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FEMAG Sync Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="FEMAG Sync Agent",
)
