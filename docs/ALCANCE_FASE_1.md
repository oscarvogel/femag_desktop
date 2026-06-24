# Alcance Fase 1 - FEMAG Desktop

Este documento delimita el alcance actual para evitar mezclar trabajo exploratorio, integraciones reales y logica pesada en PRs chicos.

## Incluido

- Shell PyQt navegable.
- Menu lateral por permisos.
- Dashboard operativo.
- Specs ABM.
- Pantalla base de ordenes de carga.
- Impresion A4 base.
- Seed demo.
- Screenshots UX.

## Fuera de alcance por ahora

- Remitos reales.
- F150 real.
- Importacion DBF/MySQL.
- Logica pesada de liquidaciones.
- Integracion con sistema anterior.
- Sincronizacion nube.
- Pedidos web.

## Regla de alcance

Si un issue necesita mover algo fuera de alcance, debe decirlo explicitamente y explicar:

- Por que es necesario ahora.
- Que datos reales podria afectar.
- Como se valida sin poner en riesgo la operacion.
- Que queda fuera aunque parezca relacionado.

## Uso para PRs

Antes de abrir un PR, comparar el diff contra este documento. Si el PR toca una area fuera de alcance sin issue especifico, separarlo o frenarlo.

Loop Engineering se usa para ordenar el trabajo dentro de este alcance. No habilita por si solo remitos reales, F150 real, importacion DBF/MySQL, logica pesada ni integraciones futuras.
