#!/usr/bin/env python3
"""ЛЗ-86 видеотерминал: генерирует SVG для профиля GitHub.

  python gen/build.py            # всё: шапка, карточки проектов, статистика

Данные тянет из публичного API GitHub и страницы contributions.
GITHUB_TOKEN из окружения (если есть) поднимает лимит запросов.
"""
import base64, datetime as dt, html, io, json, math, os, random, re, urllib.request
from collections import Counter
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "gen" / "fonts"
OUT = ROOT / "assets"
USER = "leo-need-more-coffee"

# люминофор P4 · белый
P = dict(fg="#d9e6ff", dim="#5d6d8a", hot="#ffffff", acc="#8fd4ff", ink="#05080f", inkd="#34425c", tube="#101a2c")
FS, CW, CH, BASE = 16, 9.6, 20, 15  # кегль, ширина и высота клетки, базовая линия

ORGS = ["evadepw", "mireacrm"]
# описания для карточек; карточки строятся по закреплённым (Pinned) репозиториям профиля.
# ключ без "/" — карточка целой организации (так показывается закреплённый org/.github)
DESC = {
    "leo-need-more-coffee/stageflow": "Declarative {h:LLM pipelines} for SaaS: graph in JSON, stages in Python. PyPI, docs, tests",
    "leo-need-more-coffee/stageflow-ui": "Visual {h:editor and debugger} for StageFlow: draw a graph, run it on the live core",
    "leo-need-more-coffee/stageflow-mcp": "StageFlow over {h:MCP}: an agent writes, checks and runs pipelines itself",
    "evadepw/evade-player": "Video player for {h:React} and Web Components: HLS, audio, fragment skip. On npm",
    "evadepw/evadeplayer-platform": "Video backend in {h:Go}: upload, GPU transcoding to HLS, signed playback URLs",
    "mireacrm": "Microservice {h:CRM} for service businesses: Python and Go, gRPC, RabbitMQ, NATS",
    "leo-need-more-coffee/neuro-balance": "{h:Neuroevolution} from scratch: a hand-rolled net learns to balance a ball on a platform",
    "leo-need-more-coffee/flipperzero-bomberduck": "Bomberman-style game for {h:Flipper Zero}: a duck, bombs and blasts on a 128×64 screen",
    "leo-need-more-coffee/flipperzero-4inrow": "Four in a row for {h:Flipper Zero}: the classic, on a dolphin",
    "leo-need-more-coffee/element-lazy-android": "My fork of {h:Element X}: theme config, video circles and stickers for Matrix",
    "leo-need-more-coffee/mireacrm": "{h:Mirea CRM} monorepo: 8 Python and Go services behind one gateway",
}
FALLBACK_PINS = ["leo-need-more-coffee/stageflow", "mireacrm", "evadepw/evadeplayer-platform",
                 "leo-need-more-coffee/neuro-balance", "leo-need-more-coffee/stageflow-ui", "leo-need-more-coffee/flipperzero-bomberduck"]

# наклейки: (колонка левого края, строка центра, текст, наклон в радианах, сид, масштаб)
ZINE = {
    "header": [(20, 16.75, "NEED MORE COFFEE", -0.035, 7, 1), (62, 25.3, "OPEN SOURCE", 0.04, 3, 1)],
    "card-flipperzero-bomberduck": [(26, 3.9, "QUACK!", 0.06, 11, .62)],
    "card-stageflow": [(14, 4.0, "JSON, NOT CODE", -0.03, 12, .58)],
    "card-evadeplayer-platform": [(24, 4.0, "v1.0", 0.06, 5, .66)],
    "card-mireacrm": [(20, 4.0, "17 REPOS", -0.04, 9, .6)],
    "card-neuro-balance": [(14, 4.0, "FROM SCRATCH", 0.03, 4, .56)],
    "stats": [(9, 10.55, "LAZINESS DRIVES PROGRESS", -0.025, 17, .66)],
}


# ---------------------------------------------------------------- данные
def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "lz86-profile"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    return body if raw else json.loads(body)


