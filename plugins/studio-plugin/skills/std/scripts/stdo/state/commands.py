"""state.py's subcommands, classified for the guard (00-plan §3.4): a subcommand not listed as
evidence-free needs a person's answer (closed side)."""

# stage-done records a stage's completion, not a person's decision: evidence-free. M1b (m1-plan §4.1, D-M1-2): entering
# a held state and recording a stage's results need no evidence either; leaving one (unlock), stopping a video
# (abandon) and a person's settings (overlay) do.
EVIDENCE_FREE = frozenset(["next", "record-brief", "loop", "status", "sync", "shown", "stage-done",
                           "begin", "record-source", "hold", "release-lock", "record-render", "done"])
# M0b-2: these record a person's decision and consume the guard's evidence (exit 6 without it)
APPROVAL = frozenset(["approve", "reject-source-diff", "repin", "exclude-output", "unlock", "abandon", "overlay"])
EVIDENCE = frozenset(["approve", "approve-actor", "credit", "unlock", "abandon", "move", "overlay",
                      "exclude-output", "rollback"])
IMPLEMENTED = frozenset(["next", "record-brief", "loop", "status", "sync", "stage-done",  # M0b-1
                         "shown", "approve", "reject-source-diff", "repin", "exclude-output", "unlock",
                         # M1b
                         "begin", "record-source", "hold", "release-lock", "record-render", "done", "abandon",
                         "overlay"])


def needs_evidence(name):
    return name not in EVIDENCE_FREE

# exit codes (also in commands/atoms/_contract.md)
OK, FAIL, USAGE, REFUSED, WAIT, BUSY, NO_EVIDENCE = 0, 1, 2, 3, 4, 5, 6
