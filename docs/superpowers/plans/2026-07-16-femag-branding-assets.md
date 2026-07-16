# FEMAG Branding Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar el logo oficial FEMAG en la UI, el icono de Windows y la cadena de instalación DEMO, con un contrato reutilizable por el futuro instalador productivo.

**Architecture:** Una utilidad `app.ui.branding` será la única responsable de resolver assets tanto en checkout como bajo `sys._MEIPASS`. Login y shell consumirán pixmaps escalados desde esa utilidad; PyInstaller e Inno Setup empaquetarán el mismo directorio de branding y el mismo `.ico`.

**Tech Stack:** Python 3.13, PyQt5, Pillow, PyInstaller, Inno Setup, pytest.

---

### Task 1: Contrato de assets y resolución de rutas

**Files:**
- Create: `tests/test_branding.py`
- Create: `app/ui/branding.py`
- Create: `app/ui/assets/branding/femag-logo-source.png`
- Create: `app/ui/assets/branding/femag-logo-ui.png`
- Create: `app/ui/assets/branding/femag-logo-compact.png`
- Create: `app/ui/assets/branding/femag.ico`

- [ ] Escribir tests que exijan los cuatro assets, validen formatos/tamaños y comprueben `branding_asset_path()` en checkout y con `_MEIPASS` simulado.
- [ ] Ejecutar `python -m pytest tests/test_branding.py -v` y confirmar fallos por módulo/assets ausentes.
- [ ] Copiar la fuente exacta, producir PNG optimizados e ICO 16/24/32/48/64/128/256 con Pillow.
- [ ] Implementar `branding_asset_path(name)` y `load_brand_pixmap(name, width, height)` de forma defensiva.
- [ ] Repetir `python -m pytest tests/test_branding.py -v` hasta obtener PASS.

### Task 2: Branding en login y pantalla de trabajo

**Files:**
- Modify: `tests/test_branding.py`
- Modify: `app/ui/login_window.py`
- Modify: `app/ui/desktop_app.py`

- [ ] Agregar tests UI que exijan `loginBrandLogo`, `sidebarBrandLogo`, `topbarBrandLogo`, pixmaps válidos, nombres accesibles e icono global no nulo.
- [ ] Ejecutar los tests focalizados y confirmar fallos por widgets ausentes.
- [ ] Insertar el logo completo centrado sobre el título del login y ajustar el alto sin cambiar campos ni acciones.
- [ ] Reemplazar el título textual de cabecera por una firma gráfica discreta y añadir un encabezado de marca sobre el listado lateral.
- [ ] Establecer `femag.ico` en `QApplication`, login y ventana principal.
- [ ] Repetir los tests focalizados hasta obtener PASS.

### Task 3: Empaquetado DEMO y contrato futuro

**Files:**
- Modify: `tests/test_inno_demo_installer.py`
- Modify: `installer/FEMAG_Desktop_Demo.spec`
- Modify: `installer/FEMAG_Desktop_Demo.iss`
- Modify: `docs/INSTALADOR_DEMO_INNO.md`

- [ ] Agregar asserts que exijan `app/ui/assets/branding` en `datas`, `femag.ico` en `EXE`, `SetupIconFile`, `UninstallDisplayIcon` e `IconFilename` en accesos directos.
- [ ] Ejecutar `python -m pytest tests/test_inno_demo_installer.py -v` y confirmar los fallos esperados.
- [ ] Configurar PyInstaller e Inno Setup con el asset neutral compartido.
- [ ] Documentar que DEMO lo usa hoy y el instalador productivo debe reutilizar el mismo contrato.
- [ ] Repetir el test hasta obtener PASS.

### Task 4: Evidencia visual y validación integral

**Files:**
- Create: `docs/screenshots/issue_190_branding/login.png`
- Create: `docs/screenshots/issue_190_branding/workspace.png`
- Create: `docs/screenshots/issue_190_branding/README.md`

- [ ] Generar capturas offscreen reales de login y workspace con la marca visible.
- [ ] Inspeccionar ambas imágenes para detectar recortes, deformaciones o solapamientos.
- [ ] Ejecutar `git diff --check`, `python -m pytest`, `python -m compileall app` y `python -m app.main --smoke`.
- [ ] Ejecutar `powershell -File scripts/build_demo_installer.ps1 -SkipInstallDependencies` si Inno Setup está disponible; documentar con precisión cualquier limitación.
- [ ] Revisar `git status -sb` y el diff completo antes del commit final.

### Task 5: Publicación operativa

**Files:**
- Modify: GitHub issue `#190`
- Create: GitHub pull request desde `codex/issue-190-femag-branding`

- [ ] Commit de implementación con alcance exclusivo de branding.
- [ ] Push de la rama y creación de PR draft con issue, alcance, fuera de alcance, validaciones, riesgos y capturas.
- [ ] Comentar en `#190` el cierre operativo, comandos ejecutados, evidencia y cualquier pendiente real.
