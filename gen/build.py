#!/usr/bin/env python3
"""ЛЗ-86 видеотерминал: генерирует SVG для профиля GitHub.

  python gen/build.py            # всё: header, карточки проектов, статистика

Данные тянет из публичного API GitHub и страницы contributions.
GITHUB_TOKEN из окружения (если есть) поднимает лимит запросов.
"""
import base64, datetime as dt, html, io, json, os, re, urllib.request
from collections import Counter
from pathlib import Path

from fontTools import subset
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "gen" / "fonts"
OUT = ROOT / "assets"
USER = "leo-need-more-coffee"

# люминофор P3 · янтарь
P = dict(fg="#ffb547", dim="#94591a", hot="#fff2d4", acc="#ff7b30", ink="#140b02")
PLASTIC_HI, PLASTIC_LO, SILK, SILK_HI = "#2b2824", "#1b1917", "#857e72", "#d2c8b6"
FS, CW, CH, BASE = 16, 9.6, 20, 15  # кегль, ширина и высота клетки, базовая линия

PROJECTS = [
    ("flipperzero-bomberduck", "Бомбермен для {h:Flipper Zero}: утка, бомбы, взрывы на монохромном экране 128×64"),
    ("flipperzero-4inrow", "«Четыре в ряд» для {h:Flipper Zero}: классика на дельфине"),
    ("stageflow", "Фреймворк декларативных {h:LLM-пайплайнов} для SaaS: JSON-граф, стадии, политики тенантов"),
    ("stageflow-mcp", "StageFlow через {h:MCP}: агент сам пишет, проверяет и запускает пайплайны"),
    ("element-lazy-android", "Свой форк {h:Element X}: конфиг тем, видеокружки и стикеры в Matrix"),
    ("simple-orm", "Маленькая {h:ORM} поверх sqlite3 без лишней магии"),
]


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
    page = get(f"https://github.com/users/{USER}/contributions", raw=True)
    days = {}
    for m in re.finditer(r'data-date="([\d-]+)" id="(contribution-day-component-\d+-\d+)" data-level="(\d)"', page):
        days[m.group(2)] = [m.group(1), int(m.group(3)), 0]
    for m in re.finditer(r'for="(contribution-day-component-\d+-\d+)"[^>]*>([^<]*)', page):
        n = re.match(r"(\d+) contribution", m.group(2))
        if m.group(1) in days and n:
            days[m.group(1)][2] = int(n.group(1))
    cal = sorted((d, lvl, n) for d, lvl, n in days.values())
    # серии
    best = cur = run = 0
    for _, _, n in cal:
        run = run + 1 if n else 0
        best = max(best, run)
    for _, _, n in reversed(cal[:-1] if cal and not cal[-1][2] else cal):
        if not n:
            break
        cur += 1
    langs = Counter(r["language"] for r in own if r["language"])
    return dict(
        user=user, repos=repos, own=own, by_name={r["name"]: r for r in repos},
        cal=cal, total=sum(n for *_, n in cal), best=best, cur=cur,
        stars=sum(r["stargazers_count"] for r in own), langs=langs.most_common(4),
    )


