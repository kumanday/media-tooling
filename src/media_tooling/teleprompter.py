"""Karaoke teleprompter pages timed to a reference take.

``media-teleprompter`` writes a self-contained web page (``index.html``, plus
``voice.mp3`` when an audio track is given) that scrolls a script right to left
in a thin band at the top of the screen. Each word reaches a reading line at the
moment it is spoken in the reference take (a TTS practice narration, a rough
cut, an earlier recording) and fills in as it is spoken, so a presenter can
record to camera on the same timing.

Word timings come from one of:

- a ``media-subtitle`` JSON transcript (``segments[].words[]``);
- a narration timing file (``words[]`` with ``w``/``s``/``e``/``p``, as written
  by the motion-graphics skill's ``narration_timing.py``);
- a ``media-tts-frames`` ``audio_meta.json`` (frames played back to back in
  frame order).

An optional Markdown or plain-text script supplies the words to display, the
beats (headings, or paragraphs when there are no headings) and the cue words
(``**bold**``). It is aligned to the timed words, so the script may spell a
word differently from the transcript. Spelled-out numbers can be shown as
digits ("six hundred" -> "600") in English and Spanish.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from importlib import resources
from pathlib import Path
from typing import Any

TEMPLATE_PATH = "templates/teleprompter.html"
TRAILING_PUNCT = re.compile(r"[.,;:!?…)\]\"'”’»]+$")
BEAT_LEAD_S = 0.6

# Spelled-out numbers. "small" words add to the running group; scales close it.
EN_SMALL = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
EN_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
ES_SMALL = {
    "cero": 0, "uno": 1, "una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21,
    "veintiuna": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
    "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
    "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
    "novecientas": 900,
}
ES_SCALES = {"mil": 1_000, "millon": 1_000_000, "millones": 1_000_000}
NUMERAL_LANGUAGES = {"en": (EN_SMALL, EN_SCALES), "es": (ES_SMALL, ES_SCALES)}
DEFAULT_THOUSANDS = {"en": ",", "es": "."}
# Spanish articles that are also "one": a number only inside a longer number or before a scale.
ES_ARTICLES = {"un", "una", "uno"}


@dataclass
class TimedWord:
    text: str
    start: float
    end: float
    group: int | None = None


@dataclass
class ScriptToken:
    text: str
    beat: int
    cue: bool = False


@dataclass
class Unit:
    """One displayed word: a single token, or a spoken number spanning several tokens."""

    first: int
    last: int
    key: str
    text: str


def fold(text: str) -> str:
    """Lowercase ASCII letters and digits only: the form used to compare words."""
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))


def fold_keep_hyphens(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9-]", "", "".join(c for c in text if not unicodedata.combining(c)))


# ----------------------------------------------------------------------------- inputs

def load_timed_words(path: Path) -> tuple[list[TimedWord], list[float], float | None]:
    """Timed words, scene starts (if the file has them) and the total length (if known)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        words = [
            TimedWord(str(w["word"]).strip(), float(w["start"]), float(w["end"]))
            for seg in data["segments"]
            for w in seg.get("words", [])
            if str(w.get("word", "")).strip() and w.get("type", "word") == "word"
        ]
        total = data.get("audio_duration")
        return words, [], float(total) if total else None
    if isinstance(data, dict) and isinstance(data.get("words"), list) and data["words"] and "w" in data["words"][0]:
        words = [
            TimedWord(str(w["w"]), float(w["s"]), float(w["e"]), int(w["p"]) if "p" in w else None)
            for w in data["words"]
        ]
        scenes = [float(s["start"]) for s in data.get("scenes", []) if "start" in s]
        total = data.get("total")
        return words, scenes, float(total) if total else None
    if isinstance(data, dict) and isinstance(data.get("voices"), list):
        words = []
        offset = 0.0
        for i, voice in enumerate(sorted(data["voices"], key=lambda v: v.get("frame", 0))):
            for w in voice.get("words", []):
                words.append(TimedWord(str(w["text"]), offset + float(w["start"]), offset + float(w["end"]), i))
            offset += float(voice.get("duration_s", 0.0))
        return words, [], offset or None
    raise ValueError(f"{path}: not a media-subtitle transcript, a narration timing file or an audio_meta.json")


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("`", "")


