"""guildcore.checks.pmcache — ONE engine-owned Corepack home for the deps step and the offline checks (0.102.12).

japanlifeinfo #227 (0.102.11, `007-check-developer/out/raw.txt`): `$ pnpm exec turbo run test` → `! Corepack is about to
download https://registry.npmjs.org/pnpm/-/pnpm-8.15.0.tgz` → `getaddrinfo ENOTFOUND registry.npmjs.org`, rc 1, and the
execute stage paused "테스트 요약 형식을 읽지 못함". `check_env` points `XDG_CACHE_HOME` at the run's fresh tmp, so Corepack
(no `COREPACK_HOME`) saw an empty `$XDG_CACHE_HOME/node/corepack` on every run, and the offline sandbox refused the
download — while the user's own cache (`~/.cache/node/corepack/pnpm/8.15.0`) had it.

Now (lead decision M4):
* `home()` — `~/.cache/guild-engine/corepack`, engine-owned, shared by every repo and run (a role never writes it);
* the deps step (networked) SEEDS it from the user's existing Corepack cache (read-only source: `$COREPACK_HOME`,
  `$XDG_CACHE_HOME/node/corepack`, `~/.cache/node/corepack`, `~/Library/Caches/node/corepack`) for the version
  package.json's `packageManager` pins — only a usable install (with its `.corepack` file: the `v1/<name>/<version>`
  layout; a pre-0.20 folder without one is not reused by Corepack 0.34.5 — measured). 0.102.13 (review-0102-12 m7):
  #227's user cache DOES hold the usable `~/.cache/node/corepack/v1/pnpm/8.15.0/.corepack` (2024-12-07) — the
  0.102.12 note said otherwise; a seeded copy made read-only runs `pnpm@8.15.0` offline (`COREPACK_ENABLE_NETWORK=0`,
  measured with 0.34.5, Corepack writes nothing there) — then prefetches it
  (`corepack install`, through the registry-only proxy: Corepack honours HTTP(S)_PROXY) when still missing;
* every check env carries `COREPACK_HOME=<home>` + `COREPACK_ENABLE_DOWNLOAD_PROMPT=0`, and an OFFLINE one also
  `COREPACK_ENABLE_NETWORK=0` (Corepack fails at once with a clear error instead of trying the registry);
* `offline_fetch_failure(raw)` — the output of a package-manager fetch that failed offline (`Corepack is about to
  download`, `ENOTFOUND` / `EAI_AGAIN` for a registry, `COREPACK_ENABLE_NETWORK`, `fetch failed`): an `env` stop
  (`engine-env-package-manager-offline`), never "the summary format is unreadable".
pnpm's store and Yarn's cache are not needed by an offline `pnpm exec` / `yarn run` (no fetch) — not managed here.
"""

import json
import os
import re
import shutil

PM_RE = re.compile(r"^(pnpm|yarn|npm)@(\d+\.\d+\.\d+[^+\s]*)")
OFFLINE_RE = re.compile(r"Corepack is about to download|COREPACK_ENABLE_NETWORK|Network access disabled by the environment|"
                        r"(?:ENOTFOUND|EAI_AGAIN|ECONNREFUSED)\s+(?:registry\.npmjs\.org|registry\.yarnpkg\.com|"
                        r"repo\.yarnpkg\.com)|Error when performing the request to https://(?:registry|repo)\.", re.I)
# 0.102.13 (review-0102-12 m5): `Usage Error: This project is configured to use pnpm` is a package-manager MISMATCH (e.g.
# `yarn test` in a pnpm repo) — a config error, not an empty offline cache
MISMATCH_RE = re.compile(r"Usage Error: This project is configured to use \w+", re.I)


def home(base=None):
    return os.path.join(base or os.path.expanduser("~"), ".cache", "guild-engine", "corepack")


