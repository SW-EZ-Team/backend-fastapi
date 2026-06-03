"""plan-first 블루프린트 결정성·계약 보장 집중 단위 테스트.

검증 범위:
A. 블루프린트 승격 — num_choices/target_answer_position/concept_key 결정성
B. 슬롯 count = 문항 수, 슬롯 1:1 매핑
C. concept_key 유일성 (중복 슬롯 0)
D. target_answer_position 분포 균등
E. 검증 게이트 — answer_position_plan 일치, concept_key 중복 탐지

AI 실호출 없음 — 전부 단위 테스트/mock.
"""
from __future__ import annotations

from collections import Counter

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.concept_blueprint import (
    _balanced_target_positions,
    _num_choices_for_template,
    build_question_blueprint,
    compute_answer_position_plan,
    blueprint_prompt,
)
from app.modules.ExamForge_V1.pipeline.nodes.validate_node import (
    _validate_concept_key_uniqueness,
    _validate_answer_position_plan,
)


# ── 공용 픽스처 ────────────────────────────────────────────────────────────────

def _make_topics(n: int = 5) -> list[dict]:
    """n개의 고유 주제/개념을 가진 topic 목록을 만든다."""
    topics = []
    for i in range(n):
        topics.append({
            "name": f"주제{i}",
            "chapter": f"챕터{i}",
            "importance": (n - i) * 0.2,
            "key_topics": [f"개념{i}_A", f"개념{i}_B", f"개념{i}_C"],
        })
    return topics


def _make_allocations(template_id: str, counts: dict[int, int]) -> list[dict]:
    """단일 템플릿의 난이도 배분을 만든다."""
    return [{"template_id": template_id, "count": sum(counts.values()), "difficulty_distribution": counts}]


# ── A: 블루프린트 승격 결정성 ─────────────────────────────────────────────────

class TestBlueprintDeterminism:
    """동일 입력으로 두 번 호출하면 슬롯이 완전히 동일해야 한다."""

    def test_reproducibility_same_exam_id(self) -> None:
        """같은 exam_id이면 num_choices/target_answer_position/concept_key가 동일하다."""
        topics = _make_topics(4)
        allocs = _make_allocations("ko_multiple_choice_5", {2: 2, 3: 3, 4: 2})
        bp1 = build_question_blueprint(topics, allocs, exam_id="exam_abc")
        bp2 = build_question_blueprint(topics, allocs, exam_id="exam_abc")
        assert len(bp1) == len(bp2)
        for s1, s2 in zip(bp1, bp2):
            assert s1["num_choices"] == s2["num_choices"], "num_choices가 달라졌다"
            assert s1["target_answer_position"] == s2["target_answer_position"], "정답 위치가 달라졌다"
            assert s1["concept_key"] == s2["concept_key"], "concept_key가 달라졌다"

    def test_different_exam_id_changes_positions(self) -> None:
        """다른 exam_id이면 정답 위치 배정이 달라질 수 있다."""
        topics = _make_topics(3)
        allocs = _make_allocations("ko_multiple_choice_5", {3: 10})
        bp_a = build_question_blueprint(topics, allocs, exam_id="id_aaa")
        bp_b = build_question_blueprint(topics, allocs, exam_id="id_bbb")
        pos_a = [s["target_answer_position"] for s in bp_a]
        pos_b = [s["target_answer_position"] for s in bp_b]
        # 두 seed가 다르면 shuffled 순서가 달라야 한다 (충돌 가능성 극히 낮음)
        assert pos_a != pos_b, "서로 다른 exam_id임에도 정답 위치 배정이 동일하다"

    def test_slot_count_equals_total_questions(self) -> None:
        """슬롯 수 == 문항 수 (배분 합계)."""
        topics = _make_topics(3)
        allocs = _make_allocations("ko_multiple_choice_4", {1: 3, 3: 5, 5: 2})
        bp = build_question_blueprint(topics, allocs, exam_id="e1")
        assert len(bp) == 10

    def test_all_slots_have_num_choices(self) -> None:
        """모든 슬롯에 num_choices가 양의 정수로 채워진다."""
        topics = _make_topics(2)
        allocs = _make_allocations("ko_multiple_choice_5", {3: 5})
        bp = build_question_blueprint(topics, allocs, exam_id="e2")
        for slot in bp:
            assert isinstance(slot["num_choices"], int), "num_choices가 정수가 아님"
            assert slot["num_choices"] > 0, "num_choices가 0 이하"

    def test_all_slots_have_target_answer_position(self) -> None:
        """모든 슬롯에 target_answer_position이 0..num_choices-1 범위에 있다."""
        topics = _make_topics(2)
        allocs = _make_allocations("ko_multiple_choice_5", {3: 6})
        bp = build_question_blueprint(topics, allocs, exam_id="e3")
        for slot in bp:
            pos = slot["target_answer_position"]
            nc = slot["num_choices"]
            assert isinstance(pos, int), "target_answer_position이 정수가 아님"
            assert 0 <= pos < nc, f"정답 위치 {pos}이 0..{nc-1} 범위 벗어남"


