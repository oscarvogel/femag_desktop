# Token de publicación

Antes de ejecutar `Publish FEMAG production release`, configurar en los secrets del repositorio FEMAG:

`VOGEL_RELEASES_TOKEN`

Debe ser un token con permiso de escritura de Contents sobre `oscarvogel/vogel-releases`.

Este token existe únicamente en GitHub Actions y nunca se incluye en el ejecutable FEMAG ni en el repositorio público de releases.
