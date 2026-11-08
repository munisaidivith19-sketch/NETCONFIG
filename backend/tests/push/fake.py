"""Scripted stand-in for a device session (docs/TEST_PLAN.md section 5). Records every command in order."""

from app.services.connection import ConnectFailed, ConnectionLost

RUNNING = """Building configuration...
!
hostname sw1
!
archive
 path flash0:ncs-archive
 maximum 5
!
interface Vlan1
 ip address 10.0.0.2 255.255.255.0
!
end"""
BRIEF = """Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  10.0.0.2        YES manual up                    up
GigabitEthernet0/0     unassigned      YES unset  up                    up"""
VLANS_OK = """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi0/0
10   Sales                            active
"""
RSA_KEYS = "% Key pair was generated at: 10:00:00 UTC Nov 8 2026\nKey name: sw1.lab.example.net\n Key Data:\n  30820122"


class FakeConnection:
    def __init__(self, responses=None, fail_on=None, unreachable_after_apply=False, exec_responses=None,
                 rsa_prompt=False):
        self.responses = {"show running-config": RUNNING, "show ip interface brief": BRIEF,
                          "show vlan brief": VLANS_OK, **(responses or {})}
        self.fail_on = fail_on or {}
        self.unreachable_after_apply = unreachable_after_apply
        self.exec_responses = exec_responses or {}
        self.rsa_prompt = rsa_prompt
        self.sent: list[tuple[str, str]] = []
        self.gone = False
        self.closed = 0

    def _alive(self):
        if self.gone:
            raise ConnectionLost("EOFError")

    def show(self, command):
        self._alive()
        self.sent.append(("show", command))
        return self.responses.get(command, "")

    def enter_config(self, command):
        self._alive()
        self.sent.append(("config_mode", command))
        return ""

    def config_line(self, command, prompts=None):
        self._alive()
        self.sent.append(("config", command))
        if command in self.fail_on:
            return f"{command}\n{self.fail_on[command]}"
        if prompts and self.rsa_prompt:
            question = ("% You already have RSA keys defined named sw1.lab.\n"
                        "% Do you really want to replace them? [yes/no]: ")
            for _pattern, answer in prompts:
                self.sent.append(("answer", answer))
            return question + "\n% The key modulus size is 2048 bits"
        return ""

    def exit_config(self):
        self._alive()
        self.sent.append(("exit_config", ""))
        if self.unreachable_after_apply and any(k == "config_mode" and "revert" in c for k, c in self.sent):
            self.gone = True
        return ""

    def exec(self, command):
        self._alive()
        self.sent.append(("exec", command))
        return self.exec_responses.get(command, "")

    def close(self):
        self.closed += 1

    # helpers for assertions
    def config_sent(self) -> list[str]:
        return [c for k, c in self.sent if k == "config"]


class FakeConnector:
    def __init__(self, fake: FakeConnection | None = None, fail: ConnectFailed | None = None, reconnect_fails=True,
                 fail_times: int | None = None):
        self.fake = fake or FakeConnection()
        self.fail = fail
        self.fail_times = fail_times  # None = `fail` on every open; n = only the first n opens
        self.reconnect_fails = reconnect_fails
        self.opens = 0
        self.params = []

    def open(self, params, who=None, notes=None):
        self.opens += 1
        self.params.append(params)
        if self.fail and (self.fail_times is None or self.opens <= self.fail_times):
            raise self.fail
        if self.opens > 1 and self.fail_times is None:
            if self.reconnect_fails:
                raise ConnectFailed("timeout", "The device did not answer in time.")
            self.fake.gone = False
        return self.fake
