# Decisiones Tecnicas - FEMAG Desktop

Este documento registra decisiones base para orientar trabajo futuro.

## Python escritorio

FEMAG Desktop es una aplicacion de escritorio en Python. La prioridad es mantener un flujo instalable y operable en equipos internos, con codigo claro y validaciones locales reproducibles.

## PyQt

La interfaz usa PyQt. Los cambios de UI deben respetar widgets, layouts, senales y patrones existentes. Evitar bloquear el hilo principal con operaciones pesadas.

## ABMs minimos de Ordenes de carga

Issue #70 incorpora ABMs minimos para operar Ordenes de carga en `app/ui/master_abm.py`. Estos ABMs no son el patron definitivo ni instancian todavia `pyqt5libs` AutoABM: mantienen una pantalla PyQt local pequena porque `pyqt5libs` no es importable en el entorno de validacion actual y el AutoABM generado necesita antes un adaptador FEMAG para permisos, auditoria por servicios y labels de combos de relaciones. Cuando ese adaptador exista, migrar estos maestros al patron reutilizable de `pyqt5libs` en un issue dedicado.

## MySQL

MySQL es la base de datos prevista para datos operativos. Los cambios que afecten estructura, migraciones, queries o compatibilidad de datos deben entrar por issues especificos y con validacion clara.

## Peewee

Peewee se usa como ORM. Mantener modelos explicitos, consultas legibles y separacion entre acceso a datos y comportamiento de pantalla cuando sea posible.

## Sistema interno en red local

El sistema esta pensado como herramienta interna en red local. Las decisiones deben priorizar estabilidad operativa, permisos claros y compatibilidad con el entorno de trabajo existente.

## Sincronizacion nube futura

La sincronizacion nube queda como posibilidad futura, no como alcance base de Fase 1. No introducir dependencias, endpoints o estructuras para nube sin issue dedicado.

## Importacion posterior desde DBF/MySQL legacy

La importacion desde DBF/MySQL legacy queda para una etapa posterior. No modificar formatos, campos, codificacion, decimales o fechas de integraciones legacy sin un issue que lo pida y defina pruebas.

## Regla de decision

Cuando una decision tecnica cambie arquitectura, dependencias, persistencia, integraciones o despliegue, agregar una nota en este documento o en un ADR especifico antes de cerrar el PR.
