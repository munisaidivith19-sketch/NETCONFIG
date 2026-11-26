"""Generate the animated SVGs used by README.md (CSS + SMIL, no JavaScript, so GitHub renders them).

Usage (from the project root):  python scripts/make_readme_svgs.py docs/assets/readme
"""
# ruff: noqa: E501  (long lines are SVG markup)
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

BG = """<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#07111f"/><stop offset="1" stop-color="#0d2233"/>
  </linearGradient>
  <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
    <path d="M28 0H0V28" fill="none" stroke="#16324a" stroke-width="1"/>
  </pattern>
  <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffffff" stop-opacity=".10"/><stop offset=".35" stop-color="#ffffff" stop-opacity="0"/>
  </linearGradient>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>"""

SANS = "font-family:'Segoe UI',Inter,-apple-system,Helvetica,Arial,sans-serif"
MONO = "font-family:'JetBrains Mono','Cascadia Code',Consolas,'SF Mono',Menlo,monospace"
REDUCED = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"


# ---------------------------------------------------------------- hero banner
def hero():
    W, H = 1200, 380
    nodes = {  # id: (x, y, label, sub, colour)
        "pc":   (705, 190, "NETCONFIG", "127.0.0.1", "#34d399"),
        "r1":   (950, 62,  "R1-EDGE", "router · cisco_ios", "#38bdf8"),
        "core": (950, 172, "CORE-L3", "l3switch · arista_eos", "#38bdf8"),
        "swa":  (835, 292, "SW-A", "aruba_aoscx", "#a78bfa"),
        "swb":  (1080, 292, "SW-B", "juniper_junos", "#a78bfa"),
    }
    links = [("r1", "core"), ("core", "swa"), ("core", "swb")]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="NetConfig Studio: animated network topology with configuration packets flowing">', BG,
           f"""<style>
  .t{{{SANS};fill:#e6f0fa}} .m{{{MONO}}}
  .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2.6s ease-out infinite}}
  @keyframes pulse{{0%{{transform:scale(1);opacity:.55}}100%{{transform:scale(1.9);opacity:0}}}}
  .dash{{stroke-dasharray:6 7;animation:flow 1.2s linear infinite}}
  @keyframes flow{{to{{stroke-dashoffset:-26}}}}
  .cur{{animation:blink 1s steps(1) infinite}} @keyframes blink{{50%{{opacity:0}}}}
  .fade{{animation:fade 1.4s ease-out both}} .d1{{animation-delay:.25s}} .d2{{animation-delay:.5s}} .d3{{animation-delay:.75s}}
  @keyframes fade{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
  {REDUCED}
</style>""",
           f'<rect width="{W}" height="{H}" rx="24" fill="url(#bg)"/>',
           f'<rect width="{W}" height="{H}" rx="24" fill="url(#grid)" opacity=".55"/>',
           f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="23" fill="url(#sheen)" stroke="#1f3d57"/>']

    # left side text
    out += [
        '<g class="fade"><rect x="56" y="58" width="196" height="30" rx="15" fill="#34d399" fill-opacity=".12" stroke="#34d399" stroke-opacity=".5"/>'
        '<circle cx="74" cy="73" r="5" fill="#34d399" filter="url(#glow)"><animate attributeName="opacity" values="1;.3;1" dur="1.6s" repeatCount="indefinite"/></circle>'
        '<text x="86" y="78" class="t m" font-size="13" fill="#9ff3cf" style="fill:#9ff3cf">MULTI-VENDOR · NETDEVOPS</text></g>',
        '<text x="54" y="150" class="t fade d1" font-size="58" font-weight="800" letter-spacing="-1.5">NetConfig <tspan fill="#34d399" style="fill:#34d399">Studio</tspan></text>',
        '<text x="56" y="192" class="t fade d2" font-size="20" style="fill:#a9bdd0">Plan it in a form. Preview the exact commands.</text>',
        '<text x="56" y="220" class="t fade d2" font-size="20" style="fill:#a9bdd0">Push with backup, verification and rollback.</text>',
    ]
    # typing command line
    cmd = "push  SW-A  vlans+access  →  verified ✓"
    out += [
        '<g class="fade d3"><rect x="56" y="256" width="560" height="52" rx="14" fill="#04101c" stroke="#1f3d57"/>',
        '<clipPath id="type"><rect x="78" y="262" height="40" width="0">'
        '<animate attributeName="width" values="0;0;470;470" keyTimes="0;.1;.55;1" dur="7s" repeatCount="indefinite"/></rect></clipPath>',
        '<text x="78" y="289" class="m" font-size="17" fill="#34d399">$</text>',
        f'<g clip-path="url(#type)"><text x="98" y="289" class="m" font-size="17" fill="#d6e4f0">{escape(cmd)}</text></g>',
        '<rect class="cur" x="98" y="275" width="10" height="20" fill="#34d399" opacity=".9">'
        '<animate attributeName="x" values="98;98;502;502" keyTimes="0;.1;.55;1" dur="7s" repeatCount="indefinite"/></rect></g>',
        '<text x="56" y="344" class="t m" font-size="13" style="fill:#5f7d98">Cisco IOS · Arista EOS · Juniper Junos · Aruba AOS-CX · MikroTik · Huawei · D-Link · TP-Link</text>',
    ]

    # links
    def path(a, b):
        (x1, y1, *_), (x2, y2, *_) = nodes[a], nodes[b]
        return f"M{x1},{y1} L{x2},{y2}"

    out.append(f'<path d="{path("pc", "core")}" stroke="#34d399" stroke-width="2" fill="none" class="dash" opacity=".85"/>')
    out.append('<text x="772" y="208" class="m" font-size="11" fill="#34d399" transform="rotate(-4 772 208)">SSH · host key pinned</text>')
    for i, (a, b) in enumerate(links):
        out.append(f'<path id="l{i}" d="{path(a, b)}" stroke="#2b5878" stroke-width="2.5" fill="none"/>')
    # packets (SMIL animateMotion)
    packets = [("pk0", "M705,190 L950,172", "#34d399", "2.4s", "0s"),
               ("pk1", path("core", "r1"), "#38bdf8", "2.8s", ".6s"),
               ("pk2", path("core", "swa"), "#a78bfa", "2.2s", ".2s"),
               ("pk3", path("core", "swb"), "#a78bfa", "2.6s", "1.1s"),
               ("pk4", path("swb", "core"), "#fbbf24", "3.1s", "1.7s")]
    for _id, d, c, dur, begin in packets:
        out.append(f'<circle r="4.5" fill="{c}" filter="url(#glow)"><animateMotion path="{d}" dur="{dur}" begin="{begin}" '
                   f'repeatCount="indefinite"/></circle>')
    # nodes
    for k, (x, y, label, sub, c) in nodes.items():
        w = 132 if k != "pc" else 118
        out.append(f'<g><rect class="pulse" x="{x-w/2}" y="{y-24}" width="{w}" height="48" rx="14" fill="none" stroke="{c}" stroke-width="1.5"/>'
                   f'<rect x="{x-w/2}" y="{y-24}" width="{w}" height="48" rx="14" fill="#0a1a2b" stroke="{c}" stroke-opacity=".8"/>'
                   f'<rect x="{x-w/2}" y="{y-24}" width="{w}" height="48" rx="14" fill="url(#sheen)"/>'
                   f'<circle cx="{x-w/2+16}" cy="{y-6}" r="4" fill="{c}"><animate attributeName="opacity" values="1;.35;1" '
                   f'dur="{1.4 + len(label)/10:.1f}s" repeatCount="indefinite"/></circle>'
                   f'<text x="{x-w/2+28}" y="{y-1}" class="m" font-size="13" font-weight="700" fill="#e6f0fa">{label}</text>'
                   f'<text x="{x-w/2+16}" y="{y+15}" class="m" font-size="10" fill="#7f9bb5">{sub}</text></g>')
    out.append("</svg>")
    (OUT / "hero.svg").write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------- terminal
