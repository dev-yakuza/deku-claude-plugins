**무엇을 바꿨나**

리더 요약이 없어 엔진이 기록한 사실로 만든 요약입니다.

- 바뀐 파일 5개 — 검증 경로 1개, 그 밖 4개
- 인수 기준 10개 — 리더 판정 met 10
- 실행 단계 9개 통과, 건너뜀 0개 (최종 HEAD `ef3059a87337`)

**사람이 확인할 것 (Manual Test Checklist)**

- 이 절차에는 qa 단계가 없습니다(수동 확인 항목 없음).

**가정과 검토할 결정**

- 가정: 이 이슈는 테스트만 추가하는 안전망 작업이다. `lib/` 의 운영 코드는 바꾸지 않는다(`safety_net: only`).
- 가정: 선행 이슈 #1933 은 완료(CLOSED/COMPLETED)됐다. 현재 코드에 `_isProbeStarted` 플래그와 `DefaultAssetBundle` 주입 경로가 실제로 있음을 확인했다(`lib/features/kanji_detail_modal/widgets/kanji_strokes_section.dart`).
- 가정: 이슈의 "`MediaQuery` 또는 테마 변경" 은 예시로 읽는다. 섹션 State 는 `MediaQuery`·테마에 `context` 로 직접 의존하지 않으므로 이 변경이 재호출을 일으키지 않을 수 있다. 재호출을 실제로 일으키는 어떤 의존성 변경이든 허용하고, AC #3 의 뮤테이션 실패로 효과를 증명한다.
- 가정: "탐침 로드 횟수" 는 획순 SVG 키(`assets/kanji/…`)에 대한 `load` 호출 수로 센다. `SvgPicture` 렌더링도 같은 번들을 읽을 수 있으므로, 탐침 호출을 렌더 호출과 구분하거나 둘을 합쳐도 재그리기 전후 비교가 뮤테이션을 잡는 방식인지는 design 이 정한다.
- 가정: 카운팅 번들은 기존 `test/helpers/fake_kanji_asset_bundle.dart` 를 감싸거나 확장해도 되고 새 헬퍼여도 된다. 기존 헬퍼의 동작(없는 키는 `FlutterError`)은 바꾸지 않는다.
- 가정: 새 테스트는 기존 `kanji_strokes_section_test.dart` 에 케이스로 추가해도 되고 새 파일이어도 된다. 기존 케이스는 그대로 둔다.
- 가정: 뮤테이션 증거는 PR 기록(러너 원문)으로 남기며, 뮤테이션 자체를 자동화하는 스크립트나 CI 변경은 하지 않는다.
- 가정: 라벨대로 `type: refactor` 로 분류했다. 관찰 가능한 동작 변경은 없다.
- 바뀐 검증 경로: `test/features/kanji_detail_modal/widgets/kanji_strokes_section_probe_safety_net_test.dart`

**범위 밖 발견**

- [후속 이슈 — dry-run, 만들지 않음] D1 · test-gap · `test/features/kanji_detail_modal/controller/related_words_query_test.dart:374 (그룹 '조회 속도')` — 벽시계 시간 20ms 단언이라 전체 스위트를 동시 12개로 돌릴 때 부하로 흔들립니다. safety-net-proof에서는 麟의 warm-max가 23.6ms로 나와 `--fail-fast`가 나머지 테스트를 `did not complete`로 중단시켰습니다. 한자 모달 폴더만 돌렸을 때는 4~10ms였습니다. 이 이슈의 AC와는 무관해서 고치지 않았습니다.

**분리한 후속 이슈**

- dry-run — 만들지 않음: 후속 이슈 1건 · 중복 댓글 0건 (만들었을 내용은 엔진 로컬 기록)

**범위 밖이지만 포함한 수정**

- (없음)

**근거와 기록** — 아래 항목은 접혀 있습니다. 제목을 누르면 펼쳐집니다.

<details>
<summary>인수 기준 (AC) — 10개</summary>

