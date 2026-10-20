"""state.py's subcommands, classified for the guard (00-plan §3.4): a subcommand not listed as
evidence-free needs a person's answer (closed side)."""

# stage-done records a stage's completion, not a person's decision: evidence-free
EVIDENCE_FREE = frozenset(["next", "record-brief", "loop", "status", "sync", "shown", "stage-done"])
# M0b-2: these record a person's decision and consume the guard's evidence (exit 6 without it)
APPROVAL = frozenset(["approve", "reject-source-diff", "repin", "exclude-output", "unlock"])
EVIDENCE = frozenset(["approve", "approve-actor", "credit", "unlock", "abandon", "move", "overlay",
                      "exclude-output", "rollback"])
IMPLEMENTED = frozenset(["next", "record-brief", "loop", "status", "sync", "stage-done",  # M0b-1
                         "shown", "approve", "reject-source-diff", "repin", "exclude-output", "unlock"])


def needs_evidence(name):
    return name not in EVIDENCE_FREE

# exit codes (also in commands/atoms/_contract.md)
OK, FAIL, USAGE, REFUSED, WAIT, BUSY, NO_EVIDENCE = 0, 1, 2, 3, 4, 5, 6
