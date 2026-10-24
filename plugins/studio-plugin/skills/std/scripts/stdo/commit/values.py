"""The value block of a harness commit question (m1-plan §5.1, v3 N1 · v4 R2 · R6 · v5 S5, D-M1-18).

The summary line names the protected keys only; the person also sees what they change to. Two parts:
- **settings**: one line per changed protected key of config.json, `<key>: <old canonical JSON | (없음)> → <new …>`,
  and the builtin narrators' lines (narrator.lines). The pre-commit hook recomputes this part from HEAD and the index.
- **machine** (first install only): this machine's s2v path (machine.json) and the `id` s2v reports there. Computed by
  `--stage` (which runs s2v); the hook never runs node — the guard compares these lines with the question.

Values are never cut. When one value is longer than VALUE_MAX characters, or the block is longer than LINES_MAX lines
or BYTES_MAX bytes, the whole block goes to a summary file (`.claude/studio/local/commit-summary-<tree12>.txt`, the
newest one only) and the question shows the file, its sha12 and per key how much changes (lists: items and +/−,
objects: per changed sub-key down to DEPTH, scalars: "값 바뀜"). A first install that overflows says
`first-install-overflow` (its values came from init apply without a person's answer).

The limits are provisional until U-M1c measures what AskUserQuestion shows (m1-plan §5.5)."""

import glob
import hashlib
import json
import os

from .. import narrator, paths

VALUE_MAX = 400
LINES_MAX = 40
BYTES_MAX = 4096
DEPTH = 2
SUMMARY_GLOB = "commit-summary-*.txt"
FIRST_INSTALL_OVERFLOW = "first-install-overflow"
NONE = "(없음)"


def canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def key_lines(old_cfg, new_cfg, keys):
    """[(line, value texts)] for the protected keys that differ (sorted by key)."""
    out = []
    for k in sorted(keys):
        ina = isinstance(old_cfg, dict) and k in old_cfg
        inb = isinstance(new_cfg, dict) and k in new_cfg
        a = canon(old_cfg[k]) if ina else NONE
        b = canon(new_cfg[k]) if inb else NONE
        if ina != inb or a != b:
            out.append(("%s: %s → %s" % (k, a, b), (a, b)))
    return out


# the criteria files (P-CRIT: only a person changes them; M1c review P1) — the person sees them at a harness commit
CRIT_FILES = (".claude/studio/charter.md",)
CRIT_DIRS = (".claude/studio/formats/", ".claude/studio/platforms/")
FORMATS = ".claude/studio/formats/"


def is_crit(path):
    return path in CRIT_FILES or path.startswith(CRIT_DIRS)


def _leaves(v, prefix, out):
    if isinstance(v, dict):
        for k in sorted(v):
            _leaves(v[k], "%s.%s" % (prefix, k) if prefix else str(k), out)
    else:
        out[prefix] = v
    return out


def _criteria(data):
    from .. import criteria
    if data is None:
        return {}
    try:
        return _leaves(criteria.parse(data.decode("utf-8")), "", {})
    except (criteria.Missing, UnicodeDecodeError):
        return None


def crit_parts(crit):
    """(criteria lines, file lines, count lines) of the criteria files a commit changes. `crit` = [(path, HEAD blob or
    None, index blob or None)]: a format's criteria block as `criteria.<kind>.<key>.<lang>: <old> → <new>` lines, and
    every criteria file as `<path>: <sha12 of the new content> (새로|바뀜|삭제)` (the person opens it)."""
    lines, files, cnt = [], [], []
    for path, old, new in sorted(crit, key=lambda t: t[0]):
        status = "새로" if old is None else "삭제" if new is None else "바뀜"
        sha12 = hashlib.sha256(new).hexdigest()[:12] if new is not None else "-"
        files.append("%s: %s (%s)" % (path, sha12, status))
        if path.startswith(FORMATS) and path.endswith(".md"):
            kind = path[len(FORMATS):-3]
            a, b = _criteria(old), _criteria(new)
            a, b = a or {}, b or {}
            n = 0
            for k in sorted(set(a) | set(b)):
                if (k in a) != (k in b) or canon(a.get(k)) != canon(b.get(k)):
                    lines.append("criteria.%s.%s: %s → %s" % (kind, k, canon(a[k]) if k in a else NONE,
                                                              canon(b[k]) if k in b else NONE))
                    n += 1
            if n:
                cnt.append("criteria.%s: %d개 바뀜" % (kind, n))
    return lines, files, cnt


def settings(old_cfg, new_cfg, keys, narrators=(), crit=()):
    """(lines, longest value length). `narrators` = [(id, old status, new status)]; `crit` = the criteria files."""
    kl = key_lines(old_cfg, new_cfg, keys)
    lines = [l for l, _v in kl]
    longest = max([len(x) for _l, v in kl for x in v] or [0])
    cl, fl, _cnt = crit_parts(crit)
    for l in cl + fl:
        lines.append(l)
        longest = max(longest, len(l))
    for nid, old, new in sorted(narrators, key=lambda t: t[0]):
        for l in narrator.lines(nid, old, new):
            lines.append(l)
            longest = max(longest, len(l))
    return lines, longest