- AC #1: 자산 `load` 호출 횟수를 세는 테스트용 번들을 `DefaultAssetBundle` 로 주입해 `KanjiStrokesSection` 을 그리는 위젯 테스트가 추가된다. 이 테스트는 첫 그리기 후 탐침이 끝난 시점의 획순 자산 로드 횟수를 기록한다. (must)
- AC #2: 같은 테스트에서 섹션 State 를 유지한 채 의존성 변경을 일으켜 다시 그린 뒤, 획순 자산 로드 횟수가 AC #1 에서 기록한 값과 같음을 단언하고, 현재 코드에서 이 테스트는 통과한다. (must)
- AC #3: `_isProbeStarted` 의 한 번만 실행 가드를 제거한 코드(뮤테이션)에서 이 테스트가 실패하고, 그 실패를 러너 원문 출력으로 기록한다. 뮤테이션은 되돌려져 최종 diff 에 남지 않는다. (must)
- AC #4: 새 테스트의 다시 그리기는 원래 섹션 State 를 버리고 새로 만드는 방식(키 변경, 위젯 트리 교체 등)이 아니다. 즉 같은 State 에서 `didChangeDependencies` 가 다시 불리는 경로를 쓴다. (must)
- AC #5: 첫 탐침이 실제로 하나 이상의 자산을 읽는다. 즉 AC #1 의 로드 횟수가 0보다 크다. 이렇게 해서 "아무것도 읽지 않아 같다" 로 통과하는 공허한 테스트를 막는다. (must)
- AC #6: `lib/` 아래 운영 코드는 변경되지 않는다. `git diff --stat origin/main...HEAD -- lib` 가 비어 있다. (must)
- AC #7: 기존 `test/features/kanji_detail_modal/**` 테스트 케이스의 본문·단언·골든 파일명·`tags` 는 바뀌지 않는다. 새 테스트 케이스와 그에 필요한 import·헬퍼 추가만 허용한다. (must)
- AC #8: 골든 PNG 는 한 장도 추가·수정·삭제되지 않는다. `git diff --stat origin/main...HEAD -- '*.png'` 가 비어 있다. (must)
- AC #9: 기존 한자 모달 테스트(`test/features/kanji_detail_modal/**`)와 전체 유닛 테스트 커맨드(`docs/standards/verification.md`)가 green 이다. (must)
- AC #10: 새 테스트의 이름(`testWidgets`/`group`)에는 이슈 번호나 스펙 케이스 ID 를 넣지 않는다. 이름만 읽어도 "다시 그려도 획순 탐침은 한 번만 자산을 읽는다" 는 취지가 드러나는 서술형이다. (should)

</details>

<details>
<summary>인수 기준 판정 (리더) — met 10</summary>

리더(LLM)가 쓴 판정입니다 — 엔진이 확인한 사실이 아닙니다. 엔진은 모든 AC의 판정 유무, `unmet` 없음, `manual` AC의 체크리스트 참조만 확인했습니다.

