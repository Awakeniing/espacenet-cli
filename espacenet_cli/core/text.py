"""Text/publication-number parsing helpers.

Pure functions over Espacenet response shapes — the unit-test surface.
"""

import html as html_mod
import re

from espacenet_cli.core.errors import CliError

PN_RE = re.compile(r"^([A-Z]{2})[\s-]?(\d+)[\s-]?([A-Z]\d?|)$")

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_CLAIM_NUMBERED_RE = re.compile(r"\n(?=\[\d{4}\]\s)")
_CLAIM_NUMBER_TAG_RE = re.compile(r"^\[\d{4}\]\s*")
_CLAIM_DOT_RE = re.compile(r"\n(?=\d+[..]\s)")
_CLAIM_DOT_TAG_RE = re.compile(r"^\d+[..]\s*")


def parse_publication_number(value):
    """`EP2600908A1` / `EP2600908` → dict(cc, num, kind, stem, full)."""
    raw = re.sub(r"\s+", "", str(value or "").strip().upper())
    m = PN_RE.match(raw)
    if not m:
        raise CliError(
            "INVALID_PN",
            f"Unrecognized publication number: {value}",
            action="Examples: EP2600908, EP2600908A1, US11234567B2",
            exit_code=2,
        )
    cc, num, kind = m.group(1), m.group(2), m.group(3) or ""
    return {"cc": cc, "num": num, "kind": kind, "stem": f"{cc}{num}", "full": f"{cc}{num}{kind}"}


def strip_html(value=""):
    text = _HTML_TAG_RE.sub(" ", str(value or ""))
    text = html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def xml_to_text(xml):
    """Clean OPS fulltext XML (p/hi/br tags, entities) to plain text."""
    text = str(xml or "")
    text = re.sub(r'<p\s+n="(\d+)"[^>]*>', lambda m: f"\n[{m.group(1)}] ", text)
    text = text.replace('<hi rend="subscript">', "_{").replace("</hi>", "}")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = text.replace("</p>", "\n")
    text = _HTML_TAG_RE.sub("", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_multipart_text(raw):
    """Join text parts of the highlight service multipart response."""
    text = str(raw or "").replace("\r\n", "\n")
    if not text.startswith("--"):
        return text
    boundary_line = text.split("\n", 1)[0].strip()
    contents = []
    for seg in text.split(boundary_line)[1:]:
        cleaned = seg.strip("-").strip("\n").strip()
        if not cleaned:
            continue
        idx = cleaned.find("\n\n")
        header = cleaned[:idx] if idx >= 0 else ""
        body = cleaned[idx + 2:] if idx >= 0 else cleaned
        if not body.strip():
            continue
        if not header or re.search(r"key:\s*publications\.", header, re.I):
            contents.append(body.strip())
    return "\n\n".join(contents).strip() or text


def split_claims(text):
    """Split fulltext claims into [{number, text}] (numbered or dot forms)."""
    text = str(text or "")
    numbered = [s for s in _CLAIM_NUMBERED_RE.split(text) if s.strip()]
    if len(numbered) > 1:
        return [{"number": i + 1, "text": _CLAIM_NUMBER_TAG_RE.sub("", t).strip()}
                for i, t in enumerate(numbered)]
    dotted = [s for s in _CLAIM_DOT_RE.split(text) if s.strip()]
    if len(dotted) > 1:
        return [{"number": i + 1, "text": _CLAIM_DOT_TAG_RE.sub("", t).strip()}
                for i, t in enumerate(dotted)]
    return [{"number": 1, "text": text.strip()}]


def num_to_date(value):
    s = str(value if value is not None else "")
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def same_publication(a, b):
    """Tolerant equality: kind code may be omitted on either side."""
    if not a or not b:
        return False
    norm = lambda s: re.sub(r"\s+", "", str(s).upper())
    x, y = norm(a), norm(b)
    return x == y or y.startswith(x) or x.startswith(y)