# ── B: num_choices 카탈로그 계약 읽기 ─────────────────────────────────────────

class TestNumChoicesFromCatalog:
    """카탈로그 spec must_have에서 보기 수를 정확히 읽는다."""

    def test_five_choice_template_returns_5(self) -> None:
        """ko_multiple_choice_5 → 5."""
        assert _num_choices_for_template("ko_multiple_choice_5") == 5

    def test_four_choice_template_returns_4(self) -> None:
        """ko_multiple_choice_4 → 4."""
        assert _num_choices_for_template("ko_multiple_choice_4") == 4

    def test_engineer_written_returns_5(self) -> None:
        """engineer_written(자격시험, 5지선다 집합) → 정확히 5."""
        # must_have에 '보기 N개' 절이 없어 _FIVE_OPTION_TEMPLATES 집합으로 폴백 → 5
        result = _num_choices_for_template("engineer_written")
        assert result == 5, "engineer_written은 5지선다 집합이므로 정확히 5여야 한다"

    def test_unknown_template_returns_positive_int(self) -> None:
        """알 수 없는 template_id에도 양의 정수를 반환한다 (폴백)."""
        nc = _num_choices_for_template("nonexistent_template_xyz")
        assert isinstance(nc, int) and nc > 0


# ── C: concept_key 유일성 ─────────────────────────────────────────────────────

class TestConceptKeyUniqueness:
    """전체 슬롯에 걸쳐 concept_key가 모두 다르다 (중복 슬롯 0)."""

    def test_no_duplicate_concept_keys(self) -> None:
        """슬롯 concept_key가 전부 유일하다."""
        topics = _make_topics(3)
        allocs = _make_allocations("ko_multiple_choice_5", {2: 3, 3: 3, 4: 3})
        bp = build_question_blueprint(topics, allocs, exam_id="e4")
        keys = [s["concept_key"] for s in bp]
        assert len(keys) == len(set(keys)), f"concept_key 중복 발견: {keys}"

    def test_concept_key_uniqueness_with_fewer_concepts(self) -> None:
        """개념 수보다 문항 수가 많아도 (diff·reasoning 조합으로) concept_key 중복 없음."""
        # 주제 1개, 개념 2개, 문항 10개 — (diff, reasoning) 다양화로 유일화
        topics = [{"name": "주제A", "chapter": "챕터A", "importance": 1.0, "key_topics": ["개념X", "개념Y"]}]
        allocs = _make_allocations("ko_multiple_choice_5", {1: 2, 2: 2, 3: 2, 4: 2, 5: 2})
        bp = build_question_blueprint(topics, allocs, exam_id="e5")
        keys = [s["concept_key"] for s in bp]
        assert len(keys) == len(set(keys)), f"concept_key 중복: {keys}"

    def test_validate_node_detects_duplicate_concept_keys(self) -> None:
        """validate_node의 concept_key 유일성 게이트가 중복을 탐지한다."""
        questions = [
            {"draft_id": "d1", "_concept_key": "챕터A::주제A::개념X::d3::2단계 적용 추론"},
            {"draft_id": "d2", "_concept_key": "챕터A::주제A::개념X::d3::2단계 적용 추론"},  # 중복
            {"draft_id": "d3", "_concept_key": "챕터B::주제B::개념Y::d2::개념 확인"},
        ]
        issues, failed = _validate_concept_key_uniqueness(questions)
        assert len(issues) > 0, "중복 concept_key가 탐지되지 않았다"
        assert "d2" in failed, "중복된 뒤쪽 문항이 failed_ids에 없다"
        assert "d1" not in failed, "첫 번째 문항이 잘못 실패 처리됐다"

    def test_validate_node_passes_unique_concept_keys(self) -> None:
        """concept_key가 모두 유일하면 이슈 없음."""
        questions = [
            {"draft_id": "d1", "_concept_key": "A::a::x::d3::2단계"},
            {"draft_id": "d2", "_concept_key": "B::b::y::d2::개념 확인"},
            {"draft_id": "d3", "_concept_key": "A::a::x::d4::오류 원인 분석"},
        ]
        issues, failed = _validate_concept_key_uniqueness(questions)
        assert issues == [], f"유일한 concept_key인데 이슈 발생: {issues}"
        assert failed == []


