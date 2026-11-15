"""What the four experimental drivers share. Each subclass sets its names and command syntax and writes
generate(), check() and the parsers; this base gives the review rules and the push hooks they have in common."""

from ...models.plan import ConfigPlan
from ...security.masking import MASK
from ..base import Kind, ModelInfo, Session, UnsupportedFeature

CAPABILITIES = {"vlans", "access", "trunk", "ssh"}


class ExperimentalDriver:
    os_id = ""
    os_name = ""
    netmiko_device_type = ""
    capabilities = CAPABILITIES
    cli_syntax = "ios"
    config_prompt = r"\(config[^)]*\)#"
    begin = ""  # command that enters config mode ("" = the OS has no config mode)
    leave: tuple[str, ...] = ()
    max_vlan_name = 32

    # Plan options this driver implements; every other option set in a plan is refused with a clear error.
    supports_domain = False
    supports_disable_http = False
    supports_password_encryption = False  # True: sends a command. Otherwise passwords are stored hashed anyway.
    supports_vty_timeout = False
    supports_portfast = False
    supports_descriptions = False

    def __init__(self, model: ModelInfo):
        self.model = model
        self.flags = model.flags

    def normalize_interface(self, name: str) -> str:
        return name.strip()

    # ------------------------------------------------------------- review
    def review(self, plan: ConfigPlan) -> tuple[dict[str, str], list[str]]:
        errors: dict[str, str] = {}
        notes: list[str] = []
        os_name = self.os_name
        if plan.basic and plan.basic.domain and not self.supports_domain:
            errors["basic.domain"] = f"the {os_name} driver does not set a domain name yet; leave it empty"
        h = plan.hardening
        if h:
            if h.login_block:
                errors["hardening.login_block"] = f"login blocking is not supported by the {os_name} driver"
            if h.banner:
                errors["hardening.banner"] = f"a login banner is not supported by the {os_name} driver"
            if h.disable_http and not self.supports_disable_http:
                errors["hardening.disable_http"] = f"turning off the web server is not supported by the {os_name} " \
                                                   "driver yet"
            if h.password_encryption and not self.supports_password_encryption:
                notes.append(f"{os_name} stores local passwords hashed, so 'password encryption' needs no command.")
        if plan.ssh:
            if plan.ssh.set_enable_secret:
                errors["ssh.set_enable_secret"] = f"the {os_name} driver does not set an enable secret"  # noqa: S105
            if plan.ssh.regenerate_keys:
                errors["ssh.regenerate_keys"] = f"the {os_name} driver does not regenerate SSH host keys"
            if not self.supports_vty_timeout:
                notes.append(f"The SSH idle timeout ({plan.ssh.vty_timeout_minutes} min) is not set on {os_name}.")
        for v_i, v in enumerate(plan.vlans):
            if len(v.name) > self.max_vlan_name:
                errors[f"vlans.{v_i}.name"] = f"{os_name} VLAN names have at most {self.max_vlan_name} characters"
        for i, group in enumerate(plan.access):
            if group.port_security:
                errors[f"access.{i}.port_security"] = f"port security is not supported by the {os_name} driver"
            if group.portfast and not self.supports_portfast:
                notes.append(f"Access ports {', '.join(group.interfaces)}: 'edge port' (portfast) is not set on "
                             f"{os_name}.")
            if group.description and not self.supports_descriptions:
                errors[f"access.{i}.description"] = f"port descriptions are not supported by the {os_name} driver"
        for i, t in enumerate(plan.trunks):
            if t.description and not self.supports_descriptions:
                errors[f"trunks.{i}.description"] = f"port descriptions are not supported by the {os_name} driver"
        if plan.custom_commands:
            notes.append(f"Custom commands are sent to {os_name} exactly as typed, after the generated ones.")
        notes.append(f"{os_name} has no automatic rollback here: if the push fails, restore the device from the "
                     "backup saved with the job.")
        self._review(plan, errors, notes)
        return errors, notes

    def _review(self, plan: ConfigPlan, errors: dict[str, str], notes: list[str]) -> None:
        """OS-specific rules."""

    def _check_features(self, plan: ConfigPlan) -> None:
        for feature in plan.features():
            if feature not in self.capabilities:
                raise UnsupportedFeature(feature, self.os_name)

    @staticmethod
    def _secret(plan: ConfigPlan, kind: Kind) -> str:
        if kind == "preview":
            return MASK
        if plan.ssh is None or plan.ssh.password is None:
            raise ValueError("ssh.password is required to push this plan")
        return plan.ssh.password.get_secret_value()

    # -------------------------------------------------------- push support
    def session(self, plan: ConfigPlan, name: str) -> Session:
        return Session(strategy="backup_restore", begin=self.begin, leave=self.leave, timer=False)

    def rollback_strategy(self) -> str:
        return "backup_restore"

    def info_patterns(self) -> list[str]:
        return []

    def prompts(self, command: str) -> list[tuple[str, str]] | None:
        return None

    def config_dump_commands(self) -> set[str]:
        return {self.backup_command()}

    def precheck_commands(self, plan: ConfigPlan) -> list[str]:
        return []

    def adapt_commands(self, plan, commands, outputs):
        return commands, []

    def rollback_setup(self, running_config: str) -> list[str]:
        return []

    def vlan_commands(self) -> list[str]:
        return []  # VLAN tables are read only by the built-in drivers

    def parse_vlans(self, outputs: dict[str, str]) -> list[dict]:
        return []

    def neighbor_commands(self) -> list[str]:
        return []  # topology discovery is not built for the experimental drivers

    def parse_neighbors(self, outputs: dict[str, str]) -> list[dict]:
        return []