def fetch():
    user = get(f"https://api.github.com/users/{USER}")
    repos = get(f"https://api.github.com/users/{USER}/repos?per_page=100")
    own = [r for r in repos if not r["fork"]]
    prof = get(f"https://github.com/{USER}", raw=True)
    pins = []
    for m in re.finditer(r'href="/([\w.-]+)/([\w.-]+)"[^>]*>(?:(?!</a>).)*?<span class="repo"[^>]*>([^<]+)', prof, re.S):
        if m.group(2) == m.group(3).strip():
            full = m.group(1) if m.group(2) == ".github" else f"{m.group(1)}/{m.group(2)}"
            if full not in pins:
                pins.append(full)
    pins = pins or FALLBACK_PINS
    by_org = {o: get(f"https://api.github.com/orgs/{o}/repos?per_page=100") for o in ORGS}
    for full in pins:
        if "/" not in full and full not in by_org:
            by_org[full] = get(f"https://api.github.com/orgs/{full}/repos?per_page=100")
    org_repos = [r for rs in by_org.values() for r in rs]
    known = {r["full_name"] for r in repos + org_repos}
    extra = [get(f"https://api.github.com/repos/{f}") for f in pins if "/" in f and f not in known]
    page = get(f"https://github.com/users/{USER}/contributions", raw=True)
    days = {}
    for m in re.finditer(r'data-date="([\d-]+)" id="(contribution-day-component-\d+-\d+)" data-level="(\d)"', page):
        days[m.group(2)] = [m.group(1), int(m.group(3)), 0]
    for m in re.finditer(r'for="(contribution-day-component-\d+-\d+)"[^>]*>([^<]*)', page):
        n = re.match(r"(\d+) contribution", m.group(2))
        if m.group(1) in days and n:
            days[m.group(1)][2] = int(n.group(1))
    cal = sorted((d, lvl, n) for d, lvl, n in days.values())
    best = cur = run = 0
    for _, _, n in cal:
        run = run + 1 if n else 0
        best = max(best, run)
    for _, _, n in reversed(cal[:-1] if cal and not cal[-1][2] else cal):
        if not n:
            break
        cur += 1
    langs = Counter(r["language"] for r in own + org_repos if r["language"])
    return dict(
        user=user, repos=repos, own=own, by_name={r["full_name"]: r for r in repos + org_repos + extra}, by_org=by_org, pins=pins,
        cal=cal, total=sum(n for *_, n in cal), best=best, cur=cur,
        stars=sum(r["stargazers_count"] for r in own), langs=langs.most_common(4),
    )


# ---------------------------------------------------------------- шрифты
def load_font(file, wght=None):
    f = TTFont(FONTS / file)
    if "fvar" in f:
        f = instancer.instantiateVariableFont(f, {"wght": wght or 400})
    return f


def font_face(file, family, text, wght=None):
    f = load_font(file, wght)
    o = subset.Options()
    o.flavor, o.layout_features, o.name_IDs, o.notdef_outline = "woff2", [], [], True
    s = subset.Subsetter(o)
    s.populate(text=text + " ")
    s.subset(f)
    buf = io.BytesIO()
    subset.save_font(f, buf, o)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{b64}) format('woff2')}}"


_metrics = {}


def advance(file, wght, ch, size):
    if (file, wght) not in _metrics:
        f = load_font(file, wght)
        _metrics[(file, wght)] = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    cmap, hmtx, upm = _metrics[(file, wght)]
    g = cmap.get(ord(ch))
    return hmtx[g][0] / upm * size if g else size * .6


_logo_cache = {}


def logo_bitmap(text, max_w, max_h):
    """Буквы Rubik Mono One → сетка пикселей (1 пиксель = клетка × полклетки)."""
    key = (text, max_w, max_h)
    if key in _logo_cache:
        return _logo_cache[key]
    path = str(FONTS / "RubikMonoOne.ttf")
    size = 200
    while size > 6:
        f = ImageFont.truetype(path, size)
        l, t, r, b = f.getbbox(text)
        if r - l <= max_w and b - t <= max_h:
            break
        size -= 1
    img = Image.new("L", (r - l + 2, b - t + 2), 0)
    ImageDraw.Draw(img).text((-l, -t), text, font=f, fill=255)
    w, h = img.size
    px = img.load()
    grid = [[px[x, y] > 110 for x in range(w)] for y in range(h)]
    grid = [row for row in grid if any(row)]
    cols = [x for x in range(w) if any(row[x] for row in grid)]
    grid = [row[cols[0]:cols[-1] + 1] for row in grid]
    _logo_cache[key] = grid
    return grid


def mix(a, b, t):
    a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * min(1, max(0, t))):02x}" for x, y in zip(a, b))


# ---------------------------------------------------------------- наклейки (зин из вырезанных букв)
ZFONTS = [("Oswald.ttf", 700), ("PlayfairDisplay.ttf", 900), ("RussoOne.ttf", None), ("YesevaOne.ttf", None),
          ("OldStandard-Bold.ttf", None), ("Underdog.ttf", None), ("PressStart2P.ttf", None), ("Neucha.ttf", None),
          ("PTSerif-BoldItalic.ttf", None), ("RubikMonoOne.ttf", None), ("Jura.ttf", 700)]
Z_APPROACH, Z_PRESS = .12, .34   # подлёт и прижатие наклейки, секунды
ZPAL = [("#f2efe6", "#0b0b0b"), ("#f2efe6", "#e3241b"), ("#e3241b", "#f7f4ea"), ("#ff6a10", "#0b0b0b"),
        ("#14c8ff", "#0b0b0b"), ("#8cff2e", "#0b0b0b"), ("#0b0b0b", "#f7f4ea"), ("#0b0b0b", "#ff6a10"), ("#1d3bff", "#f7f4ea")]


def pts(poly):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)