# ── D: target_answer_position 균등 분포 ──────────────────────────────────────

class TestBalancedTargetPositions:
    """_balanced_target_positions가 ChapterStudio와 동일한 균등 배정을 수행한다."""

    def test_even_distribution_4_choices(self) -> None:
        """4보기 8문항 → 각 위치 정확히 2회."""
        positions = _balanced_target_positions(8, num_choices=4, seed=0)
        counts = Counter(positions)
        assert counts == {0: 2, 1: 2, 2: 2, 3: 2}

    def test_even_distribution_5_choices(self) -> None:
        """5보기 10문항 → 각 위치 정확히 2회."""
        positions = _balanced_target_positions(10, num_choices=5, seed=0)
        counts = Counter(positions)
        assert counts == {0: 2, 1: 2, 2: 2, 3: 2, 4: 2}

    def test_positions_in_valid_range(self) -> None:
        """모든 위치 값이 0..num_choices-1 내에 있다."""
        positions = _balanced_target_positions(15, num_choices=4, seed=42)
        assert all(0 <= p < 4 for p in positions)

    def test_deterministic_with_same_seed(self) -> None:
        """같은 seed면 결과가 항상 동일하다."""
        p1 = _balanced_target_positions(12, num_choices=4, seed=7)
        p2 = _balanced_target_positions(12, num_choices=4, seed=7)
        assert p1 == p2

    def test_different_seed_gives_different_order(self) -> None:
        """다른 seed면 순서가 달라진다 (균등 분포는 유지)."""
        p1 = _balanced_target_positions(12, num_choices=4, seed=1)
        p2 = _balanced_target_positions(12, num_choices=4, seed=999)
        # 내용(개수)은 같지만 순서는 달라야 한다
        assert Counter(p1) == Counter(p2)
        assert p1 != p2, "seed가 다른데 순서가 같다"

    def test_blueprint_positions_are_uniform(self) -> None:
        """블루프린트 전체 슬롯의 target_answer_position이 균등 분포다."""
        topics = _make_topics(4)
        allocs = _make_allocations("ko_multiple_choice_5", {3: 10})
        bp = build_question_blueprint(topics, allocs, exam_id="uniform_test")
        positions = [s["target_answer_position"] for s in bp]
        counts = Counter(positions)
        # 5보기 10문항 → 각 위치 2회씩
        assert all(v == 2 for v in counts.values()), f"균등 분포 아님: {dict(counts)}"

    def test_blueprint_positions_remainder_distribution(self) -> None:
        """나머지가 있어도 최대 편차 1 이내다 (7문항 / 4보기)."""
        topics = _make_topics(3)
        allocs = _make_allocations("ko_multiple_choice_4", {3: 7})
        bp = build_question_blueprint(topics, allocs, exam_id="rem_test")
        positions = [s["target_answer_position"] for s in bp]
        counts = Counter(positions)
        values = list(counts.values())
        assert max(values) - min(values) <= 1, f"편차 초과: {dict(counts)}"


# ── E: 검증 게이트 — answer_position_plan 일치 ───────────────────────────────

