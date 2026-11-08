"""docs/TEST_PLAN.md 3.1 – validation errors keyed by field path."""

import pytest
from pydantic import ValidationError

from app.drivers.base import ModelInfo
from app.drivers.cisco_ios import ALL_CAPABILITIES, CiscoIos
from app.errors import field_path
from app.models.plan import ConfigPlan, PreviewRequest
from app.services.catalog import load_file
from app.services.validation import normalize_interfaces, validate_plan

MODELS = {m["_id"]: m for m in load_file()["models"]}
C9300 = ModelInfo.from_doc(MODELS["cisco-c9300-24t"])  # Gi1/0/1-24, Te1/1/1-4


def run(plan: dict, model: ModelInfo = C9300, caps=ALL_CAPABILITIES):
    driver = CiscoIos(model)
    p = normalize_interfaces(ConfigPlan.model_validate(plan), driver.normalize_interface)
    return validate_plan(p, model=model, capabilities=set(caps), os_name=driver.os_name)


def schema_errors(plan: dict) -> dict[str, str]:
    with pytest.raises(ValidationError) as exc:
        ConfigPlan.model_validate(plan)
    return {field_path(tuple(e["loc"])): e["msg"] for e in exc.value.errors()}


# ------------------------------------------------------------------ VLANs
@pytest.mark.parametrize("vid", [1, 1002, 1003, 1004, 1005])
def test_vlan_id_rules(vid):
    assert "vlans.0.id" in run({"vlans": [{"id": vid, "name": "x"}]}).errors


@pytest.mark.parametrize("vid", [0, 4095])
def test_vlan_out_of_range_is_schema_error(vid):
    assert "vlans.0.id" in schema_errors({"vlans": [{"id": vid, "name": "x"}]})


def test_duplicate_vlan_reported_on_second():
    r = run({"vlans": [{"id": 10, "name": "a"}, {"id": 10, "name": "b"}]})
    assert "duplicate" in r.errors["vlans.1.id"] and "vlans.0.id" not in r.errors


@pytest.mark.parametrize("name", ["Sales Dept", "x" * 33, "Sales;reload", "Sälj"])
def test_bad_vlan_names(name):
    assert "vlans.0.name" in schema_errors({"vlans": [{"id": 10, "name": name}]})


def test_good_vlan_name():
    assert run({"vlans": [{"id": 10, "name": "Sales_Dept-1"}]}).ok


def test_reserved_vlan_in_references():
    r = run({"access": [{"interfaces": ["Gi1/0/1"], "vlan": 1003}],
             "trunks": [{"interface": "Te1/1/1", "allowed_vlans": [10, 1004], "native_vlan": 1005}]})
    assert {"access.0.vlan", "trunks.0.allowed_vlans.1", "trunks.0.native_vlan"} <= set(r.errors)


# --------------------------------------------------------------- addresses
@pytest.mark.parametrize("ip", ["10.0.10.300/24", "10.0.10.1/33", "999.1.1.1/24"])
def test_invalid_interface_ip(ip):
    assert "svis.0.ip" in run({"svis": [{"vlan": 10, "ip": ip}]}).errors


def test_network_and_broadcast_address_used_as_host():
    r = run({"svis": [{"vlan": 10, "ip": "10.0.10.0/24"}, {"vlan": 20, "ip": "10.0.20.255/24"}]})
    assert "network address" in r.errors["svis.0.ip"] and "broadcast" in r.errors["svis.1.ip"]


def test_slash_31_and_32_are_hosts():
    assert run({"interfaces": [{"interface": "Te1/1/1", "ip": "10.0.0.0/31"},
                               {"interface": "Loopback0", "ip": "10.255.255.1/32"}]}).ok


def test_overlapping_subnets_rejected_on_second():
    r = run({"svis": [{"vlan": 10, "ip": "10.0.0.1/23"}, {"vlan": 20, "ip": "10.0.1.1/24"}]})
    assert "overlaps" in r.errors["svis.1.ip"] and "svis.0.ip" not in r.errors


def test_special_addresses_rejected():
    for ip in ["127.0.0.1/8", "224.0.0.5/24", "169.254.1.1/16", "0.0.0.0/8"]:
        assert "svis.0.ip" in run({"svis": [{"vlan": 10, "ip": ip}]}).errors, ip


# -------------------------------------------------------------------- DHCP
def pool(**kw):
    base = {"name": "P1", "network": "10.0.20.0/24", "default_router": "10.0.20.1"}
    return {"svis": [{"vlan": 20, "ip": "10.0.20.1/24"}], "dhcp": [{**base, **kw}]}


