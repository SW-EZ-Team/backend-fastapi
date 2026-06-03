# app/core/planfirst — plan-first 공통 계약 패키지

## 목적

4개 생성 파이프라인(커리큘럼·슬라이드·음성·모의고사)이 공유하는
plan-first 레이어의 **공통 계약·검증·위치 배정·폴백 등록소**를 제공한다.

**기존 파이프라인 동작을 재작성하지 않는다.** 새 파이프라인이나 통합 테스트에서
공통 인터페이스로 접근할 수 있는 상위 계약 레이어만 제공한다.

---

## 모듈 구성

| 파일 | 역할 |
|---|---|
| `blueprint.py` | `GenBlueprint`, `GenSlot`, `SlotConstraints` 데이터클래스 |
| `validate.py` | `SlotValidator` — count/index 완전집합 + per-slot 제약 검사 |
| `fallback.py` | `FallbackRegistry` — 기존 패스 어댑터 등록·조회 |
| `positions.py` | `balanced_target_positions`, `seed_from_key` 단일 소스 |

---

## IN/OUT 계약

### `positions.balanced_target_positions(count, num_choices, seed)`

- **IN**: 슬롯 수, 선택지 수, 정수 seed
- **OUT**: 길이 `count`인 0-index 위치 목록 (결정적, 재현 가능)
- **사용처**: ChapterStudio quiz_balance, ExamForge concept_blueprint

### `positions.seed_from_key(seed_key)`

- **IN**: 문자열 키 (강의 ID, 시험 ID 등)
- **OUT**: SHA-256 기반 고정 정수 seed
- **사용처**: ChapterStudio quiz_balance._seed_from_key, ExamForge concept_blueprint._seed_from_key

### `blueprint.GenSlot`

- **fixed_fields**: 코드가 결정 — `slide_idx`, `category`, `difficulty`, `template_id`, `target_answer_position` 등
- **ai_fields**: AI가 채울 수 있는 필드 이름 목록
- **constraints**: `SlotConstraints` — min/max chars, required_markers, exact_choices, allowed_enum

### `validate.SlotValidator`

- **`validate_count_and_index_set(blueprint, filled_slot_ids)`**: 슬롯 1:1 채움 검사
- **`validate_slot_constraints(slot, ai_output)`**: per-slot 제약 검사
- **반환**: `list[SlotViolation]` — 각 위반의 `slot_id`, `check`, `message`

### `fallback.FallbackRegistry`

- **`FallbackRegistry.default()`**: 기존 패스가 어댑터로 등록된 레지스트리
- **`registry.get(kind)`**: 등록된 핸들러 조회 (`None`이면 미등록)
- 등록 대상은 기존 함수 그대로 — 로직 변경 없음

---

## 파이프라인 대응 매핑

| ChapterStudio | ExamForge | 이 패키지 계약 |
|---|---|---|
| `SlidePlan` | 블루프린트 슬롯 dict | `GenSlot` |
| `SlidePlan` 목록 | `question_blueprint` | `GenBlueprint` |
| `visual_type`, `category` 등 | `template_id`, `difficulty` 등 | `fixed_fields` |
| `narration`, `visual.data` 등 | `stem`, `choices` 등 | `ai_fields` |
| `narration_len` | `num_choices` | `constraints` |
| `balanced_target_positions` (quiz_balance) | `_balanced_target_positions` (concept_blueprint) | `positions.balanced_target_positions` |
| `_seed_from_key` (quiz_balance) | `_seed_from_key` (concept_blueprint) | `positions.seed_from_key` |
| `ensure_visual_body` / `render_fallback_visual` | `balance_correct_answer_positions` | `FallbackRegistry` |
| `quiz_balance_pass` | — | `FallbackRegistry` |
| `voice_cohesion_pass` / `structure_gate_errors` | — | `FallbackRegistry` |
| `title_rules` | — | `FallbackRegistry` |
| — | `analyze_coverage`, `answer_position_counts` | `FallbackRegistry` |

---

## 의존성

이 패키지는 `app/core/` 하위에 있으므로 `app/modules/` 의존 금지다.
단, `FallbackRegistry.default()` 내부의 지연 임포트는 런타임에 모듈이 있을 때만 등록하며,
모듈 미설치 환경에서는 `ImportError`를 무시하고 등록을 생략한다.

---

## 사용 예시

```python
from app.core.planfirst import balanced_target_positions, seed_from_key

# 20문항, 4지선다, 시험 ID 기반 seed로 균등 배정
seed = seed_from_key("exam_2026_01")
positions = balanced_target_positions(20, num_choices=4, seed=seed)
```

```python
from app.core.planfirst import FallbackRegistry

registry = FallbackRegistry.default()
ensure_visual = registry.get("ensure_visual_body")
if ensure_visual:
    html, warnings = ensure_visual(raw_html, category, slide_idx)
```
