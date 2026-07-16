# Evidencia visual — issue #190

- `login.png`: logo oficial completo centrado en el inicio de sesión.
- `workspace.png`: composición equilibrada aprobada, con firma discreta en la cabecera y marca compacta sobre el lateral.

Las capturas se generan con:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python scripts/generate_branding_screenshots.py
```

La revisión confirma que el logo conserva su proporción, no está recortado y no se superpone con campos, navegación, búsqueda ni contenido operativo. En modo offscreen de Qt algunos textos se renderizan como bloques, pero las geometrías, pixmaps y controles corresponden a los widgets reales de la aplicación.
