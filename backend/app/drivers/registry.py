"""os_id → driver. Drivers under drivers/experimental/ are offered only with ENABLE_EXPERIMENTAL_DRIVERS=true."""

from ..config import Settings
from .arista_eos import AristaEos
from .aruba_aoscx import ArubaAoscx
from .base import Driver, ModelInfo
from .cisco_ios import CiscoIos
from .experimental.dlink_ds import DlinkDs
from .experimental.huawei_vrp import HuaweiVrp
from .experimental.mikrotik_routeros import MikrotikRouteros
from .experimental.tplink_jetstream import TplinkJetstream
from .juniper_junos import JuniperJunos

# Built-in drivers. Their catalog support level ("experimental" until the lab checklist passes) decides the
# warnings and whether production devices may use them; they are always loaded.
CORE: dict[str, type] = {"cisco_ios": CiscoIos, "arista_eos": AristaEos, "juniper_junos": JuniperJunos,
                         "aruba_aoscx": ArubaAoscx}
# Loaded only with ENABLE_EXPERIMENTAL_DRIVERS=true: no automatic rollback and not lab-proven.
EXPERIMENTAL: dict[str, type] = {"mikrotik_routeros": MikrotikRouteros, "huawei_vrp": HuaweiVrp,
                                 "dlink_ds": DlinkDs, "tplink_jetstream": TplinkJetstream}


def driver_class(os_id: str, settings: Settings) -> type | None:
    if os_id in CORE:
        return CORE[os_id]
    if settings.enable_experimental_drivers:
        return EXPERIMENTAL.get(os_id)
    return None


def get_driver(os_id: str, model: ModelInfo, settings: Settings) -> Driver | None:
    cls = driver_class(os_id, settings)
    return cls(model) if cls else None