def test_dhcp_ok():
    assert run(pool(excluded=[{"start": "10.0.20.1", "end": "10.0.20.9"}], dns_servers=["9.9.9.9"])).ok


def test_dhcp_gateway_outside_pool():
    assert "dhcp.0.default_router" in run(pool(default_router="10.0.21.1")).errors


def test_dhcp_network_with_host_bits():
    assert "did you mean 10.0.20.0/24" in run(pool(network="10.0.20.5/24")).errors["dhcp.0.network"]


def test_dhcp_excluded_range_outside_pool_or_reversed():
    assert "dhcp.0.excluded.0" in run(pool(excluded=[{"start": "10.0.30.1"}])).errors
    assert "dhcp.0.excluded.0.end" in run(pool(excluded=[{"start": "10.0.20.9", "end": "10.0.20.2"}])).errors


def test_dhcp_without_matching_interface_warns():
    r = run({"dhcp": [{"name": "P1", "network": "10.0.20.0/24", "default_router": "10.0.20.1"}]})
    assert r.ok and any("10.0.20.0/24" in w for w in r.warnings)


def test_dhcp_duplicate_pool_and_overlap():
    plan = pool()
    plan["dhcp"].append({"name": "p1", "network": "10.0.20.0/25", "default_router": "10.0.20.1"})
    r = run(plan)
    assert "dhcp.1.name" in r.errors and "dhcp.1.network" in r.errors


# ----------------------------------------------------------------- routing
@pytest.mark.parametrize("rid", ["1.2.3", "256.0.0.1", "a.b.c.d"])
def test_router_id_format(rid):
    plan = {"routing": {"eigrp": {"asn": 1, "router_id": rid, "networks": ["10.0.0.0/24"]}}}
    try:
        r = run(plan)
    except ValidationError:
        return  # rejected by the schema pattern
    assert "routing.eigrp.router_id" in r.errors


def test_router_id_zero_rejected():
    r = run({"routing": {"eigrp": {"asn": 1, "router_id": "0.0.0.0", "networks": ["10.0.0.0/24"]}}})
    assert "routing.eigrp.router_id" in r.errors


@pytest.mark.parametrize(("proto", "asn"), [("eigrp", 0), ("eigrp", 65536), ("bgp", 0), ("bgp", 4294967296)])
def test_as_ranges(proto, asn):
    body = {"asn": asn, "router_id": "1.1.1.1"}
    body |= {"networks": ["10.0.0.0/24"]} if proto == "eigrp" else {"neighbors": [{"ip": "10.0.0.2", "remote_as": 1}]}
    assert f"routing.{proto}.asn" in schema_errors({"routing": {proto: body}})


def test_bgp_four_byte_as_ok():
    assert run({"routing": {"bgp": {"asn": 4200000000, "router_id": "1.1.1.1",
                                    "neighbors": [{"ip": "203.0.113.1", "remote_as": 64500}]}}}).ok


def test_ospf_interface_needs_ip_in_plan():
    r = run({"routing": {"ospf": {"router_id": "1.1.1.1", "interfaces": [{"interface": "Te1/1/1"}]}}})
    assert "routing.ospf.interfaces.0.interface" in r.errors


def test_static_route_rules():
    r = run({"svis": [{"vlan": 10, "ip": "10.0.10.1/24"}],
             "statics": [{"prefix": "10.1.0.5/16", "next_hop": "10.0.10.2"},
                         {"prefix": "0.0.0.0/0", "next_hop": "10.0.10.1"}]})
    assert "statics.0.prefix" in r.errors and "own address" in r.errors["statics.1.next_hop"]
    assert "statics.0" in schema_errors({"statics": [{"prefix": "0.0.0.0/0"}]})


# --------------------------------------------------------------- interfaces
def test_interface_not_on_model():
    r = run({"access": [{"interfaces": ["Gi1/0/99"], "vlan": 10}]})
    assert "not a port on" in r.errors["access.0.interfaces.0"]


def test_abbreviated_interface_accepted_and_expanded():
    driver = CiscoIos(C9300)
    p = normalize_interfaces(ConfigPlan.model_validate({"access": [{"interfaces": ["gi1/0/24"], "vlan": 10}]}),
                             driver.normalize_interface)
    assert p.access[0].interfaces == ["GigabitEthernet1/0/24"]


def test_vlan_interface_only_on_switches():
    router = ModelInfo.from_doc(MODELS["cisco-iosv"])
    r = run({"interfaces": [{"interface": "Vlan10", "ip": "10.0.0.1/24"}]}, model=router)
    assert "no VLAN interfaces" in r.errors["interfaces.0.interface"]
    assert run({"interfaces": [{"interface": "Loopback0", "ip": "10.0.0.1/32"}]}, model=router).ok


