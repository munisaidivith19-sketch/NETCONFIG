"""SIMULATE_DEVICES=true (development only): an in-memory Cisco-like device for demos and the end-to-end check.

It keeps a running configuration made of the lines it receives and renders the `show` outputs that the
Cisco driver's check() parses. It is NOT an IOS emulator: it accepts every command. Use GNS3/CML for
real testing (docs/LAB_TESTING.md).
"""

import copy
import ipaddress
import re
import threading

from .connection import ConnectFailed, ConnectParams

ZERO = str(ipaddress.IPv4Address(0))  # 0.0.0.0 as display text / OSPF wildcard (not a bind)
HEADERS = ("interface ", "vlan ", "line ", "router ", "ip dhcp pool ", "ip access-list ", "archive")
REPLACE_PREFIXES = ("description", "ip address", "switchport access vlan", "switchport mode",
                    "switchport trunk native", "switchport trunk allowed", "name", "exec-timeout", "transport input",
                    "router-id", "eigrp router-id", "bgp router-id", "default-router", "network", "dns-server",
                    "lease", "path", "maximum")
TOP_REPLACE = ("hostname", "ip domain name", "login block-for", "banner motd", "enable secret")
SHORT = {"GigabitEthernet": "Gi", "FastEthernet": "Fa", "TenGigabitEthernet": "Te", "TwoGigabitEthernet": "Tw",
         "FortyGigabitEthernet": "Fo", "HundredGigE": "Hu", "Port-channel": "Po", "Vlan": "Vl", "Loopback": "Lo"}


def short_name(name: str) -> str:
    """IOS prints abbreviated names in fixed-width tables (GigabitEthernet0/1 → Gi0/1)."""
    for full, abbr in SHORT.items():
        if name.startswith(full):
            return abbr + name[len(full):]
    return name


