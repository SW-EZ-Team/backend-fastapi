"""모의고사 개선(2026-06-12) 회귀 테스트.

1. 최소 20문항 클램프 (allow_small_exam 우회 포함)
2. question_types 빈 목록 → 기본 혼합 유형 비례 분배
3. 메타 문항 결정론 필터
4. Spring 콜백 재시도 (404 레이스 → 재시도 후 성공)
5. AI 총평 약점주제 줄 파싱
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

from app.modules.ExamForge_V1.app._analysis_prompt import split_weak_topics
from app.modules.ExamForge_V1.mock_generation_callback import (
    send_generation_failed_callback,
)
from app.modules.ExamForge_V1.pipeline.nodes.plan_exam_node import (
    _DEFAULT_QUESTION_TYPES,
    _allocate_type_counts,
    _build_fallback_plan,
    _question_types,
    clamp_total_questions,
)
from app.modules.ExamForge_V1.quality.meta_question_filter import (
    filter_meta_questions,
    is_meta_question,
)


# ── 1. 최소 20문항 클램프 ──────────────────────────────────────────────


class TestMinTotalClamp:
    def test_small_total_clamped_to_20(self) -> None:
        """20 미만 요청은 계획 단계에서 20으로 클램프된다."""
        assert clamp_total_questions({"total_questions": 5})["total_questions"] == 20
        assert clamp_total_questions({"total_questions": 10})["total_questions"] == 20

    def test_explicit_small_exam_flag_bypasses_clamp(self) -> None:
        """allow_small_exam=True면 호출자의 작은 요청을 존중한다."""
        config = {"total_questions": 8, "allow_small_exam": True}
        assert clamp_total_questions(config)["total_questions"] == 8

    def test_max_100_kept(self) -> None:
        """최대 100문항 상한은 유지된다."""
        assert clamp_total_questions({"total_questions": 150})["total_questions"] == 100

    def test_normal_total_unchanged(self) -> None:
        """20 이상 요청은 그대로 유지된다."""
        assert clamp_total_questions({"total_questions": 30})["total_questions"] == 30


# ── 2. 유형 혼합 분배 ─────────────────────────────────────────────────


class TestTypeMixAllocation:
    def test_empty_types_resolve_to_default_mix(self) -> None:
        """빈 question_types는 기본 혼합 유형으로 수렴한다."""
        assert _question_types({"question_types": []}) == list(_DEFAULT_QUESTION_TYPES)

    def test_explicit_types_respected_exactly(self) -> None:
        """명시적 유형 목록(객관식 단독 등)은 정확히 그대로 사용한다."""
        explicit = ["ko_multiple_choice_5"]
        assert _question_types({"question_types": explicit}) == explicit

    def test_default_mix_for_20_matches_weights(self) -> None:
        """20문항 기본 혼합: mc5 6, mc4 3, 단답 4, 빈칸 3, OX 2, 서술 2."""
        counts = _allocate_type_counts(list(_DEFAULT_QUESTION_TYPES), 20)
        assert counts == {
            "ko_multiple_choice_5": 6,
            "ko_multiple_choice_4": 3,
            "ko_short_answer": 4,
            "ko_fill_blank": 3,
            "ko_true_false": 2,
            "ko_descriptive": 2,
        }

    def test_every_type_present_when_total_at_least_12(self) -> None:
        """총 12문항 이상이면 나열된 모든 유형이 최소 1문항씩 배정된다."""
        for total in (12, 15, 20, 30, 50, 100):
            counts = _allocate_type_counts(list(_DEFAULT_QUESTION_TYPES), total)
            assert sum(counts.values()) == total
            assert all(c >= 1 for c in counts.values()), (total, counts)

    def test_fallback_plan_uses_mixed_allocation(self) -> None:
        """폴백 계획도 동일한 혼합 분배·합계 보존을 따른다."""
        plan = _build_fallback_plan(
            subject="자료구조",
            total=20,
            config={"question_types": []},
            topics=[{"name": "스택", "importance": 1.0}],
        )
        allocations = plan["type_allocations"]
        assert sum(a["count"] for a in allocations) == 20
        assert {a["template_id"] for a in allocations} == set(_DEFAULT_QUESTION_TYPES)

    def test_fallback_plan_difficulty_follows_request(self) -> None:
        """폴백 계획의 난이도 분포는 요청 difficulty_distribution을 따른다."""
        plan = _build_fallback_plan(
            subject="자료구조",
            total=20,
            config={
                "question_types": ["ko_multiple_choice_5"],
                "difficulty_distribution": {4: 0.5, 5: 0.5},
            },
            topics=[],
        )
        dist = plan["type_allocations"][0]["difficulty_distribution"]
        assert set(dist) <= {4, 5}
        assert sum(dist.values()) == 20


# ── 3. 메타 문항 필터 ─────────────────────────────────────────────────


class TestMetaQuestionFilter:
    def test_meta_stems_detected(self) -> None:
        """시험 구성 자체를 묻는 stem(자기 참조 + 구성 요소)은 메타 문항으로 판정된다."""
        meta_stems = [
            "이 모의고사는 총 몇 문항으로 구성되어 있는가?",
            "이 시험의 합격 기준 점수는?",
            "본 문제지의 배점 방식은?",
            "이 시험의 응시 시간은 몇 분인가?",
            "해당 시험에서 객관식 문항의 비율은?",
            "이 문제의 배점은 몇 점인가?",
            "How many questions are in this exam?",
        ]
        for stem in meta_stems:
            assert is_meta_question(stem), stem

    def test_subject_stems_pass(self) -> None:
        """과목 내용 문항은 통과한다."""
        ok_stems = [
            "스택과 큐의 차이로 옳은 것은?",
            "다음 코드의 실행 결과는?",
            "TCP 3-way handshake의 순서를 배열하시오.",
        ]
        for stem in ok_stems:
            assert not is_meta_question(stem), stem

    def test_exam_as_subject_matter_passes(self) -> None:
        """시험을 '소재'로 다루는 정당한 과목 문항은 오탐하지 않는다(자기 참조 없음)."""
        ok_stems = [
            # 교육평가 — 문항 수는 과목 개념이다
            "검사 신뢰도는 문항 수가 증가하면 일반적으로 어떻게 변하는가?",
            # 자격시험 대비 강의 — 실제 시험 제도에 대한 지식
            "정보처리기사 필기시험의 합격 기준 점수는 몇 점인가?",
            "수능 수학 영역의 응시 시간은 몇 분인가?",
            # '같이 시험' — 앞 단어 끝 '이'가 자기 참조로 오탐되면 안 된다
            "다음과 같이 시험 데이터를 분할할 때 학습 데이터의 비율은?",
            # 통계 문항 — 동사 '본'(시험을 본)은 자기 참조가 아니다
            "학생들이 본 시험에서 평균 점수가 70점일 때 표준편차를 구하시오.",
            # 프로그래밍 — 'this test'(단위 테스트)는 메타가 아니다
            "What does this test verify in the following unit test code?",
            # 배점 단독 언급 — 자기 참조 없이는 메타가 아니다
            "문항 반응 이론에서 배점 가중치가 능력 추정에 미치는 영향은?",
        ]
        for stem in ok_stems:
            assert not is_meta_question(stem), stem

    def test_filter_returns_kept_and_removed(self) -> None:
        """필터는 통과 목록과 탈락 요약을 함께 반환한다."""
        drafts = [
            {"stem": "이 모의고사는 몇 문항인가?", "draft_id": "d1"},
            {"stem": "이진 탐색의 시간 복잡도는?", "draft_id": "d2"},
        ]
        kept, removed = filter_meta_questions(drafts)
        assert [d["draft_id"] for d in kept] == ["d2"]
        assert len(removed) == 1


# ── 4. 콜백 재시도 (404 레이스) ───────────────────────────────────────


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    """테스트용 HTTPError 생성 — read() 가능한 빈 본문 포함."""
    import io

    return urllib.error.HTTPError(url, code, "err", hdrs=None, fp=io.BytesIO(b"{}"))


class TestCallbackRetry:
    def test_404_then_success_retries(self) -> None:
        """Spring attempt 커밋 전 레이스(404) 후 재시도에서 성공한다."""
        calls = {"n": 0}

        class _OkResponse:
            def read(self) -> bytes:
                return b"{}"

            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *args):  # noqa: ANN002
                return False

        def fake_urlopen(request, timeout=0):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(request.full_url, 404)
            return _OkResponse()

        with patch(
            "app.modules.ExamForge_V1.mock_generation_callback.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), patch("app.modules.ExamForge_V1.mock_generation_callback.time.sleep"):
            # 예외 없이 완료되어야 한다 (1차 404 → 2차 성공)
            send_generation_failed_callback("eat_test", "이유")
        assert calls["n"] == 2

    def test_permanent_4xx_no_retry(self) -> None:
        """401 같은 영구 4xx는 즉시 실패하고 재시도하지 않는다."""
        import pytest

        from app.modules.ExamForge_V1.mock_generation_callback import (
            MockGenerationCallbackError,
        )

        calls = {"n": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ANN001
            calls["n"] += 1
            raise _http_error(request.full_url, 401)

        with patch(
            "app.modules.ExamForge_V1.mock_generation_callback.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), patch("app.modules.ExamForge_V1.mock_generation_callback.time.sleep"):
            with pytest.raises(MockGenerationCallbackError):
                send_generation_failed_callback("eat_test", "이유")
        assert calls["n"] == 1

    def test_connection_error_exhausts_all_attempts(self) -> None:
        """연결 실패는 모든 재시도(총 6회) 소진 후 실패를 올린다."""
        import pytest

        from app.modules.ExamForge_V1.mock_generation_callback import (
            MockGenerationCallbackError,
        )

        calls = {"n": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ANN001
            calls["n"] += 1
            raise urllib.error.URLError("connection refused")

        with patch(
            "app.modules.ExamForge_V1.mock_generation_callback.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), patch("app.modules.ExamForge_V1.mock_generation_callback.time.sleep"):
            with pytest.raises(MockGenerationCallbackError):
                send_generation_failed_callback("eat_test", "이유")
        assert calls["n"] == 6


# ── 5. 약점주제 줄 파싱 ───────────────────────────────────────────────


class TestWeakTopicParsing:
    def test_split_weak_topics_line(self) -> None:
        """마지막 '약점주제:' 줄을 분리하고 본문은 보존한다."""
        body, topics = split_weak_topics(
            "전반적으로 잘했어요.\n3번은 FIFO 혼동이에요.\n약점주제: FIFO/LIFO 혼동 | 포인터 | 재귀"
        )
        assert "약점주제" not in body
        assert topics == ["FIFO/LIFO 혼동", "포인터", "재귀"]

    def test_missing_line_returns_empty_topics(self) -> None:
        """형식 줄이 없으면 본문 전체 유지 + 빈 목록을 돌려준다."""
        body, topics = split_weak_topics("총평만 있어요.")
        assert body == "총평만 있어요."
        assert topics == []

    def test_duplicate_weak_topic_lines_take_last(self) -> None:
        """약점주제 줄이 두 번 있으면 마지막 줄만 분리한다(앞선 줄은 본문에 잔류)."""
        body, topics = split_weak_topics(
            "약점주제: 초기 추정 | 잘못된 줄\n본문 분석입니다.\n약점주제: 포인터 | 재귀"
        )
        assert topics == ["포인터", "재귀"]
        # 마지막 줄만 분리 — 앞선 약점주제 줄은 본문 위치 그대로 남는다(순서 보존 계약 고정).
        assert "초기 추정" in body
        assert body.endswith("본문 분석입니다.")

    def test_empty_and_whitespace_text(self) -> None:
        """빈/공백 입력은 빈 본문 + 빈 목록으로 조용히 통과한다(크래시 금지)."""
        assert split_weak_topics("") == ("", [])
        assert split_weak_topics("   \n  ") == ("", [])

    def test_weak_topic_line_with_empty_payload(self) -> None:
        """'약점주제:' 뒤가 비어 있으면 빈 목록을 돌려주고 본문은 유지한다."""
        body, topics = split_weak_topics("총평입니다.\n약점주제:")
        assert topics == []
        assert body == "총평입니다."


# ── 6. SPRING_BASE_URL 설정 검증 ─────────────────────────────────────


class TestSpringBaseUrlValidation:
    def test_empty_base_url_fails_fast_without_retry(self, monkeypatch) -> None:
        """SPRING_BASE_URL='' 이면 재시도 폭주 없이 즉시 명확한 에러를 올린다."""
        import pytest

        from app.modules.ExamForge_V1.mock_generation_callback import (
            MockGenerationCallbackError,
        )

        monkeypatch.setenv("SPRING_BASE_URL", "")
        calls = {"n": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ANN001
            calls["n"] += 1
            raise AssertionError("빈 베이스 URL이면 전송 시도 자체가 없어야 한다.")

        with patch(
            "app.modules.ExamForge_V1.mock_generation_callback.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            with pytest.raises(MockGenerationCallbackError, match="SPRING_BASE_URL"):
                send_generation_failed_callback("eat_test", "이유")
        assert calls["n"] == 0

    def test_missing_scheme_fails_fast(self, monkeypatch) -> None:
        """스킴 없는 URL(localhost:8080)도 영구 설정 오류로 즉시 실패한다."""
        import pytest

        from app.modules.ExamForge_V1.mock_generation_callback import (
            MockGenerationCallbackError,
        )

        monkeypatch.setenv("SPRING_BASE_URL", "localhost:8080/api")
        with pytest.raises(MockGenerationCallbackError, match="SPRING_BASE_URL"):
            send_generation_failed_callback("eat_test", "이유")

    def test_unset_uses_local_default(self, monkeypatch) -> None:
        """미설정이면 로컬 개발 기본값을 유지한다(기존 동작 보존)."""
        from app.modules.ExamForge_V1.mock_generation_callback import _get_spring_base_url

        monkeypatch.delenv("SPRING_BASE_URL", raising=False)
        assert _get_spring_base_url() == "http://localhost:8080/api"


# ── 6. AI 플래너 비정상 출력 견고성 (2026-06-13 실측 장애 회귀) ──────────


class TestPlanNodeRobustness:
    """Gemini 플래너가 난이도 dict 등 부분/비정상 JSON을 반환해도
    ExamPlan 필수 필드와 type_allocations가 절대 비지 않아야 한다."""

    @staticmethod
    def _run_plan_node(ai_payload):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.modules.ExamForge_V1.pipeline.nodes import plan_exam_node as mod

        connector = MagicMock()
        connector.generate = AsyncMock(return_value=MagicMock(text="json"))
        state = {
            "topics": [{"name": "스택", "importance": 1.0}],
            "exam_config": {"question_types": [], "total_questions": 20},
            "subject": "자료구조",
        }
        with (
            patch.object(mod, "get_planner_connector", return_value=connector),
            patch.object(mod, "parse_llm_json", return_value=ai_payload),
        ):
            return asyncio.run(mod.plan_exam_node(state))

    def _assert_plan_complete(self, result: dict) -> None:
        plan = result["exam_plan"]
        # ExamPlan(pydantic) 필수 필드가 모두 존재해야 직렬화가 죽지 않는다
        for field in ("exam_title", "subject", "total_points", "time_limit_minutes", "locale"):
            assert field in plan, f"필수 필드 누락: {field}"
        allocations = plan["type_allocations"]
        assert allocations, "type_allocations가 비면 생성 0건이 된다"
        # 소스 폭 캡(effective target)이 적용될 수 있으므로 literal 20이 아닌
        # 노드가 결정한 total_questions와 배분 합계가 일치하는지로 검사한다.
        # (이 테스트의 본질은 JSON robustness — 배분 합 == 계획 문항 수)
        total = plan["total_questions"]
        assert total > 0, "total_questions가 0 이하"
        assert sum(a["count"] for a in allocations) == total

    def test_difficulty_dict_only_payload_recovers(self) -> None:
        """실측 장애 케이스: 플래너가 난이도 dict만 반환."""
        self._assert_plan_complete(self._run_plan_node({"3": 3, "4": 3, "5": 2}))

    def test_partial_payload_merges_over_fallback(self) -> None:
        """일부 필드만 온 경우 폴백 베이스 위에 병합된다."""
        result = self._run_plan_node({"exam_title": "AI가 지은 제목"})
        self._assert_plan_complete(result)
        assert result["exam_plan"]["exam_title"] == "AI가 지은 제목"

    def test_non_dict_payload_falls_back(self) -> None:
        """최상위가 dict가 아니면 폴백 계획을 쓴다."""
        self._assert_plan_complete(self._run_plan_node(3.14))

    def test_broken_allocations_recover_to_fallback(self) -> None:
        """type_allocations가 깨진 타입이면 폴백 배분으로 복구한다."""
        self._assert_plan_complete(
            self._run_plan_node({"exam_title": "t", "type_allocations": {"oops": 1}})
        )

    def test_garbage_keys_do_not_leak_into_plan(self) -> None:
        """AI의 쓰레기 키('3','4','5')가 최종 plan에 남지 않는다."""
        result = self._run_plan_node({"3": 3, "4": 3, "5": 2, "exam_title": "제목"})
        plan = result["exam_plan"]
        assert "3" not in plan and "4" not in plan and "5" not in plan
        assert plan["exam_title"] == "제목"
