"""text_cleaner 모듈 단위 테스트."""
from __future__ import annotations

from app.modules.TTS_V2.processors.text_cleaner import (
    clean_text,
    collapse_whitespace,
    fix_broken_lines,
    remove_headers_footers,
    remove_ocr_artifacts,
    remove_page_numbers,
)


class TestRemovePageNumbers:
    """페이지 번호 제거 테스트."""

    def test_dash_style(self) -> None:
        """'- 3 -' 형식의 페이지 번호를 제거한다."""
        text = "본문 내용\n- 3 -\n다음 내용"
        result = remove_page_numbers(text)
        assert "- 3 -" not in result
        assert "본문 내용" in result

    def test_bracket_style(self) -> None:
        """'[3]' 또는 단독 숫자 줄을 제거한다."""
        text = "내용\n[3]\n더 내용"
        result = remove_page_numbers(text)
        assert "[3]" not in result

    def test_p_prefix_style(self) -> None:
        """'p.3' 형식의 페이지 번호를 제거한다."""
        text = "내용\np.3\n다음"
        result = remove_page_numbers(text)
        assert "p.3" not in result

    def test_em_dash_style(self) -> None:
        """em dash(—)를 쓴 '— 5 —' 형식도 제거한다."""
        text = "내용\n— 5 —\n다음"
        result = remove_page_numbers(text)
        assert "5" not in result or "— 5 —" not in result


class TestRemoveHeadersFooters:
    """반복 헤더/푸터 제거 테스트."""

    def test_repeated_line_removed(self) -> None:
        """3회 이상 반복되는 동일 줄을 제거한다."""
        repeated = "저작권 © 2024 예제 출판사"
        text = "\n".join([
            "본문1", repeated, "본문2", repeated, "본문3", repeated, "본문4"
        ])
        result = remove_headers_footers(text)
        assert repeated not in result
        assert "본문1" in result
        assert "본문4" in result

    def test_non_repeated_line_kept(self) -> None:
        """2회 이하 등장하는 줄은 제거하지 않는다."""
        text = "줄A\n줄B\n줄A\n줄C"
        result = remove_headers_footers(text)
        assert "줄A" in result


class TestFixBrokenLines:
    """깨진 줄바꿈 복원 테스트."""

    def test_mid_sentence_newline_merged(self) -> None:
        """문장 중간에 삽입된 줄바꿈을 공백으로 연결한다."""
        text = "이것은 아주 긴\n문장입니다."
        result = fix_broken_lines(text)
        # 줄바꿈이 공백으로 바뀌어야 함
        assert "\n" not in result or "긴 문장" in result

    def test_sentence_end_newline_kept(self) -> None:
        """마침표 뒤 줄바꿈은 유지한다."""
        text = "첫 번째 문장.\n두 번째 문장."
        result = fix_broken_lines(text)
        assert "\n" in result


class TestRemoveOcrArtifacts:
    """OCR 잔여물 제거 테스트."""

    def test_box_chars_removed(self) -> None:
        """박스 문자(│ ─ ┌ 등)를 제거한다."""
        text = "내용│내용─내용┌내용"
        result = remove_ocr_artifacts(text)
        assert "│" not in result
        assert "─" not in result

    def test_repeated_special_removed(self) -> None:
        """연속 특수문자(###, ***, ===)를 제거한다."""
        text = "### 제목\n*** 강조\n=== 구분선"
        result = remove_ocr_artifacts(text)
        assert "###" not in result
        assert "***" not in result
        assert "===" not in result

    def test_replacement_char_removed(self) -> None:
        """유니코드 대체 문자(U+FFFD)를 제거한다."""
        text = "정상 텍스트 �깨진 문자�"
        result = remove_ocr_artifacts(text)
        assert "�" not in result
        assert "정상 텍스트" in result


class TestCollapseWhitespace:
    """공백 정리 테스트."""

    def test_triple_newlines_collapsed(self) -> None:
        """3개 이상 연속 줄바꿈을 2개로 줄인다."""
        text = "단락1\n\n\n\n단락2"
        result = collapse_whitespace(text)
        assert "\n\n\n" not in result
        assert "단락1" in result and "단락2" in result

    def test_multiple_spaces_collapsed(self) -> None:
        """연속 공백을 1개로 줄인다."""
        text = "단어1    단어2"
        result = collapse_whitespace(text)
        assert "    " not in result

    def test_tab_converted_to_space(self) -> None:
        """탭 문자를 공백으로 변환한다."""
        text = "단어1\t단어2"
        result = collapse_whitespace(text)
        assert "\t" not in result


class TestCleanText:
    """clean_text 통합 테스트."""

    def test_full_pipeline(self) -> None:
        """여러 잡음이 섞인 텍스트를 통합 정제한다."""
        text = (
            "저작권 © 2024\n"
            "본문 내용이 여기\n"
            "에 걸쳐 있습니다.\n"
            "- 5 -\n"
            "다음 단락\n"
            "저작권 © 2024\n"
            "더 내용\n"
            "저작권 © 2024\n"
        )
        result = clean_text(text)
        assert "- 5 -" not in result
        assert "저작권 © 2024" not in result
        assert result == result.strip()
