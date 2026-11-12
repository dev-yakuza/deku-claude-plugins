# Removing Studio from a repository

[한국어](removing.ko.md) · [日本語](removing.ja.md)

Run these commands in a terminal, not through Claude Code. They take Studio out of the branch each worktree has
checked out; your own files stay. A repository can have several worktrees (`git worktree list`): steps marked
**per worktree** run in each of them, steps marked **per clone** run once, in any of its worktrees. Every block starts
from the worktree's top folder. The blocks are for bash, zsh or sh (not fish); paste each one whole.

Not covered:

- Other branches still hold the harness. Merging or checking out one of them brings it back; remove it there the same
  way.
- `studio-backup/<repo_key>/` of a worktree that was already removed or moved cannot be found (the folder names are
  hashes of the worktree's path). It only takes disk space; look for it by date under
  `~/.claude/studio-backup/` (or `$CLAUDE_CONFIG_DIR/studio-backup/`).

## Studio's folders (per worktree, in each terminal)

Studio keeps files outside the repository, in folders named by a key: the first 16 hex digits of the sha256 of the
worktree's real path (`<repo_key>`) or of the clone's git common folder (`<common_key>`). This block finds them and
`studio_root` (Studio's folder in the repository, `studio` unless you chose another). Run it first, in the same
terminal as the steps after it, with the same `CLAUDE_CONFIG_DIR` as Claude Code. It needs only git and python3, so it
also works in a worktree whose branch has no harness.

<!-- run: folders -->
```sh
cd "$(git rev-parse --show-toplevel)"
unset sr wt_key wt_backup clone_backup
eval "$(python3 -B - <<'EOF'
import hashlib, json, os, shlex, subprocess

def git(*args):
    return subprocess.run(("git",) + args, capture_output=True, text=True, check=True).stdout.strip()

def key(path):
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]

home = os.environ.get("STUDIO_HOME") or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
backups = os.path.join(home, "studio-backup")
top = git("rev-parse", "--show-toplevel")
common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
sr = None
for f in (".claude/studio/config.json", os.path.join(backups, key(common), "marker")):
    try:
        with open(f, encoding="utf-8") as fh:
            sr = sr or json.load(fh).get("studio_root")
    except (OSError, ValueError, AttributeError):
        pass
sr = (sr if isinstance(sr, str) else "studio").strip("/") or "studio"
if os.path.isabs(sr) or ".." in sr.split("/") or sr == ".":
    raise SystemExit("studio_root %r looks wrong: stop and check it" % sr)
for name, value in (("sr", sr), ("wt_key", key(top)), ("wt_backup", os.path.join(backups, key(top))),
                    ("clone_backup", os.path.join(backups, key(common)))):
    print("%s=%s" % (name, shlex.quote(value)))
EOF
)"
printf 'studio_root:   %s\nthis worktree: %s\nthis clone:    %s\n' "$sr" "$wt_backup" "$clone_backup"
```

`this worktree` is `studio-backup/<repo_key>/` (backups of git-ignored videos, the internal overlay's hash);
`this clone` is `studio-backup/<common_key>/` (the marker that says Studio was installed here).

## 0. Keep what you want to keep (per worktree, before step 1)

This copies the whole `studio_root` folder (committed and git-ignored videos, `local/videos`, renders in `out/`, texts
in `copy/`), both backup folders and `.claude/studio/local/config.internal.json` (the internal overlay you typed) to
`~/studio-kept/<repo_key>/`, a folder that must not exist yet. Change `$HOME/studio-kept` to keep them elsewhere,
outside the repository.

<!-- run: keep -->
```sh
keep="$HOME/studio-kept/${wt_key:?run the folders block first}"
mkdir -p "$HOME/studio-kept" && mkdir "$keep" &&
  { [ ! -d "$sr" ] || cp -Rp "$sr" "$keep/studio-root"; } &&
  { [ ! -d "$wt_backup" ] || cp -Rp "$wt_backup" "$keep/studio-backup-worktree"; } &&
  { [ ! -d "$clone_backup" ] || cp -Rp "$clone_backup" "$keep/studio-backup-clone"; } &&
  { [ ! -f .claude/studio/local/config.internal.json ] ||
    cp -p .claude/studio/local/config.internal.json "$keep/config.internal.json"; } &&
  echo "kept in $keep"
```

Which hook manager Studio uses in this worktree (needed in steps 2 and 3; a branch without the harness has no
`hooks.py`):

<!-- run: hook-status -->
```sh
python3 .claude/studio/scripts/hooks.py status
```

## 1. Uninstall the plugin

In Claude Code, in the repository:

```text
/plugin uninstall studio-plugin@deku-claude-plugins --scope project
```

Use the scope you installed with (`--scope local` or `--scope user` instead). If `.claude/settings.json` still lists
`"studio-plugin@deku-claude-plugins"` under `enabledPlugins`, remove that entry, keeping the JSON valid; step 3 commits
the change. Quit Claude Code before the next steps.

## 2. The hook (per clone, once)

This takes out Studio's pre-commit shim and puts back the hook it had chained (the plain-git case; nothing happens when
there is no shim, and a tracked hook file — husky, a hooks folder in the repository — is never touched), checks
`pre-commit.legacy` too (the pre-commit framework moves the hook it finds there when it is installed again after
Studio), and deletes Studio's runner folder (`<git common dir>/studio/`, also the used-answer record) and Studio's block
in `info/exclude`. When it prints that `pre-commit.studio-chained` is left, `pre-commit` is not Studio's shim and that
file is your earlier hook: put it back by hand.

<!-- run: clone -->
```sh
cd "$(git rev-parse --show-toplevel)"
(
  set -e
  h=$(git rev-parse --git-path hooks)
  shim() { grep -qs "Studio's pre-commit shim" "$1" && ! git ls-files --error-unmatch -- "$1" >/dev/null 2>&1; }
  if shim "$h/pre-commit"; then
    rm "$h/pre-commit"
    [ ! -e "$h/pre-commit.studio-chained" ] || mv "$h/pre-commit.studio-chained" "$h/pre-commit"
  fi
  if shim "$h/pre-commit.legacy"; then
    rm "$h/pre-commit.legacy"
    if grep -qs 'File generated by pre-commit' "$h/pre-commit.studio-chained"; then
      rm "$h/pre-commit.studio-chained"
    elif [ -e "$h/pre-commit.studio-chained" ]; then
      mv "$h/pre-commit.studio-chained" "$h/pre-commit.legacy"
    fi
  fi
  [ ! -e "$h/pre-commit.studio-chained" ] || echo "left: $h/pre-commit.studio-chained (your earlier hook; put it back by hand)"
  c=$(git rev-parse --path-format=absolute --git-common-dir)
  rm -rf "$c/studio"
  if [ -f "$c/info/exclude" ]; then
    if [ "$(grep -c '^# >>> studio ' "$c/info/exclude")" != "$(grep -c '^# <<< studio <<<' "$c/info/exclude")" ]; then
      echo "info/exclude: Studio's block markers are unpaired: fix them by hand, then run this again" >&2; exit 1
    fi
    sed '/^# >>> studio /,/^# <<< studio <<</d' "$c/info/exclude" > "$c/info/exclude.studio-tmp"
    mv "$c/info/exclude.studio-tmp" "$c/info/exclude"
  fi
)
```

When `hooks.py status` said **global-path** (`core.hooksPath` outside the repository), you added Studio's line to that
hook by hand; change it before step 3: `sh "$(git rev-parse --git-common-dir)/studio/pre-commit" || exit $?`. While other repositories still
use Studio, replace it with
`if [ -f "$(git rev-parse --git-common-dir)/studio/pre-commit" ]; then sh "$(git rev-parse --git-common-dir)/studio/pre-commit" || exit $?; fi`;
otherwise delete it.

## 3. The files in the repository (per worktree)

This deletes the Studio block of `lefthook-local.yml` (the lefthook case; the file goes when nothing else is in it),
Studio's tracked and git-ignored files (`.claude/studio/`, `.claude/agents/std-*.md`, the `studio_root` folder) and
Studio's block in `.gitignore` (an empty `.gitignore` is deleted), stages `.claude/settings.json` when you changed it in
step 1, then commits. Run step 2 first: Studio's hook would refuse this commit. Start with nothing staged (the block
refuses otherwise, so the commit holds only Studio's removal), and it stops without changing anything when a Studio
block's markers are unpaired.

<!-- run: worktree -->
```sh
cd "$(git rev-parse --show-toplevel)"
(
  set -e
  : "${sr:?run the folders block first}"
  git diff --cached --quiet || { echo "Studio removal: changes are already staged: commit or unstage them first" >&2; exit 1; }
  unpaired() { [ -f "$1" ] && [ "$(grep -c "$2" "$1")" != "$(grep -c "$3" "$1")" ]; }
  if unpaired lefthook-local.yml '^# >>> studio:hook >>>' '^# <<< studio:hook <<<' ||
      unpaired .gitignore '^# >>> studio ' '^# <<< studio <<<'; then
    echo "Studio's block markers are unpaired in lefthook-local.yml or .gitignore: fix them by hand, then run this again" >&2
    exit 1
  fi
  if [ -f lefthook-local.yml ]; then
    sed '/^# >>> studio:hook >>>/,/^# <<< studio:hook <<</d' lefthook-local.yml > lefthook-local.yml.studio-tmp
    mv lefthook-local.yml.studio-tmp lefthook-local.yml
    [ -n "$(tr -d '[:space:]' < lefthook-local.yml)" ] || rm lefthook-local.yml
  fi
  git rm -r -q -f --ignore-unmatch .claude/studio '.claude/agents/std-*.md' "$sr"
  rm -rf .claude/studio "${sr:?run the folders block first}"
  if [ -f .gitignore ]; then
    sed '/^# >>> studio /,/^# <<< studio <<</d' .gitignore > .gitignore.studio-tmp
    mv .gitignore.studio-tmp .gitignore
    if [ -n "$(tr -d '[:space:]' < .gitignore)" ]; then git add .gitignore; else git rm -q -f --ignore-unmatch .gitignore; rm -f .gitignore; fi
  fi
  git diff --quiet -- .claude/settings.json || git add .claude/settings.json
  git commit -q -m "Remove Studio"
)
```

A branch without the harness has nothing to commit (git says so).

When `hooks.py status` said **husky** or **custom-tracked**, the tracked `.husky/pre-commit` (or your hooks folder's
`pre-commit`) has Studio's block between `# >>> studio:hook >>>` and `# <<< studio:hook <<<`. The block runs nothing
where Studio is not set up; delete it only when Studio is gone from every branch.

## 4. The folders outside the repository

Per worktree, after step 3:

<!-- run: backups-worktree -->
```sh
rm -rf "${wt_backup:?run the folders block first}"
```

Per clone, after the last worktree:

<!-- run: backups-clone -->
```sh
rm -rf "${clone_backup:?run the folders block first}"
```

Removing Studio from this machine entirely (after every repository): also its sandbox file and the empty backup
folder.

```sh
rm -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/studio-sandbox.json"
rmdir "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/studio-backup"
```
