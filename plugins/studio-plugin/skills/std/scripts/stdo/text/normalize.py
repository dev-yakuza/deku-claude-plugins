"""The one excerpt normalization (m1-plan §7.1, M7): check_claims, the router's source diff, the source-diff gate and
the ④b excerpt comparison all use it, so an excerpt is judged the same way everywhere.

Steps: NFC → one kind of line break → Markdown to text (HTML comments, images and fence lines dropped; deleted text —
`~~…~~`, `<del>`, `<s>`, `<strike>` — dropped with its content; links keep their text; emphasis, code marks, heading
`#`, quote `>` and list markers dropped) → ruby expanded in two forms (`base`: the
written text only; `reading`: each written part followed by its reading in brackets, `空港(くうこう)`) → other HTML
tags dropped, entities decoded → runs of white space to one space.

An excerpt matches a text (`contains`): an excerpt without ruby when it is in either form of the text; an excerpt with
ruby only in the reading form (so a changed reading is a changed excerpt)."""

import html
import re
import unicodedata

COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
FENCE_LINE = re.compile(r"^\s{0,3}(?:```|~~~).*$", re.M)
IMAGE = re.compile(r"!\[(?:[^\[\]]|\[[^\[\]]*\])*\](?:\([^)]*\)|\[[^\]]*\])")
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\](?:\([^)]*\)|\[[^\]]*\])")
REFDEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S+.*$", re.M)
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
QUOTE = re.compile(r"^\s{0,3}(?:>\s?)+", re.M)
LIST = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+", re.M)
STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
EMPH = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", re.S)
STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
DELETED = re.compile(r"<(del|s|strike)\b[^>]*>.*?</\1\s*>", re.I | re.S)
CODE = re.compile(r"(`+)(.+?)\1", re.S)
RUBY = re.compile(r"<ruby\b[^>]*>(.*?)</ruby\s*>", re.I | re.S)
RP = re.compile(r"<rp\b[^>]*>.*?</rp\s*>", re.I | re.S)
RT = re.compile(r"<rt\b[^>]*>(.*?)(?:</rt\s*>|(?=<rt\b)|\Z)", re.I | re.S)
TAG = re.compile(r"</?[A-Za-z][^>]*>")
FORMS = ("base", "reading")


def _markdown(t):
    t = COMMENT.sub(" ", t)
    t = DELETED.sub(" ", t)  # deleted text is not there (M1e review S2): a retraction is no support
    t = STRIKE.sub(" ", t)
    t = FENCE_LINE.sub(" ", t)
    t = REFDEF.sub(" ", t)
    t = IMAGE.sub(" ", t)
    t = CODE.sub(lambda m: m.group(2), t)
    for _ in range(3):  # nested links keep their innermost text
        t2 = LINK.sub(lambda m: m.group(1), t)
        if t2 == t:
            break
        t = t2
    t = HEADING.sub("", t)
    t = QUOTE.sub("", t)
    t = LIST.sub("", t)
    t = STRONG.sub(lambda m: m.group(m.lastindex), t)
    t = EMPH.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), t)
    return t


def _strip_tags(t):
    return TAG.sub("", t)


def _ruby(form):
    def one(m):
        inner = RP.sub("", m.group(1))
        out, pos = [], 0
        for r in RT.finditer(inner):
            base = _strip_tags(inner[pos:r.start()]).strip()
            reading = _strip_tags(r.group(1)).strip()
            out.append(base if form == "base" or not reading else "%s(%s)" % (base, reading))
            pos = r.end()
        out.append(_strip_tags(inner[pos:]).strip())
        return "".join(out)
    return one


def has_ruby(text):
    return bool(RUBY.search(text or ""))


def plain(text, form="base"):
    """The normalized text in one of FORMS."""
    if form not in FORMS:
        raise ValueError("form is base or reading: %r" % (form,))
    t = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _markdown(t)
    t = RUBY.sub(_ruby(form), t)
    t = html.unescape(_strip_tags(t))
    t = unicodedata.normalize("NFC", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize(text):
    """The base form (what the router and gates compare when no ruby is involved)."""
    return plain(text, "base")


class Text(object):
    """A text normalized once in both forms (a source copy checked against many excerpts)."""

    def __init__(self, text):
        self.base, self.reading = plain(text, "base"), plain(text, "reading")

    def contains(self, excerpt):
        if not isinstance(excerpt, str):
            return False
        if has_ruby(excerpt):
            e = plain(excerpt, "reading")
            return bool(e) and e in self.reading
        e = plain(excerpt, "base")
        return bool(e) and (e in self.base or e in self.reading)


def contains(text, excerpt):
    return Text(text).contains(excerpt)


def chars(excerpt):
    """The normalized character count of an excerpt (the brief's length estimate: base form, spaces included)."""
    return len(plain(excerpt, "base"))
