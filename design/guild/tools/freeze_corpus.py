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
    무엇이 증거가 될지 지금 결정하지 않는다(로그·매니페스트·보드 상태 전부)."""
    out = []
    for d, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(d, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            out.append((os.path.relpath(p, root), p))
    return sorted(out)


def freeze(src, name, archive):
    if not os.path.isdir(src):
        return None, "원본이 디렉터리가 아니다: %s" % src
    files = walk(src)
    if not files:
        return None, "원본에 파일이 없다: %s" % src
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(archive, name, stamp)
    os.makedirs(dst, exist_ok=False)
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
           "files": len(entries), "bytes": total, "entries": entries}
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
    extra = {r for r, _ in walk(frozen)} - {e["path"] for e in man["entries"]} - {"MANIFEST.json"}
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
