"""Optional: import models from a LOCAL clone of the NetBox community device-type library.

The library (https://github.com/netbox-community/devicetype-library) is a set of YAML files, one per
model, with each model's interfaces. This script:

* never downloads anything – you clone the repository yourself;
* prints the repository's LICENSE file and refuses to run until you pass --accept-license after
  reading it (check the licence terms yourself; this script does not decide them for you);
* needs PyYAML, which is NOT part of requirements.txt. Install it only if you use this script:
  .venv\\Scripts\\python -m pip install pyyaml
* writes catalog JSON (default: a new file) that you then load with seed_catalog.py --file.
  Imported models are marked source="netbox-devicetype-library", verified=false.

Example (from backend/):
    git clone https://github.com/netbox-community/devicetype-library C:\\src\\devicetype-library
    .venv\\Scripts\\python scripts\\import_netbox_devicetypes.py C:\\src\\devicetype-library ^
        --vendor Cisco --match "^C9300" --series-id cisco-c9300 --accept-license --out netbox_cisco.json
    .venv\\Scripts\\python scripts\\seed_catalog.py --file netbox_cisco.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.catalog import CATALOG_FILE, load_file  # noqa: E402

PHYSICAL_SKIP = ("virtual", "lag", "bridge")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def build_model(data: dict, series: dict) -> dict | None:
    interfaces = [i for i in data.get("interfaces", []) if not str(i.get("type", "")).startswith(PHYSICAL_SKIP)]
    names = [str(i["name"]) for i in interfaces if i.get("name")]
    if not names:
        return None
    pattern = "^(?:" + "|".join(re.escape(n) for n in names) + ")$"
    uplinks = sum(1 for i in interfaces if re.search(r"(sfp|qsfp|10g|25g|40g|100g)", str(i.get("type", ""))))
    prefix = re.match(r"^[A-Za-z-]+", names[0])
    model = data.get("model") or data.get("part_number")
    return {
        "_id": slug(f"{series['brand_id']}-{data.get('slug') or model}"),
        "series_id": series["_id"],
        "brand_id": series["brand_id"],
        "name": str(model)[:80],
        "category": series["category"],
        "os_id": series["os_id"],
        "layer": 3 if series["category"] in ("l3switch", "router") else 2,
        "ports": len(names),
        "uplinks": uplinks,
        "poe": any("poe" in json.dumps(i).lower() for i in interfaces),
        "port_prefix": prefix.group(0) if prefix else "",
        "port_pattern": pattern,
        "port_examples": [names[0], names[-1]],
        "capabilities_exclude": [],
        "source": "netbox-devicetype-library",
        "verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("library", type=Path, help="path to your local clone of devicetype-library")
    parser.add_argument("--vendor", required=True, help="vendor folder name, e.g. Cisco")
    parser.add_argument("--series-id", required=True, help="existing catalog series id the models belong to")
    parser.add_argument("--match", default=".*", help="regex on the model name, e.g. ^C9300")
    parser.add_argument("--accept-license", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("netbox_import.json"))
    args = parser.parse_args()

    license_file = next((p for p in (args.library / "LICENSE", args.library / "LICENSE.md") if p.is_file()), None)
    if license_file is None:
        print("No LICENSE file found in the clone – refusing to import.")
        return 2
    if not args.accept_license:
        print(license_file.read_text(encoding="utf-8", errors="replace")[:3000])
        print("\nRead the licence above. If its terms fit your use, re-run with --accept-license.")
        return 2

    try:
        import yaml  # noqa: PLC0415 - optional dependency, see module docstring
    except ImportError:
        print("PyYAML is not installed. Run: .venv\\Scripts\\python -m pip install pyyaml")
        return 2

    catalog = load_file(CATALOG_FILE)
    series = next((s for s in catalog["series"] if s["_id"] == args.series_id), None)
    if series is None:
        print(f"Unknown series id {args.series_id}. Add the series to catalog.json first.")
        return 2

    vendor_dir = args.library / "device-types" / args.vendor
    if not vendor_dir.is_dir():
        print(f"{vendor_dir} not found.")
        return 2
    matcher = re.compile(args.match)
    models = []
    for path in sorted(vendor_dir.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not matcher.search(str(data.get("model", ""))):
            continue
        model = build_model(data, series)
        if model:
            models.append(model)

    args.out.write_text(json.dumps({"_note": f"Imported from {license_file.parent.name} ({args.vendor}); "
                                              "unverified.", "models": models}, indent=2), encoding="utf-8")
    print(f"Wrote {len(models)} models to {args.out}. Load them with: scripts\\seed_catalog.py --file {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