class SimulatedDevice:
    def __init__(self, hostname: str, mgmt_ip: str | None):
        self.lock = threading.Lock()
        self.top: list[str] = [f"hostname {hostname}", "ip http server"]
        self.sections: dict[str, list[str]] = {"vlan 1": [" name default"]}
        if mgmt_ip:
            self.sections["interface Vlan1"] = [f" ip address {mgmt_ip} 255.255.255.0"]
        self.rsa_keys = False
        self.snapshot = None
        self.context: str | None = None

    # ------------------------------------------------------------ config
    def apply(self, line: str) -> str:
        if not line.strip():
            return ""
        if line.startswith(" ") and self.context:
            body = self.sections.setdefault(self.context, [])
            text = line.rstrip()
            key = next((p for p in REPLACE_PREFIXES if text.strip().startswith(p + " ")), None)
            if key and key not in ("network", "dns-server"):
                body[:] = [b for b in body if not b.strip().startswith(key + " ")]
            if text not in body:
                body.append(text)
            return ""
        text = line.strip()
        if text.startswith(HEADERS):
            self.context = text
            self.sections.setdefault(text, [])
            return ""
        self.context = None
        if text.startswith("crypto key generate rsa"):
            self.rsa_keys = True
            return "The name for the keys will be: sim.lab\n% The key modulus size is 2048 bits"
        if text.startswith("no ") and text[3:] in self.top:
            self.top.remove(text[3:])
        key = next((p for p in TOP_REPLACE if text.startswith(p + " ")), None)
        if key:
            self.top = [t for t in self.top if not t.startswith(key + " ")]
        if text.startswith("no ip http") and text[3:] in self.top:
            self.top.remove(text[3:])
        if text not in self.top:
            self.top.append(text)
        return ""

    def begin_window(self) -> None:
        self.snapshot = (copy.deepcopy(self.top), copy.deepcopy(self.sections), self.rsa_keys)

    def revert(self) -> None:
        if self.snapshot:
            self.top, self.sections, self.rsa_keys = self.snapshot
        self.snapshot = None

    # -------------------------------------------------------------- show
    def running_config(self) -> str:
        out = ["Building configuration...", "", "!"]
        out += self.top
        for head, body in self.sections.items():
            out += ["!", head, *body]
        out += ["!", "end"]
        return "\n".join(out)

    def _interfaces(self) -> dict[str, list[str]]:
        return {h.split(" ", 1)[1]: b for h, b in self.sections.items() if h.startswith("interface ")}

    def _value(self, body: list[str], prefix: str) -> str | None:
        for b in body:
            if b.strip().startswith(prefix + " "):
                return b.strip()[len(prefix) + 1:]
        return None

    def show(self, command: str) -> str:
        c = command.strip()
        if c == "show running-config":
            return self.running_config()
        if c == "show ip interface brief":
            rows = ["Interface              IP-Address      OK? Method Status                Protocol"]
            for name, body in self._interfaces().items():
                addr = self._value(body, "ip address")
                ip = addr.split()[0] if addr else "unassigned"
                rows.append(f"{name:<22} {ip:<15} YES manual up                    up")
            return "\n".join(rows)
        if c == "show vlan brief":
            rows = ["VLAN Name                             Status    Ports",
                    "---- -------------------------------- --------- -------------------------------"]
            for head, body in self.sections.items():
                if head.startswith("vlan ") and head[5:].isdigit():
                    name = self._value(body, "name") or f"VLAN{int(head[5:]):04d}"
                    rows.append(f"{head[5:]:<4} {name:<32} active")
            return "\n".join(rows)
        if c == "show interfaces status":
            rows = ["Port         Name               Status       Vlan       Duplex  Speed Type"]
            for name, body in self._interfaces().items():
                mode = self._value(body, "switchport mode")
                vlan = "trunk" if mode == "trunk" else self._value(body, "switchport access vlan") or "1"
                if name.startswith(("Vlan", "Loopback")):
                    continue
                rows.append(f"{short_name(name):<12} {'':<18} connected    {vlan:<10} a-full a-1000 10/100/1000BaseTX")
            return "\n".join(rows)
        m = re.fullmatch(r"show interfaces (\S+) switchport", c)
        if m:
            body = self._interfaces().get(m.group(1), [])
            mode = self._value(body, "switchport mode") or "dynamic auto"
            native = self._value(body, "switchport trunk native vlan") or "1"
            allowed = self._value(body, "switchport trunk allowed vlan") or "ALL"
            return (f"Name: {m.group(1)}\nSwitchport: Enabled\nAdministrative Mode: {mode}\n"
                    f"Trunking Native Mode VLAN: {native}\nTrunking VLANs Enabled: {allowed}\n")
        if c == "show ip ssh":
            on = self.rsa_keys and "ip ssh version 2" in self.top
            return "SSH Enabled - version 2.0" if on else "SSH Disabled - version 1.99"
        if c == "show crypto key mypubkey rsa":
            return "% Key name: sim.lab\n Key Data:\n  30820122 ..." if self.rsa_keys else ""
        if c == "show ip dhcp pool":
            return "\n".join(f"\nPool {h.split()[-1]} :\n Total addresses : 254"
                             for h in self.sections if h.startswith("ip dhcp pool "))
        if c == "show ip nat statistics":
            inside = [n for n, b in self._interfaces().items() if " ip nat inside" in b]
            outside = [n for n, b in self._interfaces().items() if " ip nat outside" in b]
            return ("Outside interfaces:\n" + "".join(f"  {n}\n" for n in outside) +
                    "Inside interfaces:\n" + "".join(f"  {n}\n" for n in inside) + "Hits: 0  Misses: 0\n")
        if c == "show ip ospf interface brief":
            return self._ospf_brief()
        if c == "show ip bgp summary":
            head = next((h for h in self.sections if h.startswith("router bgp ")), None)
            if not head:
                return "% BGP not active"
            body = self.sections[head]
            rid = self._value(body, "bgp router-id") or ZERO
            rows = [f"BGP router identifier {rid}, local AS number {head.split()[-1]}", "",
                    "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd"]
            for b in body:
                mm = re.match(r"\s*neighbor (\S+) remote-as (\d+)", b)
                if mm:
                    counters = "       0       0        1    0    0 never    Idle"
                    rows.append(f"{mm.group(1):<15} 4 {mm.group(2):>12}{counters}")
            return "\n".join(rows)
        if c in ("show ip ospf neighbor", "show ip eigrp neighbors"):
            return ""
        return ""

    def _ospf_brief(self) -> str:
        head = next((h for h in self.sections if h.startswith("router ospf ")), None)
        rows = ["Interface    PID   Area            IP Address/Mask    Cost  State Nbrs F/C"]
        if not head:
            return "\n".join(rows)
        pid = head.split()[-1]
        nets = []
        for b in self.sections[head]:
            mm = re.match(r"\s*network (\S+) (\S+) area (\S+)", b)
            if mm:
                nets.append((mm.group(1), mm.group(2), mm.group(3)))
        for name, body in self._interfaces().items():
            addr = self._value(body, "ip address")
            if not addr:
                continue
            ip, mask = addr.split()[:2]
            for net_ip, wildcard, area in nets:
                if net_ip == ip and wildcard == ZERO:  # host wildcard
                    prefix = ipaddress.IPv4Network(f"{ZERO}/{mask}").prefixlen
                    rows.append(f"{short_name(name):<12} {pid:<5} {area:<15} {ip}/{prefix:<10} 1     P2P   0/0")
        return "\n".join(rows)


class SimulatedConnection:
    def __init__(self, device: SimulatedDevice):
        self.d = device

    def show(self, command: str) -> str:
        with self.d.lock:
            return self.d.show(command)

    def enter_config(self, command: str) -> str:
        with self.d.lock:
            if "revert timer" in command:
                self.d.begin_window()
        return "Enter configuration commands, one per line.  End with CNTL/Z."

    def config_line(self, command: str, prompts=None) -> str:
        with self.d.lock:
            return self.d.apply(command)

    def exit_config(self) -> str:
        self.d.context = None
        return ""

    def exec(self, command: str) -> str:
        with self.d.lock:
            if command == "configure revert now":
                self.d.revert()
                return "Rollback Done"
            if command == "configure confirm":
                self.d.snapshot = None
                return ""
            if command.startswith("write"):
                return "Building configuration...\n[OK]"
        return ""

    def close(self) -> None:
        self.d.context = None


class SimulatedConnector:
    """One SimulatedDevice per address, kept for the life of the process, so pushes accumulate."""

    def __init__(self):
        self.devices: dict[str, SimulatedDevice] = {}

    def open(self, params: ConnectParams, who=None, notes: list[str] | None = None):
        if notes is not None:
            notes.append("SIMULATION: this push went to an in-memory simulated device, not the network.")
        if params.password.get_secret_value() == "wrong":
            raise ConnectFailed("auth", "Login failed: check the username and password (not retried).")
        key = params.host or params.serial_port or "sim"
        if key not in self.devices:
            self.devices[key] = SimulatedDevice("Switch", params.host)
        return SimulatedConnection(self.devices[key])
