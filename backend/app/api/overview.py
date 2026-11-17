"""Overview dashboard (Phase 4B): KPIs, charts and the topology map, built from real devices and jobs."""

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pymongo.database import Database

from .. import clock
from ..errors import ApiError
from ..models.job import FAILED, RUNNING, WAITING
from ..security.ratelimit import RateLimiter
from ..security.rbac import require_engineer, require_viewer
from ..security.sessions import SessionUser
from .deps import get_db

router = APIRouter(prefix="/api/overview", tags=["overview"])
refresh_limit = RateLimiter(limit=6, window_seconds=60)

DAYS = 14
MAX_SAMPLES = 96


def _job_days(db: Database, now) -> list[dict]:
    """Jobs that finished per day over the last DAYS days (UTC dates), split by outcome."""
    start = (now - timedelta(days=DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    days = {(start + timedelta(days=i)).date().isoformat(): {"success": 0, "failed": 0, "other": 0}
            for i in range(DAYS)}
    pipeline = [
        {"$match": {"created_at": {"$gte": start}}},
        {"$group": {"_id": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                            "status": "$status"}, "n": {"$sum": 1}}},
    ]
    for row in db.jobs.aggregate(pipeline):
        day = days.get(row["_id"]["day"])
        if day is None:
            continue
        status = row["_id"]["status"]
        key = "success" if status == "success" else "failed" if status in FAILED else "other"
        day[key] += row["n"]
    return [{"date": d, **v} for d, v in days.items()]


def _status_history(db: Database, now) -> list[dict]:
    rows = list(db.status_samples.find({"at": {"$gte": now - timedelta(hours=24)}}, {"_id": 0}).sort("at", 1))
    step = max(1, -(-len(rows) // MAX_SAMPLES))  # ceiling: at most MAX_SAMPLES rows that still span all 24 h
    if not rows:
        return rows
    keep = sorted(set(range(len(rows) - 1, -1, -step)) | {0})  # counted from the newest sample; the oldest stays too
    if len(keep) > MAX_SAMPLES:
        del keep[1]
    return [rows[i] for i in keep]


def _port_key(name: str | None) -> str:
    """Both ends of a cable may name a port differently (CDP 'GigabitEthernet0/1', the driver 'Gi0/1'): compare
    the first two letters of the type and the number."""
    m = re.match(r"([a-z]+)[^0-9]*(.*)", (name or "").lower())
    return m.group(1)[:2] + m.group(2) if m else (name or "").lower()


def _topology(devices: list[dict], models: dict) -> dict:
    """Nodes are inventory devices. Links come from LLDP/CDP neighbours whose system name (or reported host name)
    is an inventory device, and from the uplink switch port of access points and cameras. Neighbours that are
    not in the inventory are listed as external nodes."""
    nodes, by_name = [], {}
    for d in devices:
        model = models.get(d["model_id"], {})
        node = {"id": str(d["_id"]), "name": d["name"], "category": model.get("category"),
                "model_name": model.get("name"), "mgmt_ip": d.get("mgmt_ip"),
                "reachable": d.get("status", {}).get("reachable"), "production": "production" in d.get("tags", []),
                "external": False}
        nodes.append(node)
        for alias in (d["name"], (d.get("facts") or {}).get("hostname")):
            if alias:
                by_name.setdefault(alias.split(".")[0].lower(), node["id"])
    links, uplinks, seen, external = [], [], set(), {}
    for d in devices:
        a = str(d["_id"])
        for n in d.get("neighbors") or []:
            remote = (n.get("remote") or "").split(".")[0].lower()
            if not remote:
                continue
            b = by_name.get(remote)
            if b is None:
                if remote == "unknown":  # no system name: one shared "unknown" node would wire unrelated devices
                    remote = f"unknown ({d['name']} {n.get('local') or ''})".strip()
                b = external.setdefault(remote, f"ext:{remote}")
            if a == b:
                continue
            key = tuple(sorted([(a, _port_key(n.get("local"))), (b, _port_key(n.get("port")))]))
            if key in seen:
                continue
            seen.add(key)
            links.append({"a": a, "b": b, "a_port": n.get("local"), "b_port": n.get("port"),
                          "source": n.get("protocol") or "lldp"})
        up = d.get("uplink")
        if up and up.get("device_id"):
            uplinks.append({"a": up["device_id"], "b": a, "a_port": up.get("interface"), "b_port": None,
                            "source": "uplink"})
    # A recorded uplink that LLDP/CDP also found is drawn once (the discovered link, which names both ports).
    linked = {frozenset((link["a"], link["b"])) for link in links}
    links += [u for u in uplinks if frozenset((u["a"], u["b"])) not in linked]
    known = {node["id"] for node in nodes} | set(external.values())
    links = [link for link in links if link["a"] in known and link["b"] in known]
    nodes += [{"id": node_id, "name": name, "category": None, "model_name": None, "mgmt_ip": None,
               "reachable": None, "production": False, "external": True} for name, node_id in external.items()]
    return {"nodes": nodes, "links": links}


@router.get("")
def overview(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> dict:
    now = clock.now()
    devices = list(db.devices.find({}, {"name": 1, "model_id": 1, "mgmt_ip": 1, "status.reachable": 1, "tags": 1,
                                        "facts.hostname": 1, "facts.match.status": 1, "neighbors": 1,
                                        "uplink": 1}).limit(1000))
    models = {m["_id"]: m for m in db.catalog_models.find({"_id": {"$in": list({d["model_id"] for d in devices})}},
                                                          {"name": 1, "category": 1})}

    reach = {"up": 0, "down": 0, "unknown": 0}
    by_category: dict[str, int] = {}
    mismatches = 0
    for d in devices:
        r = d.get("status", {}).get("reachable")
        reach["up" if r is True else "down" if r is False else "unknown"] += 1
        model = models.get(d["model_id"], {})
        cat = model.get("category") or "unknown"
        by_category[cat] = by_category.get(cat, 0) + 1
        if ((d.get("facts") or {}).get("match") or {}).get("status") == "mismatch":
            mismatches += 1

    week = now - timedelta(days=7)
    counts = {row["_id"]: row["n"] for row in db.jobs.aggregate([
        {"$match": {"created_at": {"$gte": week}}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    finished = sum(n for s, n in counts.items() if s == "success" or s in FAILED)
    recent = [{"id": str(j["_id"]), "status": j["status"], "kind": j.get("kind"), "created_at": j["created_at"],
               "devices": [s.get("device_name") for s in j.get("steps", [])][:5],
               "requested_by": (j.get("requested_by") or {}).get("username")}
              for j in db.jobs.find({}, {"status": 1, "kind": 1, "created_at": 1, "steps.device_name": 1,
                                         "requested_by.username": 1}).sort("created_at", -1).limit(6)]
    last = db.status_samples.find_one(sort=[("at", -1)])
    return {
        "generated_at": now,
        "kpis": {
            "devices": len(devices), **reach, "model_mismatches": mismatches,
            "jobs_7d": sum(counts.values()), "success_7d": counts.get("success", 0),
            "failed_7d": sum(counts.get(s, 0) for s in FAILED),
            "success_rate_7d": round(100 * counts.get("success", 0) / finished) if finished else None,
            "waiting": db.jobs.count_documents({"status": {"$in": list(WAITING)}}),
            "running": db.jobs.count_documents({"status": {"$in": list(RUNNING)}}),
        },
        "jobs_by_day": _job_days(db, now),
        "status_history": _status_history(db, now),
        "devices_by_category": by_category,
        "topology": _topology(devices, models),
        "recent_jobs": recent,
        "last_poll": last["at"] if last else None,
    }


@router.post("/refresh")
def refresh(request: Request, user: SessionUser = Depends(require_engineer)) -> dict:
    """Run a status poll round now (ping + port check; no login is used)."""
    if not refresh_limit.allow(user.user_id):
        raise ApiError(429, "Status was refreshed recently; wait a minute.")
    poller = getattr(request.app.state, "poller", None)
    if poller is None or poller.interval <= 0:
        raise ApiError(409, "Status checks are turned off (STATUS_POLL_SECONDS=0). Set it to 60 in backend/.env and "
                             "restart NetConfig Studio.")
    poller.wake()
    return {"ok": True}
