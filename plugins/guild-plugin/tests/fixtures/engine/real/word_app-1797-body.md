## 배경 (Why)

복습 문제 유형(`selectedQuizTypes`)은 지금 **복습 화면 헤더의 `QuizDropdown` 버튼으로만** 바꿀 수 있다. 사용자는 복습을 시작하기 전에 출제 유형을 미리 정해 두고 싶을 수 있다. 다른 퀴즈 관련 옵션(자동 넘김, 음성 자동 재생, 힌트 숨김 등)이 모여 있는 설정 화면에서도 이 항목을 바꿀 수 있어야 한다.

## 실현 가능성 (코드 확인 결과)

- 상태는 이미 전역 `SettingsController`에 있다. `selectedQuizTypes`, `toggleQuizTypeSelection`, `toggleAllQuizTypes` 모두 `SharedPreferences`(`selectedQuizTypes` 키)에 저장된다. 그래서 **새 상태나 저장소는 필요 없다.**
- 선택 UI는 `QuizDropdown.showQuizTypeSelector(context)`(`lib/features/review_screen/widgets/quiz_dropdown.dart`)라는 **정적 메서드**로 분리되어 있다. 따라서 설정 화면에서도 그대로 호출할 수 있다.
- 설정 화면에서 `CupertinoScaffold.showCupertinoModalBottomSheet`를 여는 선례가 이미 있다(`setting_in_word_screen_section.dart`). 설정 화면 위에 바텀시트를 띄우는 방식도 검증되어 있다.
- 두 화면이 같은 Rx 상태를 보므로, 설정에서 바꾼 값은 다음 복습 화면에 바로 반영된다.

## 기능 설명 (What)

- 설정 화면 **'퀴즈 화면' 섹션**(`SettingInQuizScreenSection`)에 '문제 유형' 항목을 추가한다.
- 항목을 탭하면 복습 화면과 **같은 문제 유형 선택 시트**(섹션별 체크박스 + 전체 선택/해제)가 열린다.
- 항목 오른쪽에 현재 선택 상태를 요약해 보여 준다(예: 1개면 유형 이름, 여러 개면 "N개 선택", 전부면 "전체"). 요약 문구와 형식은 design 단계에서 정한다.
- 선택 규칙(최소 1개 유지, ENV별 표시 가능 유형 필터링)은 기존과 같다.

## 인수 기준 (초안 — analyze에서 확정)

1. 설정 화면 '퀴즈 화면' 섹션에 '문제 유형' 항목이 보인다.
2. 항목을 탭하면 복습 화면과 같은 섹션·항목 구성의 선택 시트가 열린다.
3. 설정에서 바꾼 선택이 저장되고, 이후 복습 화면의 선택 시트와 실제 출제에 그대로 반영된다. 반대 방향(복습 → 설정 요약)도 반영된다.
4. 앱을 재시작해도 선택이 유지된다.
5. 새 문자열은 지원하는 모든 언어(ko/en/ja 등)에 번역이 있다. 항목에는 접근성 라벨(`Semantics`)이 있다.

## 확인 필요 (analyze에서 검증)

- `SettingsController._allAvailableQuizTypes`는 `QuizType.exampleReading`을 조건 없이 넣는다. 반면 `QuizDropdown._isAvailable`은 `ENV.hasExample`일 때만 이 유형을 노출한다. 예문이 없는 상품에서는 '전체 선택' 상태 판정(체크박스 tristate)과 출제 대상이 서로 어긋날 수 있다. 같은 시트를 두 곳에서 쓰게 되므로 이번에 함께 확인한다.
- 선택 시트 빌더를 `review_screen` 기능 폴더 밖(공용 위젯)으로 옮길지는 `docs/standards/architecture.md` 기준에 따라 design에서 결정한다.

## 관련 이슈

- #990 — 복습 화면 문제 유형 선택 UX 개선(빠른 단일 전환). 선택 시트 자체의 UX를 바꾸는 이슈다. 이 이슈는 진입점을 하나 더 만드는 것이라 범위가 다르지만, 같은 시트를 공유하므로 순서와 충돌 여부를 확인해야 한다.

## 관련 파일

- `lib/features/review_screen/widgets/quiz_dropdown.dart` (`showQuizTypeSelector`, `quizTypeLabel`, `quizTypeSections`)
- `lib/features/setting_screen/widgets/setting_in_quiz_screen_section.dart`
- `lib/controller/settings_controller.dart` (`selectedQuizTypes`, `_allAvailableQuizTypes`)
- `lib/helpers/languages/*.dart`

