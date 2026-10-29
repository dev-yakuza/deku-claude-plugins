"""Gate tuples (00-plan §3.2; m0b1-plan §4)."""

ENGINE_VOICE = ("tts", "templates", "defaults_voice")
ENGINE_SCREEN = ("composer", "renderer", "ffmpeg", "defaults_presentation")

OWNER = {"brief_core": "1", "content": "1", "source_hash": "1",
         "voice": "2", "audio": "2", "presentation": "3", "render": "4a", "renders": "4b", "copy": "4b",
         "credits": "4b"}
for _k in ENGINE_VOICE:
    OWNER["engine." + _k] = "2"
for _k in ENGINE_SCREEN:
    OWNER["engine." + _k] = "3"


def tuple_for(gate, cur, output=None, platform=None, platform_outputs=None):
    t = {}
    if gate in ("1",):
        t.update(brief_core=cur["brief_core"], content=cur["content"], source_hash=cur["source_hash"])
        return t
    if gate == "4b":
        t.update(content=cur["content"], source_hash=cur["source_hash"],
                 renders={o: cur["render"].get(o) for o in (platform_outputs or [])},
                 copy=cur["copy"].get(platform),
                 credits=cur.get("credits"))  # the credit lines the copy shows (M1h review Y3)
        return t
    t.update(brief_core=cur["brief_core"], content=cur["content"], voice=cur["voice"], audio=cur["audio"])
    for k in ENGINE_VOICE:
        t["engine." + k] = cur["engine"].get(k)
    if gate == "2":
        return t
    t["presentation"] = cur["presentation"].get(output)
    for k in ENGINE_SCREEN:
        t["engine." + k] = cur["engine"].get(k)
    if gate == "3":
        return t
    t["render"] = cur["render"].get(output)
    return t


def changed(recorded, current):
    keys = set(recorded) | set(current)
    return sorted(k for k in keys if recorded.get(k) != current.get(k))
