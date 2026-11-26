"""Generate the animated SVGs used by README.md (CSS + SMIL, no JavaScript, so GitHub renders them).

Usage (from the project root):  python scripts/make_readme_svgs.py [docs/assets/readme]
"""
# ruff: noqa: E501  (long lines are SVG markup)
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs" / "assets" / "readme"
OUT.mkdir(parents=True, exist_ok=True)
RNG = random.Random(7)  # noqa: S311  fixed seed for LED timings only, not security

G, C, V, A, R = "#34d399", "#38bdf8", "#a78bfa", "#fbbf24", "#f87171"
TXT, MUTED, DIM, LINE = "#e6f0fa", "#7f9bb5", "#4f6f8c", "#1f3d57"
SANS = "font-family:'Segoe UI',Inter,-apple-system,Helvetica,Arial,sans-serif"
MONO = "font-family:'JetBrains Mono','Cascadia Code',Consolas,'SF Mono',Menlo,monospace"
REDUCED = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"
MONO_W = 0.6  # approx. monospace character width as a fraction of font size


def defs(extra=""):
    return f"""<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#040a14"/><stop offset=".55" stop-color="#071827"/><stop offset="1" stop-color="#0b2436"/></linearGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="#12304a" stroke-width="1"/><circle cx="0" cy="0" r="1.4" fill="#1d4a6b"/></pattern>
  <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".10"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
  {extra}
</defs>"""


def frame(W, H, r=24, grid_opacity=.6):
    """Rounded dark panel with a slowly scrolling grid and a top sheen."""
    return (f'<clipPath id="panel"><rect width="{W}" height="{H}" rx="{r}"/></clipPath>'
            f'<rect width="{W}" height="{H}" rx="{r}" fill="url(#bg)"/>'
            f'<g clip-path="url(#panel)"><rect x="0" y="-32" width="{W}" height="{H + 64}" fill="url(#grid)" opacity="{grid_opacity}">'
            f'<animateTransform attributeName="transform" type="translate" from="0 0" to="0 32" dur="5s" repeatCount="indefinite"/></rect></g>'
            f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="{r - 1}" fill="url(#sheen)" stroke="{LINE}"/>')


def svg(W, H, label, style, body, extra_defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}">\n'
            f'{defs(extra_defs)}\n<style>{style}{REDUCED}</style>\n{body}\n</svg>')


def blink(dur, begin=0, lo=.25):
    return f'<animate attributeName="opacity" values="1;{lo};1" dur="{dur:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite"/>'


def packet(d, colour, dur, begin, r=4.2):
    """A glowing packet with a fading trail moving along path d."""
    out = []
    for k, (rad, op) in enumerate(((r, 1), (r * .7, .55), (r * .45, .3))):
        out.append(f'<circle r="{rad:.1f}" fill="{colour}" opacity="{op}"{" filter=" + chr(34) + "url(#glow)" + chr(34) if k == 0 else ""}>'
                   f'<animateMotion path="{d}" dur="{dur}s" begin="{begin + k * .07:.2f}s" repeatCount="indefinite"/></circle>')
    return "".join(out)