class TestAnswerPositionPlanGate:
    """_validate_answer_position_plan이 사전 배정과 실제 분포 불일치를 탐지한다."""

    def _make_questions_with_positions(self, positions: list[int], n_choices: int = 5) -> list[dict]:
        """주어진 정답 위치 목록으로 문항 더미 데이터를 만든다."""
        questions = []
        for i, pos in enumerate(positions):
            opts = [
                {"label": str(j + 1), "text": f"보기{j}", "is_correct": j == pos}
                for j in range(n_choices)
            ]
            questions.append({
                "draft_id": f"d{i}",
                "question_id": f"q{i}",
                "options": opts,
            })
        return questions

    def test_exact_match_returns_no_issues(self) -> None:
        """실제 분포 == 계획 → 이슈 없음."""
        # 5보기 10문항 균등: 각 위치 2회
        positions = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
        questions = self._make_questions_with_positions(positions)
        plan = {"answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2}}
        issues = _validate_answer_position_plan(questions, plan)
        assert issues == [], f"계획 일치인데 이슈 발생: {issues}"

    def test_mismatch_returns_issues(self) -> None:
        """실제 분포 != 계획 → 이슈 반환."""
        # 계획: 균등. 실제: 위치 0에 몰림
        positions = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        questions = self._make_questions_with_positions(positions)
        plan = {"answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2}}
        issues = _validate_answer_position_plan(questions, plan)
        assert len(issues) > 0, "불일치인데 이슈가 없다"
        assert "불일치" in issues[0] or "plan" in issues[0].lower()

    def test_no_plan_skips_check(self) -> None:
        """answer_position_plan이 없으면 검사 생략 (블루프린트 미적용 하위호환)."""
        questions = self._make_questions_with_positions([0, 1, 2])
        plan: dict = {}  # answer_position_plan 없음
        issues = _validate_answer_position_plan(questions, plan)
        assert issues == []

    def test_blueprint_generates_correct_position_plan(self) -> None:
        """build_question_blueprint 후 compute_answer_position_plan이 올바른 계획을 반환한다."""
        topics = _make_topics(3)
        allocs = _make_allocations("ko_multiple_choice_5", {3: 10})
        bp = build_question_blueprint(topics, allocs, exam_id="pp_test")
        pos_plan = compute_answer_position_plan(bp)
        # 5보기 10문항 → 각 위치 2회
        assert pos_plan == {0: 2, 1: 2, 2: 2, 3: 2, 4: 2}, f"계획 계산 오류: {pos_plan}"


# ── F: blueprint_prompt 계약 문구 ─────────────────────────────────────────────

class TestBlueprintPrompt:
    """blueprint_prompt가 num_choices와 target_answer_position을 명시한다."""

    def test_num_choices_in_prompt(self) -> None:
        """num_choices가 프롬프트에 포함된다."""
        slot = {
            "chapter": "챕터A", "concept": "개념X", "difficulty": 3,
            "bloom_level": "적용", "reasoning_type": "2단계 적용 추론",
            "num_choices": 5, "target_answer_position": 2,
        }
        prompt = blueprint_prompt(slot)
        assert "5개" in prompt, "num_choices=5가 프롬프트에 없다"
        assert "고정" in prompt, "고정 지시가 프롬프트에 없다"

    def test_target_position_in_prompt(self) -> None:
        """target_answer_position이 프롬프트에 포함된다."""
        slot = {
            "chapter": "챕터B", "concept": "개념Y", "difficulty": 2,
            "bloom_level": "이해", "reasoning_type": "개념 확인",
            "num_choices": 4, "target_answer_position": 1,
        }
        prompt = blueprint_prompt(slot)
        # 0-index 1 → label='2'
        assert "1번 인덱스" in prompt or "target_answer_position=1" in prompt or "label='2'" in prompt

    def test_none_slot_returns_empty(self) -> None:
        """slot이 None이면 빈 문자열을 반환한다."""
        assert blueprint_prompt(None) == ""

    def test_no_target_position_omits_position_line(self) -> None:
        """target_answer_position이 없으면 정답 위치 줄을 포함하지 않는다."""
        slot = {
            "chapter": "챕터C", "concept": "개념Z", "difficulty": 1,
            "bloom_level": "기억", "reasoning_type": "개념 확인",
            "num_choices": 4,
            # target_answer_position 없음
        }
        prompt = blueprint_prompt(slot)
        assert "인덱스" not in prompt, "position 미배정인데 위치 지시가 프롬프트에 있다"


# ── P1-A: target_answer_position 노드 전파 (적대적 검증 대응) ──────────────────

class TestTargetPositionPropagation:
    """_attach_blueprint → apply_task_metadata 경로에서 target_answer_position이 살아남는지 검증.

    함수에 필드를 수동 주입하는 단위 테스트는 이 결함(전파 누락)을 잡지 못한다.
    실제 노드 헬퍼 체인을 통과시켜야 P1-A가 닫혔음을 증명할 수 있다.
    """

    def test_apply_task_metadata_preserves_target_position(self) -> None:
        """apply_task_metadata가 target_answer_position과 num_choices를 복사한다."""
        from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import apply_task_metadata

        # _attach_blueprint가 만든 task와 동일한 형태
        task = {
            "template_id": "ko_multiple_choice_5", "topic": "주제A", "difficulty": 3,
            "_blueprint_slot": 1, "_chapter": "챕터A",
            "_concept_key": "챕터A::주제A::개념X::d3::2단계",
            "num_choices": 5, "target_answer_position": 2,
        }
        draft = {"stem": "문제", "options": []}
        result = apply_task_metadata(draft, task)
        assert result["target_answer_position"] == 2, "target_answer_position이 유실됐다 (P1-A 결함)"
        assert result["num_choices"] == 5, "num_choices가 유실됐다"

    def test_apply_task_metadata_preserves_position_zero(self) -> None:
        """target_answer_position=0(falsy)도 유실되지 않는다 (None만 제외)."""
        from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import apply_task_metadata

        task = {
            "template_id": "ko_multiple_choice_4", "difficulty": 2,
            "num_choices": 4, "target_answer_position": 0,
        }
        draft = {"stem": "문제", "options": []}
        result = apply_task_metadata(draft, task)
        assert result["target_answer_position"] == 0, "0-index 정답 위치가 falsy로 잘려나갔다"

    def test_attach_blueprint_carries_position_into_task(self) -> None:
        """_attach_blueprint가 슬롯의 target_answer_position을 task에 넣는다."""
        from app.modules.ExamForge_V1.pipeline.nodes.generate_questions_node import _attach_blueprint

        slot = {
            "slot": 1, "template_id": "ko_multiple_choice_5",
            "chapter": "챕터A", "topic": "주제A", "concept": "개념X",
            "difficulty": 3, "bloom_level": "적용", "reasoning_type": "2단계",
            "concept_key": "챕터A::주제A::개념X::d3::2단계",
            "num_choices": 5, "target_answer_position": 3,
        }
        task = _attach_blueprint({"template_id": "ko_multiple_choice_5", "topic": "주제A"}, slot)
        assert task["target_answer_position"] == 3
        assert task["num_choices"] == 5

    @pytest.mark.asyncio
    async def test_distractors_realigns_wrong_position_end_to_end(self) -> None:
        """AI가 정답을 슬롯 계약과 다른 위치에 채워도 distractors 노드가 재배치한다.

        이 테스트가 P1-A 핵심: 실제 _attach_blueprint→apply_task_metadata→distractors
        경로로 target_answer_position이 살아남아 _verify_and_align_positions가 실행되는지 확인.
        """
        from unittest.mock import patch
        from app.modules.ExamForge_V1.pipeline.nodes.generate_questions_node import _attach_blueprint
        from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import apply_task_metadata
        from app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node import (
            generate_distractors_node,
        )

        # 슬롯: 정답 위치는 2번(0-index)이어야 한다
        slot = {
            "slot": 1, "template_id": "ko_multiple_choice_5",
            "chapter": "챕터A", "topic": "주제A", "concept": "개념X",
            "difficulty": 3, "bloom_level": "적용", "reasoning_type": "2단계",
            "concept_key": "챕터A::주제A::개념X::d3::2단계",
            "num_choices": 5, "target_answer_position": 2,
        }
        task = _attach_blueprint({"template_id": "ko_multiple_choice_5", "topic": "주제A"}, slot)

        # AI가 정답을 0번 위치에 잘못 채운 question draft (계약은 2번)
        ai_draft = {
            "draft_id": "d1", "template_id": "ko_multiple_choice_5",
            "topic": "주제A", "difficulty": 3, "bloom_level": "적용", "stem": "문제",
            "options": [
                {"label": "1", "text": "정답", "is_correct": True},   # 0번 — 틀린 위치
                {"label": "2", "text": "오답", "is_correct": False},
                {"label": "3", "text": "오답", "is_correct": False},
                {"label": "4", "text": "오답", "is_correct": False},
                {"label": "5", "text": "오답", "is_correct": False},
            ],
        }
        # 실제 파이프라인처럼 apply_task_metadata를 거친다 (전파 경로 검증)
        question = apply_task_metadata(ai_draft, task)
        assert question["target_answer_position"] == 2, "전파 단계에서 이미 유실됨 (P1-A)"

        # distractors 재작성은 끄고(원본 보존), 정답 위치 정렬만 검증
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node.distractor_rewrite_enabled",
            return_value=False,
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node.get_text_connector",
        ):
            result = await generate_distractors_node({
                "questions": [question],
                "locale": "ko",
            })

        out = result["questions_with_distractors"][0]
        # 정렬 후 정답이 2번(0-index) 위치로 이동했는지 확인
        correct_idx = next(
            i for i, o in enumerate(out["options"]) if o.get("is_correct")
        )
        assert correct_idx == 2, (
            f"정답 위치가 슬롯 계약(2)으로 재배치되지 않음 — actual={correct_idx} (P1-A 미수정)"
        )

    @pytest.mark.asyncio
    async def test_distractors_no_move_when_position_correct(self) -> None:
        """AI가 계약대로 올바른 위치에 채우면 이동 0 (정상 경로)."""
        from unittest.mock import patch
        from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import apply_task_metadata
        from app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node import (
            generate_distractors_node,
        )

        task = {
            "template_id": "ko_multiple_choice_5", "topic": "주제A", "difficulty": 3,
            "num_choices": 5, "target_answer_position": 1,
        }
        # AI가 정답을 1번(0-index)에 올바르게 채움
        ai_draft = {
            "draft_id": "d1", "template_id": "ko_multiple_choice_5",
            "topic": "주제A", "difficulty": 3, "bloom_level": "적용", "stem": "문제",
            "options": [
                {"label": "1", "text": "오답", "is_correct": False},
                {"label": "2", "text": "정답", "is_correct": True},   # 1번 — 올바른 위치
                {"label": "3", "text": "오답", "is_correct": False},
                {"label": "4", "text": "오답", "is_correct": False},
                {"label": "5", "text": "오답", "is_correct": False},
            ],
        }
        question = apply_task_metadata(ai_draft, task)
        original_texts = [o["text"] for o in question["options"]]

        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node.distractor_rewrite_enabled",
            return_value=False,
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node.get_text_connector",
        ):
            result = await generate_distractors_node({
                "questions": [question], "locale": "ko",
            })

        out = result["questions_with_distractors"][0]
        # 보기 순서가 그대로 유지됐는지 (이동 0)
        assert [o["text"] for o in out["options"]] == original_texts, "정상 경로인데 보기가 이동됨"
        correct_idx = next(i for i, o in enumerate(out["options"]) if o.get("is_correct"))
        assert correct_idx == 1