def sticker(scr, cx, cy, text, rot, seed, big, t0):
    """Наклейка: каждая буква на своём обрывке бумаги, по краям скотч. cx, cy — левый край и центр, px."""
    R = random.Random(seed * 7919 + 1).random
    L = CH * 1.5 * big
    items, x = [], 0.0
    for ch in text:
        if ch == " ":
            x += L * .7
            continue
        fi = int(R() * len(ZFONTS))
        file, wght = ZFONTS[fi]
        size = L * (.78 + R() * .5) * (.62 if "Press" in file else 1)
        mw = max(size * .35, advance(file, wght, ch, size))
        pad = size * (.12 + R() * .14)
        r = R()
        style = "paper" if r < .42 else "dark" if r < .67 else "acc" if r < .82 else "bare"
        w, h = mw + pad * 2, size * 1.08 + pad * 1.2
        pc = ZPAL[int(R() * len(ZPAL))]
        j = size * .12
        poly = []
        for (x0, y0, x1, y1, n) in ((-w / 2, -h / 2, w / 2, -h / 2, 3), (w / 2, -h / 2, w / 2, h / 2, 2),
                                    (w / 2, h / 2, -w / 2, h / 2, 3), (-w / 2, h / 2, -w / 2, -h / 2, 2)):
            for i in range(n):
                t = i / n
                poly.append((x0 + (x1 - x0) * t + (R() - .5) * j, y0 + (y1 - y0) * t + (R() - .5) * j))
        dots = [(.12 + R() * .25, (R() - .5) * w * .85, (R() - .5) * h * .85, .6 + R() * 1.4, .6 + R() * 1.4) for _ in range(int(size * .7))]
        items.append(dict(ch=ch, fi=fi, size=size, w=w, h=h, style=style, pc=pc, poly=poly, dots=dots, line=R() - .5,
                          x=x + w / 2, y=(R() - .5) * L * .22, rot=(R() - .5) * .34, spin=1 if R() < .5 else -1))
        scr.zchars.setdefault(fi, set()).add(ch)
        x += w * (.86 + R() * .1)
    H = L * 1.6
    # не вылезать за правый край стекла (с запасом на скотч)
    cx = max(16 + L, min(cx, scr.w - 16 - L * 1.3 - x))
    out = []
    for it in items:
        bg, fg = it["pc"]
        g = []
        if it["style"] != "bare":
            g.append(f'<polygon points="{pts(it["poly"])}" transform="translate(2.2 3)" fill="#000" opacity=".75"/>')
            g.append(f'<polygon points="{pts(it["poly"])}" fill="{bg}"/>')
            dc = "#fff" if bg == "#0b0b0b" else "#000"
            g += [f'<rect x="{dx:.1f}" y="{dy:.1f}" width="{dw:.1f}" height="{dh:.1f}" fill="{dc}" opacity="{al:.2f}"/>' for al, dx, dy, dw, dh in it["dots"]]
            g.append(f'<rect x="{-it["w"] / 2:.1f}" y="{it["h"] * it["line"]:.1f}" width="{it["w"]:.1f}" height=".8" fill="{dc}" opacity=".18"/>')
            fill, stroke = fg, ""
        else:
            fill = "#ff6a10" if bg == "#0b0b0b" else bg
            stroke = f' stroke="#000" stroke-width="{it["size"] * .12:.1f}" paint-order="stroke" stroke-linejoin="round"'
        g.append(f'<text font-family="Z{it["fi"]}" font-size="{it["size"]:.1f}" text-anchor="middle" dominant-baseline="central" '
                 f'y="{it["size"] * .04:.1f}" fill="{fill}"{stroke}>{html.escape(it["ch"])}</text>')
        out.append(f'<g transform="translate({it["x"]:.1f} {it["y"]:.1f}) rotate({it["rot"] * 57.2958:.1f})">{"".join(g)}</g>')
    # скотч на крайних буквах
    if items:
        ends = [(items[0]["x"] - items[0]["w"] * .62, -H * .16, -1), (items[-1]["x"] + items[-1]["w"] * .62, -H * .12, 1)]
        for tx, ty, side in ends:
            tw, th, a = L * (1.05 + R() * .3), L * (.36 + R() * .08), side * (.62 + R() * .35)
            poly = [(-tw / 2, -th / 2), (tw / 2, -th / 2)]
            poly += [(tw / 2 + R() * th * .12, -th / 2 + th * q / 6) for q in range(7)]
            poly += [(-tw / 2, th / 2)]
            poly += [(-tw / 2 - R() * th * .12, th / 2 - th * q / 6) for q in range(7)]
            p = pts(poly)
            out.append(f'<g transform="translate({tx:.1f} {ty:.1f}) rotate({a * 57.2958:.1f})">'
                       f'<polygon points="{p}" transform="translate(1.5 2)" fill="#000" opacity=".22"/>'
                       f'<polygon points="{p}" fill="#e4dcc4" opacity=".42" stroke="#fff" stroke-opacity=".6" stroke-width=".8"/>'
                       f'<rect x="{-tw / 2:.1f}" y="{-th / 2:.1f}" width="{tw:.1f}" height="{th * .22:.1f}" fill="#fff" opacity=".22"/></g>')

    # --- как на сайте: подлёт целиком, затем прижатие слева направо;
    #     неприжатая часть загнута к зрителю (крупнее и темнее), потом глитч с RGB-разъездом
    uid = f"{seed}x{len(scr.zdefs)}"
    scr.zdefs.append(f'<g id="zk{uid}">{"".join(out)}</g>')
    xa, xb = -L * 1.7, x + L * 1.7
    W, cxp, fz = xb - xa, (xa + xb) / 2, (xb - xa) * .85
    io = lambda q: 2 * q * q if q < .5 else 1 - (-2 * q + 2) ** 2 / 2
    N, A, PZ = 16, Z_APPROACH, Z_PRESS
    D, sw = A + PZ, W / N
    strips = []
    for i in range(N):
        x0 = xa + i * sw
        scr.zdefs.append(f'<clipPath id="zc{uid}_{i}"><rect x="{x0 - .7:.1f}" y="{-L * 2.5:.1f}" width="{sw + 1.4:.1f}" height="{L * 5:.1f}"/></clipPath>')
        fr = []
        for k in range(13):
            tau = D * k / 12
            p1, p2 = min(1, tau / A), max(0, min(1, (tau - A) / PZ))
            hover = W * .5 * (1 - p1) ** 2
            hinge = W * io(p2)
            ang = (1.45 - .35 * io(p1)) * (1 - .2 * p2)
            kap = ang / max(1, W - hinge)
            xr = i * sw + sw / 2
            a = min(1.45, kap * (xr - hinge)) if xr > hinge else 0
            z = (xr - hinge) * math.sin(a) * .8 if a else 0
            if p2 >= 1:
                a = z = hover = 0
            sc = fz / max(fz * .35, fz - z - hover)
            dark = min(.55, math.sin(a) * .6)
            fr.append(f"{k * 100 / 12:.1f}%{{transform:translate({cxp * (1 - sc):.1f}px,0) scale({sc:.3f});"
                      f"filter:brightness({1 - dark:.2f});opacity:{min(1, p1 * 2.5):.2f}}}")
        scr.zcss.append(f"@keyframes z{uid}_{i}{{{''.join(fr)}}}")
        strips.append(f'<g class="zs" style="animation:z{uid}_{i} {D:.2f}s linear {t0:.2f}s both">'
                      f'<g clip-path="url(#zc{uid}_{i})"><use href="#zk{uid}"/></g></g>')
    use = lambda cls, flt, d: f'<use href="#zk{uid}" class="{cls}" filter="url(#{flt})" style="animation-delay:{d:.2f}s"/>'
    body = (use("zsh", "zfs", t0) + f'<g class="zg" style="animation-delay:{t0 + A + PZ * .4:.2f}s">' + "".join(strips)
            + use("zR", "zfr", t0 + A) + use("zC", "zfc", t0 + A) + "</g>")
    return f'<g transform="translate({cx:.1f} {cy:.1f}) rotate({rot * 57.2958:.2f})">{body}</g>'