# ------------------------------------------------------------------ hero banner
def hero():
    W, H = 1200, 480
    N = {  # id: x, y, label, sub, colour
        "net":  (905, 52, "INTERNET", "eBGP · AS 65001", A),
        "pc":   (690, 140, "NETCONFIG", "127.0.0.1 · you", G),
        "r1":   (905, 137, "R1-EDGE", "router · cisco_ios", C),
        "c1":   (800, 224, "CORE-1", "l3 · arista_eos", C),
        "c2":   (1010, 224, "CORE-2", "l3 · juniper_junos", C),
        "swa":  (705, 311, "SW-A", "aruba_aoscx", V),
        "swb":  (905, 311, "SW-B", "cisco_ios", V),
        "swc":  (1105, 311, "SW-C", "huawei_vrp", V),
        "ap":   (905, 394, "AP-1", "802.11ax · PoE", G),
    }
    links = [("net", "r1", A), ("r1", "c1", C), ("r1", "c2", C), ("c1", "swa", V), ("c1", "swb", V),
             ("c2", "swb", V), ("c2", "swc", V), ("swb", "ap", G)]

    def p(a, b):
        return f"M{N[a][0]},{N[a][1]} L{N[b][0]},{N[b][1]}"

    style = f"""
  .m{{{MONO}}} .s{{{SANS}}}
  .flow{{stroke-dasharray:4 10;animation:flow 1.1s linear infinite}} @keyframes flow{{to{{stroke-dashoffset:-28}}}}
  .ssh{{stroke-dasharray:7 6;animation:flow .9s linear infinite}}
  .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 3s ease-out infinite}}
  @keyframes pulse{{0%{{transform:scale(1);opacity:.6}}100%{{transform:scale(1.35,1.8);opacity:0}}}}
  .up{{animation:up 1s ease-out both}} .u1{{animation-delay:.15s}} .u2{{animation-delay:.3s}} .u3{{animation-delay:.45s}} .u4{{animation-delay:.6s}}
  @keyframes up{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
  .cur{{animation:cb 1s steps(1) infinite}} @keyframes cb{{50%{{opacity:0}}}}
"""
    chips = ["VALIDATE", "PREVIEW", "APPROVE", "PUSH", "VERIFY", "ROLLBACK", "AUDIT"]
    T = 7.0
    for i in range(len(chips)):
        a, b = i / len(chips) * 100, (i + 1) / len(chips) * 100
        style += (f".k{i} rect{{animation:k{i}r {T}s infinite}} .k{i} text{{animation:k{i}t {T}s infinite}}"
                  f"@keyframes k{i}r{{0%,{a:.1f}%,{b + 4:.1f}%,100%{{fill:#0a1a2b;stroke:#24506f}}{a + 2:.1f}%,{b:.1f}%{{fill:#0d3a2c;stroke:{G}}}}}"
                  f"@keyframes k{i}t{{0%,{a:.1f}%,{b + 4:.1f}%,100%{{fill:{MUTED}}}{a + 2:.1f}%,{b:.1f}%{{fill:#b9f8dd}}}}\n")

    title_grad = f"""
  <linearGradient id="tg" gradientUnits="userSpaceOnUse" x1="40" y1="0" x2="340" y2="0">
    <stop offset="0" stop-color="{TXT}"/><stop offset=".42" stop-color="{TXT}"/><stop offset=".5" stop-color="#b9f8dd"/><stop offset=".58" stop-color="{TXT}"/><stop offset="1" stop-color="{TXT}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-420 0;620 0;620 0" keyTimes="0;.55;1" dur="6s" repeatCount="indefinite"/>
  </linearGradient>
  <linearGradient id="sg" gradientUnits="userSpaceOnUse" x1="330" y1="0" x2="560" y2="0">
    <stop offset="0" stop-color="{G}"/><stop offset=".5" stop-color="{C}"/><stop offset="1" stop-color="{G}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="0 0;230 0;0 0" dur="5s" repeatCount="indefinite"/>
  </linearGradient>
  <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{C}" stop-opacity="0"/><stop offset=".85" stop-color="{C}" stop-opacity=".10"/><stop offset="1" stop-color="{C}" stop-opacity=".35"/></linearGradient>
  <linearGradient id="fadeX" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".08" stop-color="#fff"/><stop offset=".92" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <mask id="tickMask"><rect x="0" y="430" width="{W}" height="50" fill="url(#fadeX)"/></mask>"""

    b = [frame(W, H)]
    # ambient glow orbs + radar sweep
    b.append(f'<g clip-path="url(#panel)"><circle cx="905" cy="230" r="190" fill="{C}" opacity=".10" filter="url(#soft)">'
             f'<animate attributeName="r" values="170;215;170" dur="7s" repeatCount="indefinite"/></circle>'
             f'<circle cx="160" cy="120" r="140" fill="{G}" opacity=".08" filter="url(#soft)"><animate attributeName="opacity" values=".05;.12;.05" dur="6s" repeatCount="indefinite"/></circle>'
             f'<rect y="0" width="160" height="{H}" fill="url(#sweep)"><animate attributeName="x" values="-200;{W + 40}" dur="7s" repeatCount="indefinite"/></rect></g>')

    # ----- left column
    b.append(f'<g class="up"><rect x="56" y="48" width="236" height="30" rx="15" fill="{G}" fill-opacity=".10" stroke="{G}" stroke-opacity=".5"/>'
             f'<circle cx="75" cy="63" r="5" fill="{G}" filter="url(#glow)">{blink(1.4, lo=.2)}</circle>'
             f'<text x="88" y="68" class="m" font-size="12.5" fill="#9ff3cf" letter-spacing="1">MULTI-VENDOR · NETDEVOPS · v1</text></g>')
    b.append('<text x="52" y="146" class="s up u1" font-size="60" font-weight="800" letter-spacing="-1.8">'
             '<tspan fill="url(#tg)">NetConfig</tspan> <tspan fill="url(#sg)">Studio</tspan></text>')
    b.append('<text x="56" y="186" class="s up u2" font-size="19" fill="#a9bdd0">Plan network changes in a form. Preview the exact CLI.</text>'
             '<text x="56" y="213" class="s up u2" font-size="19" fill="#a9bdd0">Push with backup, verification and automatic rollback.</text>')
    # typing terminal cycling through three tasks
    cmds = ["push SW-A  vlan 10,20 + access ports  ✓ verified",
            "link R1 ⇄ CORE-1  /31 + OSPF area 0  ✓ both sides",
            "bootstrap SW-C  console → SSHv2 only  ✓ reachable"]
    fs, x_txt = 15, 100
    b.append(f'<g class="up u3"><rect x="56" y="240" width="560" height="50" rx="14" fill="#030b15" stroke="{LINE}"/>'
             f'<circle cx="72" cy="252" r="2.5" fill="{R}"/><circle cx="81" cy="252" r="2.5" fill="{A}"/><circle cx="90" cy="252" r="2.5" fill="{G}"/>'
             f'<text x="78" y="275" class="m" font-size="{fs}" fill="{G}">$</text>')
    cur_t, cur_v = ["0"], [str(x_txt)]
    n = len(cmds)
    for k, cmd in enumerate(cmds):
        w = len(cmd) * fs * MONO_W
        t0, t1, t2, t3 = k / n + .005, k / n + .13, (k + 1) / n - .03, (k + 1) / n - .005
        b.append(f'<clipPath id="ty{k}"><rect x="{x_txt}" y="252" height="34" width="0">'
                 f'<animate attributeName="width" values="0;0;{w:.0f};{w:.0f};0;0" keyTimes="0;{t0:.3f};{t1:.3f};{t2:.3f};{t3:.3f};1" dur="12s" repeatCount="indefinite"/></rect></clipPath>'
                 f'<g clip-path="url(#ty{k})"><text x="{x_txt}" y="275" class="m" font-size="{fs}" fill="#d6e4f0">{escape(cmd)}</text></g>')
        cur_t += [f"{t0:.3f}", f"{t1:.3f}", f"{t2:.3f}", f"{t3:.3f}"]
        cur_v += [str(x_txt), f"{x_txt + w:.0f}", f"{x_txt + w:.0f}", str(x_txt)]
    cur_t.append("1")
    cur_v.append(str(x_txt))
    b.append(f'<rect class="cur" x="{x_txt}" y="262" width="9" height="18" fill="{G}"><animate attributeName="x" values="{";".join(cur_v)}" '
             f'keyTimes="{";".join(cur_t)}" dur="12s" repeatCount="indefinite"/></rect></g>')
    # workflow chips lighting up in order
    x = 56
    chip_svg = []
    for i, c in enumerate(chips):
        w = len(c) * 11 * MONO_W + 22
        chip_svg.append(f'<g class="k{i}"><rect x="{x:.0f}" y="310" width="{w:.0f}" height="26" rx="13" fill="#0a1a2b" stroke="#24506f"/>'
                        f'<text x="{x + w / 2:.0f}" y="327" text-anchor="middle" class="m" font-size="11" font-weight="700" fill="{MUTED}" letter-spacing=".5">{c}</text></g>')
        x += w + 7
    b.append(f'<g class="up u4">{"".join(chip_svg)}</g>')
    b.append('<text x="56" y="376" class="m up u4" font-size="12.5" fill="#5f7d98">Cisco IOS · Arista EOS · Junos · AOS-CX · RouterOS · VRP · D-Link · TP-Link</text>')
    b.append(f'<text x="56" y="400" class="m up u4" font-size="12.5" fill="{DIM}">FastAPI · React · Netmiko · MongoDB · runs on 127.0.0.1</text>')

    # ----- topology
    for a, c2, col in links:
        b.append(f'<path d="{p(a, c2)}" stroke="#1e4563" stroke-width="3" fill="none"/>'
                 f'<path d="{p(a, c2)}" stroke="{col}" stroke-opacity=".55" stroke-width="2" fill="none" class="flow"/>')
    # LACP bundle between the cores
    for dy in (-5, 5):
        b.append(f'<path d="M800,{224 + dy} L1010,{224 + dy}" stroke="{C}" stroke-opacity=".6" stroke-width="2" class="flow"/>')
    b.append(f'<text x="905" y="214" text-anchor="middle" class="m" font-size="10" fill="{C}">LACP 2×10G</text>')
    # management SSH from the laptop
    b.append(f'<path d="{p("pc", "c1")}" stroke="{G}" stroke-width="2" fill="none" class="ssh"/>'
             f'<text x="630" y="184" class="m" font-size="10" fill="{G}">↘ SSH · host key pinned</text>')
    # ripples on the edge router and the cores
    for (cx, cy, col, d) in ((905, 137, C, 0), (800, 224, G, 1.2), (1010, 224, G, 2.1)):
        b.append(f'<circle cx="{cx}" cy="{cy}" r="20" fill="none" stroke="{col}" stroke-width="1.5">'
                 f'<animate attributeName="r" values="24;95" dur="3.3s" begin="{d}s" repeatCount="indefinite"/>'
                 f'<animate attributeName="opacity" values=".45;0" dur="3.3s" begin="{d}s" repeatCount="indefinite"/></circle>')
    # Wi-Fi arcs from the AP
    for i, rr in enumerate((16, 26, 36)):
        b.append(f'<path d="M{975 - rr * .3},{394 - rr} A{rr},{rr} 0 0 1 {975 + rr * .9},{394 - rr * .35}" fill="none" stroke="{G}" stroke-width="2" stroke-linecap="round" opacity="0">'
                 f'<animate attributeName="opacity" values="0;1;0" dur="1.8s" begin="{i * .3}s" repeatCount="indefinite"/></path>')
    # traffic: packets in both directions on every link
    pk = []
    for a, c2, col in links:
        pk.append(packet(p(a, c2), col, RNG.uniform(2.0, 3.2), RNG.uniform(0, 2)))
        pk.append(packet(p(c2, a), "#e6f0fa" if col != A else A, RNG.uniform(2.4, 3.6), RNG.uniform(.5, 3), r=3.4))
    pk.append(packet("M800,219 L1010,219", C, 1.6, .3, r=3.2))
    pk.append(packet("M1010,229 L800,229", C, 1.9, 1.1, r=3.2))
    pk.append(packet(p("pc", "c1"), G, 1.8, 0, r=4.6))
    b.append("".join(pk))
    # nodes
    for k, (x, y, label, sub, col) in N.items():
        w, h = (128 if k != "ap" else 118), 46
        x0, y0 = x - w / 2, y - h / 2
        ports = "".join(f'<rect x="{x0 + w - 34 + i * 7}" y="{y0 + 9}" width="4.5" height="4.5" rx="1" fill="{col}">{blink(RNG.uniform(.35, 1.3), RNG.uniform(0, 1), .1)}</rect>' for i in range(4))
        b.append(f'<g><rect class="pulse" style="animation-delay:{RNG.uniform(0, 3):.2f}s" x="{x0}" y="{y0}" width="{w}" height="{h}" rx="13" fill="none" stroke="{col}" stroke-width="1.5"/>'
                 f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="13" fill="#081726" stroke="{col}" stroke-opacity=".85"/>'
                 f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="13" fill="url(#sheen)"/>{ports}'
                 f'<circle cx="{x0 + 14}" cy="{y - 5}" r="4" fill="{col}" filter="url(#glow)">{blink(RNG.uniform(1.2, 2.2))}</circle>'
                 f'<text x="{x0 + 25}" y="{y}" class="m" font-size="12.5" font-weight="700" fill="{TXT}">{label}</text>'
                 f'<text x="{x0 + 14}" y="{y + 15}" class="m" font-size="9.5" fill="{MUTED}">{sub}</text></g>')

    # ----- protocol ticker
    items = ["802.1Q VLANs", "Access / Trunk", "SVIs", "Routed ports", "DHCP pools", "NAT / PAT", "Static routes", "OSPF",
             "EIGRP", "BGP", "SSHv2", "LLDP / CDP", "Host-key pinning", "Revert timer", "commit confirmed", "Two-person approval",
             "Audit hash chain", "Secrets masked"]
    fs = 12.5
    xs, xpos = [], 0.0
    for it in items:
        xs.append(xpos)
        xpos += len(it) * fs * MONO_W + 46
    span = xpos
    tk = []
    for copy in (0, span):
        for it, xx in zip(items, xs, strict=True):
            tk.append(f'<text x="{xx + copy:.0f}" y="461" class="m" font-size="{fs}" fill="{MUTED}">{escape(it)}</text>'
                      f'<rect x="{xx + copy + len(it) * fs * MONO_W + 18:.0f}" y="453" width="7" height="7" fill="{G}" opacity=".7" transform="rotate(45 {xx + copy + len(it) * fs * MONO_W + 21.5:.0f} 456.5)"/>')
    b.append(f'<rect x="1" y="430" width="{W - 2}" height="49" fill="#030a14" opacity=".75" clip-path="url(#panel)"/><line x1="0" y1="430" x2="{W}" y2="430" stroke="{LINE}"/>'
             f'<g mask="url(#tickMask)"><g><animateTransform attributeName="transform" type="translate" from="0 0" to="{-span:.0f} 0" dur="{span / 45:.1f}s" repeatCount="indefinite"/>'
             f'{"".join(tk)}</g></g>')
    (OUT / "hero.svg").write_text(svg(W, H, "NetConfig Studio: animated multi-vendor network topology with live traffic", style, "\n".join(b), title_grad), encoding="utf-8")


