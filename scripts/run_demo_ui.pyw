import os
from pathlib import Path

from app.main import main


if __name__ == "__main__":
    base_dir = Path(os.getenv("LOCALAPPDATA", Path.home())) / "FEMAG"
    raise SystemExit(main(["--demo", "--demo-db", str(base_dir / "femag_ui_review.sqlite3")]))
