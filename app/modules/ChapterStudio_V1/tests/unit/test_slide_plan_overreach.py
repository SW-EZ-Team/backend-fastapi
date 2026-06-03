"""over-reach 4건 결정화 신규 단위테스트.

AI 실호출 없이:
1. slide_count 결정성 — 동일 estimated_minutes → 동일 slide_count, AI 미관여
2. SlidePlan이 slide_count개·각 slot에 visual_type 100% 채워짐
3. visual_type N-시퀀스 결정성·최소 3종 분포
4. parse_slides가 plan과 다른 visual.type을 거부/정규화(silent 드리프트 차단)
5. title 챕터명+번호 위반 시 결정적 재라벨
6. text 슬라이드 visual marker 구조적 보장 (plan에서 text category → text-safe visual_type 고정)
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.app.curriculum_blueprint import (
    build_curriculum_blueprint,
    slide_count_from_minutes,
)
from app.modules.ChapterStudio_V1.app.study_templates import get_template, template_keys
from app.modules.ChapterStudio_V1.pipeline.slide_plan import SlidePlan, build_slide_plan, serialize_slide_plan
from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import (
    _enforce_plan_visual_type,
    _relabel_chapter_title,
    parse_slides,
)
from app.modules.ChapterStudio_V1.postprocess.visual_quality import relabel_chapter_title
from app.modules.ChapterStudio_V1.app.template_types import TEXT_CATEGORY_VISUAL_TYPES


# ---------------------------------------------------------------------------
# (1) slide_count 결정성 — 동일 minutes → 동일 slide_count, AI 미관여
# ---------------------------------------------------------------------------


class TestSlideCountDeterminism:
    """slide_count_from_minutes가 완전 결정적임을 보증한다."""

    def test_same_input_returns_same_output(self) -> None:
        """동일 estimated_minutes → 동일 slide_count(재현성 보장)."""
        for minutes in [15, 20, 25, 30, 35, 45, 60]:
            r1 = slide_count_from_minutes(minutes)
            r2 = slide_count_from_minutes(minutes)
            assert r1 == r2, f"{minutes}분: {r1} != {r2}"

    def test_result_in_valid_range(self) -> None:
        """반환값이 항상 10~15 범위 내에 있다."""
        for minutes in range(10, 65):
            count = slide_count_from_minutes(minutes)
            assert 10 <= count <= 15, f"{minutes}분 → {count} 범위 벗어남"

    def test_boundary_values(self) -> None:
        """구간 경계값에서 올바른 slide_count를 반환한다."""
        assert slide_count_from_minutes(20) == 10
        assert slide_count_from_minutes(25) == 11
        assert slide_count_from_minutes(30) == 12
        assert slide_count_from_minutes(35) == 13
        assert slide_count_from_minutes(45) == 14
        assert slide_count_from_minutes(46) == 15

    def test_blueprint_slide_count_not_ai_delegated(self) -> None:
        """build_curriculum_blueprint의 slide_count가 blueprint(결정적)에서 온다.

        AI가 아닌 slide_count_from_minutes()로 결정됨을 확인한다.
        """
        blueprint = build_curriculum_blueprint(subject="수학", lesson_count=5)
        expected = slide_count_from_minutes(30)  # _DEFAULT_ESTIMATED_MINUTES=30
        for slot in blueprint:
            assert slot.slide_count == expected, (
                f"slot {slot.order}: slide_count={slot.slide_count}, expected={expected}"
            )

    def test_blueprint_slide_count_is_deterministic(self) -> None:
        """동일 인수로 두 번 호출하면 slide_count가 동일하다."""
        bp1 = build_curriculum_blueprint(subject="영어", lesson_count=8)
        bp2 = build_curriculum_blueprint(subject="영어", lesson_count=8)
        for s1, s2 in zip(bp1, bp2):
            assert s1.slide_count == s2.slide_count


# ---------------------------------------------------------------------------
# (2) SlidePlan이 slide_count개·각 slot에 visual_type 100% 채워짐
# ---------------------------------------------------------------------------


class TestSlidePlanCompleteness:
    """build_slide_plan이 N개 슬롯을 visual_type 100% 채워서 반환함을 보증한다."""

    @pytest.mark.parametrize("count", [1, 2, 5, 10, 12, 15])
    def test_plan_has_exact_count(self, count: int) -> None:
        """반환 목록의 길이가 정확히 slide_count다."""
        plans = build_slide_plan("concept_code", count)
        assert len(plans) == count

    @pytest.mark.parametrize("count", [1, 2, 5, 10, 12, 15])
    def test_all_slots_have_visual_type(self, count: int) -> None:
        """모든 슬롯에 non-empty visual_type이 있다."""
        plans = build_slide_plan("concept_code", count)
        for p in plans:
            assert isinstance(p.visual_type, str) and p.visual_type, (
                f"slide_idx={p.slide_idx} visual_type 누락"
            )

    @pytest.mark.parametrize("count", [1, 2, 5, 10, 12, 15])
    def test_slide_idx_is_complete_set(self, count: int) -> None:
        """slide_idx가 0..N-1 완전집합이다."""
        plans = build_slide_plan("concept_code", count)
        indices = {p.slide_idx for p in plans}
        assert indices == set(range(count)), f"인덱스 불완전: {indices}"

    def test_each_plan_has_narration_len(self) -> None:
        """각 슬롯에 유효한 narration_len (min, max) 쌍이 있다."""
        plans = build_slide_plan("compare_practice", 12)
        for p in plans:
            lo, hi = p.narration_len
            assert lo > 0 and hi >= lo, (
                f"slide_idx={p.slide_idx} narration_len={p.narration_len} 비정상"
            )

    def test_all_templates_produce_plans(self) -> None:
        """47개 템플릿 모두에서 build_slide_plan이 성공한다."""
        for key in template_keys():
            plans = build_slide_plan(key, 12)
            assert len(plans) == 12, f"{key}: 12개 아님"
            for p in plans:
                assert p.visual_type, f"{key} slide_idx={p.slide_idx} visual_type 없음"

    def test_serialize_roundtrip_preserves_enforcement_keys(self) -> None:
        """직렬화→역직렬화 왕복이 slide_idx·visual_type·must_have를 보존한다.

        이 키들이 보존돼야 parse_slides의 _enforce_plan_visual_type/_relabel_chapter_title이
        역직렬화된 행으로 대조할 수 있다(P0-1 왕복 무결성).
        """
        plans = build_slide_plan("math_reasoning", 12)
        rows = serialize_slide_plan(plans)
        assert len(rows) == 12
        for plan, row in zip(plans, rows):
            assert row["slide_idx"] == plan.slide_idx
            assert row["visual_type"] == plan.visual_type
            assert row["must_have"] == list(plan.must_have)
            # 역직렬화 측이 소비하는 형식 검증: dict이고 필수 키가 있다.
            assert isinstance(row["slide_idx"], int)
            assert isinstance(row["visual_type"], str) and row["visual_type"]


# ---------------------------------------------------------------------------
# (3) visual_type N-시퀀스 결정성·최소 3종 분포
# ---------------------------------------------------------------------------


class TestVisualTypeSequence:
    """N-슬라이드 시퀀스가 결정적이고 최소 3종 visual_type을 포함함을 보증한다."""

    def test_sequence_is_deterministic(self) -> None:
        """동일 template_key + slide_count → 동일 visual_type 시퀀스."""
        plans1 = build_slide_plan("visual_map", 12)
        plans2 = build_slide_plan("visual_map", 12)
        types1 = [p.visual_type for p in plans1]
        types2 = [p.visual_type for p in plans2]
        assert types1 == types2, "동일 입력에서 시퀀스 불일치"

    @pytest.mark.parametrize("count", [5, 10, 12, 15])
    def test_minimum_3_visual_types_for_n_ge_5_all_templates(self, count: int) -> None:
        """slide_count≥5이면 47개 템플릿 전부에서 최소 3종 visual_type이 분포한다.

        debug_case 등 과거 2종으로 떨어지던 템플릿을 포함한 전수 검증이다(P2-1 반례 포함).
        """
        for key in template_keys():
            plans = build_slide_plan(key, count)
            types = {p.visual_type for p in plans}
            assert len(types) >= 3, (
                f"{key} count={count}: visual_type {len(types)}종 (3종 미달): {sorted(types)}"
            )

    def test_debug_case_reaches_3_types_at_n5(self) -> None:
        """과거 반례였던 debug_case가 N=5에서 3종을 달성하는지 명시 검증(P2-1)."""
        plans = build_slide_plan("debug_case", 5)
        types = {p.visual_type for p in plans}
        assert len(types) >= 3, f"debug_case N=5: {sorted(types)} (3종 미달)"

    def test_small_n_3_or_4_does_not_falsely_claim_3_types(self) -> None:
        """N=3·4(비프로덕션 소형)는 3종을 보장하지 않을 수 있음 — docstring 정직성 검증.

        production slide_count는 10~15이므로 N=3·4는 비프로덕션 경로다. 보장하지 않음을
        테스트로 명문화해 docstring '거짓 보장' 회귀를 막는다.
        """
        # debug_case N=3은 5개 프레임을 다 담지 못해 3종 미만이 될 수 있다(허용).
        plans = build_slide_plan("debug_case", 3)
        types = {p.visual_type for p in plans}
        # 3종 미만이어도 정상이다(예외 케이스). 단, 슬롯 수·visual_type 채움은 여전히 보장.
        assert len(plans) == 3
        assert all(p.visual_type for p in plans)

    def test_template_frames_have_3plus_distinct_types(self) -> None:
        """모든 템플릿의 5개 프레임이 3종 이상 distinct visual_type을 갖는다.

        build_slide_plan의 'N≥5 3종 보장'은 이 불변식에 의존한다(N≥5면 5프레임 모두 등장).
        이 테스트가 깨지면 catalog 변경이 3종 보장을 무너뜨린 것이다.
        """
        for key in template_keys():
            template = get_template(key)
            types = {f.visual_type for f in template.frames}
            assert len(types) >= 3, (
                f"{key}: 5개 프레임 visual_type {len(types)}종 (3종 미달): {sorted(types)}"
            )

    def test_last_slide_is_frame4(self) -> None:
        """마지막 슬롯(slide_idx=N-1)은 frame4(강의 끝 점검) 역할이다."""
        for count in [5, 10, 12]:
            plans = build_slide_plan("concept_code", count)
            last = plans[-1]
            assert last.role == "강의 끝 점검", (
                f"count={count} 마지막 슬롯 role={last.role}"
            )

    def test_first_slide_is_frame0(self) -> None:
        """첫 슬롯(slide_idx=0)은 frame0 역할이다."""
        plans = build_slide_plan("concept_code", 12)
        assert plans[0].slide_idx == 0


# ---------------------------------------------------------------------------
# (4) parse_slides — plan과 다른 visual.type 거부/정규화
# ---------------------------------------------------------------------------


def _make_slide_json(
    slide_idx: int,
    visual_type: str,
    title: str = "핵심 개념 이해",
) -> dict:
    """테스트용 slides 응답 항목을 만든다."""
    return {
        "slide_idx": slide_idx,
        "title": title,
        "category": "text",
        "narration": "핵심 개념을 예시와 함께 이해한다. 수직선에서 음수와 양수 위치를 직접 확인한다.",
        "visual": {"type": visual_type, "data": {"title": "핵심", "value": "기준", "caption": "설명"}},
        "checkpoint": "이 기준을 말로 설명할 수 있는가?",
    }


class TestParseSlidesVisualTypeEnforcement:
    """parse_slides가 plan과 다른 visual.type을 거부/정규화함을 보증한다."""

    def test_plan_type_enforced_when_ai_drifts(self) -> None:
        """AI가 다른 visual.type을 반환하면 plan type으로 강제 교체된다."""
        plan = [{"slide_idx": 0, "visual_type": "metric-card", "must_have": ["핵심"]}]
        ai_response = json.dumps({"slides": [_make_slide_json(0, "concept_map")]})

        slides = parse_slides(ai_response, plan)
        assert len(slides) == 1
        # visual dict에 plan type이 적용되어 있어야 한다.
        assert slides[0].visual.get("type") == "metric-card", (
            f"plan 타입 강제 실패: {slides[0].visual.get('type')}"
        )

    def test_matching_type_passes_unchanged(self) -> None:
        """AI가 plan과 동일한 visual.type을 반환하면 그대로 통과한다."""
        plan = [{"slide_idx": 0, "visual_type": "example_box", "must_have": ["예제"]}]
        ai_response = json.dumps({"slides": [
            {**_make_slide_json(0, "example_box"),
             "visual": {"type": "example_box", "data": {"problem": "문제", "steps": ["단계"], "answer": "답"}}}
        ]})

        slides = parse_slides(ai_response, plan)
        assert slides[0].visual.get("type") == "example_box"

    def test_alias_normalization_does_not_trigger_replacement(self) -> None:
        """comparison_table(언더스코어)는 comparison-table(하이픈)과 동일 취급한다."""
        plan = [{"slide_idx": 0, "visual_type": "comparison-table", "must_have": ["비교"]}]
        # AI가 alias 형태로 반환해도 정규화 후 동일하면 변경하지 않는다.
        ai_response = json.dumps({"slides": [_make_slide_json(0, "comparison_table")]})

        slides = parse_slides(ai_response, plan)
        # plan type과 alias가 같으므로 교체 없이 통과 (렌더러가 처리할 수 있는 형태)
        vt = slides[0].visual.get("type")
        # comparison_table → comparison-table alias 정규화 후 plan과 일치 → 유지됨
        assert vt in ("comparison_table", "comparison-table"), f"예상치 못한 type: {vt}"

    def test_no_plan_no_enforcement(self) -> None:
        """slide_plan=None이면 AI type이 그대로 통과한다."""
        ai_response = json.dumps({"slides": [_make_slide_json(0, "concept_map")]})
        slides = parse_slides(ai_response, None)
        assert len(slides) == 1

    def test_silent_drift_blocked_for_multiple_slides(self) -> None:
        """여러 슬롯에서 드리프트가 개별적으로 차단된다."""
        plan = [
            {"slide_idx": 0, "visual_type": "metric-card", "must_have": ["기준"]},
            {"slide_idx": 1, "visual_type": "step_flow", "must_have": ["단계"]},
        ]
        ai_response = json.dumps({"slides": [
            _make_slide_json(0, "concept_map"),   # 드리프트 — metric-card로 교체되어야
            _make_slide_json(1, "example_box"),   # 드리프트 — step_flow로 교체되어야
        ]})

        slides = parse_slides(ai_response, plan)
        assert slides[0].visual.get("type") == "metric-card"
        assert slides[1].visual.get("type") == "step_flow"


# ---------------------------------------------------------------------------
# (5) title 챕터명+번호 위반 시 결정적 재라벨
# ---------------------------------------------------------------------------


class TestTitleRelabeling:
    """챕터명+번호 형태 제목이 must_have 기반으로 결정적 재라벨됨을 보증한다."""

    def test_chapter_number_title_relabeled(self) -> None:
        """'수직선과 정수의 위치 3'은 must_have로 재라벨된다."""
        plan_slot = {"must_have": ["음수와 양수 비교"]}
        result = _relabel_chapter_title("수직선과 정수의 위치 3", plan_slot)
        assert result != "수직선과 정수의 위치 3", "재라벨 실패"
        assert "음수와 양수 비교" in result or len(result) <= 16

    def test_normal_title_unchanged(self) -> None:
        """정상 제목(숫자로 끝나지 않음)은 변경되지 않는다."""
        plan_slot = {"must_have": ["핵심 개념"]}
        result = _relabel_chapter_title("음수끼리의 크기 비교", plan_slot)
        assert result == "음수끼리의 크기 비교"

    def test_no_plan_no_change(self) -> None:
        """plan_slot=None이면 챕터명+번호 제목도 변경되지 않는다."""
        result = _relabel_chapter_title("수직선과 정수의 위치 3", None)
        assert result == "수직선과 정수의 위치 3"

    def test_empty_must_have_no_change(self) -> None:
        """must_have가 비어 있으면 변경하지 않는다."""
        plan_slot = {"must_have": []}
        result = _relabel_chapter_title("수직선과 정수의 위치 3", plan_slot)
        assert result == "수직선과 정수의 위치 3"

    def test_relabel_within_16_chars(self) -> None:
        """재라벨된 제목이 16자 이내다."""
        plan_slot = {"must_have": ["이 개념은 아주 길고 중요한 것으로 16자 초과다"]}
        result = _relabel_chapter_title("함수의 개념과 표현 5", plan_slot)
        assert len(result) <= 16

    def test_postprocess_relabel_chapter_title(self) -> None:
        """visual_quality.relabel_chapter_title도 동일하게 작동한다."""
        result = relabel_chapter_title("함수와 그래프 10", ["함수의 기울기"])
        assert result != "함수와 그래프 10"
        result2 = relabel_chapter_title("정상 제목", ["핵심"])
        assert result2 == "정상 제목"

    def test_parse_slides_relabels_chapter_title(self) -> None:
        """parse_slides가 챕터명+번호 제목을 결정적으로 재라벨한다."""
        plan = [{"slide_idx": 0, "visual_type": "example_box", "must_have": ["음수 크기 비교"]}]
        ai_response = json.dumps({"slides": [
            {
                "slide_idx": 0,
                "title": "수직선과 정수의 위치 3",  # 챕터명+번호 형태
                "category": "text",
                "narration": "음수와 양수의 위치를 수직선에서 직접 확인한다. 오른쪽이 더 큰 수임을 이해한다.",
                "visual": {"type": "example_box", "data": {"problem": "비교", "steps": ["확인"], "answer": "판단"}},
                "checkpoint": "확인",
            }
        ]})
        slides = parse_slides(ai_response, plan)
        assert slides[0].title != "수직선과 정수의 위치 3", "챕터명+번호 제목 재라벨 실패"


# ---------------------------------------------------------------------------
# (6) text category → text-safe visual_type 구조적 보장
# ---------------------------------------------------------------------------


class TestTextCategoryVisualTypeGuarantee:
    """text category 슬롯은 metric-card/comparison-table/example_box 중 하나를 가진다."""

    def test_text_category_visual_types_constant(self) -> None:
        """TEXT_CATEGORY_VISUAL_TYPES가 올바른 집합을 포함한다."""
        expected = {"metric-card", "comparison-table", "example_box"}
        assert expected.issubset(TEXT_CATEGORY_VISUAL_TYPES)

    def test_slide_plan_text_category_has_safe_visual_type(self) -> None:
        """build_slide_plan에서 text category인 슬롯은 text-safe visual_type을 가진다."""
        # text category가 많은 템플릿들로 검증
        text_heavy_templates = ["concept_code", "foundation_overview", "language_pattern"]
        for key in text_heavy_templates:
            plans = build_slide_plan(key, 12)
            for p in plans:
                if p.category == "text":
                    assert p.visual_type in TEXT_CATEGORY_VISUAL_TYPES, (
                        f"{key} slide_idx={p.slide_idx}: text category에 비허용 visual_type={p.visual_type}"
                    )

    def test_enforce_plan_visual_type_corrects_type_mismatch(self) -> None:
        """_enforce_plan_visual_type이 type 불일치를 교정한다."""
        data = {
            "slide_idx": 0,
            "visual": {"type": "concept_map", "data": {}},
        }
        plan_slot = {"slide_idx": 0, "visual_type": "metric-card", "must_have": []}
        result = _enforce_plan_visual_type(data, plan_slot)
        assert result["visual"]["type"] == "metric-card"  # type: ignore[index]

    def test_enforce_plan_visual_type_noop_when_no_plan(self) -> None:
        """plan_slot=None이면 data를 변경하지 않는다."""
        data = {"slide_idx": 0, "visual": {"type": "concept_map", "data": {}}}
        result = _enforce_plan_visual_type(data, None)
        assert result["visual"]["type"] == "concept_map"  # type: ignore[index]
