# Release 2026.10.21.15.04.44: el remito se completa desde el chofer

Registro del 21/10/2026. Es el build que publica el cambio de **#756** (el
transporte del remito se autocompleta desde el chofer, como en las Ordenes de
carga).

## Identidad del build

| dato | valor |
|---|---|
| version | `2026.10.21.15.04.44` |
| source_sha | `bd7f59a5024f48a6a2e281c1efd211072f8038c6` (`bd7f59a` en `oscarvogel/femag_desktop`) |
| SHA256 | `f6d5f70d796a86cb4574076e15a782551cba69b057968c81273c1303752f3167` |
| instalador | `installer/output/FEMAG_Desktop_Produccion_Setup.exe` (42.750.385 bytes) |
| tag candidate | `femag-candidate`, asset publicado el 2026-10-21 18:07:15Z |
| manifiesto `candidate.json` | 2026-10-21 18:12:38Z, commit `322a1a7` en `oscarvogel/vogel-releases` |
| tag produccion | pendiente de promover |
| version en produccion | `2026.10.21.09.36.40` |
| version anterior (rollback) | `2026.10.21.08.47.41` |

Descarga (candidate):
<https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe>

Los tres puntos coinciden: el SHA del instalador local, el digest del asset
publicado en `femag-candidate` y el `sha256` de `candidate.json` son el mismo
(`f6d5f70d...`). El tamano del asset publicado y el del instalador local tambien
coinciden (42.750.385 bytes).

## Que trae este build

- **#756**: al elegir el **chofer** en un remito, el transportista, el camion y el
  acoplado se completan solos, con la misma cascada de las Ordenes de carga.
  El acoplado sigue al camion, pero si el operador escribe la patente a mano
  manda la suya; elegir "Sin asignar" no borra el transporte cargado a mano; y
  abrir un remito en borrador no pisa el transporte ya guardado.
  Detalle en `docs/issue-756-remito-transporte-desde-chofer.md`.

Este build **no** incluye el trabajo de sobres de **#740**, que sigue en
desarrollo (PR #755 abierto).

## Que se valido

| validacion | resultado |
|---|---|
| suite completa (dentro del `release.ps1`) | `1853 passed, 3 skipped` (452 s) |
| `python -m compileall app webapp` | ok, exit 0 |
| smoke + `--production-health-check` del EXE congelado | ok (dentro del `release.ps1`) |
| seguridad del artefacto | ok (dentro del `release.ps1`) |
| digest del asset publicado vs instalador local vs manifiesto | coinciden |
| prueba manual del operador en la PC piloto (canal `candidate`) | **pendiente** |

## Lo que se casi cae en el camino

El paso **[7/7]** (publicacion del manifiesto) se quedo **colgado varios minutos**
en el `git clone` de `oscarvogel/vogel-releases`: el proceso `git` quedo vivo
varios minutos con la red hacia `github.com:443` funcionando, hasta que el clon
termino solo y el release completo con `CANDIDATE_STATUS=OK`.

No hubo que reintentar ni escribir el manifiesto a mano (a diferencia del
release del 21/10 anterior, que se cayo con `RPC failed; curl 56`). El build,
el asset y el manifiesto quedaron consistentes entre si.

**Ojo con el clon**: si se vuelve a colgar, el build **ya esta perdido para
bien** en el paso 7/7 (instalador construido, smoke y health-check hechos, asset
subido y verificado). Lo unico que falta es el manifiesto, y se puede escribir a
mano con el mismo payload que arma `release.ps1` (misma `version`, mismo
`source_sha` de `git rev-parse HEAD`, mismo `sha256` del instalador).

## Estado del workspace

El release se corrio desde `main` con el trabajo en curso de **#740** (PR #755)
guardado en un stash, y se restauro al terminar. `.env` se aparta durante el
release y se restaura al final.

## Proximo paso

1. El operador prueba el candidate en la PC piloto (canal `candidate`): abrir
   Remitos -> Nuevo remito, elegir el chofer y ver que Transportista, Camion y
   Acoplado se completan solos.
2. Con la prueba OK, promover a produccion:
   `.\release.ps1 production` (workflow `promote-production.yml`, ~2 min), que
   sube los mismos bytes al tag `latest` y deja la version anterior en
   `previous.json` para rollback.