# ---------------------------------------------------------------- разметка текста
MK = dict(h="hot", a="acc", d="dim", f="fg", k="ink", K="inkd")


def mk(s, base="fg"):
    out, last = [], 0
    for m in re.finditer(r"\{([hadfkK]):([^{}]*)\}", s):
        if m.start() > last:
            out.append((s[last:m.start()], base))
        out.append((m.group(2), MK[m.group(1)]))
        last = m.end()
    if last < len(s):
        out.append((s[last:], base))
    return out


def plain(s):
    return "".join(t for t, _ in mk(s))


def wrap(s, w, base="fg", hang=0):
    cells = [(c, cl) for t, cl in mk(s, base) for c in t]
    words, cur = [], []
    for c in cells:
        if c[0] == " ":
            if cur:
                words.append(cur)
                cur = []
        else:
            cur.append(c)
    if cur:
        words.append(cur)
    lines, line = [], []
    for wd in words:
        if line and len(line) + 1 + len(wd) > w:
            lines.append(line)
            line = [(" ", base)] * hang
        if line and len(line) > hang:
            line.append((" ", line[-1][1]))
        line += wd
    lines.append(line)
    return lines


def group(cells):
    segs = []
    for c, cl in cells:
        if segs and segs[-1][1] == cl:
            segs[-1][0] += c
        else:
            segs.append([c, cl])
    return segs


