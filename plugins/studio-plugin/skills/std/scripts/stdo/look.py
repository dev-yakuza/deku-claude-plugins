"""The brand's look in the script (0.0.26, pilot-2 P16): what `.claude/studio/brand.json` asks of a script's frontmatter
and whether the script has it.

- `brand_logo(repo, vdir)`: the brand logo judged live (not an entry of assets.json): inside the repository, a regular
  file, PNG or JPEG by its bytes, and brand.json and the logo committed (brand.json is not protected; a committed one
  is the person's, through a harness commit).
- `check_assets.py <video> --look --output <o>` (`look_main`): the frontmatter lines the brand asks for — the theme's
  accent, the logo, and the layout (no presenter layout without character art) — printed only, nothing written.
- `problems(…)`: the board check's look rules; `layout_problem(…)`: the layout rule, shared with the script check
  (`mode="script"`: the layout from the frontmatter text, absent is fine; `mode="board"`: inspect's layout, where
  absent is s2v's default `presenter`).

The theme and outputs are read from the frontmatter text: trailing ` #…` comments outside quotes are dropped first,
but an unquoted `#` value (`accent: #EC174F`) is reported before that — YAML reads it as a comment, the colour is
lost."""

import json
import os
import re
import stat

from .voice import frontmatter as fm

BRAND = ".claude/studio/brand.json"
FLOOR_REASON = "brand.json logo (committed in the harness)"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
BASES = ("light", "dark")
NEEDS_ART = ("presenter", "dialogue")
WIDE = "16:9"
MAX_LOGO = 5 * 1024 * 1024  # a logo is small: a larger file is never read (nor hashed for the board's inputs)
UNQUOTED_HASH = re.compile(r"""(?:^|[\s{,])accent\s*:\s*#""")


# ---------- brand.json and the logo ----------