# ------------------------------------------------------------------ switch faceplate
def switch():
    W, H = 1200, 262
    vlans = {10: ("#60a5fa", "VLAN 10 · Sales"), 20: (V, "VLAN 20 · Engineering"), 30: (A, "VLAN 30 · Voice"),
             99: (G, "VLAN 99 · Mgmt"), 0: (C, "802.1Q trunk")}
    port_vlan = {}
    for n in range(1, 25):
        port_vlan[n] = 10 if n <= 8 else 20 if n <= 14 else 30 if n <= 20 else 99 if n <= 22 else 0
    unplugged = {7, 12, 18}
    T = 9.0
    style = f"""
  .m{{{MONO}}} .s{{{SANS}}}
  .led{{animation:led 1s steps(2) infinite}} @keyframes led{{50%{{opacity:.12}}}}
  .cfg{{animation:cfg {T}s infinite backwards}}
  @keyframes cfg{{0%{{opacity:.15}}4%{{opacity:1}}6%{{opacity:.55}}60%{{opacity:1}}80%,100%{{opacity:.15}}}}
  .scan{{animation:scan {T}s infinite backwards}}
  @keyframes scan{{0%{{opacity:0}}3%{{opacity:1}}12%,100%{{opacity:0}}}}
"""
    grad = """<linearGradient id="metal" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b2a3a"/><stop offset=".5" stop-color="#101c29"/><stop offset="1" stop-color="#0a131d"/></linearGradient>
  <linearGradient id="ear" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#22364a"/><stop offset="1" stop-color="#132232"/></linearGradient>"""
    b = [f'<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="21" fill="url(#sheen)" stroke="{LINE}"/>']
    # rack ears + chassis
    for ex in (14, 1160):
        b.append(f'<rect x="{ex}" y="36" width="26" height="160" rx="4" fill="url(#ear)" stroke="#2b4a63"/>'
                 f'<circle cx="{ex + 13}" cy="56" r="5" fill="#050b14" stroke="#3b5d7a"/><circle cx="{ex + 13}" cy="176" r="5" fill="#050b14" stroke="#3b5d7a"/>')
    b.append('<rect x="40" y="36" width="1120" height="160" rx="8" fill="url(#metal)" stroke="#2b4a63"/>'
             '<rect x="40" y="36" width="1120" height="3" fill="#ffffff" opacity=".06"/>')
    # brand + system LEDs
    b.append(f'<text x="62" y="74" class="s" font-size="17" font-weight="800" fill="{TXT}" letter-spacing=".5">NetConfig</text>'
             f'<text x="62" y="92" class="m" font-size="10.5" fill="{MUTED}">NC-24P-L3 · PoE+ · 4×SFP+</text>')
    for i, (lbl, col, dur) in enumerate((("SYS", G, 2.0), ("PWR", G, 0), ("PoE", A, 3.1), ("FAN", G, 0))):
        x = 72 + i * 42
        anim = blink(dur, 0, .2) if dur else ""
        b.append(f'<circle cx="{x}" cy="128" r="4.5" fill="{col}" filter="url(#glow)">{anim}</circle>'
                 f'<text x="{x}" y="148" text-anchor="middle" class="m" font-size="9" fill="{MUTED}">{lbl}</text>')
    b.append(f'<text x="62" y="180" class="m" font-size="9.5" fill="{DIM}">configured by NetConfig Studio</text>')

    def rj45(x, y, n, top):
        vid = port_vlan[n]
        col = vlans[vid][0]
        plugged = n not in unplugged
        notch_y = y if top else y + 24
        pins = "".join(f'<line x1="{x + 7 + i * 3}" y1="{y + 8 if top else y + 18}" x2="{x + 7 + i * 3}" y2="{y + 12 if top else y + 22}" stroke="#b08d3a" stroke-width="1.2"/>' for i in range(8))
        out = [f'<rect x="{x}" y="{y}" width="36" height="30" rx="3" fill="#02060c" stroke="#3b5d7a"/>'
               f'<rect x="{x + 11}" y="{notch_y}" width="14" height="6" fill="#101c29"/>{pins}']
        if plugged:
            out.append(f'<rect x="{x + 4}" y="{y + (12 if top else 4)}" width="28" height="14" rx="2" fill="{col}" opacity=".35"/>')
        # VLAN bar (lights up in a configuration wave)
        bar_y = y + 33 if top else y - 7
        delay = (n - 1) * .18
        out.append(f'<rect class="cfg" style="animation-delay:{delay:.2f}s" x="{x}" y="{bar_y}" width="36" height="4" rx="2" fill="{col}"/>'
                   f'<rect class="scan" opacity="0" style="animation-delay:{delay:.2f}s" x="{x - 3}" y="{y - 3}" width="42" height="36" rx="5" fill="none" stroke="{col}" stroke-width="2" filter="url(#glow)"/>')
        # link / activity LED
        led_y = y - 9 if top else y + 35
        if plugged:
            led_col = A if vid == 30 else G
            out.append(f'<rect class="led" style="animation-duration:{RNG.uniform(.25, 1.4):.2f}s;animation-delay:{RNG.uniform(0, 1):.2f}s" x="{x + 2}" y="{led_y}" width="9" height="4" rx="1" fill="{led_col}"/>')
        else:
            out.append(f'<rect x="{x + 2}" y="{led_y}" width="9" height="4" rx="1" fill="#22313f"/>')
        out.append(f'<text x="{x + 34}" y="{led_y + 4.5}" text-anchor="end" class="m" font-size="8.5" fill="{DIM}">{n}</text>')
        return "".join(out)

    for j in range(12):
        x = 260 + j * 46 + (18 if j >= 6 else 0)
        b.append(rj45(x, 62, 2 * j + 1, True))
        b.append(rj45(x, 136, 2 * j + 2, False))
    # SFP+ uplinks
    for j in range(2):
        for r_ in range(2):
            x, y = 850 + j * 54, 70 + r_ * 66
            b.append(f'<rect x="{x}" y="{y}" width="44" height="22" rx="2" fill="#02060c" stroke="{C}" stroke-opacity=".6"/>'
                     f'<rect x="{x + 5}" y="{y + 6}" width="34" height="10" fill="{C}" opacity=".25"/>'
                     f'<rect class="led" style="animation-duration:{RNG.uniform(.2, .6):.2f}s" x="{x + 2}" y="{y + 26}" width="9" height="4" rx="1" fill="{C}"/>')
    b.append(f'<text x="902" y="180" text-anchor="middle" class="m" font-size="9.5" fill="{MUTED}">SFP+ 25–28 · uplinks</text>')
    # console + mgmt ports
    b.append(f'<rect x="980" y="74" width="40" height="28" rx="3" fill="#02060c" stroke="#60a5fa"/><rect x="992" y="74" width="16" height="6" fill="#101c29"/>'
             f'<text x="1000" y="118" text-anchor="middle" class="m" font-size="9" fill="{MUTED}">CONSOLE</text>'
             f'<rect x="980" y="134" width="40" height="28" rx="3" fill="#02060c" stroke="{G}"/><rect x="992" y="156" width="16" height="6" fill="#101c29"/>'
             f'<rect x="984" y="138" width="32" height="14" rx="2" fill="{G}" opacity=".35"/>'
             f'<rect class="led" style="animation-duration:.7s" x="982" y="168" width="9" height="4" rx="1" fill="{G}"/>'
             f'<text x="1000" y="184" text-anchor="middle" class="m" font-size="9" fill="{G}">MGMT 🔒</text>')
    # fan grille
    for gx in range(6):
        for gy in range(10):
            b.append(f'<circle cx="{1058 + gx * 16}" cy="{54 + gy * 14}" r="3.4" fill="#050b14" stroke="#1c3146"/>')
    # legend
    x = 46
    for vid in (10, 20, 30, 99, 0):
        col, lbl = vlans[vid]
        b.append(f'<rect x="{x}" y="218" width="22" height="8" rx="4" fill="{col}"/><text x="{x + 30}" y="226" class="m" font-size="12" fill="{MUTED}">{lbl}</text>')
        x += 30 + len(lbl) * 12 * MONO_W + 34
    b.append(f'<text x="46" y="250" class="m" font-size="11" fill="{DIM}">LED blink = traffic · ports 7, 12, 18 down · MGMT port protected from changes</text>')
    (OUT / "switch.svg").write_text(svg(W, H, "Animated 24-port switch: blinking port LEDs, VLAN-coloured ports and a configuration wave", style, "\n".join(b), grad), encoding="utf-8")


