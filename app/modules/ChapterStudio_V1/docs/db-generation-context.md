# DB 생성 입력 계약

## 목적

ChapterStudio_V1은 운영에서 프론트 쿼리값을 직접 신뢰하지 않고 `lesson_id`로 infra DB에 저장된 강의 생성 입력 스냅샷을 읽는다. 데모 화면은 같은 필드를 mock으로 넣어 빠른 확인만 수행한다.

## 입력 원천

| 입력 | DB 원천 |
|---|---|
| 주제/PDF 모드 | `chapter_studio.curriculum_plan.source_type` |
| PDF 파일명 | `chapter_studio.curriculum_plan.source_ref` |
| 학습 기간 | `chapter_studio.lesson_generation_status.generation_context.duration_days` |
| 깊이 | `chapter_studio.lesson_generation_status.generation_context.depth` |
| 튜터 | `chapter_studio.lesson_generation_status.generation_context.teacher` |
| tone/pace/depth/socratic | `chapter_studio.lesson_generation_status.generation_context` |
| 대상 수준 | `chapter_studio.lesson_generation_status.generation_context.audience_level` |
| 학습 목표 | `chapter_studio.curriculum_unit.learning_goal` |
| 취약점 | `chapter_studio.lesson_generation_status.generation_context.weak_points` |
| 챕터 정보 | `chapter_studio.curriculum_unit.title`, `summary`, `learning_goal`, `slide_count` |
| 템플릿 | `chapter_studio.lesson_generation_status.requested_template` |

## 운영 흐름

1. Spring이 공개 REST, 인증, 소유권, 결제 상태를 검증한다.
2. Spring이 커리큘럼 확정 후 `lesson_generation_status.generation_context`에 입력 스냅샷을 저장한다.
3. backend-fastapi는 `lesson_id`만 받아 `db.generation_context_loader.load_generation_context()`로 입력을 읽는다.
4. ChapterStudio_V1은 슬라이드, 퀴즈, 핵심노트, 과제, 음성대본을 생성해 `chapter_studio` schema에 저장한다.

## 안정성 원칙

- SQL은 `$1` 파라미터만 사용한다.
- 프론트 입력은 데모용이며 운영 생성의 진실 원천은 DB다.
- 생성 시작 시점의 스냅샷을 보존해 튜터 설정이나 사용자 선호가 중간에 바뀌어도 해당 강의 결과가 흔들리지 않게 한다.
