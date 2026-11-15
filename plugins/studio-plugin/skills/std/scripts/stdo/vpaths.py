"""Where a video's files are, by its location (the state's `location`, fixed at begin):

    public  <sr>/videos/<v>/        <sr>/out/<v>/<l>/        <sr>/copy/<v>/<l>/
    local   <sr>/local/videos/<v>/  <sr>/local/out/<v>/<l>/  <sr>/local/copy/<v>/<l>/

A local (internal) video keeps everything under `<sr>/local/`: gitignored, backed up with the video, apart from public
videos' files. Every out and copy path of scripts/ is built here (structure_test.sh checks that no other module joins
`out` or `copy` to the studio root). `repo` may be "" for a path relative to the repository."""

import os


def _base(repo, root, state):
    if state.get("location") == "local":
        return os.path.join(repo, root, "local")
    return os.path.join(repo, root)


def video_dir(repo, root, state):
    return os.path.join(_base(repo, root, state), "videos", state["video"])


def out_root(repo, root, state):
    """The video's results folder (every language)."""
    return os.path.join(_base(repo, root, state), "out", state["video"])


def copy_root(repo, root, state):
    """The video's platform copy folder (every language)."""
    return os.path.join(_base(repo, root, state), "copy", state["video"])


def out_dir(repo, root, state, lang):
    return os.path.join(out_root(repo, root, state), lang)


def copy_dir(repo, root, state, lang):
    return os.path.join(copy_root(repo, root, state), lang)


def copy_file(repo, root, state, lang, platform):
    """The platform's copy (the caller checks the name with schema.platform_ok first)."""
    return os.path.join(copy_dir(repo, root, state, lang), platform + ".md")


def audition_dir(repo, root, state, lang):
    return os.path.join(out_dir(repo, root, state, lang), "audition")


def leftovers(repo, root, video):
    """The folders of a video id in either location (begin refuses an id that has any: an abandoned video's renders
    or copy must not be mixed into a new one)."""
    out = []
    for loc in ("public", "local"):
        st = {"video": video, "location": loc}
        out += [video_dir(repo, root, st), out_root(repo, root, st), copy_root(repo, root, st)]
    return out