def test_port_used_twice():
    r = run({"access": [{"interfaces": ["Gi1/0/1"], "vlan": 10}],
             "trunks": [{"interface": "GigabitEthernet1/0/1", "allowed_vlans": [10]}]})
    assert "already used" in r.errors["trunks.0.interface"]


def test_unsupported_feature_named_never_skipped():
    l2 = ModelInfo.from_doc(MODELS["cisco-ws-c2960x-24ts-l"])
    r = run({"routing": {"eigrp": {"asn": 1, "router_id": "1.1.1.1", "networks": ["10.0.0.0/24"]}}},
            model=l2, caps=ALL_CAPABILITIES - {"eigrp"})
    assert r.unsupported == [{"feature": "eigrp", "message": r.errors["routing.eigrp"]}]
    assert "not supported on" in r.errors["routing.eigrp"]


def test_ssh_needs_domain():
    assert "basic.domain" in run({"basic": {"hostname": "sw1"}, "ssh": {"username": "netadmin"}}).errors
    assert "basic" in run({"ssh": {"username": "netadmin"}}).errors


# ---------------------------------------------------------- CLI injection
@pytest.mark.parametrize(("plan", "path"), [
    ({"basic": {"hostname": "sw1\nreload"}}, "basic.hostname"),
    ({"basic": {"hostname": "sw1;reload"}}, "basic.hostname"),
    ({"basic": {"hostname": "a|b"}}, "basic.hostname"),
    ({"basic": {"hostname": "sw 1"}}, "basic.hostname"),        # no-break space
    ({"basic": {"hostname": "sw1；reload"}}, "basic.hostname"),  # full-width semicolon
    ({"basic": {"hostname": "swı"}}, "basic.hostname"),         # dotless i
    ({"hardening": {"banner": "hi^Creload"}}, "hardening.banner"),
    ({"hardening": {"banner": "hi#\nreload"}}, "hardening.banner"),
    ({"hardening": {"banner": "x" * 241}}, "hardening.banner"),
    ({"hardening": {"banner": "Who are you?"}}, "hardening.banner"),  # "?" opens IOS context help
    ({"svis": [{"vlan": 10, "ip": "10.0.10.1/24", "description": "a\rreload"}]}, "svis.0.description"),
    ({"svis": [{"vlan": 10, "ip": "1０.0.10.1/24"}]}, "svis.0.ip"),  # full-width digit
    ({"trunks": [{"interface": "Gi0/1\nreload", "allowed_vlans": [1]}]}, "trunks.0.interface"),
    ({"ssh": {"username": "admin secret x"}}, "ssh.username"),
    ({"ssh": {"username": "netadmin", "password": "has space1"}}, "ssh.password"),
    ({"ssh": {"username": "netadmin", "password": "pass#word1"}}, "ssh.password"),
    ({"dhcp": [{"name": "P;1", "network": "10.0.0.0/24", "default_router": "10.0.0.1"}]}, "dhcp.0.name"),
    ({"custom_commands": ["vlan 10\nreload"]}, "custom_commands.0"),
    ({"custom_commands": ["vlan 10 ; reload"]}, "custom_commands.0"),
    ({"custom_commands": ["show run | include x"]}, "custom_commands.0"),
])
def test_injection_rejected_by_schema(plan, path):
    assert path in schema_errors(plan)


def test_size_limits():
    assert "vlans" in schema_errors({"vlans": [{"id": 10, "name": "a"}] * 4095})
    assert "hardening.banner" in schema_errors({"hardening": {"banner": "a" * 10_000}})


def test_extra_fields_forbidden():
    assert "run_as_root" in schema_errors({"run_as_root": True})
    assert "vlans.0.priority" in schema_errors({"vlans": [{"id": 10, "name": "a", "priority": 1}]})


def test_preview_request_needs_exactly_one_target():
    with pytest.raises(ValidationError):
        PreviewRequest.model_validate({"plan": {}})
    with pytest.raises(ValidationError):
        PreviewRequest.model_validate({"plan": {}, "model_id": "cisco-iosv", "device_id": "0" * 24})


def test_without_secrets_drops_them():
    plan = ConfigPlan.model_validate({"ssh": {"username": "u1", "password": "Secret-123", "set_enable_secret": True,
                                              "enable_secret": "Enable-123"}})
    stored = plan.without_secrets()
    assert "password" not in stored["ssh"] and "enable_secret" not in stored["ssh"]
    assert "Secret-123" not in str(stored) and "Enable-123" not in str(stored)