def terminal():
    lines = [
        ("p", "$ preview  SW-A  (Cisco IOSvL2 · cisco_ios · 10.0.0.2)"),
        ("ok", "✔ validate   VLAN 2–4094 · names · ports match Gi1/0/N"),
        ("ok", "✔ safety     denylist clean · mgmt interface protected"),
        ("h", "── generated commands ─────────────────────────────"),
        ("c", "vlan 10"),
        ("c", " name Sales"),
        ("c", "interface GigabitEthernet1/0/1"),
        ("c", " description Sales desks"),
        ("c", " switchport mode access"),
        ("c", " switchport access vlan 10"),
        ("c", " no shutdown"),
        ("h", "── push ──────────────────────────────────────────"),
        ("s", "● connect      ssh · host key fingerprint matches"),
        ("s", "● backup       show running-config  (secrets masked)"),
        ("s", "● apply        configure terminal revert timer 5"),
        ("s", "● verify       show vlan brief  →  checks passed"),
        ("s", "● confirm      configure confirm · write memory"),
        ("ok", "✔ success    commands hash frozen · written to audit log"),
    ]
    colours = {"p": "#e6f0fa", "ok": "#34d399", "h": "#4f6f8c", "c": "#7dd3fc", "s": "#c4b5fd"}
    W, top, lh = 860, 64, 21
    H = top + lh * len(lines) + 30
    T = 16.0  # loop seconds
    step = 0.55
    css = []
    body = []
    for i, (kind, text) in enumerate(lines):
        t_in = 0.6 + i * step
        a = t_in / T * 100
        b = min(a + 1.5, 99)
        css.append(f".l{i}{{animation:l{i} {T}s infinite}}@keyframes l{i}{{0%,{a:.2f}%{{opacity:0}}{b:.2f}%,94%{{opacity:1}}98%,100%{{opacity:0}}}}")
        y = top + i * lh
        body.append(f'<text class="l{i}" x="28" y="{y}" fill="{colours[kind]}">{escape(text)}</text>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Terminal animation: a plan is validated, previewed as Cisco commands, pushed with backup, verified and confirmed">
{BG}
<style>
  text{{{MONO};font-size:14px;white-space:pre}} .ttl{{{SANS};font-size:13px}}
  {''.join(css)}
  {REDUCED.replace('animation:none', 'animation:none;opacity:1')}
</style>
<rect width="{W}" height="{H}" rx="18" fill="#050d18" stroke="#1f3d57"/>
<rect width="{W}" height="38" rx="18" fill="#0c1d2e"/><rect y="20" width="{W}" height="18" fill="#0c1d2e"/>
<circle cx="24" cy="19" r="6" fill="#ff5f57"/><circle cx="44" cy="19" r="6" fill="#febc2e"/><circle cx="64" cy="19" r="6" fill="#28c840"/>
<text x="{W/2}" y="24" text-anchor="middle" class="ttl" fill="#7f9bb5">netconfig-studio — Configure ▸ Preview ▸ Run</text>
{''.join(body)}
</svg>"""
    (OUT / "terminal.svg").write_text(svg, encoding="utf-8")


# ---------------------------------------------------------------- push pipeline
def pipeline():
    steps = ["Validate", "Preview", "Approve", "Connect", "Backup", "Pre-check", "Apply", "Verify", "Save"]
    W, H = 1200, 250
    x0, gap, w, y = 30, 128, 112, 70
    T = 11.0
    css, body = [], []
    # base rail
    body.append(f'<line x1="{x0+w/2}" y1="{y+24}" x2="{x0+gap*8+w/2}" y2="{y+24}" stroke="#1f3d57" stroke-width="3"/>')
    body.append(f'<line x1="{x0+w/2}" y1="{y+24}" x2="{x0+gap*8+w/2}" y2="{y+24}" stroke="#34d399" stroke-width="3" class="rail"/>')
    # travelling token
    body.insert(2, f'<circle r="7" fill="#34d399" filter="url(#glow)"><animate attributeName="cx" values="{x0+w/2};{x0+gap*8+w/2};{x0+gap*8+w/2}" '
                f'keyTimes="0;.77;1" dur="{T}s" repeatCount="indefinite"/><animate attributeName="opacity" values="1;1;0" keyTimes="0;.9;1" '
                f'dur="{T}s" repeatCount="indefinite"/><set attributeName="cy" to="{y+24}"/></circle>')
    for i, s in enumerate(steps):
        x = x0 + i * gap
        a = 77 * i / 8  # token reaches step i at this % of the loop
        css.append(f".s{i}{{animation:s{i} {T}s infinite}}@keyframes s{i}{{0%,{a:.1f}%{{fill:#0a1a2b;stroke:#2b5878}}"
                   f"{a+2:.1f}%,92%{{fill:#0d3a2c;stroke:#34d399}}100%{{fill:#0a1a2b;stroke:#2b5878}}}}")
        sub = ["ipaddress", "diff", "2nd user", "SSH", "running", "mgmt IP", "revert timer", "show cmds", "write mem"][i]
        body.append(f'<rect class="s{i}" fill="#0a1a2b" stroke="#2b5878" x="{x}" y="{y}" width="{w}" height="48" rx="24" stroke-width="1.6"/>'
                    f'<text x="{x+w/2}" y="{y+22}" text-anchor="middle" class="lbl">{s}</text>'
                    f'<text x="{x+w/2}" y="{y+38}" text-anchor="middle" class="sub">{sub}</text>'
                    f'<text x="{x+w/2}" y="{y-14}" text-anchor="middle" class="num">{i+1:02d}</text>')
    # rollback arc from Apply/Verify back to Backup
    ax, bx = x0 + 7 * gap + w / 2, x0 + 4 * gap + w / 2
    body.append(f'<path d="M{ax},{y+48} C{ax},{y+130} {bx},{y+130} {bx},{y+48}" fill="none" stroke="#f87171" stroke-width="2" class="rb"/>'
                f'<polygon points="{bx-6},{y+60} {bx+6},{y+60} {bx},{y+50}" fill="#f87171"/>'
                f'<text x="{(ax+bx)/2}" y="{y+128}" text-anchor="middle" class="rbt">CLI error · failed check · device unreachable  →  automatic rollback</text>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Push pipeline: validate, preview, approve, connect, backup, pre-check, apply, verify, save, with automatic rollback">
{BG}
<style>
  .lbl{{{SANS};font-size:15px;font-weight:700;fill:#e6f0fa}} .sub{{{MONO};font-size:10.5px;fill:#7f9bb5}}
  .num{{{MONO};font-size:11px;fill:#4f6f8c}} .rbt{{{MONO};font-size:12px;fill:#fca5a5}}
  .rb{{stroke-dasharray:7 6;animation:fl 1.4s linear infinite}} @keyframes fl{{to{{stroke-dashoffset:-26}}}}
  .rail{{stroke-dasharray:1100;stroke-dashoffset:1100;animation:rail {T}s linear infinite}}
  @keyframes rail{{0%{{stroke-dashoffset:1100}}77%,92%{{stroke-dashoffset:0}}100%{{stroke-dashoffset:0;opacity:0}}}}
  {''.join(css)}
  {REDUCED}
  .ttl{{{SANS};font-size:13px;fill:#7f9bb5;letter-spacing:2px}}
</style>
<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/><rect width="{W}" height="{H}" rx="22" fill="url(#grid)" opacity=".45"/>
<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="21" fill="url(#sheen)" stroke="#1f3d57"/>
<text x="30" y="32" class="ttl">SAFE PUSH PIPELINE</text>
{''.join(body)}
</svg>"""
    (OUT / "pipeline.svg").write_text(svg, encoding="utf-8")


hero()
terminal()
pipeline()
print("written to", OUT)