def _tokens_with_cues(text: str) -> list[tuple[str, bool]]:
    """Whitespace tokens; a token is a cue if any of it was inside **bold**."""
    out: list[tuple[str, bool]] = []
    bold = False
    tok, tok_bold = "", False
    i = 0
    while i <= len(text):
        if text.startswith("**", i):
            bold = not bold
            i += 2
            continue
        ch = text[i] if i < len(text) else " "
        if ch.isspace():
            tok = re.sub(r"^[*_]+|[*_]+(?=[.,;:!?…)\]\"'”’»]*$)", "", tok)
            if tok:
                out.append((tok, tok_bold))
            tok, tok_bold = "", False
        else:
            tok += ch
            tok_bold = tok_bold or bold
        i += 1
    return out


def parse_script(text: str) -> tuple[list[ScriptToken], list[str]]:
    """Spoken tokens and beat labels from a Markdown or plain-text script.

    Headings at the deepest level used start beats and label them; text under
    higher-level headings (a title, an intro) is not spoken. With no headings,
    each paragraph is a beat. Blockquotes (delivery notes), code blocks, tables,
    HTML comments and horizontal rules are not spoken. **Bold** marks cue
    words; other inline Markdown is dropped.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = text.splitlines()
    levels = [len(m.group(1)) for line in lines if (m := re.match(r"(#{1,6})\s", line.strip()))]
    has_headings = bool(levels)
    beat_level = max(levels, default=0)
    labels: list[str] = []
    paragraphs: list[tuple[int, str]] = []
    current: list[str] = []
    beat = -1
    in_code = False

    def flush() -> None:
        if current:
            index = beat if has_headings else len(paragraphs)
            paragraphs.append((index, " ".join(current)))
            current.clear()

    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", line)
        if heading:
            flush()
            if len(heading.group(1)) == beat_level:
                labels.append(re.sub(r"[*_`]", "", heading.group(2)).strip())
                beat = len(labels) - 1
            else:
                beat = -1
            continue
        if not line or line.startswith(">") or line.startswith("|") or re.fullmatch(r"[-*_]{3,}", line):
            flush()
            continue
        if has_headings and beat < 0:
            continue
        current.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", line))
    flush()

    if not has_headings:
        labels = [str(i + 1) for i in range(len(paragraphs))]
    tokens = [
        ScriptToken(tok, index, cue)
        for index, para in paragraphs
        for tok, cue in _tokens_with_cues(_strip_inline_markdown(para))
    ]
    return tokens, labels


# ----------------------------------------------------------------------------- numbers

def _number_parts(token: str, small: dict[str, int], scales: dict[str, int]) -> tuple[list[str], str]:
    """Number words in a token and any non-number suffix ('five-thousand-person' -> ['five', 'thousand'], '-person')."""
    pieces = fold_keep_hyphens(token).split("-")
    parts: list[str] = []
    for piece in pieces:
        if piece in small or piece in scales:
            parts.append(piece)
        else:
            break
    if not parts:
        return [], ""
    rest = pieces[len(parts):]
    return parts, ("-" + "-".join(rest)) if rest else ""


def _number_value(parts: list[str], small: dict[str, int], scales: dict[str, int]) -> int:
    total, group = 0, 0
    for part in parts:
        if part in small:
            group += small[part]
        elif scales[part] == 100:
            group = (group or 1) * 100
        elif scales[part] == 1_000 and part == "mil":
            group = (group or 1) * 1_000
        else:
            total += (group or 1) * scales[part]
            group = 0
    return total + group


def _follows(prev: str, nxt: str, small: dict[str, int]) -> bool:
    """Whether small number word `nxt` can continue after small number word `prev` ('twenty' 'two': yes; 'two' 'three': no)."""
    a, b = small[prev], small[nxt]
    if a >= 100:
        return b < 100
    return a % 10 == 0 and a >= 20 and 0 < b < 10


def number_units(
    tokens: list[str],
    language: str | None,
    *,
    keep: list[str] | None = None,
    thousands: str | None = None,
) -> list[Unit]:
    """Group tokens into display units, writing spelled-out numbers as digits.

    With `language` None (or a language without a parser) every token is its own
    unit. Numerals keep the token's trailing punctuation and any hyphenated
    suffix ("five-thousand-person" -> "5,000-person"). Phrases in `keep` stay in
    words.
    """
    units: list[Unit] = []
    if language not in NUMERAL_LANGUAGES:
        for i, tok in enumerate(tokens):
            units.append(Unit(i, i, _token_key(tok), tok))
        return units
    small, scales = NUMERAL_LANGUAGES[language]
    sep = DEFAULT_THOUSANDS[language] if thousands is None else thousands
    kept = _kept_indices(tokens, keep or [])
    folded = [fold(t) for t in tokens]
    parts = [_number_parts(t, small, scales) for t in tokens]
    i = 0
    while i < len(tokens):
        seq, j, suffix = _number_span(i, tokens, folded, parts, kept, small, scales, language)
        if not seq:
            units.append(Unit(i, i, _token_key(tokens[i]), tokens[i]))
            i += 1
            continue
        value = _number_value(seq, small, scales)
        punct = TRAILING_PUNCT.search(tokens[j - 1])
        digits = f"{value:,}".replace(",", sep) if value >= 1000 else str(value)
        units.append(Unit(i, j - 1, f"#{value}", digits + suffix + (punct.group(0) if punct else "")))
        i = j
    return units


def _number_span(
    i: int,
    tokens: list[str],
    folded: list[str],
    parts: list[tuple[list[str], str]],
    kept: set[int],
    small: dict[str, int],
    scales: dict[str, int],
    language: str,
) -> tuple[list[str], int, str]:
    """The number words starting at token i, the index after the span, and its suffix; ([], i, '') if none."""

    def nxt_parts(k: int) -> list[str]:
        return parts[k][0] if k < len(tokens) and k not in kept else []

    if i in kept:
        return [], i, ""
    seq: list[str] = []
    j = i
    first = parts[i][0]
    if language == "en" and folded[i] == "a" and nxt_parts(i + 1)[:1] and nxt_parts(i + 1)[0] in scales \
            and not (i and folded[i - 1] in {"half", "quarter"}):
        seq, j = ["one"], i + 1
    elif not first or (first[0] in scales and first[0] != "mil"):
        return [], i, ""
    elif language == "es" and folded[i] in ES_ARTICLES and not (nxt_parts(i + 1)[:1] and nxt_parts(i + 1)[0] in scales):
        return [], i, ""
    suffix = ""
    while j < len(tokens) and j not in kept:
        nums, suf = parts[j]
        if nums:
            if seq and seq[-1] in small and nums[0] in small and not _follows(seq[-1], nums[0], small):
                break
            seq += nums
            j += 1
            if suf or TRAILING_PUNCT.search(tokens[j - 1]):
                suffix = suf
                break
            continue
        joiner = "and" if language == "en" else "y"
        nxt = nxt_parts(j + 1)
        if folded[j] == joiner and seq and nxt and nxt[0] in small:
            if language == "en" and seq[-1] in scales:
                j += 1
                continue
            if language == "es" and seq[-1] in small and 30 <= small[seq[-1]] < 100 and small[nxt[0]] < 10:
                j += 1
                continue
        break
    return seq, j, suffix


def _kept_indices(tokens: list[str], keep: list[str]) -> set[int]:
    folded = [fold(t) for t in tokens]
    kept: set[int] = set()
    for phrase in keep:
        words = [fold(w) for w in phrase.split() if fold(w)]
        for i in range(len(folded) - len(words) + 1):
            if words and folded[i:i + len(words)] == words:
                kept.update(range(i, i + len(words)))
    return kept


def _token_key(token: str) -> str:
    if re.fullmatch(r"[$€£]?\d[\d,.\s]*%?", token.strip(".,;:!?")):
        digits = re.sub(r"\D", "", token)
        return f"#{int(digits)}" if digits else fold(token)
    return fold(token)


# ----------------------------------------------------------------------------- alignment

def align(script_units: list[Unit], timed_units: list[Unit], timed: list[TimedWord]) -> tuple[list[tuple[float, float]], float]:
    """Start and end time for each script unit, and the share of units matched exactly.

    Matching uses folded words (numbers by value). Equal-length replaced runs map
    one to one (a name the transcript spells differently); any other unmatched
    units share the time between their matched neighbours.
    """
    spans = [(timed[u.first].start, timed[u.last].end) for u in timed_units]
    out: list[tuple[float, float] | None] = [None] * len(script_units)
    sm = SequenceMatcher(None, [u.key for u in script_units], [u.key for u in timed_units], autojunk=False)
    matched = 0
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            matched += a2 - a1
        if op == "equal" or (op == "replace" and a2 - a1 == b2 - b1):
            for k in range(a2 - a1):
                out[a1 + k] = spans[b1 + k]
    first_t = spans[0][0] if spans else 0.0
    last_t = spans[-1][1] if spans else 0.0
    i = 0
    while i < len(out):
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j] is None:
            j += 1
        prev_span = out[i - 1] if i else None
        next_span = out[j] if j < len(out) else None
        t0 = prev_span[1] if prev_span is not None else first_t
        t1 = next_span[0] if next_span is not None else max(last_t, t0)
        step = max(0.0, t1 - t0) / (j - i)
        for k in range(i, j):
            out[k] = (round(t0 + step * (k - i), 3), round(t0 + step * (k - i + 1), 3))
        i = j
    ratio = matched / len(script_units) if script_units else 1.0
    return [span for span in out if span is not None], ratio


# ----------------------------------------------------------------------------- page

def build_data(
    timed: list[TimedWord],
    *,
    script: str | None = None,
    language: str | None = "en",
    keep: list[str] | None = None,
    thousands: str | None = None,
    scenes: list[float] | None = None,
    total: float | None = None,
    beat_gap: float = 1.5,
    title: str = "Teleprompter",
    voice: bool = False,
) -> dict[str, Any]:
    """The page's data: words with times, beat labels and starts, and the total length."""
    if not timed:
        raise ValueError("no timed words")
    timed_units = number_units([w.text for w in timed], language, keep=keep, thousands=thousands)
    ratio = 1.0
    words: list[dict[str, Any]]
    if script is not None:
        tokens, labels = parse_script(script)
        if not tokens:
            raise ValueError("the script has no spoken text")
        units = number_units([t.text for t in tokens], language, keep=keep, thousands=thousands)
        spans, ratio = align(units, timed_units, timed)
        words = [
            {"w": u.text, "s": s, "e": e, "b": tokens[u.first].beat, "c": any(t.cue for t in tokens[u.first:u.last + 1])}
            for u, (s, e) in zip(units, spans)
        ]
    else:
        words = []
        groups = [w.group for w in timed]
        use_groups = all(g is not None for g in groups)
        beat = 0
        for k, u in enumerate(timed_units):
            if k:
                prev = timed_units[k - 1]
                if use_groups and timed[u.first].group != timed[prev.first].group:
                    beat += 1
                elif not use_groups and timed[u.first].start - timed[prev.last].end >= beat_gap:
                    beat += 1
            words.append({"w": u.text, "s": timed[u.first].start, "e": timed[u.last].end, "b": beat, "c": False})
        labels = [str(i + 1) for i in range(beat + 1)]
    beats: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        starts: list[float] = [float(w["s"]) for w in words if w["b"] == index]
        if not starts:
            continue
        start = scenes[index] if scenes and len(scenes) == len(labels) else max(0.0, min(starts) - BEAT_LEAD_S)
        beats.append({"label": label, "start": round(start, 3), "index": index})
    end = max(float(w["e"]) for w in words)
    return {
        "title": title,
        "total": round(max(total or 0.0, end + 1.0), 3),
        "voice": voice,
        "match": round(ratio, 3),
        "beats": beats,
        "words": words,
    }


