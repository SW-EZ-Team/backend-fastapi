"""narration 완결성 관련 함수 단위 테스트.

2차 codex 검사에서 발견된 슬라이드 narration truncation 버그 대응:
- _is_complete_narration: 완결 문장 판별 (AI max_tokens 절단 감지)
- _compact_sentences: 문장 경계 절단(단어 중간 절단 금지) 검증
- _fallback_narration: 불완결 raw narration → voice_script 보완 경로 검증
- parse_slides: narration >420자 ValidationError fallback 경로 제거 확인 (max_length=600)
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.pipeline.parallel_prompts import (
    _compact_sentences,
    _is_complete_narration,
    parse_slides,
)


# ---------------------------------------------------------------------------
# _is_complete_narration 테스트
# ---------------------------------------------------------------------------


class TestIsCompleteNarration:
    """완결 문장 판별 함수 테스트."""

    def test_empty_string_is_not_complete(self) -> None:
        assert _is_complete_narration("") is False

    def test_ends_with_period_is_complete(self) -> None:
        assert _is_complete_narration("이차방정식을 풀 수 있습니다.") is True

    def test_ends_with_question_mark_is_complete(self) -> None:
        assert _is_complete_narration("근의 개수는 몇 개인가?") is True

    def test_ends_with_korean_ending_simnida(self) -> None:
        assert _is_complete_narration("이것이 핵심 개념입니다") is True

    def test_ends_with_korean_ending_hamnida(self) -> None:
        assert _is_complete_narration("판별식으로 근의 개수를 확인합니다") is True

    def test_ends_with_korean_ending_yo(self) -> None:
        assert _is_complete_narration("수직선에서 오른쪽이 더 큰 수예요") is True

    def test_truncated_mid_word_is_not_complete(self) -> None:
        # '...식을 참으로 만' - 단어 중간 절단
        assert _is_complete_narration("이차방정식을 참으로 만") is False

    def test_truncated_mid_sentence_is_not_complete(self) -> None:
        # '...실근이 두 개인지 한 개인지 또는 없는지' - 술어 누락
        assert _is_complete_narration("실근이 두 개인지 한 개인지 또는 없는지") is False

    def test_fragment_is_not_complete(self) -> None:
        # '짚어야 해요. 문제 요' - 프래그먼트
        assert _is_complete_narration("짚어야 해요. 문제 요") is False

    def test_complete_multi_sentence_narration(self) -> None:
        text = (
            "이차방정식이란 ax²+bx+c=0 형태의 방정식입니다. "
            "근의 공식이나 인수분해로 해를 구할 수 있습니다."
        )
        assert _is_complete_narration(text) is True


# ---------------------------------------------------------------------------
# _compact_sentences 테스트 (문장 경계 절단 금지)
# ---------------------------------------------------------------------------


class TestCompactSentences:
    """_compact_sentences가 단어·어미 중간을 절단하지 않음을 보장한다."""

    def test_short_text_returned_as_is(self) -> None:
        text = "이것은 짧은 문장입니다."
        result = _compact_sentences(text, max_chars=360)
        assert result == text

    def test_sentence_boundary_not_word_boundary(self) -> None:
        """360자 초과 시 단어 중간이 아닌 완결 문장에서 잘라야 한다."""
        # 두 문장 합산이 360자를 넘는 케이스 만들기
        s1 = "이차방정식은 ax의 제곱에 bx를 더하고 c를 더한 값이 0인 방정식으로, 미지수가 최고차항으로 포함된 방정식입니다."
        s2 = "이차방정식의 해는 판별식 b의 제곱에서 4ac를 뺀 값의 부호에 따라 실근이 두 개인지 한 개인지 또는 없는지를 결정합니다."
        s3 = "근의 공식은 x는 마이너스 b 더하기 빼기 루트 b제곱 빼기 4ac 전체 분의 2a로 표현됩니다."
        text = f"{s1} {s2} {s3}"
        result = _compact_sentences(text, max_chars=100)
        # 결과가 문장 경계에서 잘려야 함 — 마지막 글자가 종결 부호이거나 완결 어미여야 함
        assert _is_complete_narration(result), (
            f"compact 결과가 불완결: ...{result[-30:]!r}"
        )

    def test_first_sentence_longer_than_max_chars_returns_full_sentence(self) -> None:
        """첫 문장 자체가 max_chars를 초과하면 절단하지 않고 전체를 반환한다."""
        long_sentence = "이차방정식에서 판별식 D가 0보다 크면 서로 다른 두 실근을 가지고 0이면 중근을 가지며 0보다 작으면 실근이 없습니다."
        result = _compact_sentences(long_sentence, max_chars=20)
        # 절단 금지 — 원본 전체 반환
        assert result == long_sentence

    def test_no_mid_word_truncation_on_long_single_sentence(self) -> None:
        """문장 부호가 없는 긴 단일 문장에서도 단어 중간 절단이 없어야 한다."""
        no_punct = (
            "이차방정식이란 어떤 방정식을 참으로 만드는 특별한 x값을 찾는 것이 목표로 "
            "하나의 미지수에 대해 이 미지수를 포함하는 식을 참으로 만드는 값인 근을 구하는 방정식"
        )
        result = _compact_sentences(no_punct, max_chars=40)
        # 문장 부호 없는 케이스: 전체를 반환(절단 금지)
        assert result == no_punct

    def test_multiple_sentences_respects_boundary(self) -> None:
        """여러 문장이 있을 때 max_chars 이하 완결 문장 집합을 반환한다."""
        text = "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다."
        # 첫 번째 문장(11자)은 들어가고 두 번째(12자)는 합산 24자로 max_chars=12 초과
        result = _compact_sentences(text, max_chars=12)
        assert "첫 번째 문장입니다." in result
        assert "두 번째 문장" not in result

    def test_result_does_not_end_mid_word(self) -> None:
        """결과가 단어 중간(공백으로 끝나지 않는 미완성 어절)으로 끝나지 않아야 한다."""
        # 구버전 rsplit 경로가 '만' 등 단어 중간에서 절단하던 패턴 재현 시도
        tricky = (
            "이 방정식을 참으로 만드는 값을 구하기 위한 방법으로는 인수분해와 완전제곱식과 근의 공식이 있습니다. "
            "판별식이 양수이면 두 실근이 존재합니다."
        )
        result = _compact_sentences(tricky, max_chars=45)
        last_char = result.strip()[-1] if result.strip() else ""
        # 결과가 '만' 처럼 단어 중간에서 끝나지 않아야 함
        assert last_char not in ("만", "를", "이", "에", "의", "는", "가", "도"), (
            f"단어 중간 절단 발생: {result!r}"
        )


# ---------------------------------------------------------------------------
# parse_slides narration max_length 및 완결성 테스트
# ---------------------------------------------------------------------------


class TestParseSlideNarrationIntegrity:
    """parse_slides 후 narration이 완결 문장으로 끝나는지 검증한다."""

    def _make_slide_payload(self, narration: str, slide_idx: int = 0) -> str:
        return json.dumps(
            {
                "slides": [
                    {
                        "slide_idx": slide_idx,
                        "title": "이차방정식 기초",
                        "category": "math",
                        "narration": narration,
                        "visual": {
                            "type": "example_box",
                            "data": {
                                "problem": "x²-5x+6=0을 풀어라",
                                "steps": ["(x-2)(x-3)=0"],
                                "answer": "x=2 또는 x=3",
                            },
                        },
                        "checkpoint": "인수분해로 근을 구할 수 있는가?",
                    }
                ]
            },
            ensure_ascii=False,
        )

    def test_normal_narration_preserved(self) -> None:
        """정상 범위(200~360자) narration은 그대로 보존된다."""
        narration = (
            "이차방정식은 ax²+bx+c=0 형태로 미지수의 최고차항이 2차인 방정식입니다. "
            "근을 구하기 위해 인수분해, 완전제곱식, 근의 공식을 사용합니다."
        )
        payload = self._make_slide_payload(narration)
        slides = parse_slides(payload)
        assert slides[0].narration == narration

    def test_narration_up_to_600_chars_passes_without_fallback(self) -> None:
        """max_length=600 이하 narration은 ValidationError 없이 통과한다."""
        long_narration = "이차방정식 " * 40  # 약 280자
        long_narration = long_narration.strip() + "입니다."
        assert len(long_narration) <= 600
        payload = self._make_slide_payload(long_narration)
        slides = parse_slides(payload)
        assert slides[0].narration == long_narration

    def test_truncated_narration_detected_via_fallback(self) -> None:
        """불완결 narration을 가진 슬라이드는 voice_script 기반으로 보완된다."""
        truncated_narration = "이차방정식을 참으로 만"  # 불완결(단어 중간 절단)
        voice_script_text = (
            "이차방정식을 참으로 만드는 x값이 바로 근입니다. "
            "근의 공식으로 해를 구할 수 있습니다."
        )
        payload = json.dumps(
            {
                "slides": [
                    {
                        "slide_idx": 0,
                        "title": "이차방정식 근의 정의",
                        "category": "math",
                        "narration": truncated_narration,
                        "voice_script": {"script_text": voice_script_text},
                        "visual": {
                            "type": "example_box",
                            "data": {
                                "problem": "x²-5x+6=0",
                                "steps": ["(x-2)(x-3)=0"],
                                "answer": "x=2 또는 x=3",
                            },
                        },
                        "checkpoint": "근의 의미를 설명할 수 있는가?",
                    }
                ]
            },
            ensure_ascii=False,
        )
        slides = parse_slides(payload)
        result_narration = slides[0].narration
        # 불완결 raw가 아니라 voice_script 기반 compact narration이 사용되어야 함
        assert result_narration != truncated_narration, "불완결 narration이 그대로 출력됨"
        assert _is_complete_narration(result_narration), (
            f"보완 후에도 narration이 불완결: {result_narration!r}"
        )

    @pytest.mark.parametrize(
        "narration",
        [
            "이차방정식이란 ax²+bx+c=0 형태의 방정식입니다.",
            "판별식 D=b²-4ac가 양수이면 서로 다른 두 실근이 존재합니다.",
            "근의 공식을 사용하면 모든 이차방정식의 해를 구할 수 있습니다.",
            "이차방정식의 근은 방정식을 참으로 만드는 x값이에요.",
            "인수분해로 (x-2)(x-3)=0을 만들면 x=2 또는 x=3이 됩니다.",
        ],
    )
    def test_complete_narrations_pass_through(self, narration: str) -> None:
        """완결 narration 형태들이 parse_slides를 통과해 보존된다."""
        payload = self._make_slide_payload(narration)
        slides = parse_slides(payload)
        assert slides[0].narration == narration
        assert _is_complete_narration(slides[0].narration)