# ------------------------------------------------------------------ stats cards
def stats():
    W, H = 1200, 172
    cards = [("8", "OS drivers", "4 core · 4 opt-in", G, .8),
             ("448", "automated tests", "347 backend · 101 UI", C, .92),
             ("9", "step safe push", "backup → verify → confirm", V, 1.0),
             ("0", "passwords stored", "memory only, wiped after", A, .0)]
    style = f".m{{{MONO}}} .s{{{SANS}}} .up{{animation:up .9s ease-out both}} @keyframes up{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}"
    b = []
    circ = 2 * 3.14159 * 30
    for i, (num, lbl, sub, col, frac) in enumerate(cards):
        x = 12 + i * 297
        cx, cy = x + 56, 92
        off = circ * (1 - frac) if frac else circ * .97
        ring_col = col if frac else R
        spark = " ".join(f"{x + 166 + k * 10},{60 - RNG.uniform(0, 22):.0f}" for k in range(10))
        b.append(f'<g class="up" style="animation-delay:{i * .15:.2f}s">'
                 f'<rect x="{x}" y="14" width="281" height="144" rx="22" fill="#071524" stroke="{LINE}"/><rect x="{x}" y="14" width="281" height="144" rx="22" fill="url(#sheen)"/>'
                 f'<circle cx="{cx}" cy="{cy}" r="30" fill="none" stroke="#14304a" stroke-width="7"/>'
                 f'<circle cx="{cx}" cy="{cy}" r="30" fill="none" stroke="{ring_col}" stroke-width="7" stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{off:.1f}" transform="rotate(-90 {cx} {cy})" filter="url(#glow)">'
                 f'<animate attributeName="stroke-dashoffset" values="{circ:.1f};{off:.1f};{off:.1f};{circ:.1f}" keyTimes="0;.3;.85;1" dur="6s" begin="{i * .4:.1f}s" repeatCount="indefinite"/></circle>'
                 f'<circle cx="{cx}" cy="{cy}" r="4" fill="{col}">{blink(1.2 + i * .3, 0, .2)}</circle>'
                 f'<polyline points="{spark}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" stroke-dasharray="200" stroke-dashoffset="0" opacity=".8">'
                 f'<animate attributeName="stroke-dashoffset" values="200;0;0;-200" keyTimes="0;.4;.8;1" dur="4.5s" begin="{i * .3:.1f}s" repeatCount="indefinite"/></polyline>'
                 f'<text x="{x + 106}" y="100" class="s" font-size="42" font-weight="800" fill="{TXT}">{num}</text>'
                 f'<text x="{x + 106}" y="124" class="s" font-size="15" font-weight="600" fill="{col}">{lbl}</text>'
                 f'<text x="{x + 106}" y="143" class="m" font-size="11" fill="{MUTED}">{sub}</text></g>')
    (OUT / "stats.svg").write_text(svg(W, H, "8 OS drivers, 448 automated tests, a 9-step safe push, 0 device passwords stored", style, "\n".join(b)), encoding="utf-8")


