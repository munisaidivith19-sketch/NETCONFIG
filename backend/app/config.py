"""Application settings, read from environment variables and backend/.env."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    env: Literal["development", "production", "test"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allow_remote: bool = False

    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "netconfig"
    mongo_timeout_ms: int = 2000

    # Vite dev server origin, accepted only when env != production.
    dev_origin: str = "http://localhost:5173"

    session_cookie: str = "ncs_session"
    session_absolute_hours: int = 8
    session_idle_minutes: int = 30
    cookie_secure: bool = False  # always on when SSL_CERTFILE/SSL_KEYFILE are set
    # HTTPS: PEM certificate and private key served by uvicorn. Required to listen beyond localhost (CLAUDE.md 8.1).
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None

    bcrypt_rounds: int = Field(default=12, ge=12, le=16)
    lockout_threshold: int = 5
    lockout_minutes: int = 15
    login_rate_per_minute: int = 10

    max_body_bytes: int = 1_000_000
    enable_experimental_drivers: bool = False
    # Development only: pushes go to an in-memory simulated device instead of the network (demo / tests).
    simulate_devices: bool = False
    # Background ping + port check of every device with a management address (0 turns it off).
    status_poll_seconds: int = Field(default=60, ge=0, le=86400)
    # AI assistant (Phase 5A, optional). Free options only: local Ollama or a hosted free tier. "off" sends nothing.
    ai_provider: Literal["off", "ollama", "groq", "gemini"] = "off"
    ai_api_key: SecretStr | None = None
    ai_model: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9._:-]*$")  # "" = the provider default
    ai_timeout_seconds: int = Field(default=30, ge=5, le=120)
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def https(self) -> bool:
        return self.ssl_certfile is not None and self.ssl_keyfile is not None

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure or self.https

    @property
    def allowed_hosts(self) -> set[str]:
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if self.allow_remote and self.host not in LOCAL_HOSTS:
            hosts.add(f"{self.host}:{self.port}")
        return hosts

    @property
    def allowed_origins(self) -> set[str]:
        scheme = "https" if self.secure_cookies else "http"
        origins = {f"{scheme}://{h}" for h in self.allowed_hosts}
        if not self.is_production:
            origins.add(self.dev_origin)
        return origins

    def check_simulation(self) -> None:
        if self.simulate_devices and self.is_production:
            raise RuntimeError("SIMULATE_DEVICES=true is not allowed with ENV=production.")

    def check_bind_address(self) -> None:
        """Listening beyond localhost needs ALLOW_REMOTE=true *and* HTTPS (CLAUDE.md 8.1); login is always on."""
        if self.host in LOCAL_HOSTS:
            return
        if not self.allow_remote:
            raise RuntimeError(
                f"Refusing to bind to {self.host}: set ALLOW_REMOTE=true, SSL_CERTFILE and SSL_KEYFILE "
                "to listen on a non-localhost address."
            )
        if not self.https:
            raise RuntimeError(
                f"Refusing to bind to {self.host} without HTTPS: set SSL_CERTFILE and SSL_KEYFILE "
                "(PEM certificate and key)."
            )
        missing = [str(p) for p in (self.ssl_certfile, self.ssl_keyfile) if not p.is_file()]
        if missing:
            raise RuntimeError("HTTPS file not found: " + ", ".join(missing))
