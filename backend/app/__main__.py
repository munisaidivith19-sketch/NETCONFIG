"""Run with: python -m app [--reload]. Refuses non-localhost binds unless ALLOW_REMOTE=true."""

import logging
import sys

import uvicorn

from .config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    settings.check_bind_address()
    uvicorn.run(
        "app.asgi:app",
        host=settings.host,
        port=settings.port,
        reload="--reload" in sys.argv,
        proxy_headers=False,
        server_header=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