def read_brand(repo):
    """(brand dict, None) or (None, why)."""
    try:
        with open(os.path.join(repo, BRAND), encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return None, "%s is missing" % BRAND
    except ValueError as e:
        return None, "%s is not JSON (%s)" % (BRAND, e)
    if not isinstance(data, dict):
        return None, "%s is not an object" % BRAND
    color = data.get("accent_color")
    if not isinstance(color, str) or not HEX.match(color):
        return None, "%s accent_color is not #RRGGBB" % BRAND
    logo = data.get("logo", "")
    if not isinstance(logo, str):
        return None, "%s logo is not a path (\"\" for no logo)" % BRAND
    return data, None


def _uncommitted(repo, rels):
    from .state import flow
    return flow.uncommitted(repo, rels)


def brand_logo(repo, vdir, committed=None):
    """None when brand.json names no logo; else {path, script_src, sha256, status, reason}. `status` is ok · invalid ·
    outside · missing · not-a-file · format · ext-mismatch · uncommitted. `committed`: a stub for tests (rels → [(rel,
    why)]), else git."""
    brand, why = read_brand(repo)
    if why:
        return {"path": None, "script_src": None, "sha256": None, "status": "invalid", "reason": why}
    logo = brand.get("logo") or ""
    if not logo.strip():
        return None
    rel = os.path.normpath(logo).replace(os.sep, "/")
    out = {"path": rel, "script_src": None, "sha256": None, "status": "ok", "reason": None}
    top = os.path.realpath(repo)
    full = os.path.join(repo, rel)
    real = os.path.realpath(full)
    if os.path.isabs(logo) or rel.startswith("../") or rel == ".." or \
            not real.startswith(top.rstrip(os.sep) + os.sep):
        out.update(status="outside", reason="brand logo %s is outside the repository" % logo)
        return out
    out["script_src"] = os.path.relpath(full, vdir).replace(os.sep, "/")
    if not os.path.lexists(full):
        out.update(status="missing", reason="brand logo %s does not exist" % rel)
        return out
    try:
        st = os.lstat(full)
    except OSError:
        st = None
    if st is None or not stat.S_ISREG(st.st_mode):  # a link, a folder, a FIFO or a device is never opened
        out.update(status="not-a-file", reason="brand logo %s is not a regular file" % rel)
        return out
    if st.st_size > MAX_LOGO:
        out.update(status="too-large", reason="brand logo %s is larger than %d MB" % (rel, MAX_LOGO // (1024 * 1024)))
        return out
    from .source import assets as assets_mod
    st, reason, info = assets_mod.judge_file(repo, rel)
    out["sha256"] = info.get("sha256")
    if st != "ok":
        out.update(status=reason, reason="brand logo %s is not PNG or JPEG%s" % (
            rel, " (its extension says otherwise)" if reason == "ext-mismatch" else ""))
        return out
    left = (committed or _uncommitted)(repo, [BRAND, rel])
    if left:
        out.update(status="uncommitted", reason="brand logo is not committed — make a harness commit (%s)" % "; ".join(
            "%s: %s" % (p, w) for p, w in left))
    return out


def brand_asset(bl):
    """The credits view of an ok brand logo (assets.json's fields a CREDITS entry is checked against), else None."""
    if not bl or bl.get("status") != "ok":
        return None
    return {"script_src": bl["script_src"], "sha256": bl["sha256"], "status": "ok", "floor": "public",
            "floor_reason": FLOOR_REASON, "brand": True}


def logo_reason(bl, path):
    """Why `path` cannot be used when it is the brand logo's script_src and the logo is not ok (else None)."""
    if bl and bl.get("status") != "ok" and bl.get("script_src") == path:
        return bl.get("reason")
    return None


# ---------- the frontmatter text ----------

def strip_comment(line):
    """`line` without a trailing ` #…` comment outside quotes (a line that starts with `#` is all comment)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _lines(text):
    """The frontmatter lines with comments dropped (comment-only lines skipped)."""
    out = []
    for line in fm.head(text):
        if line.strip().startswith("#"):
            continue
        out.append(strip_comment(line))
    return out


def _clean(text):
    return "---\n%s\n---\n" % "\n".join(_lines(text))


def _top_block(raw_lines, key):
    """The raw lines of a top-level key and its children."""
    out = []
    for i, line in enumerate(raw_lines):
        m = fm.TOP.match(line)
        if m and m.group(1) == key:
            out.append(line)
            for nxt in raw_lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace():
                    break
                out.append(nxt)
            break
    return out


def theme_of(text):
    """(theme, problem). theme: None (no theme) · "light"/"dark"/other scalar · {base, accent, …}. problem: an unquoted
    `#` colour (checked on the raw text, before comments are dropped)."""
    raw = _top_block(fm.head(text), "theme")
    if not raw:
        return None, None
    first = fm.TOP.match(raw[0]).group(2)
    unquoted = ("the theme's colour is not quoted — write accent: \"#RRGGBB\" (YAML reads an unquoted # as a "
                "comment)")
    if re.match(r"^\s*#[0-9A-Fa-f]{3,8}\b", first) or UNQUOTED_HASH.search(first):
        return None, unquoted
    for line in raw[1:]:
        if line.strip().startswith("#"):
            continue  # a comment-only child line
        if UNQUOTED_HASH.search(line):
            return None, unquoted
    m = fm.TOP.match(strip_comment(raw[0]))
    if m and m.group(2) and fm.inline(m.group(2)) is None:
        return fm.scalar(m.group(2)), None
    value = fm.block(_clean(text), "theme")
    return (value if value else None), None


def outputs_of(text):
    """{output: {aspect, layout, …}} from the frontmatter text (inline or nested), comments dropped."""
    value = fm.block(_clean(text), "outputs")
    return {k: v for k, v in (value or {}).items() if isinstance(v, dict)}


def title_of(text):
    for line in _lines(text):
        m = fm.TOP.match(line)
        if m and m.group(1) == "title":
            return fm.scalar(m.group(2)) or None
    return None


# ---------- the layout ----------

def cast_art(ins, output):
    """(the speaking cast, the cast with usable character art) from inspect: `voices` are the cast that speaks;
    `characters` lists only art s2v could read (an unreadable one is left out with its reason — inspect.ts), and an
    entry counts only with its `source` (classic · imported · parts). Other presentation reasons (a missing bgm, …) do
    not touch the art."""
    cast = set(v.get("cast") for v in ins.get("voices") or [] if isinstance(v, dict) and v.get("cast"))
    art = set(c.get("cast") for c in ins.get("characters") or []
              if isinstance(c, dict) and c.get("cast") and isinstance(c.get("source"), str) and c["source"].strip())
    return cast, art


def layout_problem(layout, cast, art, mode, aspect=WIDE, output="youtube"):
    """The layout rule: a 16:9 output shows no presenter or dialogue layout unless every speaking cast member has
    character art (without art s2v draws no one). mode "script": an absent layout is fine (board sets it); "board":
    absent is s2v's default presenter."""
    if (aspect or WIDE) != WIDE or layout == "shorts":
        return None
    if layout is None:
        if mode == "script":
            return None
        layout = "presenter"
    if layout in NEEDS_ART and not (cast and cast <= art):
        return ("outputs.%s.layout is %s, which shows no one without character art — use fullscreen "
                "(check_assets.py <video> --look --output %s)" % (output, layout, output))
    return None


def _output_info(ins, output):
    for o in ins.get("outputs") or []:
        if isinstance(o, dict) and o.get("name") == output:
            return o
    return {}


def required(bl, brand, ins, output):
    """The lines --look prints: [(key, value)]."""
    out = [("theme.accent", '"%s"' % brand["accent_color"])]
    out.append(("logo.src", '"%s"' % bl["script_src"]) if bl else ("logo", "none"))
    info = _output_info(ins, output)
    if (info.get("aspect") or WIDE) == WIDE and info.get("layout") != "shorts":
        cast, art = cast_art(ins, output)
        out.append(("outputs.%s.layout" % output, "presenter" if cast and cast <= art else "fullscreen"))
    return out


def _accent(theme):
    return theme.get("accent") if isinstance(theme, dict) else None


def problems(repo, vdir, ins, text, output, committed=None):
    """The board check's look problems (each names --look)."""
    hint = " (check_assets.py <video> --look --output %s)" % output
    brand, why = read_brand(repo)
    if why:
        return [why]
    out = []
    left = (committed or _uncommitted)(repo, [BRAND])
    if left:
        out.append("%s is not committed — commit it in a harness commit (%s)" % (BRAND, left[0][1]))
    theme, tp = theme_of(text)
    if tp:
        out.append(tp)
    elif _accent(theme) is None:
        if isinstance(theme, str):
            out.append("theme is %s: set theme: { base: %s, accent: \"%s\" }%s" % (theme, theme, brand["accent_color"],
                                                                                   hint))
        else:
            out.append("the theme has no accent: set theme.accent to \"%s\"%s" % (brand["accent_color"], hint))
    elif str(_accent(theme)).lower() != brand["accent_color"].lower():
        out.append("theme.accent is %s, not the brand's %s%s" % (_accent(theme), brand["accent_color"], hint))
    bl = brand_logo(repo, vdir, committed=committed)
    logos = [f for f in ins.get("files") or [] if isinstance(f, dict)
             and "logo" in [k for k in str(f.get("kind") or "").split(",") if k]]
    if bl is None:
        if logos:
            out.append("the script has a logo (%s) but brand.json names none — remove it, or set the logo in "
                       "brand.json (harness commit)" % logos[0].get("path"))
    elif bl["status"] != "ok":
        out.append("%s — choose a committed PNG/JPEG logo in %s (harness commit) or set it to \"\"" % (bl["reason"],
                                                                                                      BRAND))
    else:
        hit = [f for f in logos if f.get("path") == bl["script_src"]]
        if not hit:
            out.append("the script's logo is not the brand logo: set logo: { src: \"%s\" }%s" % (bl["script_src"],
                                                                                              hint))
        elif hit[0].get("sha256") != bl["sha256"]:
            out.append("the logo file s2v sees is not the brand logo's bytes (%s)" % bl["script_src"])
    info = _output_info(ins, output)
    cast, art = cast_art(ins, output)
    lp = layout_problem(info.get("layout"), cast, art, "board", info.get("aspect"), output)
    if lp:
        out.append(lp)
    return out


def base_of(theme):
    if isinstance(theme, dict) and theme.get("base") in BASES:
        return theme["base"]
    if theme in BASES:
        return theme
    return "light"


def look_main(repo, vdir, ctx, output, providers, out):
    """--look: print the lines; 0 · 1 (brand.json unusable or the logo not ok)."""
    from .state import commands as C
    brand, why = read_brand(repo)
    if why:
        out.write("look: FAIL — %s\n" % why)
        return C.FAIL
    bl = brand_logo(repo, vdir)
    if bl is not None and bl["status"] != "ok":
        out.write("look: FAIL — %s; choose a committed PNG/JPEG logo in %s (harness commit) or set it to \"\"\n"
                  % (bl["reason"], BRAND))
        return C.FAIL
    ins = providers.inspect(ctx)
    try:
        with open(ctx["script"], encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    theme, _tp = theme_of(text)
    lines = required(bl, brand, ins, output)
    out.write("look for %s (from %s)\n" % (output, BRAND))
    for k, v in lines:
        out.write("%s: %s\n" % (k, v))
    out.write("paste into the frontmatter (keep the other keys):\n")
    out.write('theme: { base: %s, accent: "%s" }\n' % (base_of(theme), brand["accent_color"]))
    if bl:
        out.write('logo: { src: "%s" }\n' % bl["script_src"])
    for k, v in lines:
        if k.startswith("outputs."):
            out.write("outputs.%s: set layout: %s (keep its other keys)\n" % (output, v))
    return C.OK