| AC | 판정 | 근거 (리더) |
|---|---|---|
| AC #1 | met | kanji_strokes_section_probe_safety_net_test.dart: pumpSection 이 _CountingAssetBundle 을 DefaultAssetBundle 로 주입하고, pumpAndSettle 다음 baseline = counter.strokeAssetLoads 로 기준값을 기록한다. |
| AC #2 | met | '번들이 바뀌어 의존성이 갱신돼도 …' 케이스와 '번들이 여러 번 바뀌어도 …' 케이스: bundle.value 를 교체한 뒤 expect(counter.strokeAssetLoads, baseline) 와 byKey 동일을 단언한다. test run exit 0 으로 현재 코드에서 통과한다. |
| AC #3 | met | M1 killed: lib/.../kanji_strokes_section.dart 에서 `if (_isProbeStarted) return;` 를 제거하면 safety_net_test.dart:116 의 expect(counter.strokeAssetLoads, baseline) 가 실패한다(Expected <9>, Actual <18>). 최종 diff 에 lib 변경은 없다. |
| AC #4 | met | 두 재그리기 케이스: expect(tester.state(sectionFinder()), same(stateBefore)) 로 같은 State 임을 확인하고, DefaultAssetBundle.of(...) 가 same(replacement) 인지도 확인한다. M1 killed 로 didChangeDependencies 가 실제로 다시 불린다는 것이 입증된다. |
| AC #5 | met | '처음 그릴 때 획순 자산을 한 번 이상 읽는다' 케이스: strokeAssetLoads greaterThan(0) 을 단언한다. 재그리기 케이스들도 expect(baseline, greaterThan(0)) 을 단언한다. |
| AC #6 | met | review.diff 에 lib/ 경로 변경이 없다. no-production-change run 은 exit 0 이다. 변경 파일은 docs/specs/1938/* 와 새 테스트 파일 하나뿐이다. |
| AC #7 | met | review.diff 에서 test/features/kanji_detail_modal/** 의 변경은 새 파일 kanji_strokes_section_probe_safety_net_test.dart 하나다. 기존 테스트 파일과 fake_kanji_asset_bundle.dart 에는 수정이 없다. |
| AC #8 | met | review.diff 에 *.png 변경이 없다(골든 추가·수정·삭제 0건). |
| AC #9 | met | verification.md 의 test 커맨드 run 은 exit 0 이고 flaky·base_red 가 아니다. CI 골든 잡은 not_checked_locally 이지만 골든과 기존 테스트에는 변경이 없다. |
| AC #10 | met | group '획순 탐침' 과 testWidgets 3개의 이름에 이슈 번호나 케이스 ID 가 없다. 이름만 읽어도 '재그리기에도 획순 자산을 다시 읽지 않는다' 는 서술형 취지가 드러난다. |

</details>

<details>
<summary>이슈 요구 ↔ AC 대응표</summary>

| 이슈 요구 | AC |
|---|---|
| 자산 로드 횟수를 세는 테스트용 번들로 KanjiStrokesSection 을 그린다 | AC #1, AC #5 |
| 의존성 변경을 일으켜 다시 그려도(예: MediaQuery 또는 테마 변경) 탐침 로드 횟수가 처음과 같다 | AC #2, AC #4 |
| 플래그를 제거한 코드에서는 이 테스트가 실패한다(뮤테이션으로 확인) | AC #3 |
| 기존 한자 모달 테스트·골든은 바뀌지 않는다 | AC #7, AC #8, AC #9 |
| (배경) 플래그가 탐침을 한 번만 돌게 막는 현재 동작을 고정한다 — 운영 코드 변경 없이 | AC #6 |
| (근거) docs/specs/1933/skeleton.md §8.2 "load 호출 횟수를 세는 가짜로 재호출 시 증가하지 않음을 S 케이스 하나로 고정" | AC #1, AC #2 |
| (표준 quality-bar) 테스트 이름은 자기완결적 서술 | AC #10 |

</details>

<details>
<summary>검증 범위</summary>

엔진이 기록한 사실(facts)로 만든 표입니다 — 역할이 쓰지 않았습니다.

| 단계 | 명령 | 결과 | 시도 | 검증한 HEAD |
|---|---|---|---|---|
| `ac-format` | `ac-format` | 통과 (종료 코드 0) | 3 | `ef3059a87337` |
| `ac-coverage` | `ac-coverage` | 통과 (종료 코드 0) | 3 | `ef3059a87337` |
| `setup` | `setup` | 통과 (종료 코드 0) | 3 | `ef3059a87337` |
| `safety-net-proof` | `safety-net-proof` | 통과 (엔진 판정 — 조건 충족) | 3 | `ef3059a87337` |
| `no-production-change` | `no-production-change` | 통과 (엔진 판정 — 조건 충족) | 2 | `ef3059a87337` |
| `test` | `test` | 통과 (종료 코드 0) | 2 | `ef3059a87337` |
| `lint` | `lint` | 통과 (종료 코드 0) | 2 | `ef3059a87337` |
| `check-verification-doc-refs` | `check-verification-doc-refs` | 통과 (종료 코드 0) | 2 | `ef3059a87337` |
| `verify-gate` | `verify-gate` | 통과 (종료 코드 0) | 2 | `ef3059a87337` |

</details>

<details>
<summary>뮤테이션 실행</summary>

