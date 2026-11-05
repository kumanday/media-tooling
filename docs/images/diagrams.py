"""Draw the README overview diagrams as SVG, then render each to PNG.

    python3 docs/images/diagrams.py            # writes *.svg and *.png beside this file

PNG rendering uses rsvg-convert (``brew install librsvg``). Edit the layouts below
and re-run; the README embeds the PNGs.
"""

from __future__ import annotations

import shutil
import subprocess
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
SANS = "Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "Menlo, SFMono-Regular, Consolas, monospace"

INK = "#1D2433"
MUTED = "#5B6475"
LINE = "#98A2B3"
CARD = "#FFFFFF"
NODE = "#F7F8FA"
STROKE = "#D0D5DD"
# one accent per stage or skill group
ACCENT = {
    "source": "#64748B",
    "process": "#2F6FEB",
    "plan": "#7C4DDB",
    "assemble": "#0E9384",
    "deliver": "#2E9E48",
    "create": "#D97706",
    "narration": "#D97706",
    "motion": "#DB2777",
}


class Svg:
    def __init__(self, width: int, height: int, title: str) -> None:
        self.w, self.h = width, height
        self.parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="{SANS}">',
            f"<title>{escape(title)}</title>",
            "<defs><marker id=\"arrow\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" markerWidth=\"7\" markerHeight=\"7\" "
            f"orient=\"auto-start-reverse\"><path d=\"M0,0 L10,5 L0,10 z\" fill=\"{LINE}\"/></marker></defs>",
            f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="18" fill="{CARD}" stroke="{STROKE}"/>',
        ]

    def text(self, x: float, y: float, s: str, *, size: int = 15, weight: int = 400, color: str = INK,
             mono: bool = False, anchor: str = "start", italic: bool = False) -> None:
        family = f' font-family="{MONO}"' if mono else ""
        style = ' font-style="italic"' if italic else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                          f'text-anchor="{anchor}"{family}{style}>{escape(s)}</text>')

    def rect(self, x: float, y: float, w: float, h: float, *, fill: str = NODE, stroke: str = STROKE, rx: int = 10,
             dash: bool = False) -> None:
        d = ' stroke-dasharray="6 5"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"'
                          f' stroke-width="1.2"{d}/>')

    def node(self, x: float, y: float, w: float, title: str, lines: list[str], accent: str, *, code: bool | int = True,
             dash: bool = False) -> float:
        """A box with an accent bar, a title and lines; the first `code` lines are commands. Returns its height."""
        mono_lines = len(lines) if code is True else int(code)
        h = 48 + 22 * len(lines)
        self.rect(x, y, w, h, dash=dash)
        self.parts.append(f'<rect x="{x}" y="{y + 10}" width="4" height="{h - 20}" rx="2" fill="{accent}"/>')
        self.text(x + 18, y + 29, title, size=19, weight=600)
        for i, line in enumerate(lines):
            self.text(x + 18, y + 54 + 22 * i, line, size=16, color=MUTED, mono=i < mono_lines)
        return h

    def path(self, d: str, *, dash: bool = False, arrow: bool = True) -> None:
        extra = ' stroke-dasharray="6 5"' if dash else ""
        end = ' marker-end="url(#arrow)"' if arrow else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.6"{extra}{end}/>')

    def save(self, name: str) -> Path:
        out = HERE / f"{name}.svg"
        out.write_text("\n".join(self.parts + ["</svg>"]) + "\n", encoding="utf-8")
        return out


