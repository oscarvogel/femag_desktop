# Evidencia: despliegue claro de combos autocompletables

Captura generada con PyQt5 en modo `QT_QPA_PLATFORM=offscreen` desde
`scripts/generate_combo_deploy_screenshot.py`.

La captura muestra el combo con el popup abierto (equivalente a hacer clic en el campo),
evidenciando que el despliegue ahora es descubrible: clic en cualquier parte del campo abre
la lista completa y al tipear se filtra en vivo.

Limitación conocida: en modo offscreen el texto puede renderizarse como bloques; el
comportamiento funcional queda cubierto por `tests/test_combo_autocomplete.py`.
