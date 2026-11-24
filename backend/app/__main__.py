"""Run with: python -m app [--reload]. Refuses non-localhost binds unless ALLOW_REMOTE=true and HTTPS is set."""

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
        # Demo on Render: the host's proxy is the only way in, so its X-Forwarded-For is the visitor's real
        # address (needed for the per-IP login rate limit). Locally nothing sits in front, so it is never trusted.
        proxy_headers=settings.demo_mode,
        forwarded_allow_ips="*" if settings.demo_mode else None,
        server_header=False,
        log_level="info",
        ssl_certfile=str(settings.ssl_certfile) if settings.https else None,
        ssl_keyfile=str(settings.ssl_keyfile) if settings.https else None,
    )


if __name__ == "__main__":
    main()
