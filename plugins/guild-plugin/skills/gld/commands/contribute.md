# CONTRIBUTE (repo→central — upstream a flow/overlay improvement)

**Package a locally-proven flow improvement as an upstream contribution to the central Guild plugin (repo→중앙 기여).** Semi-automatic and human-gated: **candidate → sanitize → dedup → human review → send**. NEVER fully auto-registers (INV5 — 정보 유출). Contributes **flow-base** improvements (the shared spine/policy) — *not* local agent/knowledge evolution, which stays local (두 진화 고도).

`$1` (optional): the overlay area or evolve flow-friction candidate to contribute.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — read config. Resolve the **central repo** from the plugin manifest (`repository`/`homepage` in `plugin.json` — e.g. `dev-yakuza/deku-claude-plugins`). Hold the literal value.

**1. Detect candidates**
- `.claude/guild/overlay/*` — local flow-policy overrides that proved useful (the intended source).
- `.claude/guild/overlay/contribute-candidates.md` — evolve's **"flow friction → upstream-contribution candidate"** flags (friction the spine caused, not locally fixable; `evolve.md`'s Phase 2 flow-friction routing appends one line per flagged item here). Each line has the exact labeled-field shape `- problem: <one-line> — change: <one-line> — evidence: <ref> — evolve #<n>` — parse by these labels, not by positional em-dash splitting (a `problem`/`change` clause may itself contain an em dash). `evolve #<n>` is the provenance link back to the run that flagged it — carry it into the sent issue body (or the dedup search) as a local cross-reference, but sanitize before sending (step 2) since it's a repo-local run number, not upstream-meaningful on its own. Absent/empty → no flags this cycle, not an error.
- **Scope to `$1` when given**: match candidates by filename/area/keyword against `$1` (case-insensitive substring against the overlay file's path or the candidate's `problem`/`change` text) and present only the matches. No match for a given `$1` → say so explicitly ("`$1`과 일치하는 후보 없음") rather than silently falling back to the full list — the human asked for that one area. Empty/absent `$1` → consider all candidates below.
- **Multiple matched candidates** → process **one at a time**, same discipline as `evolve.md` Phase 5: sanitize → dedup → present → confirm/decline for candidate 1 in full before moving to candidate 2. Never bundle several candidates into one combined review — each may dedup against a different upstream issue and needs its own confirm.
- None found (in scope) → "기여할 overlay/flow 개선이 없습니다 (로컬 진화는 로컬에 남깁니다)." Stop.

**2. Sanitize (INV5 — hard requirement)**
1. **Deterministic secret scan first** — do not rely on judgment alone for the one class of leak that is mechanically detectable. Run the candidate text through the commit gate's own scanner (its own Bash call; a bundled `python3 script.py` invocation is a sanctioned `_bash_rules.md` exception). Write the candidate text to a temp file with the Write tool, then feed it in as stdin:
   ```bash
   python3 .claude/guild/gates/scripts/gate_precommit.py --scan-text
   ```
   It prints one `SECRET-TEXT <line-no>` per offending line and exits 1 if any, 0 if clean — **never the value itself**. Any hit → the candidate is blocked until the human confirms the match was removed; never pass a hit through to sub-step (2) "on the assumption it'll get caught there."
   ⚠ **Call the script; do not copy its regexes.** An earlier version of this step said to "reuse `INLINE_SECRET_RES`" from `gate_precommit.py` — but that script had no text-scan entry point at the time (its `main()` only parsed a `PreToolUse` hook payload and self-filtered to `git commit`), so the only way to follow the instruction was to hand-copy a security-critical pattern set into a local grep, where it would drift silently. `--scan-text` exists precisely so this consumer and the commit gate share one definition of "secret".
2. **LLM-judgment generalization** — for a `contribute-candidates.md`-sourced item, its `problem`/`change` fields are already the reusable pattern (evolve wrote them as one-line, already-somewhat-generalized clauses) — this step's job is to strip what's still repo-specific/sensitive from them and from `evidence`: repo/owner names, file paths, proprietary domain detail, the local `evidence: <ref>` (usually a repo-local issue/PR/commit reference — drop it or replace with a generic description), and the local `evolve #<n>` run number (keep for the dedup search below, but do not send it upstream verbatim). For an `overlay/*`-sourced item (no evolve line to start from), generalize freehand into the same shape: problem → proposed flow/base change → why it's broadly useful. This sub-step catches what a deterministic regex can't (context, proprietary naming) — it is a supplement to sub-step (1)'s scan, not a replacement for it.
3. **Show the sanitized form** — nothing leaves the machine un-sanitized, and nothing leaves without having passed sub-step (1)'s scan.

**3. Dedup check** — search the central repo for an equivalent proposal:
```bash
gh issue list --repo <central> --state all --search "<key terms>" --json number,title,state
```
Already proposed → surface it; offer to **comment on the existing** issue instead of opening a duplicate.

**4. Human review + send (INV1)** — present the sanitized contribution + the dedup result; **confirm before sending**. On confirm → open the upstream issue (or a draft PR) on the central repo (`gh issue create --repo <central> --body-file <temp>`), tagged as a Guild flow contribution. Report the link. Decline → keep it local (nothing sent). **Either way, if the candidate came from `.claude/guild/overlay/contribute-candidates.md`, remove that line now** (Edit tool, matching the **original raw line** verbatim as `old_string` — not the sanitized/generalized text step 2 produced, which won't match anything in the file; the `evolve #<n>` suffix uniquely identifies the line even when another pending candidate has similar `problem`/`change` wording) — sent or declined, it shouldn't keep resurfacing as a candidate on the next `/gld contribute` run.

## Hard rules
- **Never fully auto-register** — the chain candidate → sanitize → dedup → human review → send always ends at an explicit human confirm.
- **Sanitize is mandatory** (INV5) — nothing repo-specific or sensitive leaves the machine; the sanitized form is shown first.
- **Flow-base only** — upstreams the central spine/policy improvements; local agent/knowledge/standard evolution stays local (that's what `evolve` is for).
