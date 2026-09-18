# Release FEMAG Desktop — flujo único

Un solo punto de entrada: `release.ps1` en la raíz del repo.

## Requisitos en la PC (Windows)

- Python (con `.venv` del proyecto creado), Git y GitHub CLI (`gh`) autenticado.
- Acceso de escritura a `oscarvogel/vogel-releases` (el `gh auth` del usuario o
  `$env:VOGEL_RELEASES_TOKEN`).
- Inno Setup 6 **no** necesita estar preinstalado: si falta `ISCC.exe`, el
  release lo instala automáticamente con `winget` (o Chocolatey como respaldo).
  - Rutas soportadas: `ISCC_PATH`, `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`,
    `C:\Program Files\Inno Setup 6\ISCC.exe`, `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`, `ISCC.exe` en `PATH`.
  - Para desactivar la auto-instalación: `-NoAutoInstall`.
  - Para forzar una ruta: `-IsccPath "C:\ruta\ISCC.exe"` o `$env:ISCC_PATH`.

## Uso normal (un solo comando)

```powershell
.\release.ps1 candidate
```

Hace automáticamente, en orden:

1. Verifica que estás en `main`.
2. Si hay cambios locales (tracked o untracked), los guarda con
   `git stash push --include-untracked` y los restaura al finalizar,
   incluso si algo falla. Tus archivos nunca se pierden.
3. `git fetch origin` + `git merge --ff-only origin/main`.
4. Preflight: Python, `gh`, resolución de Inno Setup (con auto-instalación).
5. `pytest -q` completo (no se omite; si falla, se muestra el error real).
6. `compileall` de `app` y `scripts`.
7. Build del EXE (PyInstaller) + instalador (Inno Setup) con
   `scripts/build_production_installer.ps1`.
8. `--smoke` y `--production-health-check` sobre el EXE congelado
   (con `LOCALAPPDATA` aislado).
9. Chequeo de secretos en `dist\` e `installer\output\`.
10. SHA256 del instalador.
11. `gh release upload` a `femag-candidate` en `oscarvogel/vogel-releases`.
12. Actualización de `apps/femag/candidate.json` (solo ese archivo).
13. Impresión final de `VERSION`, `SHA256`, `SOURCE_SHA`, `INSTALLER_PATH`,
    `DOWNLOAD_URL` y `CANDIDATE_STATUS=OK`.

El instalador queda siempre en:

```text
installer/output/FEMAG_Desktop_Produccion_Setup.exe
```

## Variantes

```powershell
.\release.ps1 candidate -Local       # explícito, igual al comando por defecto
.\release.ps1 candidate -UseActions  # dispara publish-production.yml en GitHub Actions y lo sigue
.\release.ps1 candidate -SkipDeps    # no reinstala requirements-build.txt (más rápido, menos robusto)
.\release.ps1 production             # promueve el candidate publicado a producción (workflow promote-production.yml)
.\release.ps1 production -Local      # promueve con scripts/publish_femag_release.ps1 sin Actions
```

## Notas

- `release_local.ps1` quedó como shim que delega a `.\release.ps1 candidate -Local`.
- `scripts/build_production_installer.ps1` expone `Resolve-InnoSetup`
  (vía `scripts/Resolve-InnoSetup.ps1`): usa `ISCC_PATH`, rutas conocidas,
  `PATH`, e instala con `winget`/`choco` antes de fallar, informando cada intento.
- El flujo no desactiva ni oculta tests. Si Actions o el release local fallan
  en tests, el error mostrado es el real y debe repararse (ver ejemplo:
  `BudgetService` propaga observaciones del destino al presupuesto separado).
- Los archivos de versión `app/build_version.py` / `app/build_info.py` se
  regeneran en cada build y se descartan antes de restaurar tu stash, para que
  nunca bloqueen ni ensucien tu trabajo.
