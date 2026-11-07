from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def main() -> None:
    os.chdir(Path(__file__).resolve().parent.parent)

    from app.config import settings
    from app.main import app

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
