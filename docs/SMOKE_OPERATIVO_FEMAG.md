# Smoke operativo FEMAG

Issue: #105

Este smoke valida el flujo operativo disponible sin usar datos productivos. Crea una base SQLite local descartable con datos sinteticos prefijados `ISSUE105`.

## Comando

```bash
py -3 scripts/femag_operational_smoke.py
```

Opciones utiles:

```bash
py -3 scripts/femag_operational_smoke.py --database-path .tmp/issue_105.sqlite3 --evidence-dir .tmp/issue_105_evidence --report-path .tmp/issue_105_report.md
```

## Que valida

| Modulo | Estado | Validacion |
|---|---|---|
| App / schema | Cubierto | Abre SQLite local, crea schema runtime y permisos base. |
| ABMs de transporte | Cubierto | Crea transportista, chofer y camion sinteticos. |
| Cliente, lugar y producto demo | Cubierto | Crea cliente, direccion de entrega y producto sinteticos. |
| Ordenes de carga | Cubierto | Crea orden, emite, imprime PDF y cierra. |
| Liberacion de chofer | Cubierto | Verifica chofer disponible luego del cierre. |
| Cuenta corriente y pagos | Cubierto | Emision genera saldo, pago sintetico lo deja en cero. |

## Modulos no disponibles

| Modulo | Estado | Motivo |
|---|---|---|
| Remitos | Modulo no disponible | Queda fuera de #105 y no debe usarse remito real. |
| F150 | Modulo no disponible | Queda fuera de #105 y no debe usarse fiscal real. |
| Rendicion de transportistas | Modulo no disponible | Pendiente de diseno/implementacion en issues separados. |
| Importacion DBF/MySQL | Modulo no disponible | Area protegida; este smoke usa solo SQLite sintetico. |

## Salidas esperadas

- Exit code `0`.
- PDF `orden_carga_N.pdf` en el directorio de evidencia.
- Reporte Markdown actualizado en `docs/SMOKE_OPERATIVO_FEMAG.md` o en el path indicado por `--report-path`.
- Base local descartable con datos `ISSUE105`.
- Saldo del cliente en cero despues del pago.

## Alcance

Este smoke no implementa funcionalidades faltantes. No usa remitos reales, F150 real, importacion DBF/MySQL, bases productivas ni logica fiscal.