# ------------------------------------------------------------------ section divider
def divider():
    W, H = 1200, 34
    style = ".flow{stroke-dasharray:3 9;animation:f 1s linear infinite} @keyframes f{to{stroke-dashoffset:-24}}"
    b = [f'<line x1="0" y1="17" x2="{W}" y2="17" stroke="{C}" stroke-opacity=".18" stroke-width="2"/>',
         f'<line x1="0" y1="17" x2="{W}" y2="17" stroke="{C}" stroke-opacity=".5" stroke-width="2" class="flow"/>']
    for dur, col, beg in ((6, G, 0), (8.5, C, 2), (11, V, 4.5)):
        b.append(packet(f"M-10,17 L{W + 10},17", col, dur, beg, r=3.6))
    b.append(f'<circle cx="600" cy="17" r="6" fill="none" stroke="{G}"><animate attributeName="r" values="6;16" dur="2s" repeatCount="indefinite"/>'
             f'<animate attributeName="opacity" values=".8;0" dur="2s" repeatCount="indefinite"/></circle>'
             f'<rect x="594" y="11" width="12" height="12" rx="2" fill="#071827" stroke="{G}" stroke-width="2" transform="rotate(45 600 17)"/>'
             f'<circle cx="600" cy="17" r="2.5" fill="{G}">{blink(1.2)}</circle>')
    (OUT / "divider.svg").write_text(svg(W, H, "section divider", style, "\n".join(b)), encoding="utf-8")