def machine_lines(s2v_path, s2v_id):
    return ["s2v 경로(이 기기, 커밋되지 않음): %s" % s2v_path, "s2v id: %s" % s2v_id]


def overflows(lines, longest):
    block = "\n".join(lines)
    return longest > VALUE_MAX or len(lines) > LINES_MAX or len(block.encode("utf-8")) > BYTES_MAX


def _count(key, old, new, depth, out):
    if isinstance(new, dict) and (old is None or isinstance(old, dict)) and depth < DEPTH:
        old = old or {}
        for sub in sorted(set(old) | set(new)):
            if canon(old.get(sub)) != canon(new.get(sub)) or (sub in old) != (sub in new):
                _count("%s.%s" % (key, sub), old.get(sub), new.get(sub), depth + 1, out)
        return
    if isinstance(new, list):
        olds = [canon(x) for x in old] if isinstance(old, list) else []
        news = [canon(x) for x in new]
        added = len([x for x in news if x not in olds])
        removed = len([x for x in olds if x not in news])
        out.append("%s: %d개 (+%d −%d)" % (key, len(new), added, removed))
    elif isinstance(new, dict):
        out.append("%s: 키 %d개" % (key, len(new)))
    elif new is None and old is not None:
        out.append("%s: 삭제" % key)
    else:
        out.append("%s: 값 바뀜" % key)


def counts(old_cfg, new_cfg, keys):
    """How much each changed protected key changes (shown instead of the values when the block overflows)."""
    out = []
    for k in sorted(keys):
        ina = isinstance(old_cfg, dict) and k in old_cfg
        inb = isinstance(new_cfg, dict) and k in new_cfg
        a = old_cfg.get(k) if ina else None
        b = new_cfg.get(k) if inb else None
        if ina != inb or canon(a) != canon(b):
            _count(k, a, b, 0, out)
    return out


def summary_rel(tree):
    return ".claude/studio/local/commit-summary-%s.txt" % tree[:12]


def file_line(rel, sha12):
    return "값 블록 파일: %s (sha %s)" % (rel, sha12)


def block(old_cfg, new_cfg, keys, narrators, machine, tree, first_install, crit=()):
    """The block for commit-ok.json: {"settings", "machine", "shown", "overflow"}. `shown` is what the question must
    contain; overflow = {"file", "sha12", "reason"} or None."""
    lines, longest = settings(old_cfg, new_cfg, keys, narrators, crit)
    mach = list(machine or [])
    longest = max([longest] + [len(l) for l in mach])
    full = lines + mach
    if not full:
        return {"settings": [], "machine": [], "shown": [], "overflow": None}
    if not overflows(full, longest):
        return {"settings": lines, "machine": mach, "shown": full, "overflow": None}
    text = "\n".join(full) + "\n"
    rel = summary_rel(tree)
    sha12 = _sha(text)[:12]
    reason = FIRST_INSTALL_OVERFLOW if first_install else "overflow"
    _cl, crit_files, crit_counts = crit_parts(crit)
    shown = [file_line(rel, sha12)] + counts(old_cfg, new_cfg, keys) + crit_counts + crit_files + \
        [l for l in lines if l.startswith("내레이터:")]
    if first_install:
        shown.append("%s: 첫 설치의 설정이 질문에 다 보이지 않는다 — 파일을 열어 확인할 것" % FIRST_INSTALL_OVERFLOW)
    return {"settings": lines, "machine": mach, "shown": shown,
            "overflow": {"file": rel, "sha12": sha12, "reason": reason, "text": text}}


def write_summary(top, blk):
    """Write the overflow file (and remove older ones: the newest one only). Returns its path or None."""
    ov = blk.get("overflow")
    d = os.path.join(top, ".claude", "studio", "local")
    for p in glob.glob(os.path.join(glob.escape(d), SUMMARY_GLOB)):
        if not ov or os.path.basename(p) != os.path.basename(ov["file"]):
            try:
                os.remove(p)
            except OSError:
                pass
    if not ov:
        return None
    paths.check_local(top)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(top, ov["file"])
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(ov["text"])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    paths.check_local(top)
    return p


def summary_problem(top, ok):
    """The hook's check of an overflow file (its sha and its lines = settings + machine), or None."""
    ov = ok.get("overflow")
    if not ov:
        return None
    try:
        raw = paths.read_local(top, os.path.basename(ov.get("file") or ""))
    except paths.UnsafeLocal as e:
        return str(e)
    if raw is None:
        return "the value block file %s is missing — stage again" % ov.get("file")
    text = raw.decode("utf-8", "replace")
    if _sha(text)[:12] != ov.get("sha12") or text != "\n".join((ok.get("values_settings") or []) +
                                                               (ok.get("values_machine") or [])) + "\n":
        return "the value block file %s is not the one Studio prepared — stage again" % ov.get("file")
    return None


def shown_in(lines, question):
    """Every line of the block is in the question (normalized like the summary line)."""
    from .summary import norm
    q = norm(question)
    return all(norm(l) in q for l in lines)