# ---------------------------------------------------------------- холст
CSS = """
.t{font:%(fs)spx 'LZ',monospace;white-space:pre}
.fg{fill:%(fg)s}.dim{fill:%(dim)s}.hot{fill:%(hot)s}.acc{fill:%(acc)s}.ink{fill:%(ink)s}.inkd{fill:%(inkd)s}
.a{opacity:0;animation:on 1ms linear forwards}
.boot{animation:off 1ms linear forwards}
.cur{animation:blink 1.06s steps(1) infinite}
.pow{transform-box:view-box;transform-origin:50%% 50%%;animation:pow .5s ease-out both}
.ray{animation:ray 7s linear infinite}
.fl{animation:fl 5s steps(1) infinite}
.zsh{opacity:0;animation:zsh .55s ease-out both}
.zg{animation:zg .5s steps(1) both}
.zR,.zC{opacity:0;mix-blend-mode:screen;animation:zR .5s steps(1) forwards}.zC{animation-name:zC}
@keyframes on{to{opacity:1}}
@keyframes off{to{opacity:0}}
@keyframes blink{50%%{opacity:0}}
@keyframes pow{0%%{transform:scale(1,.004);opacity:.2}55%%{transform:scale(1,.004);opacity:1}100%%{transform:scale(1,1)}}
@keyframes ray{from{transform:translateY(-160px)}to{transform:translateY(%(h)spx)}}
@keyframes fl{0%%,100%%{opacity:1}47%%{opacity:.93}49%%{opacity:1}83%%{opacity:.96}}
@keyframes zsh{0%%{transform:translate(18px,26px);opacity:0}25%%{opacity:.6}100%%{transform:none;opacity:0}}
@keyframes zg{0%%{transform:translate(3px,0);opacity:.8}12%%{transform:translate(-3px,1px);opacity:1}24%%{transform:translate(2px,-1px);opacity:.7}36%%{transform:translate(-1px,0);opacity:1}50%%{transform:translate(1px,0)}62%%,100%%{transform:none;opacity:1}}
@keyframes zR{0%%{opacity:.38;transform:translate(-5px,0)}15%%{opacity:0}30%%{opacity:.3;transform:translate(4px,1px)}45%%{opacity:0}60%%{opacity:.35;transform:translate(-2px,0)}75%%,100%%{opacity:0;transform:none}}
@keyframes zC{0%%{opacity:.38;transform:translate(5px,0)}15%%{opacity:0}30%%{opacity:.3;transform:translate(-4px,-1px)}45%%{opacity:0}60%%{opacity:.35;transform:translate(2px,0)}75%%,100%%{opacity:0;transform:none}}
@media (prefers-reduced-motion:reduce){.a{animation:none;opacity:1}.boot{display:none}.cur,.pow,.ray,.fl,.zg{animation:none}.zs{animation:none!important}.zsh,.zR,.zC{display:none}.ray{display:none}}
"""