# ------------------------------------------------------------------ terminal
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
    colours = {"p": TXT, "ok": G, "h": DIM, "c": "#7dd3fc", "s": "#c4b5fd"}
    W, top, lh = 860, 66, 21
    H = top + lh * len(lines) + 30
    T, step = 16.0, 0.55
    css, body = [], []
    for i, (kind, text) in enumerate(lines):
        a = (0.6 + i * step) / T * 100
        css.append(f".l{i}{{animation:l{i} {T}s infinite}}@keyframes l{i}{{0%,{a:.2f}%{{opacity:0}}{min(a + 1.5, 99):.2f}%,94%{{opacity:1}}98%,100%{{opacity:0}}}}")
        y = top + i * lh
        body.append(f'<text class="l{i}" x="28" y="{y}" fill="{colours[kind]}">{escape(text)}</text>')
    last = len(lines) - 1
    cx = 28 + len(lines[last][1]) * 14 * MONO_W + 6
    body.append(f'<g class="l{last}"><rect class="cur" x="{cx:.0f}" y="{top + last * lh - 13}" width="8" height="16" fill="{G}"/></g>')
    style = (f"text{{{MONO};font-size:14px;white-space:pre}} .ttl{{{SANS};font-size:13px}} .cur{{animation:cb 1s steps(1) infinite}} @keyframes cb{{50%{{opacity:0}}}}"
             + "".join(css) + "@media (prefers-reduced-motion: reduce){text{opacity:1!important}}")
    head = (f'<rect width="{W}" height="{H}" rx="18" fill="#050d18" stroke="{LINE}"/>'
            f'<rect width="{W}" height="40" rx="18" fill="#0c1d2e"/><rect y="22" width="{W}" height="18" fill="#0c1d2e"/>'
            f'<circle cx="24" cy="20" r="6" fill="#ff5f57"/><circle cx="44" cy="20" r="6" fill="#febc2e"/><circle cx="64" cy="20" r="6" fill="#28c840"/>'
            f'<text x="{W / 2}" y="25" text-anchor="middle" class="ttl" fill="{MUTED}">netconfig-studio — Configure ▸ Preview ▸ Run</text>'
            f'<circle cx="{W - 120}" cy="20" r="4" fill="{G}" filter="url(#glow)">{blink(1.2, 0, .2)}</circle>'
            f'<text x="{W - 110}" y="24" style="font-size:11px" fill="{G}">SSH 10.0.0.2</text>'
            f'<rect x="0" y="40" width="{W}" height="2" fill="{G}" opacity=".08"><animate attributeName="y" values="40;{H - 4};40" dur="8s" repeatCount="indefinite"/></rect>')
    (OUT / "terminal.svg").write_text(svg(W, H, "Terminal animation: a plan is validated, previewed as Cisco commands, pushed with backup, verified and confirmed", style, head + "".join(body)), encoding="utf-8")


