#!/usr/bin/env python3
"""측정 코퍼스를 **지속 경로**에 얼린다 — 스크래치패드가 아니라.

WHY THIS EXISTS
---------------
이 작업에서 코퍼스를 **두 번** 잃었다:

  1. arm-A 동결본을 세션 스크래치패드(`/private/tmp/claude-.../scratchpad`)에 뒀다가
     `/tmp` 정리로 날아갔다. 레포 원본이 살아 있어 타임스탬프 경계로 복구했지만,
     그사이 스프린트 389 에 새 attempt 가 쌓여 **arm-A 와 arm-B 가 섞일 뻔했다.**
  2. `word_app` 의 **유인 `/gld dev` 트랜스크립트 133개**가 통째로 사라졌다
     (`sessions-index.json` 에 항목만 남고 `.jsonl` 은 0개). 그 로그는
     **A2(유인/무인 읽기 행동이 같은가)와 M10(호출 시점 분포)을 닫을 유일한 데이터**였다.
     복구 경로가 없다.

⚠ 둘은 성질이 다르다. (1)은 **내 부주의**, (2)는 **호스트가 회전시킨 것**이다. 전자는 경로만
바꾸면 되고, 후자는 **사라지기 전에 복사해 두는 것** 말고 방법이 없다.

⚠⚠ 이것은 A20 의 다른 얼굴이다. A20 은 «라이브 소스에 대고 재면 실행마다 수가 변한다» 였고,
여기는 «라이브 소스는 **사라지기도 한다**» 다. §11 이 도구 출력에 «동결 스냅샷에 대고 돌려라»
를 적게 만든 그 문제의 극단.

WHAT IT DOES
------------
    freeze_corpus.py --src <dir> --name <label> [--archive <dir>]

`<archive>/<label>/<YYYYMMDD-HHMMSS>/` 에 복사하고 `MANIFEST.json` 을 쓴다:
파일별 크기·sha256, 원본 경로, 동결 시각. 그리고 **검증**한다 — 복사본이 원본과 바이트 단위로
같은지 즉시 확인하고, 아니면 **실패**한다(조용히 반쪽 복사하지 않는다).

기본 archive 는 `~/.claude/guild-corpus` — **`/tmp` 가 아니고 레포 안도 아니다**:
레포에 넣으면 200MB 로그가 git 에 들어가고, `/tmp` 에 넣으면 이 파일이 존재하는 이유가 된다.

    --verify <동결디렉터리>   이미 얼린 것이 MANIFEST 와 여전히 일치하는지 확인
    --list                   archive 에 무엇이 있는지

⚠ **얼린 뒤에는 원본이 변해도 된다.** 그것이 목적이다 — 스프린트 389 처럼 같은 디렉터리에
다른 팔의 로그가 쌓여도, 이미 얼린 팔은 그대로다.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys

DEFAULT_ARCHIVE = os.path.expanduser("~/.claude/guild-corpus")


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def walk(root):
    """root 아래 **모든 파일**을 (상대경로, 절대경로) 로. 확장자를 가리지 않는다 —
    무엇이 증거가 될지 지금 결정하지 않는다(로그·매니페스트·보드 상태 전부).

    반환: (files, skipped_dir_links). 두 번째가 비어 있지 않으면 **호출부가 경고해야 한다.**

    ⚠⚠ **심볼릭 링크를 조용히 건너뛰면 안 된다.** 첫 판이 `islink` 를 전부 `continue` 했고,
    그래서 **Guild 자신의 `memory` 심볼릭 링크**(`§8.1b` — 런의 신호를 워크트리 밖으로
    나르는 바로 그 링크)가 동결본에서 **말없이 빠졌다**. 실측: 원본 2파일 중 1파일만 얼렸다.
    「무엇이 증거가 될지 지금 결정하지 않는다」고 적어 놓고 조용히 결정하고 있었다.

    → **파일 링크는 따라가 내용을 얼린다**(그것이 신호다). **디렉터리 링크는 따라가지 않되
    목록으로 돌려준다** — 따라가면 순환·중복 트리 위험이 있고, 그 판단은 사람 몫이다.
    """
    out, skipped = [], []
    for d, dirs, fs in os.walk(root, followlinks=False):
        for sub in sorted(dirs):
            sp = os.path.join(d, sub)
            if os.path.islink(sp):
                skipped.append((os.path.relpath(sp, root), os.path.realpath(sp)))
        for f in sorted(fs):
            fp = os.path.join(d, f)
            if not os.path.isfile(fp):
                # ⚠ 끊어진 링크·소켓 등. **조용히 버리지 않는다** — 빠진 것이 기록에 없으면
                #    「전부 얼렸다」로 읽힌다(디렉터리 링크와 같은 이유).
                skipped.append((os.path.relpath(fp, root), os.path.realpath(fp)))
                continue
            out.append((os.path.relpath(fp, root), fp))
    return sorted(out), sorted(skipped)


def _nested(a, b):
    """a 가 b 안에(또는 같은 곳에) 있는가."""
    a, b = os.path.abspath(a) + os.sep, os.path.abspath(b) + os.sep
    return a.startswith(b) or b.startswith(a)


def freeze(src, name, archive):
    if not os.path.isdir(src):
        return None, "원본이 디렉터리가 아니다: %s" % src
    # ⚠⚠ **archive 가 src 안에 있으면 동결본이 자기 자신을 삼킨다.** 실측: 같은 src 를 두 번
    #    얼리자 두 번째가 **1파일이 아니라 3파일**(첫 동결본 포함)이 됐다. 코퍼스의 정의가
    #    조용히 오염되는 것이고, 그 수로 잰 결과는 되돌릴 수 없다.
    if _nested(archive, src):
        return None, ("archive 가 원본 안(또는 그 반대)이다 — 동결본이 자기를 삼킨다:\n"
                      "  src=%s\n  archive=%s" % (os.path.abspath(src), os.path.abspath(archive)))
    files, dirlinks = walk(src)
    if not files:
        return None, "원본에 파일이 없다: %s" % src
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(archive, name, stamp)
    # ⚠ 같은 초에 같은 이름으로 두 번 얼리면 첫 판은 **FileExistsError 트레이스백**으로 죽었다
    #    (실측). 스크립트로 여러 코퍼스를 도는 흔한 경우이고, 죽을 이유가 없다 — 접미사를 붙인다.
    for n in range(2, 100):
        if not os.path.exists(dst):
            break
        dst = os.path.join(archive, name, "%s-%d" % (stamp, n))
    os.makedirs(dst, exist_ok=False)
    # ⚠⚠ **실패하면 반쪽 동결본을 지운다.** 첫 판은 읽기 권한이 없는 파일 하나에
    #    `PermissionError` 트레이스백으로 죽으면서 **MANIFEST 없는 디렉터리를 남겼다** —
    #    그것은 나중에 동결본처럼 보이고, `--verify` 는 「이 도구가 얼린 것이 아니다」라고만
    #    말한다. 절반만 얼린 코퍼스로 잰 수는 되돌릴 수 없다.
    try:
        return _copy_all(src, dst, name, stamp, files, dirlinks)
    except OSError as e:
        shutil.rmtree(dst, ignore_errors=True)
        return None, "복사 실패 — 반쪽 동결본을 지웠다: %s" % e


def _copy_all(src, dst, name, stamp, files, dirlinks):
    entries, total = [], 0
    for rel, ap in files:
        tp = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        shutil.copy2(ap, tp)
        # ⚠ **복사 직후 검증한다.** 반쪽 복사를 「동결 완료」로 기록하면, 나중에 그것으로 잰
        #    수가 틀렸을 때 원인을 찾을 수 없다.
        # ⚠⚠ **이 가드는 변이로 발화시킬 수 없다 — 그래서 스위트에 검사를 만들지 않았다.**
        #    `shutil.copy2` 는 건강한 파일시스템에서 다른 사본을 만들지 않으므로, `if False:`
        #    로 바꿔도 테스트가 붉어지지 않는다(실측). 이 가드가 겨냥하는 것은 **디스크가
        #    찼거나 쓰기가 잘린 경우**이고 그것은 유닛 테스트로 재현할 수 없다.
        #    「발화할 수 없는 검사를 만들지 않는다」는 규율에 따라, 검사 대신 이 주석을 남긴다 —
        #    이 작업에서 **일곱 번** 만든 공허한 검사를 여덟 번째로 만들지 않기 위해서다.
        s1, s2 = sha256(ap), sha256(tp)
        if s1 != s2:
            return None, "복사가 원본과 다르다: %s" % rel
        sz = os.path.getsize(tp)
        total += sz
        entries.append({"path": rel, "bytes": sz, "sha256": s1})
    man = {"name": name, "frozen_at": stamp, "source": os.path.abspath(src),
           "files": len(entries), "bytes": total, "entries": entries,
           # ⚠ 안 얼린 것을 **기록한다.** 빠진 것이 매니페스트에 없으면 「전부 얼렸다」로 읽힌다.
           "skipped": [{"path": r, "target": t} for r, t in dirlinks]}
    with open(os.path.join(dst, "MANIFEST.json"), "w") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    return dst, None


def verify(frozen):
    mp = os.path.join(frozen, "MANIFEST.json")
    if not os.path.isfile(mp):
        return ["MANIFEST.json 이 없다 — 이 디렉터리는 이 도구가 얼린 것이 아니다"]
    man = json.load(open(mp))
    bad = []
    for e in man["entries"]:
        p = os.path.join(frozen, e["path"])
        if not os.path.isfile(p):
            bad.append("사라짐: " + e["path"]); continue
        if os.path.getsize(p) != e["bytes"] or sha256(p) != e["sha256"]:
            bad.append("변경됨: " + e["path"])
    extra = {r for r, _ in walk(frozen)[0]} - {e["path"] for e in man["entries"]} - {"MANIFEST.json"}
    bad += ["추가됨: " + x for x in sorted(extra)]
    return bad


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--src")
    p.add_argument("--name")
    p.add_argument("--archive", default=DEFAULT_ARCHIVE)
    p.add_argument("--verify")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()

    if a.list:
        if not os.path.isdir(a.archive):
            print("archive 가 아직 없다: %s" % a.archive); return 0
        for name in sorted(os.listdir(a.archive)):
            nd = os.path.join(a.archive, name)
            if not os.path.isdir(nd):
                continue
            for stamp in sorted(os.listdir(nd)):
                mp = os.path.join(nd, stamp, "MANIFEST.json")
                if os.path.isfile(mp):
                    m = json.load(open(mp))
                    print("  %-22s %s  %5d파일 %10s B  ← %s"
                          % (name, stamp, m["files"], format(m["bytes"], ","), m["source"]))
        return 0

    if a.verify:
        bad = verify(a.verify)
        if not bad:
            print("동결본이 MANIFEST 와 일치한다: %s" % a.verify); return 0
        for b in bad:
            print("불일치: " + b)
        return 1

    if not (a.src and a.name):
        print(__doc__); return 2
    dst, err = freeze(a.src, a.name, a.archive)
    if err:
        print("실패: " + err, file=sys.stderr); return 1
    man = json.load(open(os.path.join(dst, "MANIFEST.json")))
    print("얼렸다: %s\n  %d파일 · %s B · 원본 %s"
          % (dst, man["files"], format(man["bytes"], ","), man["source"]))
    sk = man.get("skipped") or []
    if sk:
        # ⚠ **경고는 stderr 로, 조용히 넘어가지 않는다.** Guild 의 `memory` 링크가 여기 걸린다.
        sys.stderr.write("⚠ 얼리지 않은 항목 %d개 (디렉터리 링크·끊어진 링크 — MANIFEST 에 기록):\n" % len(sk))
        for e in sk:
            sys.stderr.write("    %s → %s\n" % (e["path"], e["target"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
