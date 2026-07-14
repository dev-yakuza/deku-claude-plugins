# CONTRIBUTE (repo→central — upstream a flow/overlay improvement)

**Package a locally-proven flow improvement as an upstream contribution to the central Guild plugin (plan §10 repo→중앙 기여).** Semi-automatic and human-gated: **candidate → sanitize → dedup → human review → send**. NEVER fully auto-registers (INV5 · T4 정보 유출). Contributes **flow-base** improvements (the shared spine/policy) — *not* local agent/knowledge evolution, which stays local (§10 두 진화 고도).

`$1` (optional): the overlay area or evolve flow-friction candidate to contribute.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K).

---

## Process
**0. Preflight** — read config. Resolve the **central repo** from the plugin manifest (`repository`/`homepage` in `plugin.json` — e.g. `dev-yakuza/deku-claude-plugins`). Hold the literal value.

**1. Detect candidates**
- `.claude/guild/overlay/*` — local flow-policy overrides that proved useful (the intended source).
- `evolve`'s **"flow friction → upstream-contribution candidate"** flags (§8 P2 — friction the spine caused, not locally fixable).
- None found → "기여할 overlay/flow 개선이 없습니다 (로컬 진화는 로컬에 남깁니다)." Stop.

**2. Sanitize (INV5 · T4 — hard requirement)**
Strip everything repo-specific/sensitive from the candidate: repo/owner names, file paths, secrets, proprietary domain detail, issue/PR numbers. **Generalize** it into a reusable pattern (problem → proposed flow/base change → why it's broadly useful). **Show the sanitized form** — nothing leaves the machine un-sanitized.

**3. Dedup check** — search the central repo for an equivalent proposal:
```bash
gh issue list --repo <central> --state all --search "<key terms>" --json number,title,state
```
Already proposed → surface it; offer to **comment on the existing** issue instead of opening a duplicate.

**4. Human review + send (INV1)** — present the sanitized contribution + the dedup result; **confirm before sending**. On confirm → open the upstream issue (or a draft PR) on the central repo (`gh issue create --repo <central> --body-file <temp>`), tagged as a Guild flow contribution. Report the link. Decline → keep it local (nothing sent).

## Hard rules
- **Never fully auto-register** (§10) — the chain candidate → sanitize → dedup → human review → send always ends at an explicit human confirm.
- **Sanitize is mandatory** (INV5/T4) — nothing repo-specific or sensitive leaves the machine; the sanitized form is shown first.
- **Flow-base only** — upstreams the central spine/policy improvements; local agent/knowledge/standard evolution stays local (that's what `evolve` is for).
