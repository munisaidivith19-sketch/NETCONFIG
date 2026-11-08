"""Application settings, read from environment variables and backend/.env."""

from pathlib import Path
from typing import Literal

from pydantic import Field
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
    cookie_secure: bool = False  # set true when serving over HTTPS (ALLOW_REMOTE)

    bcrypt_rounds: int = Field(default=12, ge=12, le=16)
    lockout_threshold: int = 5
    lockout_minutes: int = 15
    login_rate_per_minute: int = 10

    max_body_bytes: int = 1_000_000
    enable_experimental_drivers: bool = False
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def allowed_hosts(self) -> set[str]:
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if self.allow_remote and self.host not in LOCAL_HOSTS:
            hosts.add(f"{self.host}:{self.port}")
        return hosts

    @property
    def allowed_origins(self) -> set[str]:
        scheme = "https" if self.cookie_secure else "http"
        origins = {f"{scheme}://{h}" for h in self.allowed_hosts}
        if not self.is_production:
            origins.add(self.dev_origin)
        return origins

    def check_bind_address(self) -> None:
        """Refuse to listen beyond localhost unless ALLOW_REMOTE is set (CLAUDE.md 8.1)."""
        if self.host not in LOCAL_HOSTS and not self.allow_remote:
            raise RuntimeError(
                f"Refusing to bind to {self.host}: set ALLOW_REMOTE=true (and use HTTPS) "
                "to listen on a non-localhost address."
            )
