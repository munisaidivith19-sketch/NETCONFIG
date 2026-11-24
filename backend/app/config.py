"""Application settings, read from environment variables and backend/.env."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# A wildcard bind listens everywhere, but browsers never send it as their Host header, so the allowlist could
# not name the address people really use. Remote mode binds to one address of this PC instead.
WILDCARD_HOSTS = {"0.0.0.0", "::", ""}  # noqa: S104  # nosec B104 - the list of addresses that are refused


class Settings(BaseSettings):
    # env_ignore_empty: "SSL_CERTFILE=" (as copied from .env.example) means "not set", not Path(".") – which would
    # turn HTTPS on with no certificate – and "AI_API_KEY=" is no key, not an empty one.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", env_ignore_empty=True)

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
    # Public demo on a cloud host (Render): simulated devices only, behind the host's HTTPS proxy, one public
    # hostname. Never reaches a real device. See docs/DEPLOY_RENDER.md.
    demo_mode: bool = False
    # How many X-Forwarded-For entries, counted from the right, the host's own proxies wrote (app/security/clientip.py).
    trusted_proxy_hops: int = Field(default=1, ge=1, le=5)
    public_host: str = Field(default="", max_length=253, pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9-]*$")
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
        # Demo: the browser talks HTTPS to the host's proxy, even though the proxy talks plain HTTP to us.
        return self.cookie_secure or self.https or self.demo_mode

    @property
    def hsts(self) -> bool:
        # Only in remote mode: HSTS for "localhost" would force https on every localhost port (also the Vite dev
        # server) for a year, even after HTTPS is turned off again.
        return (self.https and self.host not in LOCAL_HOSTS) or self.demo_mode

    @property
    def allowed_hosts(self) -> set[str]:
        if self.demo_mode:
            # Only the public name: the proxy forwards the browser's Host header unchanged (on port 443).
            return {self.public_host}
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if self.allow_remote and self.host not in LOCAL_HOSTS:
            hosts.add(f"{self.host}:{self.port}")
        return hosts

    @property
    def allowed_origins(self) -> set[str]:
        if self.demo_mode:
            return {f"https://{self.public_host}"}
        scheme = "https" if self.https else "http"  # what the server really serves
        origins = {f"{scheme}://{h}" for h in self.allowed_hosts}
        if not self.is_production:
            origins.add(self.dev_origin)
        return origins

    def check_simulation(self) -> None:
        # The public demo is the one production setup that must simulate: it has no network to reach.
        if self.simulate_devices and self.is_production and not self.demo_mode:
            raise RuntimeError("SIMULATE_DEVICES=true is not allowed with ENV=production.")

    def check_demo(self) -> None:
        """DEMO_MODE is all or nothing: every setting that keeps a public demo away from real devices must hold."""
        if not self.demo_mode:
            return
        problems = []
        if not self.public_host or "." not in self.public_host:
            problems.append("PUBLIC_HOST must be the demo's domain name (for example nettool.example.com)")
        if not self.is_production:
            problems.append("ENV must be production (no /docs, no dev origin)")
        if not self.simulate_devices:
            problems.append("SIMULATE_DEVICES must be true (a cloud host cannot reach real devices)")
        if self.allow_remote or self.https:
            problems.append("ALLOW_REMOTE and SSL_CERTFILE/SSL_KEYFILE must be unset (the host's proxy does HTTPS)")
        if self.ai_provider != "off":
            problems.append("AI_PROVIDER must be off (public visitors would spend the API key)")
        if problems:
            raise RuntimeError("DEMO_MODE=true needs: " + "; ".join(problems) + ".")

    def check_bind_address(self) -> None:
        """Listening beyond localhost needs ALLOW_REMOTE=true *and* HTTPS (CLAUDE.md 8.1); login is always on.
        The public demo is the exception: the cloud host's proxy is the only way in and it does the HTTPS."""
        if self.demo_mode:
            self.check_demo()
            return
        if (self.ssl_certfile is None) != (self.ssl_keyfile is None):
            raise RuntimeError("HTTPS needs both SSL_CERTFILE and SSL_KEYFILE (or neither).")
        missing = [str(p) for p in (self.ssl_certfile, self.ssl_keyfile) if p and not p.is_file()]
        if missing:
            raise RuntimeError("HTTPS file not found: " + ", ".join(missing))
        if self.host in LOCAL_HOSTS:
            return
        if self.host in WILDCARD_HOSTS:
            raise RuntimeError(
                f"Refusing to bind to {self.host!r}: set HOST to this PC's own address on the engineering network "
                "(for example 192.168.1.10). Only that address is accepted in the Host header."
            )
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
