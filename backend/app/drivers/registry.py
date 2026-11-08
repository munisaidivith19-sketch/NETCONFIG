"""os_id → driver. Drivers under drivers/experimental/ are offered only with ENABLE_EXPERIMENTAL_DRIVERS=true."""

from ..config import Settings
from .base import Driver, ModelInfo
from .cisco_ios import CiscoIos

CORE: dict[str, type] = {"cisco_ios": CiscoIos}
EXPERIMENTAL: dict[str, type] = {}  # filled in Phase 4 (MikroTik, Huawei VRP, D-Link, TP-Link)


def driver_class(os_id: str, settings: Settings) -> type | None:
    if os_id in CORE:
        return CORE[os_id]
    if settings.enable_experimental_drivers:
        return EXPERIMENTAL.get(os_id)
    return None


def get_driver(os_id: str, model: ModelInfo, settings: Settings) -> Driver | None:
    cls = driver_class(os_id, settings)
    return cls(model) if cls else None
