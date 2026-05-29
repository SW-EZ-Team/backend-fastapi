"""semantic_chunker 모듈 단위 테스트."""
from __future__ import annotations

from app.modules.TTS_V2.processors.semantic_chunker import (
    chunk_sections,
    merge_and_split_sentences,
    split_by_sentences,
    split_section_to_chunks,
)


class TestSplitBySentences:
    """문장 단위 분할 테스트."""

    def test_period_split(self) -> None:
        """마침표로 문장이 분리된다."""
        text = "첫 번째 문장. 두 번째 문장. 세 번째 문장."
        result = split_by_sentences(text)
        assert len(result) == 3

    def test_question_mark_split(self) -> None:
        """물음표로 문장이 분리된다."""
        text = "어디 가세요? 집에 갑니다."
        result = split_by_sentences(text)
        assert len(result) == 2

    def test_decimal_not_split(self) -> None:
        """소수점(3.14)은 문장 경계로 처리하지 않는다."""
        text = "원주율은 3.14입니다."
        result = split_by_sentences(text)
        assert len(result) == 1
        assert "3.14" in result[0]

    def test_no_punctuation(self) -> None:
        """구두점 없는 텍스트는 전체를 하나의 문장으로 반환한다."""
        text = "구두점이 없는 텍스트"
        result = split_by_sentences(text)
        assert len(result) == 1

    def test_empty_string(self) -> None:
        """빈 문자열은 빈 목록을 반환한다."""
        result = split_by_sentences("")
        assert result == []


class TestMergeAndSplitSentences:
    """문장 병합 및 분할 테스트."""

    def test_short_sentences_merged(self) -> None:
        """min_chars 미만의 짧은 문장을 다음 문장과 병합한다."""
        sentences = ["짧다.", "이것도.", "그리고 이것도."]
        result = merge_and_split_sentences(sentences, min_chars=40, max_chars=120)
        # 짧은 문장들이 병합되어 결과 수가 줄어야 함
        assert len(result) < len(sentences)

    def test_long_sentence_split(self) -> None:
        """max_chars를 초과하는 문장을 절 단위로 분할한다."""
        long_sent = "이것은 매우 길고 복잡한 문장으로, 콤마로 구분된 여러 절이 포함되어 있으며, 최대 문자 수를 초과할 가능성이 높습니다."
        result = merge_and_split_sentences([long_sent], min_chars=10, max_chars=40)
        assert len(result) >= 2
        for chunk in result:
            # 단어 하나가 max_chars 초과인 극단적 예외만 허용
            assert len(chunk) <= 40 or " " not in chunk

    def test_normal_sentences_unchanged(self) -> None:
        """적당한 길이의 문장은 구조를 유지한다."""
        sentences = ["이것은 적당한 길이의 문장입니다.", "그리고 이것도 마찬가지입니다."]
        result = merge_and_split_sentences(sentences, min_chars=10, max_chars=120)
        assert any("적당한" in r for r in result)


class TestSplitSectionToChunks:
    """섹션 청크 분할 테스트."""

    def test_chunk_id_format(self) -> None:
        """chunk_id가 ch_NNN_NNN 형식이어야 한다."""
        text = "첫 번째 문장입니다. 두 번째 문장입니다."
        chunks = split_section_to_chunks(text, "제목", 0)
        for chunk in chunks:
            assert chunk["chunk_id"].startswith("ch_000_")

    def test_metadata_fields_present(self) -> None:
        """청크에 필수 메타데이터 필드가 모두 있어야 한다."""
        text = "테스트 문장입니다."
        chunks = split_section_to_chunks(text, "섹션 제목", 2)
        required_fields = {
            "chunk_id", "chapter_idx", "section_title",
            "original_text", "normalized_text", "planned_text",
        }
        assert chunks
        assert required_fields.issubset(chunks[0].keys())

    def test_section_title_propagated(self) -> None:
        """섹션 제목이 모든 청크에 전파되어야 한다."""
        text = "문장 하나. 문장 둘."
        title = "1장 서론"
        chunks = split_section_to_chunks(text, title, 0)
        for chunk in chunks:
            assert chunk["section_title"] == title

    def test_normalized_and_planned_empty(self) -> None:
        """normalized_text와 planned_text는 초기에 빈 문자열이어야 한다."""
        text = "테스트."
        chunks = split_section_to_chunks(text, "", 0)
        for chunk in chunks:
            assert chunk["normalized_text"] == ""
            assert chunk["planned_text"] == ""

    def test_chapter_idx_set_correctly(self) -> None:
        """chapter_idx가 section_idx 값과 일치해야 한다."""
        text = "테스트 문장."
        chunks = split_section_to_chunks(text, "", 5)
        for chunk in chunks:
            assert chunk["chapter_idx"] == 5


class TestChunkSections:
    """chunk_sections 통합 테스트."""

    def test_skip_sections_excluded(self) -> None:
        """skip=True인 섹션은 청크에 포함되지 않아야 한다."""
        sections = [
            {"title": "", "text": "코드블록 내용", "level": 0, "skip": True},
            {"title": "본문", "text": "이것은 본문 문장입니다.", "level": 1, "skip": False},
        ]
        chunks = chunk_sections(sections)
        for chunk in chunks:
            assert "코드블록" not in chunk["original_text"]

    def test_normal_sections_included(self) -> None:
        """skip=False인 섹션은 청크에 포함되어야 한다."""
        sections = [
            {"title": "서론", "text": "이것은 본문 내용입니다.", "level": 1, "skip": False},
        ]
        chunks = chunk_sections(sections)
        assert len(chunks) >= 1
        assert any("본문 내용" in c["original_text"] for c in chunks)

    def test_multiple_sections_sequential_ids(self) -> None:
        """여러 섹션의 청크 ID가 섹션 인덱스 기준으로 순서대로 생성된다."""
        sections = [
            {"title": "1장", "text": "첫 번째 섹션 문장.", "level": 1, "skip": False},
            {"title": "2장", "text": "두 번째 섹션 문장.", "level": 1, "skip": False},
        ]
        chunks = chunk_sections(sections)
        ids = [c["chunk_id"] for c in chunks]
        assert any(i.startswith("ch_000_") for i in ids)
        assert any(i.startswith("ch_001_") for i in ids)

    def test_empty_sections(self) -> None:
        """빈 섹션 목록은 빈 청크 목록을 반환한다."""
        result = chunk_sections([])
        assert result == []

    def test_all_skip_sections(self) -> None:
        """모든 섹션이 skip이면 청크는 비어야 한다."""
        sections = [
            {"title": "", "text": "표 내용", "level": 0, "skip": True},
            {"title": "", "text": "각주", "level": 0, "skip": True},
        ]
        result = chunk_sections(sections)
        assert result == []