# ------------------------------------------------------------------ push pipeline
def pipeline():
    steps = ["Validate", "Preview", "Approve", "Connect", "Backup", "Pre-check", "Apply", "Verify", "Save"]
    subs = ["ipaddress", "diff", "2nd user", "SSH", "running", "mgmt IP", "revert timer", "show cmds", "write mem"]
    W, H = 1200, 250
    x0, gap, w, y = 30, 128, 112, 70
    T = 11.0
    css, body = [], []
    body.append(f'<line x1="{x0 + w / 2}" y1="{y + 24}" x2="{x0 + gap * 8 + w / 2}" y2="{y + 24}" stroke="{LINE}" stroke-width="3"/>')
    body.append(f'<line x1="{x0 + w / 2}" y1="{y + 24}" x2="{x0 + gap * 8 + w / 2}" y2="{y + 24}" stroke="{G}" stroke-width="3" class="rail"/>')
    body.append(f'<circle r="8" fill="{G}" filter="url(#glow)" cy="{y + 24}"><animate attributeName="cx" values="{x0 + w / 2};{x0 + gap * 8 + w / 2};{x0 + gap * 8 + w / 2}" '
                f'keyTimes="0;.77;1" dur="{T}s" repeatCount="indefinite"/><animate attributeName="opacity" values="1;1;0" keyTimes="0;.9;1" dur="{T}s" repeatCount="indefinite"/></circle>')
    for i, s in enumerate(steps):
        x = x0 + i * gap
        a = 77 * i / 8
        css.append(f".s{i}{{animation:s{i} {T}s infinite}}@keyframes s{i}{{0%,{a:.1f}%{{fill:#0a1a2b;stroke:#2b5878}}"
                   f"{a + 2:.1f}%,92%{{fill:#0d3a2c;stroke:{G}}}100%{{fill:#0a1a2b;stroke:#2b5878}}}}"
                   f".g{i}{{animation:g{i} {T}s infinite}}@keyframes g{i}{{0%,{a:.1f}%{{opacity:0}}{a + 1:.1f}%{{opacity:.9}}{a + 9:.1f}%,100%{{opacity:0}}}}")
        body.append(f'<rect class="g{i}" x="{x - 4}" y="{y - 4}" width="{w + 8}" height="56" rx="28" fill="none" stroke="{G}" stroke-width="3" opacity="0" filter="url(#glow)"/>'
                    f'<rect class="s{i}" fill="#0a1a2b" stroke="#2b5878" x="{x}" y="{y}" width="{w}" height="48" rx="24" stroke-width="1.6"/>'
                    f'<text x="{x + w / 2}" y="{y + 22}" text-anchor="middle" class="lbl">{s}</text>'
                    f'<text x="{x + w / 2}" y="{y + 38}" text-anchor="middle" class="sub">{subs[i]}</text>'
                    f'<text x="{x + w / 2}" y="{y - 14}" text-anchor="middle" class="num">{i + 1:02d}</text>')
    ax, bx = x0 + 7 * gap + w / 2, x0 + 4 * gap + w / 2
    rb = f"M{ax},{y + 48} C{ax},{y + 130} {bx},{y + 130} {bx},{y + 50}"
    body.append(f'<path d="{rb}" fill="none" stroke="{R}" stroke-width="2" class="rb"/>'
                f'<polygon points="{bx - 6},{y + 60} {bx + 6},{y + 60} {bx},{y + 50}" fill="{R}"/>'
                + packet(rb, R, 2.6, 0, r=3.6) +
                f'<text x="{(ax + bx) / 2}" y="{y + 128}" text-anchor="middle" class="rbt">CLI error · failed check · device unreachable  →  automatic rollback</text>')
    style = (f".lbl{{{SANS};font-size:15px;font-weight:700;fill:{TXT}}} .sub{{{MONO};font-size:10.5px;fill:{MUTED}}}"
             f".num{{{MONO};font-size:11px;fill:{DIM}}} .rbt{{{MONO};font-size:12px;fill:#fca5a5}} .ttl{{{SANS};font-size:13px;fill:{MUTED};letter-spacing:2px}}"
             ".rb{stroke-dasharray:7 6;animation:fl 1.4s linear infinite} @keyframes fl{to{stroke-dashoffset:-26}}"
             f".rail{{stroke-dasharray:1100;stroke-dashoffset:1100;animation:rail {T}s linear infinite}}"
             "@keyframes rail{0%{stroke-dashoffset:1100}77%,92%{stroke-dashoffset:0}100%{stroke-dashoffset:0;opacity:0}}" + "".join(css))
    head = frame(W, H, 22, .45) + '<text x="30" y="32" class="ttl">SAFE PUSH PIPELINE</text>'
    (OUT / "pipeline.svg").write_text(svg(W, H, "Push pipeline: validate, preview, approve, connect, backup, pre-check, apply, verify, save, with automatic rollback", style, head + "".join(body)), encoding="utf-8")


for make in (hero, switch, stats, divider, terminal, pipeline):
    make()
print("written to", OUT)
