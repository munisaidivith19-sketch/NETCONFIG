"""Plan → validated, safety-checked command list for one target. Shared by the preview API and jobs (3A)."""

import hashlib
from dataclasses import dataclass, field

from pymongo.database import Database

from ..config import Settings
from ..drivers.base import Driver, ModelInfo
from ..drivers.registry import get_driver
from ..errors import ApiError
from ..models.common import oid
from ..models.device import PRODUCTION_TAG
from ..models.plan import ConfigPlan
from ..security.masking import mask_lines
from . import safety, validation
from .catalog import effective_capabilities

PRODUCTION_CUSTOM = "custom commands are not allowed on production devices"


@dataclass
class Prepared:
    plan: ConfigPlan
    model: dict
    driver_doc: dict
    device: dict | None
    driver: Driver | None
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unsupported: list[dict] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)  # masked
    verify_commands: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def production(self) -> bool:
        return bool(self.device and PRODUCTION_TAG in self.device.get("tags", []))

    @property
    def commands_hash(self) -> str:
        return commands_hash(self.commands)


def commands_hash(commands: list[str]) -> str:
    return hashlib.sha256("\n".join(commands).encode("utf-8")).hexdigest()


def _target(db: Database, device_id: str | None, model_id: str | None) -> tuple[dict | None, dict]:
    device = None
    if device_id:
        device = db.devices.find_one({"_id": oid(device_id)})
        if not device:
            raise ApiError(404, "Device not found.")
        model_id = device["model_id"]
    model = db.catalog_models.find_one({"_id": model_id})
    if not model:
        raise ApiError(404, "Catalog model not found.")
    return device, model


def prepare(db: Database, settings: Settings, plan: ConfigPlan, *, device_id: str | None = None,
            model_id: str | None = None) -> Prepared:
    device, model = _target(db, device_id, model_id)
    driver_doc = db.os_drivers.find_one({"_id": model["os_id"]}) or {"_id": model["os_id"], "name": model["os_id"]}
    info = ModelInfo.from_doc(model)
    driver = get_driver(model["os_id"], info, settings)
    p = Prepared(plan=plan, model=model, driver_doc=driver_doc, device=device, driver=driver)
    target_key = "device_id" if device else "model_id"

    if driver is None:
        support = driver_doc.get("support", "inventory")
        why = {"planned": "its driver is planned but not built yet",
               "experimental": "its experimental driver is disabled (ENABLE_EXPERIMENTAL_DRIVERS)",
               }.get(support, "it is an inventory-only device")
        p.errors[target_key] = f"NetConfig Studio cannot configure {model.get('name')}: {why}."
        return p
    if driver_doc.get("support") == "experimental":
        p.warnings.append(f"The {driver.os_name} driver is experimental: it has not passed the lab checklist yet.")

    plan = validation.normalize_interfaces(plan, driver.normalize_interface)
    p.plan = plan
    caps = set(effective_capabilities(driver_doc, model)) & set(driver.capabilities)
    result = validation.validate_plan(plan, model=info, capabilities=caps, os_name=driver.os_name)
    p.errors.update(result.errors)
    p.warnings += result.warnings
    p.unsupported = result.unsupported

    if plan.custom_commands and p.production:
        p.errors.setdefault("custom_commands", PRODUCTION_CUSTOM)
    if p.errors:
        return p

    commands = driver.generate(plan, "preview")
    via_ssh = bool(device and device.get("connection", {}).get("method") == "ssh")
    violations = safety.check_denylist(commands) + safety.check_management(
        commands, mgmt_interface=None, mgmt_ip=(device or {}).get("mgmt_ip"), via_ssh=via_ssh,
        normalize_interface=driver.normalize_interface)
    custom_start = len(commands) - len(plan.custom_commands)
    for v in violations:
        path = f"custom_commands.{v.index - custom_start}" if v.index >= custom_start else "commands"
        p.errors.setdefault(path, v.message)
    if p.errors:
        return p

    p.commands = mask_lines(commands)
    p.verify_commands = driver.verify_commands(plan)
    if device and device.get("mgmt_ip"):
        p.warnings.append(f"Before applying, the device is checked for the interface holding {device['mgmt_ip']}; "
                          "changes that would cut that connection are blocked.")
    return p