def processing_flow() -> Path:
    s = Svg(1600, 800, "Media processing flow")
    s.text(36, 48, "Media processing flow", size=24, weight=700)
    s.text(36, 74, "From raw recordings to a checked, finished video. Your agent runs the commands; you review the plan and the cut.",
           size=17, color=MUTED)
    col = [36 + i * 316 for i in range(5)]
    w = 264
    rows = [188, 308, 428]
    stages = [("1  Source media", "source"), ("2  Process", "process"), ("3  Plan", "plan"),
              ("4  Assemble", "assemble"), ("5  Check and deliver", "deliver")]
    for x, (label, key) in zip(col, stages):
        s.text(x, 128, label.upper(), size=15, weight=700, color=ACCENT[key])

    # 1 source -> 2 process, row by row
    sources = [("Spoken audio and video", "podcasts, interviews, talks"), ("Silent screen recordings", "UI demos, walkthroughs"),
               ("Screenshots and stills", "slides, photos, captures")]
    processed = [("Transcripts and subtitles", ["media-subtitle", "media-pack-transcript"]),
                 ("Contact sheets", ["media-contact-sheet", "media-timeline-view"]),
                 ("Indexed stills", ["inventory, by the ingest skill"])]
    for y, (title, note), (ptitle, plines) in zip(rows, sources, processed):
        h = s.node(col[0], y, w, title, [note], ACCENT["source"], code=False)
        s.node(col[1], y, w, ptitle, plines, ACCENT["process"], code=not plines[0].startswith("inventory"))
        s.path(f"M{col[0] + w},{y + h / 2} L{col[1] - 4},{y + h / 2}")

    # 3 plan: one box the processed material feeds
    top, bottom = rows[0], rows[2] + 92
    s.rect(col[2], top, w, bottom - top)
    s.parts.append(f'<rect x="{col[2]}" y="{top + 10}" width="4" height="{bottom - top - 20}" rx="2" fill="{ACCENT["plan"]}"/>')
    s.text(col[2] + 18, top + 29, "Plan with your agent", size=19, weight=600)
    items = [("Inventory and analysis notes", "what the footage contains"), ("Shot list and storyboard", "strongest clips, sequence"),
             ("EDL or rough-cut spec", "edl.json: ranges, overlays")]
    for i, (title, note) in enumerate(items):
        y = top + 68 + i * 98
        s.parts.append(f'<line x1="{col[2] + 18}" y1="{y - 18}" x2="{col[2] + w - 18}" y2="{y - 18}" stroke="{STROKE}"/>')
        s.text(col[2] + 18, y + 6, title, size=17, weight=600)
        s.text(col[2] + 18, y + 30, note, size=16, color=MUTED)
    for y in rows:
        s.path(f"M{col[1] + w},{y + 46} L{col[2] - 4},{y + 46}")

    # 4 assemble
    rough_h = s.node(col[3], rows[0], w, "Rough cut", ["media-rough-cut", "cards, holds, clip extracts"], ACCENT["assemble"],
                     code=1)
    edit_y = rows[1]
    edit_h = s.node(col[3], edit_y, w, "Edited render", ["media-edl-render", "grade, fades, loudness,", "overlays, subtitles"],
                    ACCENT["assemble"], code=1)
    s.path(f"M{col[2] + w},{rows[0] + rough_h / 2} L{col[3] - 4},{rows[0] + rough_h / 2}")
    s.path(f"M{col[2] + w},{edit_y + 46} L{col[3] - 4},{edit_y + 46}")

    # 5 check and deliver, with the iterate loop back to the plan
    check_h = s.node(col[4], edit_y, w, "Self-check", ["media-verify", "cuts, duration, grade, pops"], ACCENT["deliver"], code=1)
    s.path(f"M{col[3] + w},{edit_y + 46} L{col[4] - 4},{edit_y + 46}")
    fin_y = rows[2] + 40
    s.node(col[4], fin_y, w, "Finished video", ["renders/<name>.mp4", "or FCPXML for Resolve"], ACCENT["deliver"], code=1)
    s.path(f"M{col[4] + w / 2},{edit_y + check_h} L{col[4] + w / 2},{fin_y - 4}")
    loop_y = 162
    s.path(f"M{col[4] + w / 2},{edit_y} L{col[4] + w / 2},{loop_y} L{col[2] + w / 2},{loop_y} L{col[2] + w / 2},{top - 4}",
           dash=True)
    s.text(col[3] + w / 2, loop_y - 8, "iterate on the plan", size=15, color=MUTED, italic=True, anchor="middle")

    # create band: material made for the piece, cut in by the edited render
    band_y = 616
    s.rect(24, band_y, 1552, 148, fill="#FFF8EB", stroke="#F5D9A8", rx=14)
    s.text(col[0], band_y + 40, "CREATE NEW MATERIAL", size=15, weight=700, color=ACCENT["create"])
    s.text(col[0], band_y + 66, "Made for the piece", size=17, color=MUTED)
    s.text(col[0], band_y + 88, "when the footage alone", size=17, color=MUTED)
    s.text(col[0], band_y + 110, "isn't enough", size=17, color=MUTED)
    made = [("Narration", ["media-tts", "media-tts-frames"]), ("Motion graphics", ["HyperFrames, or raea (pilot)"]),
            ("Generated footage", ["media-generated", "via TTV providers"]), ("Music and effects", ["media-video-music"])]
    for x, (title, lines) in zip(col[1:], made):
        s.node(x, band_y + 32, w, title, lines, ACCENT["create"], code=0 if title == "Motion graphics" else 1 if title == "Generated footage" else True)
    s.path(f"M{col[3] + w / 2},{band_y} L{col[3] + w / 2},{edit_y + edit_h + 4}")
    s.text(col[3] + w / 2 + 10, band_y - 14, "cut into the edit", size=15, color=MUTED, italic=True)
    return s.save("media-processing-flow")