# ---------------------------------------------------------------- шрифты
def font_face(file, family, text, weight="400"):
    o = subset.Options()
    o.flavor, o.layout_features, o.name_IDs, o.notdef_outline = "woff2", [], [], True
    f = subset.load_font(str(FONTS / file), o)
    s = subset.Subsetter(o)
    s.populate(text=text + " ")
    s.subset(f)
    buf = io.BytesIO()
    subset.save_font(f, buf, o)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"@font-face{{font-family:'{family}';font-weight:{weight};src:url(data:font/woff2;base64,{b64}) format('woff2')}}"


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
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


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
        body = len(line)
        if line and body + 1 + len(wd) > w:
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
.fg{fill:%(fg)s}.dim{fill:%(dim)s}.hot{fill:%(hot)s}.acc{fill:%(acc)s}.ink{fill:%(ink)s}.inkd{fill:#6b3d0c}
.silk{font:700 13px 'LZS',sans-serif;letter-spacing:.34em;fill:%(silk_hi)s}
.silk2{font:500 10px 'LZS',sans-serif;letter-spacing:.26em;fill:%(silk)s}
.a{opacity:0;animation:on 1ms linear forwards}
.boot{animation:off 1ms linear forwards}
.cur{animation:blink 1.06s steps(1) infinite}
.pow{transform-box:view-box;transform-origin:50%% 50%%;animation:pow .5s ease-out both}
.ray{animation:ray 7s linear infinite}
.fl{animation:fl 5s steps(1) infinite}
@keyframes on{to{opacity:1}}
@keyframes off{to{opacity:0}}
@keyframes blink{50%%{opacity:0}}
@keyframes pow{0%%{transform:scale(1,.004);opacity:.2}55%%{transform:scale(1,.004);opacity:1}100%%{transform:scale(1,1)}}
@keyframes ray{from{transform:translateY(-160px)}to{transform:translateY(%(h)spx)}}
@keyframes fl{0%%,100%%{opacity:1}47%%{opacity:.93}49%%{opacity:1}83%%{opacity:.96}}
@media (prefers-reduced-motion:reduce){.a{animation:none;opacity:1}.boot{display:none}.cur,.pow,.ray,.fl{animation:none}.ray{display:none}}
"""


class Screen:
    """Экран ЭЛТ с сеткой клеток; ox/oy — левый верхний угол сетки в SVG."""

    def __init__(self, w, h, ox, oy, cols, rows):
        self.w, self.h, self.ox, self.oy, self.cols, self.rows = w, h, ox, oy, cols, rows
        self.el, self.chars, self.silk_chars = [], set(), set()

    X = lambda s, c: s.ox + c * CW
    Y = lambda s, r: s.oy + r * CH

    def add(self, e):
        self.el.append(e)
        return e

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
            if line is None:
                continue
            g.append(self.text(x + 2, y + 1 + i, line))
        return "\n".join(g)

    def bar(self, row, left, right=""):
        """Инверсная строка меню / статуса."""
        g = [self.rect(0, row, self.cols, 1, P["fg"])]
        g.append(self.text(1, row, left, "inkd"))
        if right:
            g.append(self.text(self.cols - 1 - len(plain(right)), row, right, "inkd"))
        return "\n".join(g)

    def logo(self, col, row, text, w, rows, center=True):
        grid = logo_bitmap(text, w, rows * 2)
        gh, gw = len(grid), len(grid[0])
        col += (w - gw) // 2 if center else 0
        out = []
        for y, line in enumerate(grid):
            c = mix(P["hot"], P["fg"], y / max(1, gh - 1)) if y < gh * .6 else mix(P["fg"], P["acc"], (y - gh * .6) / max(1, gh * .4))
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

    def defs(self, sx, sy, sw, sh, r):
        return f"""<defs>
<clipPath id="scr"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{r}"/></clipPath>
<pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse"><rect y="2" width="4" height="1" fill="#000" opacity=".38"/></pattern>
<pattern id="desk" width="{CW}" height="{CH / 2}" patternUnits="userSpaceOnUse"><rect width="1.6" height="1.6" fill="{P['dim']}" opacity=".45"/></pattern>
<radialGradient id="vig" cx="50%" cy="50%" r="72%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".72"/></radialGradient>
<radialGradient id="tube" cx="50%" cy="45%" r="70%"><stop offset="0" stop-color="#2a1806"/><stop offset="100%" stop-color="{P['ink']}"/></radialGradient>
<linearGradient id="rayg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{P['fg']}" stop-opacity="0"/><stop offset=".5" stop-color="{P['fg']}" stop-opacity=".06"/><stop offset="1" stop-color="{P['fg']}" stop-opacity="0"/></linearGradient>
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".07"/><stop offset=".35" stop-color="#fff" stop-opacity="0"/></linearGradient>
<linearGradient id="plastic" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{PLASTIC_HI}"/><stop offset="1" stop-color="{PLASTIC_LO}"/></linearGradient>
<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>"""

    def render(self, frame, screen_xywh, r, content, silk="", path=None):
        sx, sy, sw, sh = screen_xywh
        style = CSS % dict(fs=FS, h=sh, silk=SILK, silk_hi=SILK_HI, **P)
        style += font_face("PTMono.ttf", "LZ", "".join(self.chars))
        if self.silk_chars:
            style += font_face("Jura.ttf", "LZS", "".join(self.silk_chars), "300 700")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}">
<style>{style}</style>
{self.defs(sx, sy, sw, sh, r)}
{frame}
<g clip-path="url(#scr)">
<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#tube)"/>
<g class="fl"><g filter="url(#glow)">
{content}
</g></g>
<rect class="ray" x="{sx}" y="{sy}" width="{sw}" height="160" fill="url(#rayg)"/>
<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#scan)"/>
<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#vig)"/>
<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="url(#glass)"/>
</g>
<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="{r}" fill="none" stroke="#000" stroke-width="3"/>
{silk}
</svg>"""
        path.write_text(svg)
        print(f"{path.relative_to(ROOT)}  {len(svg) // 1024} КБ")


def anim(el, t, cls="a"):
    return f'<g class="{cls}" style="animation-delay:{t:.2f}s">{el}</g>'


def bezel_frame(w, h, r=26):
    return (f'<rect width="{w}" height="{h}" rx="{r}" fill="url(#plastic)"/>'
            f'<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="{r - 1}" fill="none" stroke="#fff" stroke-opacity=".06" stroke-width="1.5"/>')


# ---------------------------------------------------------------- шапка
def build_header(D):
    COLS, ROWS = 100, 28
    BX, BY, BB, PAD = 30, 30, 78, 20
    sw, sh = COLS * CW + 2 * PAD, ROWS * CH + 2 * PAD
    W, H = int(sw + 2 * BX), int(sh + BY + BB)
    s = Screen(W, H, BX + PAD, BY + PAD, COLS, ROWS)
    c = []

    # загрузка
    boot, t = [], 0.55
    lines = [
        ("{h:ЛЗ-86 ВИДЕОТЕРМИНАЛ}{d:   ПЗУ v2.6.1}", None),
        ("{d:(с) lazy, 1986–2026}", None),
        ("", None),
        ("ПРОВЕРКА ОЗУ ........ ", "640 КБ {h:ОК}"),
        ("СТРОЧНАЯ РАЗВЁРТКА .. ", "15,625 кГц {h:ОК}"),
        ("ПРОЦЕССОР ........... ", "К1810ВМ86 {h:ОК}"),
        ("КОФЕВАРКА ........... ", "12 %  {a:МАЛО, НО СОЙДЁТ}"),
        ("", None),
    ]
    for i, (a, b) in enumerate(lines):
        boot.append(anim(s.text(1, 2 + i, a), t))
        if b:
            boot.append(anim(s.text(1 + len(plain(a)), 2 + i, b), t + .22))
            t += .22
        t += .2
    row = 2 + len(lines)
    pre = "ЗАГРУЗКА profile.sys  "
    boot.append(anim(s.text(1, row, pre + "{d:[}" + " " * 18 + "{d:]}"), t))
    for k in range(18):
        t += .045
        boot.append(anim(s.text(1 + len(pre) + 1 + k, row, "▰" if False else "█"), t))
    t += .15
    boot.append(anim(s.text(1 + len(pre) + 20, row, "{h: 100%}"), t))
    t += .35
    boot.append(anim(s.text(1, row + 2, "{d:C:\\>} profile.exe"), t))
    t += .45
    c.append(f'<g class="boot" style="animation-delay:{t:.2f}s">{"".join(boot)}</g>')

    # рабочий стол
    T = t
    c.append(anim(s.rect(0, 1, COLS, ROWS - 2, "url(#desk)"), T))
    c.append(s.bar(0, "{k:≡ ЛЗ-86}   {k:Ф}айл  {k:П}равка  {k:В}ид  {k:К}офе  {k:С}правка", "{k:lazy}@github  P3"))
    c.append(anim(s.bar(ROWS - 1, "{k:F1} Помощь  {k:F2} Проекты  {k:F3} Статистика  {k:F10} Выход",
                        "ЛЗ-86 · P3 · 1986–2026"), T))

    u = D["user"]
    langs = D["langs"]
    top = max(n for _, n in langs) if langs else 1
    status = "{h:открыт к работе}" if u.get("hireable") else "занят"
    wins = [
        (2, 2, 60, 14, "LEO-NEED-MORE-COFFEE", True, None),
        (64, 2, 34, 14, "ПОЛЬЗОВАТЕЛЬ", False, [
            "{d:ник}      leo-need-more-coffee",
            "{d:имя}      {h:лень}",
            "{d:статус}   " + status,
            "{d:учёба}    РТУ МИРЭА",
            f"{{d:репо}}     {u['public_repos']} · {{a:*}} {D['stars']} · {u['followers']} фолл.",
            None,
            "{d:ДАТЧИКИ}",
            [("кофе     ", "dim")] + s.meter(.12, 12, "acc") + [(" 12 %", "acc")],
            [("лень     ", "dim")] + s.meter(1, 12, "hot") + [(" 100 %", "hot")],
            [("код      ", "dim")] + s.meter(.65, 12) + [(" 65 %", "fg")],
        ]),
        (2, 17, 60, 9, "СЕЙЧАС В РАБОТЕ", False, [
            "{a:▪} {h:StageFlow}: декларативные LLM-пайплайны для SaaS",
            "{a:▪} {h:stageflow-mcp}: агент сам пишет и гоняет пайплайны",
            "{a:▪} игры для {h:Flipper Zero} на C",
            "{a:▪} {h:element-lazy}: Matrix-клиент с темами и кружками",
            None,
            None,
            "{d:lazy@lz86:~$} make coffee",
        ]),
        (64, 17, 34, 9, "ЯЗЫКИ · ПО РЕПО", False,
         [[(f"{n:<11}", "dim")] + s.meter(k / top, 13) + [(f" {k}", "hot")] for n, k in langs]
         + [None, "{d:+ Kotlin · Swift · SQL · Bash}"]),
    ]
    for i, (x, y, w, h, title, active, body) in enumerate(wins):
        if body is None:
            body = []
        el = s.window(x, y, w, h, title, body, active)
        if active:
            el += s.logo(x + 2, y + 2, "ЛЕНЬ", w - 4, 7)
            el += s.text(x + 2, y + 10, "{h:пишу код, пока не кончится кофе}", center_w=w - 4)
            el += s.text(x + 2, y + 12, "{d:Python · C · LLM-пайплайны · Flipper Zero · Matrix}", center_w=w - 4)
        c.append(anim(el, T + .12 + i * .14))
    # мигающий курсор после make coffee
    cx = 2 + 2 + len("lazy@lz86:~$ make coffee") + 1
    c.append(anim(f'<g class="cur">{s.rect(cx, 24, .9, 1, P["fg"])}</g>', T + .7))

    content = f'<g class="pow">{"".join(c)}</g>'

    # нижняя губа корпуса
    ly = BY + sh + BB / 2
    silk = []
    for txt in ("ЛЗ-86", "ВИДЕОТЕРМИНАЛ", "ПИТАНИЕ", "РАЗМАГН.", "P3", "ЗВУК"):
        s.silk_chars.update(txt)
    silk.append(f'<circle cx="{BX + 14}" cy="{ly}" r="4" fill="#8dff6a"/><circle cx="{BX + 14}" cy="{ly}" r="10" fill="#8dff6a" opacity=".18"/>')
    silk.append(f'<text class="silk" x="{BX + 32}" y="{ly + 5}">ЛЗ-86</text>')
    silk.append(f'<text class="silk2" x="{BX + 118}" y="{ly + 4}">ВИДЕОТЕРМИНАЛ</text>')
    kx = W - BX
    for label, lit in reversed([("ПИТАНИЕ", True), ("РАЗМАГН.", False), ("P3", True), ("ЗВУК", False)]):
        kw = 26 + len(label) * 9.5
        kx -= kw
        silk.append(f'<rect x="{kx}" y="{ly - 14}" width="{kw}" height="28" rx="3" fill="url(#plastic)" stroke="#0a0908"/>'
                    f'<rect x="{kx}" y="{ly + 12}" width="{kw}" height="4" rx="2" fill="#090807"/>'
                    f'<circle cx="{kx + 11}" cy="{ly}" r="2.6" fill="{"#d9e6ff" if lit else "#2c2723"}"/>'
                    f'<text class="silk2" style="font-weight:700;fill:{SILK_HI}" x="{kx + 20}" y="{ly + 4}">{label}</text>')
        kx -= 8
    s.render(bezel_frame(W, H), (BX, BY, sw, sh), 16, content, "".join(silk), OUT / "header.svg")


# ---------------------------------------------------------------- карточки проектов
def build_cards(D):
    COLS, ROWS, BX, PAD = 48, 7, 12, 14
    sw, sh = COLS * CW + 2 * PAD, ROWS * CH + 2 * PAD
    W, H = int(sw + 2 * BX), int(sh + 2 * BX)
    for name, desc in PROJECTS:
        r = D["by_name"].get(name, {})
        s = Screen(W, H, BX + PAD, BX + PAD, COLS, ROWS)
        body = wrap(desc, COLS - 4)[:3]
        while len(body) < 3:
            body.append(None)
        lang = r.get("language") or "—"
        meta = f"{{a:*}} {r.get('stargazers_count', 0)}   {{d:язык}} {lang}"
        if r.get("fork"):
            meta += "   {d:форк}"
        body += [None, meta]
        el = s.window(0, 0, COLS, ROWS, name.upper(), body, active=True)
        el += s.text(COLS - 2 - len("[ ОТКРЫТЬ ]"), ROWS - 2, "{h:[ ОТКРЫТЬ ]}")
        s.render(bezel_frame(W, H, 14), (BX, BX, sw, sh), 8, el, path=OUT / f"card-{name}.svg")


# ---------------------------------------------------------------- статистика
def build_stats(D):
    COLS, ROWS, BX, PAD = 103, 14, 14, 20
    sw, sh = COLS * CW + 2 * PAD, ROWS * CH + 2 * PAD
    W, H = int(sw + 2 * BX), int(sh + 2 * BX)
    s = Screen(W, H, BX + PAD, BX + PAD, COLS, ROWS)
    c = []
    cal = D["cal"]
    # сетка недель: столбец = неделя, строка = день недели (вс..сб, как у GitHub)
    first = dt.date.fromisoformat(cal[0][0])
    off = (first.weekday() + 1) % 7
    weeks = (len(cal) + off + 6) // 7
    GLY = {0: ("·", "dim"), 1: ("░", "fg"), 2: ("▒", "fg"), 3: ("▓", "fg"), 4: ("█", "hot")}
    hx, hy = 2 + 5, 3
    body = [None] * 10
    win = s.window(0, 0, 66, 13, "АКТИВНОСТЬ · 52 НЕДЕЛИ", [], active=True)
    c.append(win)
    for i, name in enumerate(["пн", "ср", "пт"]):
        c.append(s.text(2, hy + 1 + i * 2, "{d:" + name + "}"))
    months = "янв фев мар апр май июн июл авг сен окт ноя дек".split()
    last_m = None
    cols_el = [[] for _ in range(weeks)]
    for i, (d, lvl, n) in enumerate(cal):
        k = i + off
        wk, wd = divmod(k, 7)
        date = dt.date.fromisoformat(d)
        if wd == 0 and date.month != last_m and wk < weeks - 2:
            c.append(s.text(hx + wk, hy - 1, "{d:" + months[date.month - 1] + "}"))
            last_m = date.month
        ch, cl = GLY[lvl]
        cols_el[wk].append(s.text(hx + wk, hy + wd, [(ch, cl)]))
    for wk, els in enumerate(cols_el):
        c.append(anim("".join(els), .15 + wk * .018))
    c.append(s.text(hx, hy + 8, "{d:меньше} · ░ ▒ ▓ {h:█} {d:больше}"))
    c.append(s.text(hx + 30, hy + 8, f"{{h:{D['total']}}} {{d:вкладов за год}}"))

    u = D["user"]
    rows = [
        ("вкладов за год", str(D["total"])),
        ("лучшая серия", f"{D['best']} дн."),
        ("текущая серия", f"{D['cur']} дн."),
        None,
        ("репозиториев", str(u["public_repos"])),
        ("звёзд у своих", str(D["stars"])),
        ("фолловеров", str(u["followers"])),
        ("на GitHub с", u["created_at"][:4]),
    ]
    kv = [None if r is None else f"{{d:{r[0]:<16}}}{{h:{r[1]}}}" for r in rows]
    c.append(anim(s.window(68, 0, 35, 13, "СЧЁТЧИКИ", kv), .3))
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c.append(s.bar(ROWS - 1, f"{{k:F3}} Статистика   обновлено {now}", "github actions · раз в сутки"))
    s.render(bezel_frame(W, H, 16), (BX, BX, sw, sh), 10, "".join(c), path=OUT / "stats.svg")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    D = fetch()
    build_header(D)
    build_cards(D)
    build_stats(D)
