"""VLAN tables and OS detection used by discovery (Phase 4B). Sample outputs follow the vendors' documented
formats; they are replaced by real lab output when each driver passes docs/LAB_TESTING.md (item P1)."""

import pytest

from app.config import Settings
from app.drivers.base import ModelInfo
from app.drivers.registry import get_driver
from app.services.discovery import clean, detect_os, model_match

SETTINGS = Settings(_env_file=None, enable_experimental_drivers=True)
EOS_VLAN = """VLAN  Name                             Status    Ports
----- -------------------------------- --------- -------------------------------
1     default                          active    Et3
10    Staff                            active    Et1, Et2
"""
AOSCX_VLAN = """--------------------------------------------------------------------------------------
VLAN  Name                              Status  Reason          Type      Interfaces
--------------------------------------------------------------------------------------
1     DEFAULT_VLAN_1                    up      ok              default   1/1/1-1/1/28
10    Staff                             up      ok              static    1/1/2
"""
JUNOS_VLANS = """Routing instance        VLAN name             Tag          Interfaces
default-switch          Guests                20
                                                           ge-0/0/2.0*
default-switch          Staff                 10
                                                           ge-0/0/0.0*
default-switch          default               1
"""


def driver(os_id, category="l3switch"):
    return get_driver(os_id, ModelInfo(id="m", name="m", category=category), SETTINGS)


@pytest.mark.parametrize("os_id,command,text,want", [
    ("arista_eos", "show vlan", EOS_VLAN, [(1, "default"), (10, "Staff")]),
    ("aruba_aoscx", "show vlan", AOSCX_VLAN, [(1, "DEFAULT_VLAN_1"), (10, "Staff")]),
    ("juniper_junos", "show vlans", JUNOS_VLANS, [(1, "default"), (10, "Staff"), (20, "Guests")]),
])
def test_vlan_tables(os_id, command, text, want):
    d = driver(os_id)
    assert d.vlan_commands() == [command]
    assert [(v["id"], v["name"]) for v in d.parse_vlans({command: text})] == want


def test_routers_and_experimental_drivers_read_no_vlan_table():
    assert driver("cisco_ios", "router").vlan_commands() == []
    assert driver("juniper_junos", "router").vlan_commands() == []  # SRX
    assert driver("mikrotik_routeros", "switch").vlan_commands() == []


@pytest.mark.parametrize("text,os_id", [
    ("Cisco IOS Software, IOSv Software (VIOS-ADVENTERPRISEK9-M), Version 15.9(3)M6", "cisco_ios"),
    ("Arista cEOSLab\nSoftware image version: 4.32.0F", "arista_eos"),
    ("Hostname: vjunos1\nModel: ex9214\nJunos: 23.2R1.14", "juniper_junos"),
    ("Version      : FL.10.13.1000\nProduct Name : ArubaOS-CX Simulator", "aruba_aoscx"),
    ("nothing useful", None),
])
def test_detect_os(text, os_id):
    assert detect_os({"show version": text}) == os_id


def test_model_match_uses_name_id_and_part_number():
    doc = {"_id": "aruba-cx6100-24g", "name": "6100 24G 4SFP+ (JL678A)"}
    assert model_match(doc, "aruba_aoscx", "aruba_aoscx", "JL678A")["status"] == "match"
    assert model_match(doc, "aruba_aoscx", None, None)["status"] == "unknown"
    assert model_match(doc, "aruba_aoscx", "aruba_aoscx", "JL663A")["status"] == "mismatch"


def test_clean_keeps_untrusted_output_short_and_printable():
    assert clean("ok\x1b[31m\nmore" + "x" * 200).startswith("ok[31mmorex")  # control characters removed
    assert len(clean("x" * 500)) == 80 and clean("   ") is None and clean(None) is None
