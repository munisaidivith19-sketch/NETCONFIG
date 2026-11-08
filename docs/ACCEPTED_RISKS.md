# Accepted risks

Findings from `pip-audit`, `npm audit` and `bandit` that are not fixed yet, why, and when they will be.
Every entry needs a reason and an exit condition. Reviewed at every phase review.

| Date | Finding | Package / where | Why accepted | Exit condition |
|---|---|---|---|---|
| 2026-11-08 | CVE-2026-114605 | `dnspython` 2.8.0 (dependency of `pymongo`) | The fix (2.9.0) requires Python ≥ 3.11 and this machine runs Python 3.10 for now. pymongo uses dnspython only to resolve `mongodb+srv://` DNS records; NetConfig Studio connects to `mongodb://127.0.0.1:27017` directly, so the DNS code is not used. | Install Python 3.12, rebuild `.venv`, upgrade dnspython, remove this row. |
| 2026-11-08 | 17 CVEs in `filelock` 4.1.0 | `filelock` (pulled in by `pip-audit` → CacheControl) | Development tool only – never imported by the running app. The fix (4.2.1) requires Python ≥ 3.11. | Same as above. |

`npm audit`: 0 vulnerabilities (2026-11-08).
`bandit -r app scripts`: 0 findings (2026-11-08).
