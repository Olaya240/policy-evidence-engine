#!/usr/bin/env python3
"""Generate the architecture diagrams as Excalidraw scene files.

The scenes in docs/diagrams/src are the drawing; there is no PNG in the
repository, because a picture nobody can regenerate rots. Render one when you
need an image:

    python3 scripts/render_diagrams.py
    # then, with the Excalidraw MCP server:
    excalidraw.render(path="docs/diagrams/src/arch-01-system-overview.excalidraw",
                      format="svg", saveTo="docs/diagrams/arch-01-system-overview.svg")

The look follows the P2-bridge component map: hand-drawn Virgil type, rough 2 px
strokes, one Open Color accent per family, accent-coloured card titles over dark
body text, no frames, and dashed callouts carrying the caveat.

Layout rules the engine enforces, so a figure cannot drift when a line changes:

  * **A left rail owns every band heading.** Cards start after the rail, so no
    connector can ever cross a heading; the numbered rail also gives the sheet a
    reading order at a glance.
  * **A column grid, not free placement.** Cards snap to cells and may span
    columns; every band's cards share one height, so rows read as shelves.
  * **Lanes live in the gutters.** A cross-band arrow drops into the gutter above
    its target band, runs sideways, and enters the card from the top.
  * **A card is exactly as tall as its text**, and a card that would clip its own
    text fails the build instead of shipping.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams" / "src"

CHAR = 0.64  # Virgil advance width as a fraction of font size
LINE = 1.25
PAD = 16
TITLE = 15
BODY = 13


@dataclass(frozen=True)
class Theme:
    background: str = "#ffffff"
    ink: str = "#1e1e1e"
    body: str = "#343a40"
    muted: str = "#868e96"
    faint: str = "#adb5bd"
    font: int = 1  # Virgil, the hand-drawn face
    title: int = 28
    subtitle: int = 15
    heading: int = 13
    body_size: int = BODY
    label: int = 11
    stroke: float = 2
    arrow: float = 2
    roughness: int = 1
    corner: int = 12
    palettes: dict[str, tuple[str, str]] = field(default_factory=dict)

    def colors(self, name: str) -> tuple[str, str]:
        return self.palettes[name]


# Open Color: one stroke per family, one very light tint for its cards.
SKETCH = Theme(palettes={
    "green": ("#ebfbee", "#2f9e44"),
    "orange": ("#fff4e6", "#f08c00"),
    "pink": ("#fff0f6", "#d6336c"),
    "blue": ("#e7f5ff", "#1971c2"),
    "violet": ("#f3f0ff", "#7048e8"),
    "grey": ("#f8f9fa", "#495057"),
    "sand": ("#fdf2e3", "#a05a00"),
    "red": ("#fff5f5", "#e03131"),
})


@dataclass
class Card:
    key: str
    band: int
    col: int
    span: int
    title: str
    detail: str
    palette: str


@dataclass
class Band:
    index: int
    heading: str
    note: str = ""
    cards: list[Card] = field(default_factory=list)
    height_hint: float | None = None
    heading_y: float = 0.0
    top: float = 0.0
    height: float = 0.0

    @property
    def lane(self) -> float:
        return self.top - 22

    @property
    def bottom(self) -> float:
        return self.top + self.height


@dataclass
class Link:
    source: str
    target: str
    label: str = ""
    dashed: bool = False
    color: str | None = None


class Figure:
    """A scene built from bands of grid-placed cards."""

    def __init__(self, columns: list[float], *, x0: int = 110, rail: int = 270,
                 gutter: int = 40, theme: Theme = SKETCH, scale: float = 1.0) -> None:
        # A poster-scale sheet multiplies type and padding together, so a wider
        # grid keeps the same characters per card instead of shrinking the text.
        self.scale = scale
        self.title_size = TITLE * scale
        self.body_size = BODY * scale
        self.pad = PAD * scale
        self.theme = theme if scale == 1.0 else Theme(**{
            **theme.__dict__,
            "title": round(theme.title * scale),
            "subtitle": round(theme.subtitle * scale),
            "heading": round(theme.heading * scale),
            "body_size": round(theme.body_size * scale),
            "label": round(theme.label * scale),
        })
        self.columns = columns
        self.x0 = x0
        self.rail = rail
        self.gutter = gutter
        self.grid_x = x0 + rail
        self.right = self.grid_x + sum(columns) + gutter * (len(columns) - 1)
        self.elements: list[dict] = []
        self.bands: list[Band] = []
        self.cards: dict[str, Card] = {}
        self.links: list[Link] = []
        self._ids: set[str] = set()
        self._rects: dict[str, dict] = {}
        self._obstacles: list[tuple[float, float, float, float]] = []
        self._post: list = []
        self._footer: tuple[str, str, str, float] | None = None
        self._notes: tuple[str, str] | None = None
        self._unconnected_ok: dict[str, str] = {}
        self._bottom = 0.0
        self.app_state = {"gridSize": None, "viewBackgroundColor": theme.background}

    # -- geometry ---------------------------------------------------------
    def col_x(self, col: int) -> float:
        return self.grid_x + sum(self.columns[:col]) + self.gutter * col

    def col_w(self, col: int, span: int = 1) -> float:
        return sum(self.columns[col:col + span]) + self.gutter * (span - 1)

    # -- primitives -------------------------------------------------------
    def _id(self, prefix: str) -> str:
        while True:
            candidate = f"{prefix}-{random.randrange(16**8):08x}"
            if candidate not in self._ids:
                self._ids.add(candidate)
                return candidate

    def _base(self, kind: str, x: float, y: float, w: float, h: float, **extra) -> dict:
        theme = self.theme
        element = {
            "id": self._id(kind),
            "type": kind,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "angle": 0,
            "strokeColor": theme.ink,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": theme.stroke,
            "strokeStyle": "solid",
            "roughness": theme.roughness,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": random.randrange(1, 2**31),
            "version": 1,
            "versionNonce": random.randrange(1, 2**31),
            "isDeleted": False,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
        }
        element.update(extra)
        self.elements.append(element)
        return element

    @staticmethod
    def measure(lines: list[str], size: float) -> float:
        return max((len(line) for line in lines), default=0) * size * CHAR

    def text(self, x: float, y: float, value: str, size: float | None = None,
             color: str | None = None, width: float | None = None) -> dict:
        theme = self.theme
        size = theme.body_size if size is None else size
        color = theme.body if color is None else color
        lines = value.split("\n")
        # The declared box is wider than the measured advance on purpose: the
        # renderer squeezes glyphs when the box is narrower than the real text,
        # and Virgil is wider than the 0.64 estimate the layout guards use.
        w = width if width is not None else self.measure(lines, size) * 1.16 + 8
        h = len(lines) * size * LINE
        return self._base(
            "text", x, y, w, h,
            text=value, originalText=value, fontSize=size, fontFamily=theme.font,
            textAlign="left", verticalAlign="top", lineHeight=LINE,
            autoResize=True, containerId=None, strokeColor=color,
        )

    # -- structure --------------------------------------------------------
    def band(self, heading: str, note: str = "", height: float | None = None) -> int:
        self.bands.append(Band(index=len(self.bands) + 1, heading=heading,
                               note=note, height_hint=height))
        return len(self.bands) - 1

    def card(self, band: int, col: int, span: int, title: str, detail: str = "",
             palette: str = "grey") -> str:
        key = f"{band}:{col}:{span}:{title}"
        spec = Card(key, band, col, span, title, detail, palette)
        self.cards[key] = spec
        self.bands[band].cards.append(spec)
        return key

    def link(self, source: str, target: str, label: str = "",
             dashed: bool = False, color: str | None = None) -> None:
        self.links.append(Link(source, target, label, dashed, color))

    def unconnected_ok(self, key: str, reason: str) -> None:
        """Declare a card that is listed, not routed, and say why."""
        self._unconnected_ok[key] = reason

    def after_layout(self, draw) -> None:
        """Draw once the bands have y positions (charts, axes)."""
        self._post.append(draw)

    # -- header, legend, callout -----------------------------------------
    def header(self, title: str, subtitle: str, index: int,
               total: int | None = None) -> None:
        t = self.theme
        # The sheet index is a property of the set, not of one builder call.
        total = len(FIGURES) if total is None else total
        self.text(self.x0, 44, title, t.title, t.ink)
        self.text(self.x0, 86, subtitle, t.subtitle, t.muted)
        self.text(self.right - 74, 90, f"{index:02d} / {total:02d}", t.label, t.faint)
        # One pale rule closes the title block, so the sheet starts where it starts.
        self._base("line", self.x0, 168, self.right - self.x0, 0,
                   points=[[0, 0], [self.right - self.x0, 0]],
                   strokeColor="#dee2e6", strokeWidth=1, roughness=0)

    def legend(self, items: list[tuple[str, str]], y: int = 128) -> None:
        size = self.theme.label
        widths = [24 + self.measure([label], size) + 34 for _, label in items]
        x = self.right - sum(widths) + 34
        for (palette, label), width in zip(items, widths):
            fill, stroke = self.theme.colors(palette)
            self._base("rectangle", x, y + 2, 11, 11, strokeColor=stroke,
                       backgroundColor=fill, strokeWidth=1.5,
                       roundness={"type": 3, "value": 3})
            self.text(x + 17, y - 1, label, size, self.theme.muted)
            x += width

    def callout(self, title: str, detail: str, palette: str, width: float,
                pad: int = 16) -> None:
        """Dashed footer box, drawn after the bands so it sits below them."""
        self._footer = (title, detail, palette, width)

    def notes(self, left: str, right: str = "scripts/render_diagrams.py") -> None:
        self._notes = (left, right)

    # -- layout -----------------------------------------------------------
    def card_height(self, spec: Card) -> float:
        lines = spec.detail.split("\n") if spec.detail else []
        return (self.pad * 2 + self.title_size * LINE
                + len(lines) * self.body_size * LINE)

    def _layout(self, top: int, gap: int) -> None:
        y = float(top)
        for band in self.bands:
            heights = [self.card_height(spec) for spec in band.cards]
            band.height = band.height_hint if band.height_hint is not None else max(heights, default=0.0)
            band.heading_y = y
            band.top = y
            y = band.bottom + gap
        self._bottom = self.bands[-1].bottom if self.bands else float(top)

    def _draw_band_headings(self) -> None:
        t = self.theme
        for band in self.bands:
            x = self.x0
            self.text(x, band.heading_y + 1, f"{band.index:02d}", t.label, t.faint)
            assert self.measure([band.heading], t.heading) <= self.rail - 14, (
                f"heading '{band.heading}' is wider than the {self.rail}px rail")
            heading = self.text(x, band.heading_y + 19, band.heading.upper(),
                                t.heading, t.muted)
            self._obstacles.append((heading["x"], heading["y"],
                                    heading["width"], heading["height"]))
            if band.note:
                note = self.text(x, band.heading_y + 38, band.note, t.label, t.faint)
                self._obstacles.append((note["x"], note["y"],
                                        note["width"], note["height"]))

    def _draw_cards(self) -> None:
        t = self.theme
        for band in self.bands:
            for spec in band.cards:
                w = self.col_w(spec.col, spec.span)
                fill, stroke = t.colors(spec.palette)
                x, y, h = self.col_x(spec.col), band.top, band.height
                body_lines = spec.detail.split("\n") if spec.detail else []
                need = max(self.measure([spec.title], self.title_size),
                           self.measure(body_lines, self.body_size)) + self.pad * 2
                assert need <= w + 0.5, (
                    f"'{spec.title}' wants {need:.0f}px but its cell is {w:.0f}px")
                rect = self._base(
                    "rectangle", x, y, w, h, strokeColor=stroke, backgroundColor=fill,
                    roundness={"type": 3, "value": t.corner},
                )
                self._rects[spec.key] = rect
                self._obstacles.append((x, y, w, h))
                block = (self.title_size * LINE
                         + len(body_lines) * self.body_size * LINE)
                ty = y + (h - block) / 2
                self.text(x + self.pad, ty, spec.title, self.title_size, stroke)
                if body_lines:
                    self.text(x + self.pad, ty + self.title_size * LINE,
                              spec.detail, self.body_size, t.body)

    def _draw_footer(self) -> None:
        t = self.theme
        if self._footer:
            title, detail, palette, width = self._footer
            fill, stroke = t.colors(palette)
            lines = detail.split("\n") if detail else []
            h = 32 + t.heading * LINE + len(lines) * t.body_size * LINE
            y = self._bottom + 46
            self._base("rectangle", self.x0, y, width, h, strokeColor=stroke,
                       backgroundColor=fill, strokeStyle="dashed",
                       roundness={"type": 3, "value": t.corner})
            self.text(self.x0 + PAD, y + PAD - 2, title, t.heading, stroke)
            if detail:
                self.text(self.x0 + PAD, y + PAD + t.heading * LINE - 1, detail,
                          t.body_size, t.body)
            self._bottom = y + h
        if self._notes:
            left, right = self._notes
            self.text(self.x0, self._bottom + 34, left, t.label, t.faint)
            self.text(self.right - self.measure([right], t.label) - 8,
                      self._bottom + 34, right, t.label, t.faint)

    # -- arrows -----------------------------------------------------------
    @staticmethod
    def _overlaps(a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float], margin: float = 6) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (ax + aw + margin <= bx or bx + bw + margin <= ax
                    or ay + ah + margin <= by or by + bh + margin <= ay)

    def _seat(self, w: float, h: float,
              candidates: list[tuple[float, float]]) -> tuple[float, float]:
        """First candidate position that touches no card, heading or label."""
        for cx, cy in candidates:
            if not any(self._overlaps((cx, cy, w, h), other) for other in self._obstacles):
                self._obstacles.append((cx, cy, w, h))
                return cx, cy
        cx, cy = candidates[0]
        self._obstacles.append((cx, cy, w, h))
        return cx, cy

    def _arrow(self, points: list[tuple[float, float]], source: str, target: str,
               color: str, dashed: bool) -> None:
        ox = min(p[0] for p in points)
        oy = min(p[1] for p in points)
        w = max(max(p[0] for p in points) - ox, 0.5)
        h = max(max(p[1] for p in points) - oy, 0.5)
        arrow = self._base(
            "arrow", ox, oy, w, h,
            points=[[p[0] - ox, p[1] - oy] for p in points],
            strokeColor=color, strokeWidth=self.theme.arrow,
            strokeStyle="dashed" if dashed else "solid",
            startBinding={"elementId": self._rects[source]["id"], "focus": 0, "gap": 8},
            endBinding={"elementId": self._rects[target]["id"], "focus": 0, "gap": 8},
            startArrowhead=None, endArrowhead="arrow", elbowed=False,
        )
        self._rects[source]["boundElements"].append({"type": "arrow", "id": arrow["id"]})
        self._rects[target]["boundElements"].append({"type": "arrow", "id": arrow["id"]})

    def _draw_links(self) -> None:
        t = self.theme
        for link in self.links:
            a, b = self._rects[link.source], self._rects[link.target]
            sa, sb = self.cards[link.source], self.cards[link.target]
            stroke = b["strokeColor"]
            color = link.color or (stroke if stroke.startswith("#") else t.muted)
            x_overlap = (min(a["x"] + a["width"], b["x"] + b["width"])
                         - max(a["x"], b["x"]))
            if sa.band == sb.band:
                forward = b["x"] > a["x"]
                y = min(a["y"], b["y"]) + min(a["height"], b["height"]) / 2
                start = (a["x"] + (a["width"] if forward else 0), y)
                end = (b["x"] + (0 if forward else b["width"]), y)
                self._arrow([start, end], link.source, link.target, color, link.dashed)
                if link.label:
                    w = self.measure([link.label], t.label) + 8
                    lx = (start[0] + end[0]) / 2 - w / 2
                    gap = abs(end[0] - start[0])
                    # A label wider than the gap would print across both cards, so
                    # a short hop carries its label above the band instead.
                    if gap < w + 16:
                        lx = (start[0] + end[0]) / 2 - w / 2
                        lx, ly = self._seat(w, t.label * LINE,
                                            [(lx, a["y"] - 26), (lx, y - 22), (lx, y + 8)])
                    else:
                        lx, ly = self._seat(w, t.label * LINE, [(lx, y - 22), (lx, y + 8)])
                    self.text(lx, ly, link.label, t.label, t.muted)
                continue

            below = sb.band > sa.band
            if below and x_overlap >= 90:
                # A wide card above a narrow one: drop straight in, no lane.
                sx = min(max(b["x"] + b["width"] / 2, a["x"] + 24),
                         a["x"] + a["width"] - 24)
                points = [(sx, a["y"] + a["height"]), (sx, b["y"])]
                seat = "side"
            else:
                lane = self.bands[sb.band].lane if below else self.bands[sb.band].bottom + 20
                sx = a["x"] + a["width"] / 2
                tx = b["x"] + b["width"] / 2
                start = (sx, a["y"] + (a["height"] if below else 0))
                end = (tx, b["y"] if below else b["y"] + b["height"])
                points = [start, (sx, lane), (tx, lane), end]
                seat = "lane"
            self._arrow(points, link.source, link.target, color, link.dashed)
            if not link.label:
                continue
            w = self.measure([link.label], t.label) + 8
            if seat == "lane":
                lane = points[1][1]
                lx = (points[1][0] + points[2][0]) / 2 - w / 2
                lx, ly = self._seat(w, t.label * LINE, [(lx, lane - 20), (lx, lane + 6)])
            else:
                lx = points[0][0] + 12
                ly = (points[0][1] + points[-1][1]) / 2 - t.label * LINE / 2
                lx, ly = self._seat(w, t.label * LINE, [(lx, ly), (lx - w - 24, ly)])
            self.text(lx, ly, link.label, t.label, t.muted)

    # -- output -----------------------------------------------------------
    def save(self, name: str, top: int = 210, gap: int = 56) -> Path:
        self._layout(top, gap)
        self._draw_band_headings()
        self._draw_cards()
        for draw in self._post:
            draw()
        self._draw_links()
        self._draw_footer()
        # A box nobody points at and that points at nothing is decoration, not
        # information. Fail the build rather than ship a floating card.
        orphans = {key: spec for key, spec in self.cards.items()
                   if not self._rects[key]["boundElements"]}
        undeclared = [spec.title for key, spec in orphans.items()
                      if key not in self._unconnected_ok]
        assert not undeclared, (
            f"{name}: {len(undeclared)} card(s) with no connector: "
            + ", ".join(sorted(undeclared)))
        for key in orphans:
            print(f"  {name}: listed, not routed — {self.cards[key].title}: "
                  f"{self._unconnected_ok[key]}")
        OUT.mkdir(parents=True, exist_ok=True)
        scene = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": self.elements,
            "appState": self.app_state,
            "files": {},
        }
        path = OUT / f"{name}.excalidraw"
        path.write_text(json.dumps(scene, indent=1) + "\n", encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# 1. System overview
# ---------------------------------------------------------------------------
def system_overview() -> Figure:
    fig = Figure([330, 330, 330], rail=240)
    fig.header("System overview",
               "One Vite app, three FastAPI services, loopback only, synthetic data", 1)
    fig.legend([("green", "demo"), ("orange", "handover"), ("pink", "comparison"),
                ("grey", "process state")], y=126)

    b = fig.band("Client", "one browser tab, no account")
    browser = fig.card(b, 0, 1, "Browser", "fetch wrapper, hash router\nno auth, no cookie", "grey")
    vite = fig.card(b, 1, 2, "Vite dev server  :5174",
                    "proxies /api -> :8081 and /demo-api -> :8083; :8082 is not proxied",
                    "sand")

    b = fig.band("Services", "three FastAPI apps, one port each")
    demo = fig.card(b, 0, 1, "Demo API  :8083", "/demo-api\nscenarios, sessions, challenge", "green")
    legacy = fig.card(b, 1, 1, "Handover API  :8081", "/api\ninvestigations, claims, history", "orange")
    compare = fig.card(b, 2, 1, "Comparison API  :8082", "/policy-comparisons\nstateless, CORS only :5174", "pink")

    b = fig.band("Process", "what each port actually runs")
    demo_impl = fig.card(b, 0, 1, "policy_demo_api", "policy_evidence_demo decides;\nthe API projects a graph and plans", "green")
    legacy_impl = fig.card(b, 1, 1, "app/main + app/engine", "five fixed claims, SQLite;\nprovider boundary in front", "orange")
    compare_impl = fig.card(b, 2, 1, "policy_api", "validate pair, compare,\nvalidate result, persist nothing", "pink")

    b = fig.band("State", "the only things that outlive a request")
    sessions = fig.card(b, 0, 1, "In-memory sessions", "one dict per process,\nbounded event log", "grey")
    sqlite = fig.card(b, 1, 1, "SQLite", "data/prototype.sqlite3\nhandover only, git-ignored", "sand")
    nothing = fig.card(b, 2, 1, "Nothing else", "the comparison API holds\nno state between calls", "grey")

    fig.link(browser, vite)
    fig.link(vite, demo)
    fig.link(vite, legacy)
    fig.link(vite, compare)
    fig.link(demo, demo_impl)
    fig.link(legacy, legacy_impl)
    fig.link(compare, compare_impl)
    fig.link(demo_impl, sessions, "events", dashed=True)
    fig.link(legacy_impl, sqlite, "read / write", dashed=True)
    fig.link(compare_impl, nothing, "persists nothing", dashed=True)

    fig.callout("The boundary this design crosses",
                "No provider call, no vector store, no authentication. A loopback listener bounds blast radius; it is\n"
                "not an authorization boundary, and nothing here is production software.",
                "violet", fig.right - fig.x0)
    fig.notes("Read from README.md, backend/app/main.py, policy_api.py, policy_demo_api.py, vite.config.ts on 2026-10-30.")
    return fig


# ---------------------------------------------------------------------------
# 2. Backend module map
# ---------------------------------------------------------------------------
def backend_modules() -> Figure:
    fig = Figure([330, 330, 330, 330], rail=240)
    fig.header("Backend module map",
               "Three entry points over one shared seam; graph, planner and evaluation stay offline", 2)
    fig.legend([("green", "demo"), ("orange", "handover"), ("pink", "comparison"),
                ("blue", "core"), ("sand", "graph"), ("violet", "safety")], y=126)

    b = fig.band("Entry points", "one FastAPI app per port")
    demo = fig.card(b, 0, 1, "policy_demo_api.py", ":8083  /demo-api\nscenario, challenge, history", "green")
    api = fig.card(b, 1, 1, "policy_api.py", ":8082  /policy-comparisons\none POST, no session", "pink")
    main = fig.card(b, 2, 1, "app/main.py", ":8081  /api\ninvestigations, claims", "orange")

    b = fig.band("Seam", "what each entry point builds")
    evidence = fig.card(b, 0, 1, "policy_evidence_demo.py", "the scenario corpus and the\nrecompute after a challenge", "green")
    runner = fig.card(b, 1, 1, "policy_mock_provider_runner.py", "called by policy_evidence_demo;\nrefuses an unknown shape", "pink")
    orchestration = fig.card(b, 2, 1, "policy_orchestration.py", "orchestrate_policy_comparison\nthe candidate to pair mapping", "pink")
    engine = fig.card(b, 3, 1, "app/engine.py", "AssessmentEngine and status;\ndeterministic, uncalibrated", "orange")

    b = fig.band("Shared core", "shared by demo and comparison")
    contract = fig.card(b, 0, 1, "policy_proposal_contract.py", "builds and normalizes the\nenvelope, sha256 of sources", "blue")
    compare = fig.card(b, 1, 1, "policy_compare.py", "validate pair, compare,\nvalidate result, citations", "blue")
    adapter = fig.card(b, 2, 1, "policy_candidate_adapter.py", "PolicyCandidateGenerator\nprotocol, fake adapter", "blue")
    models = fig.card(b, 3, 1, "app/models.py", "Record, Claim, Evidence,\nStatus, Stance, review state", "orange")

    b = fig.band("Records", "storage, visibility, sessions")
    session = fig.card(b, 0, 1, "policy_demo_session.py", "InMemoryDemoSessionManager\nbounded log, reset, history", "grey")
    store = fig.card(b, 1, 1, "app/store.py", "explicit init, BEGIN IMMEDIATE\nrevision check on challenge", "orange")
    access = fig.card(b, 2, 1, "app/access.py", "visible_records filters\nbefore anything is returned", "orange")

    b = fig.band("Graph and planner", "reached only from the :8083 challenge route")
    demo_graph = fig.card(b, 0, 1, "policy_demo_graph.py", "the scenario projection:\npair + investigation to nodes", "green")
    graph = fig.card(b, 1, 1, "policy_dependency_graph.py", "immutable nodes and edges,\nhashes validated on build", "sand")
    propagation = fig.card(b, 2, 1, "policy_challenge_propagation.py", "plan_challenge_impact\nproposes, never mutates", "sand")

    b = fig.band("Wire", "one attempt, one origin")
    safety = fig.card(b, 0, 1, "app/provider_safety.py", "allowlist, 16 KiB request,\nsingle-flight gate", "violet")
    transport = fig.card(b, 1, 1, "app/httpx_transport.py", "pinned origin, no redirect,\n4 KiB response, 20 s", "violet")
    mock = fig.card(b, 2, 1, "app/mock_provider.py", "in-process assessor, the\nonly provider wired today", "violet")

    b = fig.band("Evaluation", "offline, 21 gold cases")
    evaluate = fig.card(b, 0, 1, "app/evaluate.py", "runs the cases through the\nsame engine, then scores", "violet")
    protocol = fig.card(b, 1, 1, "evaluation/protocol_v1.py", "attempt scheduling, metric\nstates, minimum denominators", "violet")

    fig.link(demo, evidence)
    fig.link(api, orchestration)
    fig.link(main, engine)
    fig.link(evidence, contract)
    fig.link(orchestration, compare, "imports")
    fig.link(engine, models, "imports")
    # The challenge route's import is stated in this band's note rather than drawn:
    # a drop from column 0 would run through the seam, core and records cards.
    fig.link(demo_graph, graph, "projects")
    fig.link(graph, propagation)
    fig.link(safety, transport)
    fig.link(evaluate, protocol)
    # Every remaining arrow is a real import, short enough to stay in one gutter.
    fig.link(evidence, runner, "calls")
    fig.link(orchestration, adapter)
    fig.link(adapter, compare)
    fig.link(evaluate, mock)
    fig.unconnected_ok(session, "called by :8083 three bands up; routing it would cross the core")
    fig.unconnected_ok(store, "called by :8081 and the evaluator, both outside its band")
    fig.unconnected_ok(access, "called by :8081 three bands up; routing it would cross the core")

    fig.callout("Where the layer boundary now sits",
                "app/* serves :8081 while policy_* serves :8082 and :8083, so the two product paths share no runtime module.\n"
                "policy_demo_graph.py is the only module that knows both layers: it projects the demo's pair and investigation\n"
                "into typed nodes, while policy_dependency_graph imports nothing from the scenario layer. The challenge route\n"
                "re-projects and re-plans per request, so the graph is reached but never stored. Arrows are the imports that\n"
                "define a layer, not the full import graph.",
                "grey", fig.right - fig.x0)
    fig.notes("Read from the import statements in backend/ and backend/app/ on 2026-10-30.")
    return fig


# ---------------------------------------------------------------------------
# 3. Demo proposal flow
# ---------------------------------------------------------------------------
def demo_flow() -> Figure:
    fig = Figure([280, 280, 280, 280, 280], rail=240)
    fig.header("Demo proposal flow",
               "One synthetic policy pair on :8083, from scenario to honest abstention, then a reviewer challenge", 3)
    fig.legend([("green", "scenario"), ("pink", "proposal seam"), ("blue", "validation"),
                ("orange", "challenge"), ("grey", "session")], y=126)

    b = fig.band("Pipeline", "one pass per request")
    s1 = fig.card(b, 0, 1, "1  scenario", "policy_evidence_demo\nscheduling / uniform", "green")
    s2 = fig.card(b, 1, 1, "2  envelope", "build_proposal_request\nbounded, sha256 of sources", "pink")
    s3 = fig.card(b, 2, 1, "3  candidate", "DeterministicMockAdapter\nfrozen, request-id bound", "pink")
    s4 = fig.card(b, 3, 1, "4  normalize", "normalize_proposal_response\nstrict, no repairs", "pink")
    s5 = fig.card(b, 4, 1, "5  validate", "compare_candidate\n+ validate_result", "blue")

    b = fig.band("Challenge", "a reviewer names a passage")
    challenge = fig.card(b, 0, 1, "challenge", "side, passage id, exact\nquote checked first", "orange")
    audit = fig.card(b, 1, 1, "applicability audit", "scope state per version,\nGROUNDED only from source", "orange")
    recompute = fig.card(b, 2, 2, "recompute",
                         "drop the challenged baseline citation, then re-run the pair:\n"
                         "a one-sided change is INCONCLUSIVE with reasons, never a flip",
                         "orange")

    b = fig.band("Session", "the one place a run is kept")
    sess = fig.card(b, 0, 2, "InMemoryDemoSessionManager",
                    "scenario-bound, bounded event log;\nreset clears it, nothing reaches disk",
                    "grey")
    history = fig.card(b, 2, 1, "GET /session/{id}/history",
                       "ordered events with the\nrelation before and after", "grey")

    fig.link(s1, s2)
    fig.link(s2, s3)
    fig.link(s3, s4)
    fig.link(s4, s5)
    fig.link(s5, challenge, "challenge posted", dashed=True)
    fig.link(challenge, audit)
    fig.link(audit, recompute)
    fig.link(recompute, sess, "one event appended", dashed=True)
    fig.link(sess, history)

    fig.callout("The one sentence to take away",
                "The challenge lane re-uses the pair from step 1 and lowers a relation to INCONCLUSIVE, never to a contradiction.\n"
                "The graph summary and impact plan the challenge now returns are computed beside this lane and never feed it.\n"
                "Nothing is persisted, so nothing can drift out of sync with the source text.",
                "green", fig.right - fig.x0)
    fig.notes("Read from policy_evidence_demo.py, policy_proposal_contract.py, policy_mock_provider_runner.py, policy_compare.py on 2026-10-30.")
    return fig


# ---------------------------------------------------------------------------
# 4. Provider boundary
# ---------------------------------------------------------------------------
def provider_boundary() -> Figure:
    fig = Figure([300, 300, 300, 300], rail=280)
    fig.header("Provider boundary",
               "The only path a policy could leave the machine, and every point that refuses first", 4)
    fig.legend([("violet", "guard"), ("green", "released"), ("red", "refusal")], y=126)

    # Each band is one stage: the guard in the middle, its refusals either side.
    b = fig.band("Projection", "before anything is encoded")
    bad_context = fig.card(b, 0, 1, "invalid_context",
                           "a record the projection\nis not allowed to read", "red")
    project = fig.card(b, 1, 2, "allowlisted projection",
                       "the bounded envelope goes in; the serializer\nemits approved fields, never the raw record", "violet")
    too_large = fig.card(b, 3, 1, "request_too_large",
                         "over 16 KiB, counted\nbefore the wire", "red")

    b = fig.band("Guard", "no budget, no call")
    disabled = fig.card(b, 0, 1, "provider_disabled",
                        "no budget configured,\nso no call at all", "red")
    gate = fig.card(b, 1, 2, "budget and quota gate",
                    "disabled until budgeted; the attempt is reserved\nand a failure does not refund it", "violet")
    no_boundary = fig.card(b, 3, 1, "mandatory_boundary_required",
                           "a transport or path\nthat skips the guard", "red")

    b = fig.band("Wire", "one attempt, one origin")
    concurrent = fig.card(b, 0, 1, "concurrent_request",
                          "a second attempt while\none is still open", "red")
    flight = fig.card(b, 1, 2, "single-flight dispatch",
                      "https origin and path are pinned, so the caller\nchooses neither; a second in-flight call is refused", "violet")
    timeout = fig.card(b, 3, 1, "invalid_timeout",
                       "outside 0 < t <= 20 s,\nnever a fallback", "red")

    b = fig.band("Response", "bounded before parsed")
    response_big = fig.card(b, 0, 1, "response_too_large",
                            "a body that would\nexceed 4 KiB", "red")
    cap = fig.card(b, 1, 2, "response cap",
                   "read in 1 KiB chunks before JSON is parsed;\nan oversized body is cut off, not truncated", "violet")
    malformed = fig.card(b, 3, 1, "malformed_response",
                         "a shape the parser\nwill not accept", "red")

    b = fig.band("Parsed", "shape-checked, then normalised")
    returned = fig.card(b, 1, 2, "parsed candidate",
                        "no retry and no partial\nresult reaches the caller", "green")

    fig.link(project, bad_context)
    fig.link(project, too_large)
    fig.link(project, gate)
    fig.link(gate, disabled)
    fig.link(gate, no_boundary)
    fig.link(gate, flight)
    fig.link(flight, concurrent)
    fig.link(flight, timeout)
    fig.link(flight, cap)
    fig.link(cap, response_big)
    fig.link(cap, malformed)
    fig.link(cap, returned)

    fig.callout("After any refusal",
                "The attempt is spent and its quota is not refunded, so a failure cannot quietly become a loop; and the error\n"
                "carries a code, so provider text and response headers never reach the caller. The mock adapter sits behind the\n"
                "same boundary, so the demo exercises these refusals instead of bypassing them, and a real provider would\n"
                "inherit every check without a call site changing.",
                "violet", fig.right - fig.x0)
    fig.notes("Constants read from backend/app/provider_safety.py on 2026-10-30: 16 KiB request, 4 KiB response, 20 s timeout, 17 attempts, $5.00.")
    return fig


# ---------------------------------------------------------------------------
# 5. Test map
# ---------------------------------------------------------------------------
def test_map() -> Figure:
    fig = Figure([310, 310, 310, 310], rail=240)
    fig.header("Test map",
               "481 tests in 20 modules; bar length is test count, not coverage of behaviour", 5)
    fig.legend([("orange", "handover"), ("pink", "comparison"), ("green", "demo"),
                ("violet", "protocol"), ("grey", "launcher")], y=126)

    groups = [
        ("Handover app", "engine, api, store  \u00b7  66", "orange", [
            ("test_engine", 31), ("test_api", 22), ("test_evaluation", 7),
            ("test_experiment_control", 5), ("test_store_path_safety", 1),
        ]),
        ("Comparison core", "the policy_* seam  \u00b7  89", "pink", [
            ("test_policy_proposal_contract", 27), ("test_policy_compare", 26),
            ("test_policy_candidate_adapter", 15), ("test_policy_api", 11),
            ("test_policy_orchestration", 10),
        ]),
        ("Demo on :8083", "sessions and the adapter  \u00b7  76", "green", [
            ("test_policy_demo_api", 38), ("test_session_concurrency", 14),
            ("test_policy_evidence_demo", 13), ("test_policy_mock_provider_runner", 11),
        ]),
        ("Protocol and safety", "offline, one wire  \u00b7  200", "violet", [
            ("test_policy_dependency_graph", 57), ("test_policy_challenge_propagation", 32),
            ("test_protocol_v1", 64), ("test_provider_safety", 25),
            ("test_httpx_transport", 22),
        ]),
        ("Launcher", "scripts/, Windows only  \u00b7  50", "grey", [("test_launcher", 50)]),
    ]

    scale = 10.4
    bar_x = fig.grid_x + 330
    row_height = 26
    bands = []
    for heading, note, palette, modules in groups:
        index = fig.band(heading, note, height=len(modules) * row_height)
        bands.append((fig.bands[index], palette, modules))

    def draw_chart() -> None:
        t = fig.theme
        # Totals belong in the rail, next to the group they count.
        top = bands[0][0].top - 36
        bottom = bands[-1][0].bottom
        for tick in (0, 20, 40, 60):
            x = bar_x + tick * scale
            fig._base("line", x, top, 0, bottom - top,
                      points=[[0, 0], [0, bottom - top]],
                      strokeColor=t.faint, strokeWidth=1, strokeStyle="dotted",
                      roughness=0)
            fig.text(x - 5, top - 18, str(tick), t.label, t.faint)
        for band, palette, modules in bands:
            fill, stroke = t.colors(palette)
            for row, (name, count) in enumerate(modules):
                y = band.top + row * row_height
                fig.text(fig.grid_x, y + 4, name, t.label, t.body)
                fig._base("rectangle", bar_x, y + 6, count * scale, 13,
                          strokeColor=stroke, backgroundColor=fill,
                          strokeWidth=1.5, roundness={"type": 3, "value": 4})
                fig.text(bar_x + count * scale + 9, y + 4, str(count), t.label, stroke)

    fig.after_layout(draw_chart)

    fig.callout("What the counts cannot show",
                "62 tests assert nothing but raise, 15 of them in the contract module, and only 68 of 481 carry a docstring,\n"
                "so behaviour has to be read from the body. Two fail away from Windows: launcher identity is ntpath and\n"
                "PowerShell. And no test reaches the UI at all, which is why the hook-order crash survived until the review.",
                "grey", fig.right - fig.x0)

    fig.notes("Counts come from parsing backend/tests on 2026-10-30; they describe size, not defensibility.")
    return fig


# ---------------------------------------------------------------------------
# 6. Four stacks
# ---------------------------------------------------------------------------
def four_stacks() -> Figure:
    """The four programs in the repo, ordered by what imports what."""
    fig = Figure([330, 330, 330, 330], rail=250)
    fig.header("Four stacks, one repo",
               "What each program owns, what it keeps, and the imports that cross between them", 6)
    fig.legend([("orange", "A  handover"), ("pink", "B  comparison"),
                ("green", "D  demo"), ("sand", "C  graph")], y=126)

    b = fig.band("Entry point", "the process a request lands in")
    a = fig.card(b, 0, 1, "app/main.py  :8081",
                 "POST /investigations, challenge;\nGET history; /docs still served", "orange")
    bb = fig.card(b, 1, 1, "policy_api.py  :8082",
                  "one POST /policy-comparisons;\nno session, no storage", "pink")
    d = fig.card(b, 2, 1, "policy_demo_api.py  :8083",
                 "scenario, session, challenge;\nVite proxies /demo-api", "green")
    c = fig.card(b, 3, 1, "no route of its own",
                 "reached from :8083 per challenge;\nprojected, planned, not stored", "sand")

    b = fig.band("What it owns", "the code that decides")
    ao = fig.card(b, 0, 1, "app/engine.py",
                  "record -> evidence -> claim;\nfive fixed hypotheses", "orange")
    bo = fig.card(b, 1, 1, "policy_compare.py",
                  "pair validation, code-point\ncitations, INCONCLUSIVE result", "pink")
    do = fig.card(b, 2, 1, "policy_evidence_demo.py",
                  "three hotel scenarios and the\npost-challenge recompute", "green")
    co = fig.card(b, 3, 1, "policy_dependency_graph.py",
                  "8 node types, 7 edge types;\nbounded impact planner", "sand")

    b = fig.band("What it keeps", "what survives the request")
    ak = fig.card(b, 0, 1, "SQLite, revisions",
                  "claim_versions + history rows;\nrevision CAS on challenge", "orange")
    bk = fig.card(b, 1, 1, "nothing at all",
                  "stateless: the response is\nthe only thing that exists", "pink")
    dk = fig.card(b, 2, 1, "a dict in this process",
                  "20 events per session, pop(0)\npast that; reset clears", "green")
    ck = fig.card(b, 3, 1, "nothing, by design",
                  "immutable and in memory;\nno snapshot has been stored", "sand")

    b = fig.band("What the code proves", "tests per stack, parsed not run")
    at = fig.card(b, 0, 1, "66 tests",
                  "engine, api, store, safety\nsplit across modules", "orange")
    bt = fig.card(b, 1, 1, "89 tests",
                  "contracts, adapter, api,\norchestration", "pink")
    dt = fig.card(b, 2, 1, "76 tests",
                  "demo api, sessions, corpus,\nrunner", "green")
    ct = fig.card(b, 3, 1, "89 tests",
                  "graph 57, planner 32;\nevery test imports the demo", "sand")

    # Each stack is a column, read top to bottom.
    for entry, owns, keeps, tests in ((a, ao, ak, at), (bb, bo, bk, bt),
                                      (d, do, dk, dt), (c, co, ck, ct)):
        fig.link(entry, owns)
        fig.link(owns, keeps)
        fig.link(keeps, tests)

    # Arrows between stacks, each pointing the way the dependency runs.
    fig.link(do, bo, "imports 5 modules", dashed=True)
    fig.link(do, co, "projects the graph")

    fig.callout("The arrow that is no longer there",
                "policy_dependency_graph used to import the hotel corpus, so the abstract layer sat on the scenario layer. The\n"
                "projection now lives in policy_demo_graph.py, which imports both sides; the graph module imports neither the demo\n"
                "nor its constants. Stack C is reached from :8083, so neither the graph nor the planner is an island — but nothing\n"
                "imports app/*, and app/* imports nothing outside its own package. That handover isolation is a different decision,\n"
                "not this one, and it is still open.",
                "grey", fig.right - fig.x0)
    fig.notes("Read from the import statements in backend/ on 2026-10-31; test counts parsed from backend/tests.")
    return fig


# ---------------------------------------------------------------------------
# 7. The three seams
# ---------------------------------------------------------------------------
def seams() -> Figure:
    """What breaks at the joins, what it costs, and what the fix forces."""
    fig = Figure([400, 400, 400], rail=250)
    fig.header("The three seams",
               "Three joins where claim and mechanism part: what the seam is, what it costs, and what fixing it forces", 7)
    fig.legend([("red", "seam"), ("sand", "cost"), ("blue", "fix"),
                ("violet", "forced decision")], y=126)

    b = fig.band("The seam", "where the claim and the mechanism part")
    s1 = fig.card(b, 0, 1, "identity blind to the graph",
                  "_snapshot_identity commits to comparison\nid, version digests and challenge ids;\nno edges, no claims, no citations", "red")
    s2 = fig.card(b, 1, 1, "the recompute is a script",
                  "recompute_investigation_after_challenge\nreturns a literal INCONCLUSIVE, not a\nderivation from the plan or the graph", "red")
    s3 = fig.card(b, 2, 1, "the audit trail is a ring buffer",
                  "20 events per session, pop(0) past\nthat, events.clear() on reset; the\ndocstring still says append-only", "red")

    b = fig.band("What it costs", "the failure a user would meet")
    c1 = fig.card(b, 0, 1, "two graphs, one hash",
                  "edge and claim tampering cannot be\ndetected by the token the cache and\nthe snapshot are pinned to", "sand")
    c2 = fig.card(b, 1, 1, "no path from plan to result",
                  "the plan names the affected nodes,\nthe recompute ignores them, and the\nUI reads as derivation", "sand")
    c3 = fig.card(b, 2, 1, "no evidence surface",
                  "a lost or cleared event leaves nothing\nto compare against, so completeness\nis unprovable rather than false", "sand")

    b = fig.band("The fix", "one change per seam, each with a guard")
    f1 = fig.card(b, 0, 1, "commit edges and claims",
                  "identity covers edges, claims and\ncitations, so a recovery append\nproduces a new hash", "blue")
    f2 = fig.card(b, 1, 1, "derive it, or label it",
                  "compute the relation from the plan,\nor mark the response SCRIPTED in the\nAPI and the UI", "blue")
    f3 = fig.card(b, 2, 1, "journal outside the session",
                  "the write path stops being the demo's\ndict; reset appends a tombstone\ninstead of clearing", "blue")

    b = fig.band("What each fix forces", "not a refactor: a decision")
    q1 = fig.card(b, 0, 1, "one canonical node key",
                  "every cache, snapshot and projection\nmust agree on it", "violet")
    q2 = fig.card(b, 1, 1, "who owns reassessment",
                  "the demo's script, or the planner's\nconsumer, and on which evidence", "violet")
    q3 = fig.card(b, 2, 1, "who owns the write path",
                  "the demo becomes a consumer of the\nrecord, not the record itself", "violet")

    for seam, cost, fix, forced in ((s1, c1, f1, q1), (s2, c2, f2, q2),
                                    (s3, c3, f3, q3)):
        fig.link(seam, cost, "cost")
        fig.link(cost, fix, "so")
        fig.link(fix, forced)

    fig.callout("The decision that outranks the other two",
                "Stack A files a claim as (investigation, claim, version) with a JSON body; stack C files it as a content-addressed\n"
                "node id. That key decides both the identity seam and the journal seam: make the node key canonical and A's\n"
                "before/after history has to be re-referenced or lost; keep the blob key and typed edges never land. The recompute\n"
                "seam forces a separate owner choice, and waiting on it costs copy, not a migration.",
                "grey", fig.right - fig.x0)
    fig.notes("Read from backend/policy_dependency_graph.py, policy_demo_session.py, policy_evidence_demo.py, app/store.py on 2026-10-31.")
    return fig



# ---------------------------------------------------------------------------
# 8. Claim identity fork
# ---------------------------------------------------------------------------
def claim_identity() -> Figure:
    """The one choice in the tree that a later change cannot undo."""
    fig = Figure([430, 430], rail=290)
    fig.header("Claim identity",
               "The one irreversible choice: what a claim is keyed by, and what each key can still prove", 8)
    fig.legend([("orange", "A  handover"), ("sand", "C  graph"),
                ("blue", "node id wins"), ("red", "blob key wins")], y=126)

    b = fig.band("The two keys", "what a stored claim is filed under")
    key_a = fig.card(b, 0, 1, "(investigation, claim, version)",
                     "a JSON blob per row, plus a\nhistory row per version", "orange")
    key_c = fig.card(b, 1, 1, "content-addressed claim id",
                     "claim:{comparison}:{candidate}: the id\nderives from what the claim is about", "sand")

    b = fig.band("What it decides", "not the schema: the queries it allows")
    hist = fig.card(b, 0, 1, "for history",
                    "before/after rows resolve, the CAS\ncompares whole JSON, 409 on stale", "orange")
    graph = fig.card(b, 1, 1, "for propagation",
                     "typed edges resolve, 8 node types\nand bounded impact plans", "sand")

    b = fig.band("Two ways out", "each keeps one half and gives up the other")
    opt1 = fig.card(b, 0, 1, "Option 1: node id canonical",
                    "survives: edges, propagation and an\nidentity that can see edges\n"
                    "costs: every stored before/after is\nre-referenced as an event over a node\n"
                    "id, and the revision CAS is rebuilt", "blue")
    opt2 = fig.card(b, 1, 1, "Option 2: blob key canonical",
                    "survives: A's history and its CAS\n"
                    "costs: the graph stays a view of a\ncorpus it cannot key, so propagation\n"
                    "never reaches a stored conclusion", "red")

    fig.link(key_a, hist)
    fig.link(key_c, graph)
    fig.link(hist, opt1, "if the quote survives")
    fig.link(graph, opt1)
    fig.link(hist, opt2)
    fig.link(graph, opt2, "if it does not")

    fig.callout("The test that decides, and what waiting costs",
                "Can every stored before/after be re-expressed as an event over a node id, without guessing at a quote and\n"
                "without losing which passage was cited? If yes, take Option 1. If no, Option 2 is the honest choice and the graph\n"
                "stays a view. Deciding now costs one migration; deciding later costs either the audit trail or the graph, because\n"
                "both are already written in the other key.",
                "grey", fig.right - fig.x0)
    fig.notes("Read from app/store.py (claim_versions, history) and policy_dependency_graph.py (node ids) on 2026-10-31.")
    return fig


# ---------------------------------------------------------------------------
# 9. System atlas
# ---------------------------------------------------------------------------
def system_atlas() -> Figure:
    """Every stage of the system on one sheet.

    Each band reads left to right as one sentence: context, input, mechanism,
    what that mechanism refuses, and what it emits. The mechanism column is the
    spine, so following it down traces a single request from a question to a
    stored event; the last three bands are the parts outside that path.
    """
    fig = Figure([480] * 5, rail=360, gutter=48, scale=1.28)
    fig.header(
        "System atlas",
        "One request through every layer, and the parts beside it: what enters, what computes, what refuses, what is stored",
        9,
    )
    fig.legend([
        ("grey", "request & state"), ("blue", "evidence"),
        ("pink", "candidate seam"), ("sand", "graph"),
        ("green", "challenge lane"), ("violet", "gate"),
        ("red", "refusal"),
    ], y=126)

    # (heading, rail note, five cards: context, input, mechanism, refusal, output)
    stages: list[tuple[str, str, list[tuple[str, str, str]]]] = [
        ("Runtime", "what actually runs on the host", [
            ("Three processes", "8081 handover, 8082 compare,\n8083 demo; one host,\nno shared state", "grey"),
            ("Vite :5174", "serves the React app;\nproxies /api and /demo-api", "sand"),
            ("Demo API :8083", "policy_demo_api; sessions\nlive in process memory,\nnot on disk", "green"),
            ("No auth", "no account, role or tenant;\nloopback is not a\nsecurity boundary", "red"),
            ("What runs", "three FastAPI apps and\none Vite dev server", "violet"),
        ]),
        ("Intent", "one question, one kind of answer", [
            ("Policy reviewer", "operations or audit,\nnot the policy owner", "grey"),
            ("Two policy versions", "one document, v1 and v2,\nboth synthetic", "grey"),
            ("Change question", "did v2 change an obligation,\nand where does the change\nland in the document?", "blue"),
            ("Out of scope", "legal force, precedence,\nreal employees", "red"),
            ("Answer scope", "provenance and reachability,\nnot correctness", "blue"),
        ]),
        ("Admission", "a request becomes bounded", [
            ("Browser or curl", "same-origin fetch;\nno cookie, no key", "grey"),
            ("JSON body", "content type checked\nbefore parsing", "grey"),
            ("Bounded reader", "32 KiB cap, streamed and\ncounted before the parse;\nthe body is read once", "violet"),
            ("413 / 415 / 422", "oversize, wrong type,\ninvalid field", "red"),
            ("Parsed model", "allowlisted scenario and\ndepartment only", "violet"),
        ]),
        ("Session", "one scenario, one generation", [
            ("Session id", "32 lowercase hex;\nnever guessed", "grey"),
            ("Scenario binding", "fixed when the session\nis created", "grey"),
            ("Generation gate", "reset bumps the generation;\na write from the old one\nis refused", "grey"),
            ("404 / 409 / 422", "missing, reset, or\nscenario mismatch", "red"),
            ("Accepted context", "session and scenario\nagree", "grey"),
        ]),
        ("Pair", "checked once, then frozen", [
            ("Pair JSON", "older and newer text,\nplus passages", "blue"),
            ("Same document", "distinct version ids;\nboth allowlisted", "blue"),
            ("validate_policy_pair", "freezes types, ids, passages;\nsha256 per version; rejects\nsame-version pairs", "blue"),
            ("invalid_types / ids", "wrong shape, wrong id,\nthe same version twice", "red"),
            ("Frozen PolicyPair", "digest triple per version;\nno raw bytes", "blue"),
        ]),
        ("Envelope", "what a candidate may see", [
            ("Frozen pair", "validated, immutable", "pink"),
            ("Request envelope", "request id, sha256\nsources, bounded text", "pink"),
            ("Deterministic adapter", "fake candidate; no model,\nno network, no credential\nis consulted", "pink"),
            ("contract refused", "unknown key, unbounded\nor unsafe text", "red"),
            ("Raw candidate", "relation, citations,\nreasoning", "pink"),
        ]),
        ("Normalize", "strict: no repairs, no invention", [
            ("Raw candidate", "untrusted shape", "pink"),
            ("Exact keys", "citation fields and spans\nchecked, not fixed", "pink"),
            ("normalize_proposal_response", "canonical citations; empty\nhints kept; any mismatch\nis refused, never repaired", "pink"),
            ("invalid_citation", "no silent correction,\nno default passage", "red"),
            ("Normalized candidate", "citations carry exact\noffsets and quotes", "pink"),
        ]),
        ("Compare", "assertions stay assertions", [
            ("Normalized candidate", "a proposal, not a finding", "pink"),
            ("Claims to test", "requirement, precedence,\nimpact", "blue"),
            ("compare_candidate", "checks requirement, precedence\nand impact; keeps caller\nclaims asserted", "blue"),
            ("one-sided change", "refused, never flipped", "red"),
            ("Case result", "classification pinned;\nreasons listed", "blue"),
        ]),
        ("Validate", "the only output the system signs", [
            ("Case result", "with citations and\nreasons", "blue"),
            ("Enums and invariants", "exact values; no policy\nmutation", "blue"),
            ("validate_result", "exact enums, citation\nequality, no policy mutation;\nthe result stays INCONCLUSIVE", "blue"),
            ("positive finding", "impossible by contract", "red"),
            ("INCONCLUSIVE", "human_review_required;\nreasons sorted and bounded", "blue"),
        ]),
        ("Challenge", "names the rule and the place", [
            ("Reviewer challenge", "server-built; no caller\nquote or side", "green"),
            ("Department + target", "passage named by the\nreviewer", "grey"),
            ("Applicability audit", "scope state per version;\nGROUNDED only where the\nsource says so", "green"),
            ("unknown department", "422; not in the\nscenario allowlist", "red"),
            ("Challenged baseline", "older passage targeted;\nbuild id pinned", "green"),
        ]),
        ("Recompute", "what the demo actually computes", [
            ("Pair + challenge", "plus the initial result", "green"),
            ("Drop the citation", "the challenged baseline is\nremoved, not re-reasoned", "green"),
            ("recompute (scripted)", "literal INCONCLUSIVE with\nthree fixed reasons; not\nderived from the plan", "green"),
            ("not derivation", "the impact plan never\nfeeds this result", "red"),
            ("One event", "relation before and after,\nbounded reasons", "green"),
        ]),
        ("Project", "a view, rebuilt per request", [
            ("Pair + result", "challenge and audit too", "sand"),
            ("Derived ids", "node, passage and citation\nids recomputed", "sand"),
            ("project_policy_graph", "projects pair, result and\nchallenge into 8 node types;\nrebuilt, never stored", "sand"),
            ("invalid_citation", "budget, cycle, ownership,\nunknown applicability", "red"),
            ("Typed snapshot", "8 node and 7 edge types;\none comparison", "sand"),
        ]),
        ("Plan", "reachability, not truth", [
            ("ChallengeRequest", "comparison, challenge,\ntarget, category", "sand"),
            ("Target", "the challenged\napplicability condition", "sand"),
            ("plan_challenge_impact", "typed traversal with explicit\nlimits; every path states\nwhy it stopped", "sand"),
            ("UNCHANGED scoped", "complete search only;\na limit names the gap", "red"),
            ("Impact plan", "states, paths, blockers,\ncompleteness", "sand"),
        ]),
        ("Record", "compute first, write second", [
            ("Graph + plan", "both built before the\nsession write", "grey"),
            ("Event", "scenario-bound,\ngeneration-checked", "grey"),
            ("Ring buffer", "20 events per session;\nthe oldest is dropped\nwithout a record", "grey"),
            ("503 graph_unavailable", "no event recorded", "red"),
            ("Response", "recompute, graph, plan,\nhistory count", "grey"),
        ]),
        ("Prove", "what it can and cannot claim", [
            ("481 tests", "20 modules; no skips,\nno markers", "violet"),
            ("Gates", "suite, typecheck,\ndiagram guard, health", "violet"),
            ("800 pass / 2 fail", "the suite's two failures are\nWindows-only launcher tests;\nweakening them is not a fix", "violet"),
            ("Not claimed", "audit completeness,\nsemantic support, auth", "red"),
            ("Guarantees", "provenance, determinism,\nbounded planning", "violet"),
        ]),
        ("Siblings", "the parts outside the demo path", [
            ("Handover :8081", "React page, SQLite,\ninvestigation records", "orange"),
            ("Comparison :8082", "pair in, proposal out;\n512 KB cap; not proxied\nby Vite", "pink"),
            ("Shared vocabulary", "policy_compare and the\nproposal contract, used\nby both policy surfaces", "blue"),
            ("No cross-import", "app/* and policy_*\nshare no runtime module", "red"),
            ("Isolation", "three apps, three ports,\nno shared session", "grey"),
        ]),
        ("Stores", "four regimes, one blocked", [
            ("SQLite", "handover claims and\nrevisions; CAS 409", "orange"),
            ("Session dict", "demo only; lost on\nprocess exit", "green"),
            ("No graph store", "the projection is rebuilt\non every request; the\npersistence contract is design", "sand"),
            ("Blocked gate", "vectors exist; database\nexecution is BLOCKED", "red"),
            ("Not tamper-evident", "no audit log, no backup\nclaim", "grey"),
        ]),
    ]

    spine: list[str] = []
    for index, (heading, note, cards) in enumerate(stages):
        band = fig.band(heading, note)
        keys = [fig.card(band, col, 1, title, detail, palette)
                for col, (title, detail, palette) in enumerate(cards)]
        for left, right in zip(keys, keys[1:]):
            fig.link(left, right)
        if 1 <= index <= 14:
            spine.append(keys[2])
    for above, below in zip(spine, spine[1:]):
        fig.link(above, below)

    fig.callout(
        "How to read this sheet, and the five laws it encodes",
        "Each band is one stage. Read it left to right: context, input, mechanism, refusal, output. Horizontal arrows order\n"
        "the reading, not a dependency; the middle column is the spine, and following it down traces one request from a\n"
        "question to a stored event. A refusal is a designed outcome, not a missing arrow. Bands 02–15 are that path; 16–17\n"
        "stores beside it. The laws: a citation is exact text, never a summary; a challenge narrows, never confirms; every\n"
        "traversal names its limit; the candidate generator sees a projection, not state; INCONCLUSIVE is the only signed\n"
        "classification. Everything below the mechanism column is a contract, and every contract here refuses something.",
        "grey", fig.right - fig.x0,
    )
    fig.notes("Read from backend/*.py, backend/app/*.py, tests and AGENTS.md on 2026-10-31; case counts from the local suite.")
    return fig


FIGURES = {
    "arch-01-system-overview": system_overview,
    "arch-02-backend-modules": backend_modules,
    "arch-03-demo-proposal-flow": demo_flow,
    "arch-04-provider-boundary": provider_boundary,
    "arch-05-test-map": test_map,
    "arch-06-four-stacks": four_stacks,
    "arch-07-three-seams": seams,
    "arch-08-claim-identity": claim_identity,
    "arch-09-system-atlas": system_atlas,
}


def main() -> None:
    random.seed(20261030)
    for name, builder in FIGURES.items():
        path = builder().save(name)
        print(path.relative_to(OUT.parents[2]))


if __name__ == "__main__":
    main()