# ── P1-B: 개수 보장 하드 게이트 라우팅 (적대적 검증 대응) ──────────────────────

class TestCountGateRouting:
    """개수만 부족한 경우(9/10, 구조OK·검증PASS·중복0)가 passed로 새지 않는지 검증.

    이전 결함: _validate_answer_position_plan/개수 미달이 global_issues에만 남고
    route_after_validation은 global_issues를 안 봐서 passed로 출고됨.
    """

    def _passing_question(self, i: int, slot_id: int) -> dict:
        """구조·검증 모두 통과하는 문항 더미를 만든다."""
        return {
            "draft_id": f"d{i}", "question_id": f"q{i}",
            "template_id": "ko_multiple_choice_5",
            "_blueprint_slot": slot_id,
            "_concept_key": f"key::{slot_id}",
            "stem": f"문제{i}",
            "options": [
                {"label": str(j + 1), "text": f"보기{j}", "is_correct": j == (i % 5)}
                for j in range(5)
            ],
            "correct_answer": str((i % 5) + 1),
            "explanation": "정답 근거: ... 오답 해설: ...",
            "_verification": {"passed": True},
        }

    def _blueprint(self, n: int) -> list[dict]:
        """n개 슬롯의 블루프린트를 만든다."""
        return [{"slot": i + 1, "concept_key": f"key::{i + 1}"} for i in range(n)]

    def test_validate_node_count_gate_detects_shortfall(self) -> None:
        """블루프린트 10슬롯인데 9문항만 채워지면 missing_count=1, failed_ids에 placeholder."""
        from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _validate_question_count

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(9)]  # 9개
        plan = {"total_questions": 10, "question_blueprint": self._blueprint(10)}
        failed_ids: list[str] = []
        issues, missing = _validate_question_count(questions, plan, failed_ids)
        assert missing == 1, f"누락 슬롯 1개를 못 잡음: missing={missing}"
        assert len(issues) > 0, "누락 이슈 메시지가 없다"
        assert any(m.startswith("__missing_slot_") for m in failed_ids), (
            "누락 슬롯 placeholder가 failed_ids에 없다"
        )

    def test_validate_node_count_gate_passes_full_set(self) -> None:
        """10슬롯 10문항 모두 채워지면 missing_count=0."""
        from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _validate_question_count

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(10)]
        plan = {"total_questions": 10, "question_blueprint": self._blueprint(10)}
        failed_ids: list[str] = []
        issues, missing = _validate_question_count(questions, plan, failed_ids)
        assert missing == 0
        assert issues == []
        assert failed_ids == []

    def test_count_gate_no_blueprint_uses_total(self) -> None:
        """블루프린트 없으면 total_questions로 단순 비교."""
        from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _validate_question_count

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(7)]
        plan = {"total_questions": 10}  # 블루프린트 없음
        failed_ids: list[str] = []
        issues, missing = _validate_question_count(questions, plan, failed_ids)
        assert missing == 3
        assert any(m.startswith("__missing_count_") for m in failed_ids)

    def test_route_sends_count_shortfall_to_retry(self) -> None:
        """9/10 + 구조OK·검증PASS·중복1.0인데도 missing_count>0이면 retry로 라우팅."""
        from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation

        # 9문항 전부 통과 상태 — 구조/검증 실패 없음
        questions = [self._passing_question(i, slot_id=i + 1) for i in range(9)]
        state = {
            "verified_questions": questions,
            "failed_question_ids": ["__missing_slot_10"],  # validate_node가 넣은 placeholder
            "retry_count": 0,
            "max_retries": 3,
            "exam_plan": {
                "total_questions": 10,
                "answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2},
                "question_blueprint": self._blueprint(10),
            },
            "validation_report": {
                "answer_accuracy_rate": 1.0,   # 검증 PASS
                "dedup_score": 1.0,            # 중복 0
                "missing_count": 1,            # 개수 부족
                "answer_position_mismatch": False,
            },
        }
        result = route_after_validation(state)
        assert result == "retry", f"개수 부족인데 {result}로 라우팅됨 (P1-B 미수정)"

    def test_route_count_shortfall_exhausted_at_max_retries(self) -> None:
        """개수 부족 + 최대 재시도 도달 시 exhausted."""
        from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(9)]
        state = {
            "verified_questions": questions,
            "failed_question_ids": ["__missing_slot_10"],
            "retry_count": 3,
            "max_retries": 3,
            "exam_plan": {
                "total_questions": 10,
                "answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2},
                "question_blueprint": self._blueprint(10),
            },
            "validation_report": {
                "answer_accuracy_rate": 1.0, "dedup_score": 1.0,
                "missing_count": 1, "answer_position_mismatch": False,
            },
        }
        result = route_after_validation(state)
        assert result == "exhausted"

    def test_route_full_set_passes(self) -> None:
        """10/10 모두 통과 + missing_count=0이면 passed (회귀 방지)."""
        from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(10)]
        state = {
            "verified_questions": questions,
            "failed_question_ids": [],
            "retry_count": 0,
            "max_retries": 3,
            "exam_plan": {
                "total_questions": 10,
                "answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2},
                "question_blueprint": self._blueprint(10),
            },
            "validation_report": {
                "answer_accuracy_rate": 1.0, "dedup_score": 1.0,
                "missing_count": 0, "answer_position_mismatch": False,
            },
        }
        result = route_after_validation(state)
        assert result == "passed"

    def test_route_position_mismatch_to_retry(self) -> None:
        """정답 위치 분포 불일치도 retry로 승격된다."""
        from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation

        questions = [self._passing_question(i, slot_id=i + 1) for i in range(10)]
        state = {
            "verified_questions": questions,
            "failed_question_ids": [],
            "retry_count": 0,
            "max_retries": 3,
            "exam_plan": {
                "total_questions": 10,
                "answer_position_plan": {0: 2, 1: 2, 2: 2, 3: 2, 4: 2},
                "question_blueprint": self._blueprint(10),
            },
            "validation_report": {
                "answer_accuracy_rate": 1.0, "dedup_score": 1.0,
                "missing_count": 0,
                "answer_position_mismatch": True,  # 위치 불일치
            },
        }
        result = route_after_validation(state)
        assert result == "retry", "위치 분포 불일치인데 passed로 라우팅됨"


