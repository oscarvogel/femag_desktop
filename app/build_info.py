"""Build identity injected by the production build.

Development defaults are intentionally inert so local/source executions never
identify themselves as an installed FEMAG production build.
"""

APP_ID = "development"
BUILD_VERSION = "0.0.0.0.0.0"
