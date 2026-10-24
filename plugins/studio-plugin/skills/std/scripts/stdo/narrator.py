"""The default narrator (m1-plan §5.3, D-M1-4): `<sr>/cast/<id>/{profile.md,status.json}` with `kind: builtin` — an
engine's built-in speaker, so no voice files enter the repository. Read by the commit checks (a harness commit may carry
these two files), the summary's narrator line, setup.py (writes them) and check_assets --actors (M1f).

status.json = {"schema": 1, "id", "kind": "builtin", "voice": {"<lang>": {"engine": "qwen:<speaker>", "style": "…",
"state": "ready"}}, "character": "none", "building": false, "visibility": "public"}"""

import json
import re

SCHEMA = 1
FILES = ("profile.md", "status.json")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Qwen3-TTS built-in speakers (qwen_tts 0.1.1 model card) and their native language
QWEN_SPEAKERS = {"Vivian": "zh", "Serena": "zh", "Uncle_Fu": "zh", "Dylan": "zh", "Eric": "zh", "Ryan": "en",
                 "Aiden": "en", "Ono_Anna": "ja", "Sohee": "ko"}
SUGGESTED = {"ko": "qwen:Sohee", "ja": "qwen:Ono_Anna", "en": "qwen:Ryan"}  # s2v scaffold's defaults (U-M1-8)
LANGS = ("ko", "ja", "en")
STYLE_MAX = 200


def parse(data):
    """The status.json object, or None (not JSON / not an object)."""
    if data is None:
        return None
    try:
        v = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError):
        return None
    return v if isinstance(v, dict) else None


def is_builtin(status):
    return isinstance(status, dict) and status.get("kind") == "builtin"


def engine_ok(engine):
    return isinstance(engine, str) and engine.startswith("qwen:") and engine[len("qwen:"):] in QWEN_SPEAKERS


def problems(status, folder_id):
    """Why a status.json is not a valid builtin narrator record (empty list = valid)."""
    out = []
    if not isinstance(status, dict):
        return ["status.json is not a JSON object"]
    if status.get("schema") != SCHEMA:
        out.append("schema is not %d" % SCHEMA)
    if status.get("id") != folder_id or not ID.match(str(folder_id)):
        out.append("id %r is not the folder's name %r" % (status.get("id"), folder_id))
    if status.get("kind") != "builtin":
        out.append("kind is not builtin")
    voice = status.get("voice")
    if not isinstance(voice, dict) or not voice:
        out.append("voice has no language")
    else:
        for lang, v in sorted(voice.items()):
            if lang not in LANGS:
                out.append("voice.%s: not a supported language (%s)" % (lang, ", ".join(LANGS)))
            if not isinstance(v, dict) or not engine_ok(v.get("engine")):
                out.append("voice.%s.engine must be qwen:<built-in speaker> (%s)" % (
                    lang, ", ".join(sorted(QWEN_SPEAKERS))))
            elif not isinstance(v.get("style"), str) or len(v["style"]) > STYLE_MAX or "\n" in v["style"]:
                out.append("voice.%s.style must be one line of at most %d characters" % (lang, STYLE_MAX))
            elif v.get("state") != "ready":
                out.append("voice.%s.state must be ready" % lang)
    for k, want in (("character", "none"), ("building", False), ("visibility", "public")):
        if status.get(k) != want:
            out.append("%s must be %s" % (k, json.dumps(want)))
    extra = sorted(set(status) - {"schema", "id", "kind", "voice", "character", "building", "visibility"})
    if extra:
        out.append("unknown keys: %s" % ", ".join(extra))
    return out


def record(nid, voices):
    """A status.json object for `voices` = {lang: (engine, style)}."""
    return {"schema": SCHEMA, "id": nid, "kind": "builtin",
            "voice": {l: {"engine": e, "style": s, "state": "ready"} for l, (e, s) in sorted(voices.items())},
            "character": "none", "building": False, "visibility": "public"}


def dumps(status):
    return json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _voice(status, lang):
    v = ((status or {}).get("voice") or {}).get(lang) if isinstance(status, dict) else None
    return (v.get("engine"), v.get("style")) if isinstance(v, dict) else None


def voice_text(v):
    return "%s %s" % (v[0], json.dumps(v[1], ensure_ascii=False))


def lines(nid, old, new):
    """The summary's narrator lines (m1-plan §5.3): `내레이터: <id> <lang> <engine> "<style>" (새로|old → new|삭제)`."""
    out = []
    langs = set(((old or {}).get("voice") or {}) if isinstance(old, dict) else {}) | \
        set(((new or {}).get("voice") or {}) if isinstance(new, dict) else {})
    for lang in sorted(langs):
        a, b = _voice(old, lang), _voice(new, lang)
        if a == b:
            continue
        if a is None:
            out.append("내레이터: %s %s %s (새로)" % (nid, lang, voice_text(b)))
        elif b is None:
            out.append("내레이터: %s %s (삭제, 전: %s)" % (nid, lang, voice_text(a)))
        else:
            out.append("내레이터: %s %s %s → %s" % (nid, lang, voice_text(a), voice_text(b)))
    return out
