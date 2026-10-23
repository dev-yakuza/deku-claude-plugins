"""The sandbox proxy mode (00-plan §3.4 "대행 모드", m0d2-plan §7.1) — the rule lives in `stdo/sandbox.py`, shared
with run_s2v.py's watermark (m1-plan §4.2): only when the guard's own environment has STUDIO_SANDBOX=1 (set by the
person who started Claude Code; a command that sets it is denied) and the repository lies under `sandbox_root` of the
per-user `studio-sandbox.json`."""

from ..sandbox import active  # noqa: F401