class TestValidateNodeCountGateIntegration:
    """validate_node → route_after_validation 통합: 9/10이 실제로 retry로 가는지."""

    @pytest.mark.asyncio
    async def test_nine_of_ten_routes_to_retry_end_to_end(self) -> None:
        """검증 모두 PASS·중복0인 9문항이 validate_node를 거쳐 retry로 라우팅된다."""
        from app.modules.ExamForge_V1.pipeline.nodes.validate_node import validate_node
        from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation

        # 서로 다른 concept_key·정답위치를 가진 9문항 (구조/검증 통과)
        questions = []
        for i in range(9):
            pos = i % 5
            questions.append({
                "draft_id": f"d{i}", "question_id": f"q{i}",
                "template_id": "ko_multiple_choice_5",
                "_blueprint_slot": i + 1,
                "_concept_key": f"챕터{i}::주제{i}::개념{i}::d3::2단계",
                "topic": f"주제{i}", "difficulty": 3, "bloom_level": "적용",
                "stem": f"서로 다른 발문 {i}: 개념 {i}을 적용한 결과로 옳은 것은?",
                "options": [
                    {"label": str(j + 1), "text": f"보기{i}_{j}", "is_correct": j == pos}
                    for j in range(5)
                ],
                "correct_answer": str(pos + 1),
                "explanation": "정답 근거: ... 오답 해설: 2번/3번/4번/5번 각각 오개념 ...",
                "_verification": {"passed": True},
            })

        plan = {
            "total_questions": 10,
            "topic_weights": {f"주제{i}": 0.1 for i in range(9)},
            # 블루프린트 10슬롯 (1개 누락 유도)
            "question_blueprint": [
                {"slot": i + 1, "concept_key": f"챕터{i}::주제{i}::개념{i}::d3::2단계"}
                for i in range(10)
            ],
            # 9문항 실제 위치 분포에 맞춘 계획 (위치 게이트는 통과시키고 개수만 부족하게)
            "answer_position_plan": dict(Counter(i % 5 for i in range(9))),
        }
        state = {
            "verified_questions": questions,
            "exam_plan": plan,
            "source_text": "일반 학습 자료",
            "retry_count": 0,
            "max_retries": 3,
        }

        validate_result = await validate_node(state)
        report = validate_result["validation_report"]
        # 개수 게이트가 누락을 잡았는지
        assert report["missing_count"] == 1, f"개수 게이트 미작동: {report.get('missing_count')}"

        # validate 결과를 state에 반영해 라우팅
        routing_state = {
            **state,
            "validation_report": report,
            "failed_question_ids": validate_result["failed_question_ids"],
        }
        route = route_after_validation(routing_state)
        assert route == "retry", (
            f"9/10인데 {route}로 라우팅됨 — 모자란 시험이 출고될 뻔함 (P1-B 미수정)"
        )