class Screen:
    """Фуллскрин-экран ЭЛТ с сеткой клеток; pad — поле от края стекла до сетки."""

    def __init__(self, cols, rows, pad=20):
        self.cols, self.rows = cols, rows
        self.w, self.h = round(cols * CW + 2 * pad), round(rows * CH + 2 * pad)
        self.ox = self.oy = pad
        self.chars, self.zchars, self.zdefs, self.zcss = set(), {}, [], []

    X = lambda s, c: s.ox + c * CW
    Y = lambda s, r: s.oy + r * CH

    def text(self, col, row, s, base="fg", center_w=None):
        segs = group([(c, cl) for t, cl in mk(s, base) for c in t]) if isinstance(s, str) else group(s)
        n = sum(len(t) for t, _ in segs)
        if center_w:
            col += max(0, (center_w - n) // 2)
        for t, _ in segs:
            self.chars.update(t)
        spans = "".join(f'<tspan class="{cl}">{html.escape(t)}</tspan>' for t, cl in segs)
        return f'<text class="t" xml:space="preserve" x="{self.X(col):.1f}" y="{self.Y(row) + BASE:.1f}">{spans}</text>'

    def rect(self, col, row, w, h, fill, extra=""):
        return f'<rect x="{self.X(col):.1f}" y="{self.Y(row):.1f}" width="{w * CW:.1f}" height="{h * CH:.1f}" fill="{fill}" {extra}/>'

    def window(self, x, y, w, h, title, body, active=False):
        """Окно текстового режима. body — список строк (str c разметкой или список клеток)."""
        g = [self.rect(x + 1, y + .5, w, h, "#000", 'opacity=".6"'), self.rect(x, y, w, h, P["ink"])]
        x0, y0 = self.X(x) + CW / 2, self.Y(y) + CH / 2
        x1, y1 = self.X(x + w - 1) + CW / 2, self.Y(y + h - 1) + CH / 2
        col = P["fg"] if active else P["dim"]
        for d in ((-2.5, 2.5) if active else (0,)):
            g.append(f'<rect x="{x0 - d:.1f}" y="{y0 - d:.1f}" width="{x1 - x0 + 2 * d:.1f}" height="{y1 - y0 + 2 * d:.1f}" fill="none" stroke="{col}" stroke-width="1.4"/>')
        t = f" {title} "
        lead = "{a:[■]}" if active else ""
        tw = len(t) + (3 if active else 0)
        g.append(self.rect(x + 2, y, tw, 1, P["ink"]))
        g.append(self.text(x + 2, y, lead + "{h:" + t + "}"))
        for i, line in enumerate(body):
            if line is not None:
                g.append(self.text(x + 2, y + 1 + i, line))
        return "\n".join(g)

    def bar(self, row, left, right=""):
        """Инверсная строка меню / статуса."""
        g = [self.rect(0, row, self.cols, 1, P["fg"]), self.text(1, row, left, "inkd")]
        if right:
            g.append(self.text(self.cols - 1 - len(plain(right)), row, right, "inkd"))
        return "\n".join(g)

    def logo(self, col, row, text, w, rows, center=True):
        grid = logo_bitmap(text, w, rows * 2)
        gh, gw = len(grid), len(grid[0])
        col += (w - gw) // 2 if center else 0
        out = []
        for y, line in enumerate(grid):
            c = mix(P["hot"], P["fg"], y / (gh * .6)) if y < gh * .6 else mix(P["fg"], P["acc"], (y - gh * .6) / (gh * .4))
            x = 0
            while x < gw:
                if line[x]:
                    s = x
                    while x < gw and line[x]:
                        x += 1
                    out.append(f'<rect x="{self.X(col + s):.1f}" y="{self.Y(row) + y * CH / 2:.1f}" width="{(x - s) * CW + .4:.1f}" height="{CH / 2 + .4:.1f}" fill="{c}"/>')
                x += 1
        return "\n".join(out)

    def meter(self, frac, cells, cls="fg"):
        f = round(frac * cells)
        return [(c, cls) for c in "█" * f] + [(c, "dim") for c in "░" * (cells - f)]

    def stickers(self, key, t0):
        return "".join(sticker(self, self.X(c), self.Y(r), txt, rot, seed, big, t0 + i * .9)
                       for i, (c, r, txt, rot, seed, big) in enumerate(ZINE.get(key, [])))

    def render(self, content, path, zine="", r=12):
        w, h = self.w, self.h
        style = CSS % dict(fs=FS, h=h, **P) + "".join(self.zcss)
        style += font_face("PTMono.ttf", "LZ", "".join(self.chars))
        for fi, chs in self.zchars.items():
            style += font_face(ZFONTS[fi][0], f"Z{fi}", "".join(chs), ZFONTS[fi][1])
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<style>{style}</style>
<defs>
<clipPath id="scr"><rect width="{w}" height="{h}" rx="{r}"/></clipPath>
<pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse"><rect y="2" width="4" height="1" fill="#000" opacity=".38"/></pattern>
<pattern id="desk" width="{CW}" height="{CH / 2}" patternUnits="userSpaceOnUse"><rect width="1.6" height="1.6" fill="{P['dim']}" opacity=".45"/></pattern>
<radialGradient id="vig" cx="50%" cy="50%" r="72%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".72"/></radialGradient>
<radialGradient id="tube" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="{P['tube']}"/><stop offset="100%" stop-color="{P['ink']}"/></radialGradient>
<linearGradient id="rayg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{P['fg']}" stop-opacity="0"/><stop offset=".5" stop-color="{P['fg']}" stop-opacity=".05"/><stop offset="1" stop-color="{P['fg']}" stop-opacity="0"/></linearGradient>
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".06"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="zfs" x="-20%" y="-50%" width="140%" height="200%"><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0"/><feGaussianBlur stdDeviation="5"/></filter>
<filter id="zfr"><feColorMatrix values="0 0 0 0 1  0 0 0 0 .08  0 0 0 0 .15  0 0 0 1 0"/></filter>
<filter id="zfc"><feColorMatrix values="0 0 0 0 0  0 0 0 0 .9  0 0 0 0 1  0 0 0 1 0"/></filter>
{''.join(self.zdefs)}
<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<g clip-path="url(#scr)">
<rect width="{w}" height="{h}" fill="url(#tube)"/>
<g class="fl"><g filter="url(#glow)">
{content}
</g></g>
{zine}
<rect class="ray" width="{w}" height="160" fill="url(#rayg)"/>
<rect width="{w}" height="{h}" fill="url(#scan)"/>
<rect width="{w}" height="{h}" fill="url(#vig)"/>
<rect width="{w}" height="{h}" fill="url(#glass)"/>
</g>
</svg>"""
        path.write_text(svg)
        print(f"{path.relative_to(ROOT)}  {len(svg) // 1024} КБ")


def anim(el, t, cls="a"):
    return f'<g class="{cls}" style="animation-delay:{t:.2f}s">{el}</g>'


# ---------------------------------------------------------------- шапка
def build_header(D):
    COLS, ROWS = 100, 28
    s = Screen(COLS, ROWS)
    c = []

    # загрузка
    boot, t = [], 0.55
    lines = [
        ("{h:LZ-86 VIDEO TERMINAL}{d:   ROM v2.6.1}", None),
        ("{d:(c) lazy, 1986–2026}", None),
        ("", None),
        ("MEMORY TEST ......... ", "640 KB {h:OK}"),
        ("H-SCAN .............. ", "15.625 kHz {h:OK}"),
        ("CPU ................. ", "K1810VM86 {h:OK}"),
        ("COFFEE MAKER ........ ", "12 %  {a:LOW, WILL DO}"),
        ("", None),
    ]
    for i, (a, b) in enumerate(lines):
        boot.append(anim(s.text(1, 2 + i, a), t))
        if b:
            boot.append(anim(s.text(1 + len(plain(a)), 2 + i, b), t + .22))
            t += .22
        t += .2
    row = 2 + len(lines)
    pre = "LOADING profile.sys   "
    boot.append(anim(s.text(1, row, pre + "{d:[}" + " " * 18 + "{d:]}"), t))
    for k in range(18):
        t += .045
        boot.append(anim(s.text(1 + len(pre) + 1 + k, row, "█"), t))
    t += .15
    boot.append(anim(s.text(1 + len(pre) + 20, row, "{h: 100%}"), t))
    t += .35
    boot.append(anim(s.text(1, row + 2, "{d:C:\\>} profile.exe"), t))
    t += .45
    c.append(f'<g class="boot" style="animation-delay:{t:.2f}s">{"".join(boot)}</g>')

    # рабочий стол
    T = t
    c.append(anim(s.rect(0, 1, COLS, ROWS - 2, "url(#desk)"), T))
    c.append(s.bar(0, "{k:≡ LZ-86}   {k:F}ile  {k:E}dit  {k:V}iew  {k:C}offee  {k:H}elp", "{k:lazy}@github  P4"))
    c.append(anim(s.bar(ROWS - 1, "{k:F1} Help  {k:F2} Projects  {k:F3} Stats  {k:F10} Exit",
                        "LZ-86 · P4 · 1986–2026"), T))

    u = D["user"]
    langs = D["langs"]
    top = max(n for _, n in langs) if langs else 1
    status = "{h:open to work}" if u.get("hireable") else "busy"
    wins = [
        (2, 2, 60, 14, "LEO-NEED-MORE-COFFEE", True, []),
        (64, 2, 34, 14, "USER", False, [
            "{d:handle}   leo-need-more-coffee",
            "{d:name}     {h:lazy}",
            "{d:status}   " + status,
            "{d:study}    RTU MIREA",
            f"{{d:repos}}    {u['public_repos']} · {{a:*}} {D['stars']} stars",
            f"{{d:followers}} {u['followers']}",
            None,
            "{d:SENSORS}",
            [("coffee   ", "dim")] + s.meter(.12, 12, "acc") + [(" 12 %", "acc")],
            [("laziness ", "dim")] + s.meter(1, 12, "hot") + [(" 100 %", "hot")],
            [("code     ", "dim")] + s.meter(.65, 12) + [(" 65 %", "fg")],
        ]),
        (2, 17, 60, 9, "NOW WORKING ON", False, [
            "{a:▪} {h:StageFlow}: LLM pipelines, an editor, MCP for agents",
            "{a:▪} {h:EvadePlayer}: npm video player + HLS backend in Go",
            "{a:▪} {h:@mireacrm}: a CRM in 17 repos, gRPC, RabbitMQ, NATS",
            "{a:▪} {h:Flipper Zero} games and my own Matrix client",
            None,
            None,
            "{d:lazy@lz86:~$} make coffee",
        ]),
        (64, 17, 34, 9, "LANGUAGES · BY REPO", False,
         [[(f"{n:<11}", "dim")] + s.meter(k / top, 13) + [(f" {k}", "hot")] for n, k in langs]
         + [None, "{d:+ Kotlin · Swift · SQL · Bash}"]),
    ]
    for i, (x, y, w, h, title, active, body) in enumerate(wins):
        el = s.window(x, y, w, h, title, body, active)
        if active:
            el += s.logo(x + 2, y + 2, "LAZY", w - 4, 7)
            el += s.text(x + 2, y + 10, "{h:writing code until the coffee runs out}", center_w=w - 4)
            el += s.text(x + 2, y + 12, "{d:Python · Go · TypeScript · C · LLM · video · Flipper}", center_w=w - 4)
        c.append(anim(el, T + .12 + i * .14))
    cx = 2 + 2 + len("lazy@lz86:~$ make coffee") + 1
    c.append(anim(f'<g class="cur">{s.rect(cx, 24, .9, 1, P["fg"])}</g>', T + .7))

    content = f'<g class="pow">{"".join(c)}</g>'
    s.render(content, OUT / "header.svg", s.stickers("header", T + 1.0), r=14)


# ---------------------------------------------------------------- карточки проектов
def build_cards(D):
    COLS, ROWS = 48, 7
    for old in OUT.glob("card-*.svg"):
        old.unlink()
    cards = []
    for full in D["pins"]:
        desc = DESC.get(full) or html.escape((D["by_name"].get(full) or {}).get("description") or "")
        if "/" not in full:  # карточка целой организации
            rs = D["by_org"].get(full, [])
            lg = " · ".join(l for l, _ in Counter(x["language"] for x in rs if x["language"]).most_common(2))
            owner, name = full, full
            r = dict(org=True, n=len(rs), langs=lg, stars=sum(x["stargazers_count"] for x in rs))
        else:
            r = D["by_name"].get(full, {})
            owner, name = full.split("/")
        s = Screen(COLS, ROWS, pad=14)
        body = wrap(desc, COLS - 4)[:3]
        while len(body) < 3:
            body.append(None)
        lang = r.get("language") or "—"
        meta = f"{{a:*}} {r.get('stargazers_count', 0)}   {{d:lang}} {lang}"
        if r.get("org"):
            meta = f"{{d:org}} {r['n']} repos   {{d:langs}} {r['langs']}"
        if r.get("fork"):
            meta += "   {d:fork}"
        body += [None, meta]
        title = name.upper() if owner in (USER, name) else f"{owner}/{name}".upper()
        if r.get("org"):
            title = f"@{name}".upper()
        el = s.window(0, 0, COLS, ROWS, title, body, active=True)
        btn = "[ ORG ]" if r.get("org") else "[ OPEN ]"
        el += s.text(COLS - 2 - len(btn), ROWS - 2, "{h:" + btn + "}")
        key = f"card-{name}"
        s.render(el, OUT / f"{key}.svg", s.stickers(key, .25), r=10)
        cards.append((full, f"{key}.svg"))
    return cards


def build_readme(cards):
    link = lambda f: f"https://github.com/{f}"
    img = lambda f, svg: f'<a href="{link(f)}"><img src="assets/{svg}" width="49%" alt="{f}"></a>'
    rows = "\n".join("  " + " ".join(img(*c) for c in cards[i:i + 2]) for i in range(0, len(cards), 2))
    (ROOT / "README.md").write_text(f"""<p align="center">
  <img src="assets/header.svg" width="100%" alt="LZ-86 video terminal · lazy · leo-need-more-coffee">
</p>

<p align="center">
{rows}
</p>

<p align="center">
  <img src="assets/stats.svg" width="100%" alt="activity over the last year and counters">
</p>

<sub>screens are rendered daily from pinned repos by <a href="gen/build.py">gen/build.py</a> · fonts: PT Mono, Rubik Mono One and a zine set (OFL)</sub>
""")


# ---------------------------------------------------------------- статистика
def build_stats(D):
    COLS, ROWS = 100, 15
    s = Screen(COLS, ROWS)
    c = []
    cal = D["cal"]
    first = dt.date.fromisoformat(cal[0][0])
    off = (first.weekday() + 1) % 7
    weeks = (len(cal) + off + 6) // 7
    GLY = {0: ("·", "dim"), 1: ("░", "fg"), 2: ("▒", "fg"), 3: ("▓", "fg"), 4: ("█", "hot")}
    hx, hy = 7, 3
    c.append(s.window(0, 0, 65, 14, "ACTIVITY · 52 WEEKS", [], active=True))
    for i, name in enumerate(["Mon", "Wed", "Fri"]):
        c.append(s.text(2, hy + 1 + i * 2, "{d:" + name + "}"))
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    last_m = None
    cols_el = [[] for _ in range(weeks)]
    for i, (d, lvl, n) in enumerate(cal):
        wk, wd = divmod(i + off, 7)
        date = dt.date.fromisoformat(d)
        if wd == 0 and date.month != last_m and wk < weeks - 2:
            c.append(s.text(hx + wk, hy - 1, "{d:" + months[date.month - 1] + "}"))
            last_m = date.month
        ch, cl = GLY[lvl]
        cols_el[wk].append(s.text(hx + wk, hy + wd, [(ch, cl)]))
    for wk, els in enumerate(cols_el):
        c.append(anim("".join(els), .15 + wk * .018))
    c.append(s.text(hx, hy + 9, "{d:less} · ░ ▒ ▓ {h:█} {d:more}"))
    c.append(s.text(hx + 30, hy + 9, f"{{h:{D['total']}}} {{d:contributions this year}}"))

    u = D["user"]
    rows = [
        ("contributions", str(D["total"])),
        ("best streak", f"{D['best']} d"),
        ("current streak", f"{D['cur']} d"),
        None,
        ("repositories", str(u["public_repos"])),
        ("stars (own)", str(D["stars"])),
        ("followers", str(u["followers"])),
        ("on GitHub since", u["created_at"][:4]),
    ]
    kv = [None if r is None else f"{{d:{r[0]:<16}}}{{h:{r[1]}}}" for r in rows]
    c.append(anim(s.window(67, 0, 33, 14, "COUNTERS", kv), .3))
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c.append(s.bar(ROWS - 1, f"{{k:F3}} Stats   updated {now}", "github actions · daily"))
    s.render("".join(c), OUT / "stats.svg", s.stickers("stats", 1.3))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    cache = os.environ.get("LZ_CACHE")  # локально: LZ_CACHE=/tmp/lz.json, чтобы не жечь лимит API
    if cache and os.path.exists(cache):
        D = json.load(open(cache))
    else:
        D = fetch()
        if cache:
            json.dump(D, open(cache, "w"))
    build_header(D)
    build_readme(build_cards(D))
    build_stats(D)
