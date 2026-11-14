# fix-0102 §1.5: the reference for verify.json and verify.md without teaching notes — verify_json and verify_md of
# stdo/claims/check.py at f60349f (0.1.1), unchanged (they import nothing). Do not edit.
"""0.1.1's verify.json and verify.md (a video without teaching notes gets these bytes from 0.1.2 too)."""


def verify_json(state, lang, draft, shas):
    return {"schema": 1, "video": state["video"], "lang": lang, "from": shas,
            "sentences": [{k: s.get(k) for k in ("text", "kind", "verdict", "claims", "excerpts", "note")
                           if s.get(k) is not None} for s in draft["sentences"]]}


def verify_md(v):
    facts = [s for s in v["sentences"] if s["kind"] == "fact"]
    links = [s for s in v["sentences"] if s["kind"] == "link"]
    lines = ["# Verify — %s (%s)" % (v["video"], v["lang"]), "",
             "Made by check_claims.py from verify.json (%d fact sentence(s), %d link sentence(s)); every fact is "
             "supported by the source copy." % (len(facts), len(links)), "", "## Facts", ""]
    for n, s in enumerate(facts, 1):
        lines.append("%d. [%s] %s" % (n, s.get("verdict"), s["text"]))
        for c in s.get("claims") or []:
            lines.append("   - claim %s" % c)
        for e in s.get("excerpts") or []:
            lines.append("   > %s" % e.replace("\n", " "))
        if s.get("note"):
            lines.append("   - note: %s" % s["note"])
    lines += ["", "## Link sentences (not checked against the source — read them)", ""]
    for n, s in enumerate(links, 1):
        lines.append("%d. %s" % (n, s["text"]))
        lines.append("   - why a link: %s" % s.get("note"))
    if not links:
        lines.append("(none)")
    return "\n".join(lines) + "\n"