def skills_system() -> Path:
    s = Svg(1600, 900, "Agent skills system")
    s.text(36, 48, "Agent skills system", size=24, weight=700)
    s.text(36, 74, "You ask for an outcome. The project's AGENTS.md points the agent at the skills, and each skill runs the media-* commands.",
           size=17, color=MUTED)

    # row 1: prompt -> agent <- linked skills
    y1 = 106
    s.node(36, y1, 340, "You", ["“Make a 3-minute recap of", "this session”"], ACCENT["source"], code=False)
    s.node(405, y1, 400, "Your coding agent", ["Claude Code, Codex, Antigravity,", "or any agent that reads skills"],
           ACCENT["process"], code=False)
    s.node(1100, y1, 464, "Skills on this machine", ["media-tooling-link-skills  →  ~/.agents/skills,",
                                                     "~/.claude/skills, ~/.gemini/…  (+ your private skills)"],
           ACCENT["process"], code=False)
    s.path(f"M376,{y1 + 46} L401,{y1 + 46}")
    s.path(f"M1100,{y1 + 46} L809,{y1 + 46}")
    s.text(955, y1 + 34, "discovered from", size=15, color=MUTED, italic=True, anchor="middle")

    # row 2: init writes AGENTS.md, which the agent reads
    y2 = 236
    s.node(36, y2, 340, "media-tooling-init", ["sets up $PROJECT_DIR"], ACCENT["plan"], code=True)
    s.node(405, y2, 400, "Project AGENTS.md", ["which skills and commands to use;", "keep all work in the project"],
           ACCENT["plan"], code=False)
    s.path(f"M376,{y2 + 46} L401,{y2 + 46}")
    s.path(f"M605,{y1 + 92} L605,{y2 - 4}")
    s.text(615, y2 - 14, "reads", size=15, color=MUTED, italic=True)

    # row 3: the orchestrator over three groups; narration is used directly
    y3 = 372
    s.node(36, y3, 1139, "media-render-pipeline", ["end-to-end: transcribe → plan → EDL → render → self-check → iterate;",
                                                   "delegates each step to the skills below"], ACCENT["deliver"], code=False)
    s.path(f"M605,{y2 + 92} L605,{y3 - 4}")
    s.text(615, y3 - 14, "finished video from raw media", size=15, color=MUTED, italic=True)
    s.path(f"M805,{y2 + 46} L1383,{y2 + 46} L1383,{528 - 4}")
    s.text(1094, y2 + 34, "or a single job, directly", size=15, color=MUTED, italic=True, anchor="middle")

    groups = [
        ("Ingest and transcripts", ACCENT["process"], [
            ("media-corpus-ingest", "inventory a mixed corpus of media", False),
            ("media-subtitle-pipeline", "transcripts, SRT subtitles, audio", False)]),
        ("Assembly and finishing", ACCENT["assemble"], [
            ("media-rough-cut-assembly", "EDL renders, grading, loudness,", False),
            ("", "self-check, quick rough cuts", False)]),
        ("Motion graphics", ACCENT["motion"], [
            ("media-motion-graphics", "storyboards, HyperFrames, TTV shots", False),
            ("media-motion-raea", "the same on raea (pilot)", False),
            ("manim-video", "math animation (optional extra)", True)]),
        ("Narration", ACCENT["narration"], [
            ("media-tts", "ElevenLabs voiceover and timings", False),
            ("media-teleprompter", "prompter timed to a reference take", False)]),
    ]
    y4, gw = 528, 361
    for i, (title, accent, skills) in enumerate(groups):
        x = 36 + i * (gw + 28)
        s.rect(x, y4, gw, 262)
        s.parts.append(f'<rect x="{x}" y="{y4}" width="{gw}" height="6" rx="3" fill="{accent}"/>')
        s.text(x + 20, y4 + 38, title.upper(), size=15, weight=700, color=accent)
        row = 0
        for name, note, optional in skills:
            if not name:  # a second note line for the previous skill
                s.text(x + 20, y4 + 100 + 70 * (row - 1) + 22, note, size=16, color=MUTED)
                continue
            yy = y4 + 74 + 70 * row
            s.text(x + 20, yy, name, size=17, weight=700, mono=True, color=MUTED if optional else INK)
            s.text(x + 20, yy + 26, note, size=16, color=MUTED, italic=optional)
            row += 1
        if i < 3:
            s.path(f"M{x + gw / 2},{y3 + 92} L{x + gw / 2},{y4 - 4}")

    y5 = 818
    s.rect(36, y5, 1528, 56, fill="#F2F4F7")
    s.text(56, y5 + 35, "Each skill runs media-* commands (see Toolkit commands) and writes everything into $PROJECT_DIR.",
           size=17, color=INK)
    return s.save("agent-skills")


def main() -> None:
    rsvg = shutil.which("rsvg-convert")
    for svg in (processing_flow(), skills_system()):
        if rsvg:
            subprocess.run([rsvg, "-w", "2000", "-o", str(svg.with_suffix(".png")), str(svg)], check=True)
        print(svg.name, "and PNG" if rsvg else "(rsvg-convert not found: no PNG)")


if __name__ == "__main__":
    main()
