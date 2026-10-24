from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# La hoja de QR por turno usa reportlab.graphics.barcode.qr: sin estos
# hiddenimports y datas, el congelado no encuentra el codigo QR.
hiddenimports = collect_submodules("reportlab.graphics.barcode")
datas = collect_data_files("reportlab")

# Las plantillas de Flask (base, login, production, order, home, error) tienen
# que viajar como datos: en un congelado, el paquete webapp queda dentro del
# PYZ y Jinja no encuentra los .html en disco si no se extraen aca.
datas += collect_data_files("webapp", includes=["templates/*.html"])

a = Analysis(
    ["../webapp/server_entrypoint.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    # El servidor no usa PyQt: la webapp no importa app.ui (medido: create_app
    # carga 26 modulos de app.* y ninguno de app.ui). Excluirlo mantiene el
    # paquete chico y evita arrastrar pyqt5libs.
    excludes=["pytest", "tkinter", "PyQt5", "pyqt5libs", "matplotlib", "numpy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FEMAG Webapp Server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Con consola: el servicio redirige stdout/stderr a un archivo de log, y
    # sin consola esa redireccion se queda vacia.
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="FEMAG Webapp Server",
)
