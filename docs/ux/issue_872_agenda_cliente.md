# Checklist UX previo — agenda del cliente (#872)

- **Objetivo:** registrar hechos y consultarlos por texto y fechas desde el trabajo diario.
- **Usuario:** operador con acceso a la ficha, cuenta corriente, pagos u órdenes.
- **Permisos:** se hereda el acceso de la pantalla de origen; no hay permiso separado para la agenda. Confirmar con el operador que esta política es adecuada para datos sensibles.
- **Datos mínimos:** cliente, fecha de lo sucedido, texto y usuario; se guarda además la fecha de registro.
- **Acciones:** agregar una anotación, buscar texto, filtrar por fechas y cerrar sin alterar el formulario de origen.
- **Estados:** vacío y sin resultados informados; datos en tabla; rango inválido y error de base informados. La consulta es síncrona; no hay estado de carga independiente. El acceso sin permiso queda cubierto por la pantalla de origen.
- **Validación manual:** abrir desde los cuatro orígenes, consultar cada cliente de una orden múltiple, registrar una nota y volver al pago u orden sin perder lo ingresado.
- **Criterios visuales:** datos legibles, controles de fecha completos, acciones visibles y feedback de error.
- **Fuera de alcance:** edición, eliminación, recordatorios e integraciones externas. La búsqueda comprende el texto de la anotación; fecha de ocurrencia y registro son independientes.
- **Lista para implementar:** sí; validación con operador pendiente antes del cierre.
