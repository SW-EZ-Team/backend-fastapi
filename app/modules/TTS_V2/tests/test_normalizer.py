"""text_normalizer 모듈 단위 테스트."""
from __future__ import annotations

from app.modules.TTS_V2.processors.text_normalizer import (
    expand_abbreviations,
    expand_numbers,
    expand_symbols,
    expand_units,
    normalize_for_tts,
    normalize_punctuation,
    _int_to_korean,
)


class TestIntToKorean:
    """정수 → 한국어 발화형 변환 단위 테스트."""

    def test_zero(self) -> None:
        assert _int_to_korean(0) == "영"

    def test_single_digit(self) -> None:
        assert _int_to_korean(5) == "오"

    def test_tens(self) -> None:
        assert _int_to_korean(42) == "사십이"

    def test_hundreds(self) -> None:
        assert _int_to_korean(100) == "백"

    def test_thousands(self) -> None:
        assert _int_to_korean(1000) == "천"

    def test_ten_thousands(self) -> None:
        # 한국어 관용상 10000은 "일만"으로 발음함
        assert _int_to_korean(10000) == "일만"

    def test_complex(self) -> None:
        assert _int_to_korean(2024) == "이천이십사"


class TestExpandNumbers:
    """숫자 변환 테스트."""

    def test_phone_number(self) -> None:
        """전화번호 변환."""
        text = "연락처: 010-1234-5678"
        result = expand_numbers(text)
        # 숫자 형태의 전화번호 패턴이 한국어로 변환되어야 함
        assert "010-1234-5678" not in result

    def test_year(self) -> None:
        """연도 변환."""
        text = "2024년 기준"
        result = expand_numbers(text)
        assert "이천이십사" in result

    def test_percent(self) -> None:
        """퍼센트 변환."""
        text = "정확도 95%"
        result = expand_numbers(text)
        assert "퍼센트" in result
        assert "구십오" in result

    def test_money(self) -> None:
        """금액 변환."""
        text = "가격 10,000원"
        result = expand_numbers(text)
        assert "만 원" in result

    def test_date(self) -> None:
        """날짜 변환."""
        text = "4월 23일 출시"
        result = expand_numbers(text)
        assert "사월" in result
        assert "이십삼일" in result

    def test_code_number_preserved(self) -> None:
        """코드나 ID 내 숫자는 변환하지 않는다."""
        # 한글이 없는 순수 숫자/코드는 변환 대상이 아님
        text = "version=3.14"
        result = expand_numbers(text)
        # 소수점 패턴은 한글 인접 시에만 변환 — 순수 영문 맥락은 유지
        assert "version" in result


class TestExpandUnits:
    """단위 변환 테스트."""

    def test_kilometer(self) -> None:
        text = "거리 10km"
        result = expand_units(text)
        assert "킬로미터" in result

    def test_kilogram(self) -> None:
        text = "무게 5kg"
        result = expand_units(text)
        assert "킬로그램" in result

    def test_celsius(self) -> None:
        text = "온도 36.5°C"
        result = expand_units(text)
        assert "섭씨" in result

    def test_gigabyte(self) -> None:
        text = "용량 8GB"
        result = expand_units(text)
        assert "기가바이트" in result

    def test_standalone_m_preserved(self) -> None:
        """독립 단어 'm'은 단위로 처리하지 않는다."""
        text = "I am fine"
        result = expand_units(text)
        # 숫자 없이 'm'만 있는 경우 변환하면 안 됨
        assert "미터" not in result


class TestExpandAbbreviations:
    """약어 변환 테스트."""

    def test_known_abbr(self) -> None:
        text = "AI 기반 시스템"
        result = expand_abbreviations(text)
        assert "에이아이" in result

    def test_api_abbr(self) -> None:
        text = "API 엔드포인트"
        result = expand_abbreviations(text)
        assert "에이피아이" in result

    def test_tts_abbr(self) -> None:
        text = "TTS 모델"
        result = expand_abbreviations(text)
        assert "티티에스" in result

    def test_unknown_abbr_letter_by_letter(self) -> None:
        """미등록 약어는 글자별 발음으로 분리한다."""
        text = "AWS 클라우드"
        result = expand_abbreviations(text)
        # A=에이, W=더블유, S=에스
        assert "에이" in result


class TestExpandSymbols:
    """기호 변환 테스트."""

    def test_arrow(self) -> None:
        text = "A → B"
        result = expand_symbols(text)
        assert "→" not in result
        assert "로" in result

    def test_multiply(self) -> None:
        text = "2 × 3"
        result = expand_symbols(text)
        assert "×" not in result
        assert "곱하기" in result

    def test_and_symbol(self) -> None:
        text = "A & B"
        result = expand_symbols(text)
        assert "앤드" in result

    def test_at_symbol(self) -> None:
        text = "이메일 @ 서버"
        result = expand_symbols(text)
        assert "앳" in result


class TestNormalizePunctuation:
    """구두점 정리 테스트."""

    def test_ellipsis_simplified(self) -> None:
        """줄임표를 마침표로 단순화한다."""
        text = "계속..."
        result = normalize_punctuation(text)
        assert "..." not in result

    def test_multiple_exclamation(self) -> None:
        """연속 느낌표를 1개로 줄인다."""
        text = "대박!!!"
        result = normalize_punctuation(text)
        assert "!!!" not in result
        assert "!" in result

    def test_multiple_question(self) -> None:
        """연속 물음표를 1개로 줄인다."""
        text = "정말???"
        result = normalize_punctuation(text)
        assert "???" not in result

    def test_short_paren_removed(self) -> None:
        """10자 이하 괄호 내용을 제거한다."""
        text = "단어(주석)"
        result = normalize_punctuation(text)
        assert "(주석)" not in result

    def test_long_paren_content_kept(self) -> None:
        """11자 이상 괄호 내용은 괄호만 제거하고 내용 유지한다."""
        text = "설명(이 부분은 매우 길고 중요한 내용입니다)"
        result = normalize_punctuation(text)
        assert "(" not in result
        assert "이 부분은" in result


class TestNormalizeForTts:
    """normalize_for_tts 통합 테스트."""

    def test_full_pipeline(self) -> None:
        """복합 변환이 순서대로 적용된다."""
        text = "2024년 AI 성능이 95% 향상되어 10km 속도로 달린다!!!"
        result = normalize_for_tts(text)
        assert "이천이십사" in result
        assert "에이아이" in result
        assert "퍼센트" in result
        assert "킬로미터" in result

    def test_rust_terms_pronounced_in_korean(self) -> None:
        """러스트 강의용 영문 기술 용어는 한국어 발화형으로 변환한다."""
        result = normalize_for_tts("Rust ownership과 borrow 규칙")
        assert "러스트" in result
        assert "오너십" in result
        assert "보로우" in result
        assert "!!!" not in result

    def test_edge_empty_string(self) -> None:
        """빈 문자열은 그대로 반환된다."""
        assert normalize_for_tts("") == ""
