# Release 2026.10.20.18.55.30: el build que no pisa lo editado

Registro del 21/10/2026. Es el build que publica el cambio de **#746** (la
importacion de maestros no pisa lo que el operador edito a mano), con el comando
de puesta a punto de **#744**.

## Identidad del build

| dato | valor |
|---|---|
| version | `2026.10.20.18.55.30` |
| source_sha | `8d014265b9fde236c385add4e95e9b03a18220ef` (`8d01426` en `oscarvogel/femag_desktop`) |
| SHA256 | `a04abad5e011ffa46ae5c806d79e0a39754f1b3ab08baa43c0b757d4a8b43dad` |
| instalador | `installer/output/FEMAG_Desktop_Produccion_Setup.exe` (42.756.947 bytes) |
| tag candidate | `femag-candidate`, publicado el 2026-10-20 21:57Z |
| tag produccion | `latest`, promovido el 2026-10-21 10:11Z (run `39582694801`) |
| version anterior | `2026.10.20.15.56.57` (queda en `femag-previous`) |

Descarga (produccion):
<https://github.com/oscarvogel/vogel-releases/releases/download/latest/FEMAG_Desktop_Produccion_Setup.exe>

Los tres puntos coinciden: el SHA del instalador local, el digest del asset
publicado en `femag-candidate` y en `latest`, y el `sha256` de `candidate.json` y
`latest.json` son el mismo.

## Que trae este build

- **#744**: comando unico de puesta a punto para el F150
  (`scripts/setup_f150_data.py`): importa la referencia DGR, despues los
  maestros, y configura el origen DGR que falta. Sale con `exit 0` solo si la
  base quedo lista para emitir.
- **#746**: la importacion de maestros deja de pisar lo que el operador edito a
  mano. Por defecto va en modo `patch` (solo completa lo vacio); el modo
  `overwrite` queda como opcion explicita para una recarga deliberada.

## Que se valido

| validacion | resultado |
|---|---|
| suite completa | `1840 passed, 3 skipped` |
| smoke + `--production-health-check` del EXE congelado | ok (dentro del `release.ps1`) |
| instalacion real en la PC piloto (canal `candidate`) | exit 0 |
| health-check de la app instalada | `FEMAG production health OK: config, logging, models, ui-components, pyqt, database-readonly, schema-readonly` |
| base del cliente (dump real) con ediciones simuladas | telefono, razon social y domicilios respetados; localidad DGR completada; remito de 15 a 0 problemas |

## Lo que fallo en el camino

El `release.ps1 candidate` **se caigo en el paso [7/7]**, al clonar
`oscarvogel/vogel-releases`: la conexion se corto a mitad del `fetch-pack`.

```
error: RPC failed; curl 56 Recv failure: Connection was reset
error: 737 bytes of body are still expected
fetch-pack: unexpected disconnect while reading sideband packet
fatal: early EOF
```

Lo importante es **que ya estaba hecho** cuando se cayo:

- el EXE y el instalador estaban construidos y validados (smoke + health-check);
- el instalador **ya estaba subido** al tag `femag-candidate` (`gh release upload
  --clobber`), con el digest ya verificado;
- el unico paso que faltaba era el manifiesto `apps/femag/candidate.json` del
  repo de releases, que es lo que lee el updater de la app.

Como el build era correcto y el asset era el mismo, **no se relanzo el release**
(son ~20 min): se reintento el clon (a la primera) y se escribio el manifiesto a
mano con el mismo payload que arma `release.ps1` (misma `version`, mismo
`source_sha` tomado de `git rev-parse HEAD`, mismo `sha256` del instalador).
Commit `d477e78` en `oscarvogel/vogel-releases`, push a `main`.

Despues, `release.ps1 production` (workflow `promote-production.yml`, run
`39582694801`) quedo en verde: `latest.json` quedo con la version y el SHA de este
build, y `previous.json` con el anterior, para rollback.

**Para la maquina del cliente**: hay que **actualizar la app primero**. Con la
version anterior, la importacion sigue pisando lo editado; con esta, no.
