from __future__ import annotations

import os

from waitress import serve

from app.config.database import initialize_runtime_database
from webapp import create_app


def main() -> None:
    initialize_runtime_database()
    host = os.getenv("FEMAG_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("FEMAG_WEB_PORT", "8000"))
    serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