def package_manager(root):
    """(name, version) of package.json's `packageManager` (`pnpm@8.15.0+sha512.…` → ("pnpm", "8.15.0")), or None."""
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
            pm = json.load(fh).get("packageManager")
    except (IOError, OSError, ValueError, AttributeError):
        return None
    m = PM_RE.match(str(pm or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _layouts(base, name, ver):
    return [os.path.join(base, "v1", name, ver), os.path.join(base, name, ver)]


def _usable(d):
    """An install Corepack reuses: its folder holds `.corepack` (locator, hash, bin) — measured with Corepack 0.34.5:
    a folder without it (the pre-0.20 layout `~/.cache/node/corepack/pnpm/8.15.0`) is downloaded again."""
    return os.path.isfile(os.path.join(d, ".corepack"))


def present(base, name, ver):
    """The engine home has a usable install (Corepack ≥ 0.20 reads `<home>/v1/<name>/<version>`)."""
    return _usable(os.path.join(base, "v1", name, ver))


def user_sources(env=None, user_home=None):
    """The user's existing Corepack caches (read-only seed sources), the engine's own excluded."""
    e = env or os.environ
    uh = user_home or os.path.expanduser("~")
    out = []
    for d in (e.get("GUILD_USER_COREPACK_HOME"), e.get("COREPACK_HOME"),
              os.path.join(e["XDG_CACHE_HOME"], "node", "corepack") if e.get("XDG_CACHE_HOME") else None,
              os.path.join(uh, ".cache", "node", "corepack"), os.path.join(uh, "Library", "Caches", "node", "corepack")):
        if d and os.path.isdir(d) and os.path.realpath(d) != os.path.realpath(home(user_home)) and d not in out:
            out.append(d)
    return out


def seed(root, env=None, user_home=None, dest=None):
    """Copy the pinned version from a user cache into the engine home when it is not there yet → a note, or None
    (no `packageManager`, already present, or no source has it)."""
    pm = package_manager(root)
    if pm is None:
        return None
    dest = dest or home(user_home)
    name, ver = pm
    if present(dest, name, ver):
        return None
    for src in user_sources(env, user_home):
        for s in _layouts(src, name, ver):
            if _usable(s):
                d = os.path.join(dest, "v1", name, ver)
                tmp = d + ".seed-tmp"
                try:
                    shutil.rmtree(tmp, True)  # fs-ok: engine-owned corepack home (a half copy of an earlier seed)
                    os.makedirs(os.path.dirname(d), exist_ok=True)  # fs-ok: engine-owned ~/.cache/guild-engine/corepack
                    shutil.copytree(s, tmp, symlinks=True)  # fs-ok: engine-owned ~/.cache/guild-engine/corepack (seed copy)
                    os.replace(tmp, d)  # fs-ok: engine-owned ~/.cache/guild-engine/corepack (seed copy)
                except (OSError, shutil.Error) as e:
                    shutil.rmtree(tmp, True)  # fs-ok: engine-owned corepack home (failed seed copy)
                    return "corepack seed of %s@%s from %s failed: %s" % (name, ver, src, e)
                return "corepack: seeded %s@%s from %s" % (name, ver, src)
    return None


def env_for(env, offline, user_home=None):
    """`env` with the engine's Corepack home; `offline` also turns Corepack's network off."""
    e = dict(env or {})
    e["COREPACK_HOME"] = home(user_home)
    e["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    if offline:
        e["COREPACK_ENABLE_NETWORK"] = "0"
    else:
        e.pop("COREPACK_ENABLE_NETWORK", None)
    return e


def offline_fetch_failure(raw):
    """The first output line that shows a package-manager fetch failing offline, or None."""
    for ln in (raw or "").split("\n"):
        if OFFLINE_RE.search(ln):
            return " ".join(ln.split())[:200]
    return None


def mismatch_failure(raw):
    """The first output line that shows the command used another package manager than package.json pins, or None."""
    for ln in (raw or "").split("\n"):
        if MISMATCH_RE.search(ln):
            return " ".join(ln.split())[:200]
    return None


def mismatch_line(where, raw, root=None):
    """The `env` stop line for a package-manager mismatch (the command's tool is not the one package.json pins)."""
    pm = package_manager(root) if root else None
    return ("engine-env-package-manager-mismatch: %s — the command runs another package manager than package.json's "
            "packageManager (%s): %s — set commands.test (and commands.*) to the pinned package manager, then "
            "continue" % (where, "%s@%s" % pm if pm else "-", mismatch_failure(raw) or "-"))


def offline_line(where, raw, root=None):
    """The `env` stop line for an offline package-manager fetch failure (names the cache and the way to fill it)."""
    pm = package_manager(root) if root else None
    spec = "%s@%s" % pm if pm else "the packageManager version"
    return ("engine-env-package-manager-offline: %s — the offline suite needed %s, which is not in the engine's "
            "Corepack cache (%s): %s — run `COREPACK_HOME=%s corepack install` in the repo (or let the deps step "
            "reach the registry), then continue" % (where, spec, home(), offline_fetch_failure(raw) or "-", home()))