def render_page(data: dict[str, Any]) -> str:
    template = resources.files("media_tooling").joinpath(TEMPLATE_PATH).read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__TITLE__", html.escape(str(data["title"]))).replace("__DATA__", payload)


def extract_voice(source: Path, dest: Path, ffmpeg_bin: str = "ffmpeg") -> None:
    """Write the reference take's audio as MP3 next to the page."""
    cmd = [ffmpeg_bin, "-nostdin", "-v", "error", "-y", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-q:a", "3", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}")


def media_duration(path: Path, ffprobe_bin: str = "ffprobe") -> float | None:
    proc = subprocess.run([ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a karaoke teleprompter web page timed to a reference take.",
        epilog="Open OUT/index.html in a browser; press H on the page for its keys.",
    )
    p.add_argument("words", help="word timings: media-subtitle JSON, a narration timing.json, or a media-tts-frames audio_meta.json")
    p.add_argument("--script", help="Markdown or text script to display (headings = beats, **bold** = cue words)")
    p.add_argument("--audio", help="the reference take (audio or video); its audio becomes the page's voice track")
    p.add_argument("--out", default="teleprompter", help="output folder (default: ./teleprompter)")
    p.add_argument("--title", default="Teleprompter", help="page title")
    p.add_argument("--language", default="en", help="script language; numbers are written as digits for en and es")
    p.add_argument("--no-numerals", action="store_true", help="keep spelled-out numbers as words")
    p.add_argument("--keep-words", action="append", default=[], metavar="PHRASE",
                   help="a phrase to keep in words, e.g. 'half a million' (repeatable)")
    p.add_argument("--thousands", default=None, help="thousands separator (default ',' for en, '.' for es; '' for none)")
    p.add_argument("--beat-gap", type=float, default=1.5,
                   help="without a script or groups, start a new beat after a pause this long (s)")
    p.add_argument("--ffmpeg-bin", default="ffmpeg")
    p.add_argument("--ffprobe-bin", default="ffprobe")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        timed, scenes, total = load_timed_words(Path(a.words).expanduser())
        script = Path(a.script).expanduser().read_text(encoding="utf-8") if a.script else None
        out = Path(a.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        voice = False
        if a.audio:
            source = Path(a.audio).expanduser()
            if not source.is_file():
                raise FileNotFoundError(f"{source} not found")
            if shutil.which(a.ffmpeg_bin) is None:
                raise RuntimeError(f"{a.ffmpeg_bin} not found on PATH")
            extract_voice(source, out / "voice.mp3", a.ffmpeg_bin)
            total = max(total or 0.0, media_duration(out / "voice.mp3", a.ffprobe_bin) or 0.0) or total
            voice = True
        language = None if a.no_numerals else a.language
        data = build_data(timed, script=script, language=language, keep=a.keep_words, thousands=a.thousands,
                          scenes=scenes, total=total, beat_gap=a.beat_gap, title=a.title, voice=voice)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"media-teleprompter: {exc}", file=sys.stderr)
        return 1
    (out / "index.html").write_text(render_page(data), encoding="utf-8")
    numerals = sum(1 for w in data["words"] if re.search(r"\d", w["w"]))
    cues = sum(1 for w in data["words"] if w["c"])
    print(f"{out / 'index.html'}: {len(data['words'])} words, {len(data['beats'])} beats, {cues} cue words, "
          f"{numerals} numerals, {data['total']:.1f} s" + (", voice.mp3" if voice else ", no voice track"))
    if script is not None:
        print(f"script/timing match {data['match']:.3f}" + ("  (low: check the script matches the take)" if data["match"] < 0.9 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
