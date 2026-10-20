"""Studio's shared script code (copied into a repository's .claude/studio/scripts/ by init).

Python standard library only. Entry scripts set sys.dont_write_bytecode = True so no
__pycache__ is left in the repository.
"""

# The scripts' own version: bumped only when scripts/ change (not with the plugin version).
# The guard compares it with the copy in a repository's .claude/studio/scripts/ (plan §3.5).
SCRIPTS_VERSION = "4"