엔진이 선언된 변경을 HEAD에 하나씩 적용하고 `test`를 실행한 사실입니다. 바꿀 자리와 내용은 개발자 역할이 골랐습니다. `killed`만 증거이고, 어떤 AC가 충족됐는지는 리더가 판정합니다.

- HEAD `ef3059a87337` · 대조 실행(변경 없음): 종료 코드 0

| id | AC | 파일 | 바꾼 글 | 넣은 글 | 결과 |
|---|---|---|---|---|---|
| M1 | 3 | `lib/features/kanji_detail_modal/widgets/kanji_strokes_section.dart` | `if (_isProbeStarted) return;` | (없음) | killed — 테스트가 빨강, 종료 코드 1 |

</details>

<details>
<summary>로컬에서 확인하지 않은 항목 — 9개</summary>

- code_quality/golden_test — needs sudo (CI machine setup); rewrites git state; rewrites tracked files (golden / fix / write mode); step 'Check if golden tests exist': shell logic (if / loops / heredoc); uses GitHub runner variables; uses a workflow expression (PR context / CI runner values)
- code_quality/test_all — needs sudo (CI machine setup)
- code_quality/upload-failure-golden-images — needs sudo (CI machine setup); rewrites git state; rewrites tracked files (golden / fix / write mode); uses GitHub runner variables; uses a workflow expression (PR context / CI runner values); uses actions/github-script
- e2e_test/e2e_test — needs an Android emulator / SDK manager; needs sudo (CI machine setup); step 'Free up disk space': shell logic (if / loops / heredoc); uses reactivecircus/android-emulator-runner; whole job is bound to the CI machine — its other commands were not carried
- set_assignees/set-assignees — uses actions/github-script
- update_release_notes_draft/validate_pr — uses Slashgear/action-check-pr-title; uses danielchabr/pr-labels-checker; uses release-drafter/release-drafter/autolabeler
- update_release_notes_draft/update_release_draft — uses release-drafter/release-drafter
- build — flutter build apk needs GitHub release hosts, Android SDK writes and the signing key (key.properties is a secret path) inside srt (measured 2026-11-23, tools/out/BASE_GREEN.md) (base-green check: cannot run inside the sandbox — human decision)
- e2e — needs an Android emulator and the adb server socket, impossible inside srt (measured 2026-11-23; CI also needs an emulator + KVM) (base-green check: cannot run inside the sandbox — human decision)

</details>

<details>
<summary>리더 결정 — 3건</summary>

- check#1 `plan-gate`: `plan` · 이유 `fits-template` — 이슈의 수용 기준 3개와 배경·근거(1933 skeleton §8.2)가 모두 AC로 덮여 있다. 선행 이슈 #1933은 CLOSED/COMPLETED이고, #1986은 스프린트 참조일 뿐 선행 이슈가 아니다. 테스트만 추가하는 안전망 작업이므로 safety-net 템플릿으로 진행하고 추가 스텝은 없다(UI·텍스트·보안 표면 없음). 다음 역할에게: 섹션…
- check#1 `done-gate`: `rerun` → `safety-net` · 이유 `real-defect` — AC #3(플래그 제거 뮤테이션에서 테스트 실패, 러너 원문 기록)에 대한 증거가 없다: done_gate.mutations 가 null 이고, 뮤테이션 선언도 실행 결과도 없다. 커밋 메시지나 보고서에 적힌 말은 증거로 치지 않는다. safety-net 역할에게: 테스트 파일은 그대로 두고 mutations.json 에 AC 3 용 행 하나를 선언할 것…
- check#2 `done-gate`: `approve` · 이유 `acceptance-met` — 지난 done-gate 에서 비어 있던 AC #3 증거가 이제 있다. M1 은 `if (_isProbeStarted) return;` 를 제거한 변경이고 결과는 killed 다. 실패한 케이스는 '번들이 바뀌어 의존성이 갱신돼도 같은 State 에서 획순 자산을 다시 읽지 않는다' 이고, 실패 위치는 test 116행의 `expect(counter.str…

</details>

<details>
<summary>엔진 기록 — 측정용 사실 경고 0건</summary>

**측정용 사실 경고**: 0건

</details>

