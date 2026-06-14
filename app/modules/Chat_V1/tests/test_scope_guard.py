# Chat_V1 범위 가드 단위 테스트다.
# 정책 변경(2026-06-12): 강의 범위 밖 질문도 거절하지 않고 답변을 유지한 채
# 끝에 SCOPE_NOTICE 한 줄만 덧붙인다. 슬라이드 인용 추출은 기존 동작을 유지한다.
from __future__ import annotations

from app.modules.Chat_V1.app.schemas import ChatRequest, LectureContext, SlideContext
from app.modules.Chat_V1.app.scope_guard import (
    SCOPE_NOTICE,
    apply_hallucination_guard,
    build_lecture_keywords,
    extract_referenced_slides,
)


def _request() -> ChatRequest:
    return ChatRequest(
        session_id="s-1",
        user_message="질문",
        lecture_context=LectureContext(
            chapter_title="이진 탐색",
            slides=[
                SlideContext(slide_idx=0, title="이진 탐색 개념", content="정렬된 배열에서 절반씩 줄여 찾는다."),
                SlideContext(slide_idx=1, title="시간복잡도", content="이진 탐색은 O(log n)이다."),
            ],
        ),
    )


class TestOutOfScopeNowAnswers:
    def test_out_of_scope_answer_is_kept_with_notice_appended(self) -> None:
        keywords = build_lecture_keywords(_request())
        answer = "환율이 오르면 수입 물가가 함께 상승하는 경향이 있어요."

        final, guarded = apply_hallucination_guard(answer, keywords)

        assert guarded is True
        # 답변 본문이 유지된다 — 거절문으로 교체하지 않는다
        assert answer in final
        # 끝에 범위 밖 안내문이 덧붙는다
        assert final.endswith(SCOPE_NOTICE)

    def test_notice_not_duplicated(self) -> None:
        keywords = build_lecture_keywords(_request())
        answer = f"환율이 오르면 수입 물가가 상승해요.\n\n{SCOPE_NOTICE}"

        final, guarded = apply_hallucination_guard(answer, keywords)

        assert guarded is False
        assert final.count(SCOPE_NOTICE) == 1

    def test_in_scope_answer_untouched(self) -> None:
        keywords = build_lecture_keywords(_request())
        answer = "이진 탐색은 정렬된 배열을 절반씩 줄여서 찾아요."

        final, guarded = apply_hallucination_guard(answer, keywords)

        assert guarded is False
        assert final == answer
        assert SCOPE_NOTICE not in final

    def test_cited_answer_untouched(self) -> None:
        keywords = build_lecture_keywords(_request())
        answer = "복잡한 개념이지만 핵심은 간단해요. [슬라이드 2]"

        final, guarded = apply_hallucination_guard(answer, keywords)

        assert guarded is False
        assert final == answer

    def test_short_answer_exempt(self) -> None:
        final, guarded = apply_hallucination_guard("네!", ["이진", "탐색"])

        assert guarded is False
        assert final == "네!"

    def test_no_keywords_exempt(self) -> None:
        answer = "키워드 기준이 없으면 보수적으로 통과해요."

        final, guarded = apply_hallucination_guard(answer, [])

        assert guarded is False
        assert final == answer


class TestSlideCitationExtraction:
    def test_citations_extracted_zero_based(self) -> None:
        refs = extract_referenced_slides("정의는 [슬라이드 1], 예시는 [슬라이드 2]에 있어요.")

        assert refs == [0, 1]

    def test_out_of_range_citation_dropped(self) -> None:
        refs = extract_referenced_slides("[슬라이드 7]을 보세요.", slide_count=3)

        assert refs == []

    def test_citation_still_works_after_notice_appended(self) -> None:
        keywords = build_lecture_keywords(_request())
        answer = "이진 탐색은 절반씩 줄여요. [슬라이드 1]"

        final, _ = apply_hallucination_guard(answer, keywords)
        refs = extract_referenced_slides(final, slide_count=2)

        assert refs == [0]


class TestGuardEdgeCases:
    def test_empty_answer_untouched(self) -> None:
        """빈 답변에는 안내문을 덧붙이지 않는다(크래시 금지)."""
        answer, appended = apply_hallucination_guard("", ["이진", "탐색"])
        assert answer == ""
        assert appended is False

    def test_whitespace_only_answer_untouched(self) -> None:
        """공백뿐인 답변도 짧은 답변 면제 규칙으로 그대로 둔다."""
        answer, appended = apply_hallucination_guard("   \n  ", ["이진", "탐색"])
        assert appended is False

    def test_answer_already_ending_with_notice_not_duplicated(self) -> None:
        """답변이 이미 SCOPE_NOTICE로 끝나면 다시 덧붙이지 않는다(중복 방지 고정)."""
        original = f"양자역학은 물리학의 한 분야예요.\n\n{SCOPE_NOTICE}"
        answer, appended = apply_hallucination_guard(original, ["이진", "탐색"])
        assert appended is False
        assert answer.count(SCOPE_NOTICE) == 1

    def test_notice_appended_answer_is_idempotent(self) -> None:
        """가드를 두 번 통과해도 안내문은 한 번만 붙는다."""
        keywords = build_lecture_keywords(_request())
        first, appended = apply_hallucination_guard(
            "양자역학의 파동함수는 확률 진폭을 나타내는 복소함수예요.", keywords
        )
        assert appended is True
        second, appended_again = apply_hallucination_guard(first, keywords)
        assert appended_again is False
        assert second.count(SCOPE_NOTICE) == 1
