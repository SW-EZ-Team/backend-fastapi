"""common/llm_output 단위 테스트.

모델 스왑(codex → Qwen/Claude) 시 reasoning·마크다운·잡텍스트가 섞여도
첫 유효 JSON을 견고하게 뽑아내는지 검증한다. 정답 계약을 지키기 위해
파싱 실패는 삼키지 않고 예외로 드러나는지도 함께 확인한다.
"""
from __future__ import annotations

import pytest

from common.llm_output import (
    clean_llm_text,
    extract_json_block,
    loads_lenient,
    strip_thinking,
)


class TestStripThinking:
    """strip_thinking — reasoning 블록 제거 동작."""

    def test_closed_think_block_removed(self) -> None:
        """닫힌 <think>...</think> 블록을 제거하고 본문만 남긴다."""
        raw = "<think>정답은 3번이라고 추론</think>\n[{\"label\":\"3\"}]"
        assert strip_thinking(raw) == '[{"label":"3"}]'

    def test_truncated_think_truncates_rest(self) -> None:
        """닫는 태그 없는 <think>는 그 지점부터 끝까지 절단한다."""
        raw = '[{"stem":"본문"}]\n<think>여기서 응답이 잘림'
        assert strip_thinking(raw) == '[{"stem":"본문"}]'

    def test_truncated_think_at_start_yields_empty(self) -> None:
        """본문 없이 잘린 think만 있으면 빈 문자열로 절단한다."""
        raw = "<think>정답을 고민 중인데 응답이 끊김"
        assert strip_thinking(raw) == ""

    def test_no_think_is_noop(self) -> None:
        """think가 없으면 strip만 적용하고 내용은 보존한다 (codex 회귀 0)."""
        raw = '[{"stem":"평이"}]'
        assert strip_thinking(raw) == raw


class TestCleanLlmText:
    """clean_llm_text — reasoning + 마크다운 펜스 제거."""

    def test_fenced_body_extracted(self) -> None:
        """```json 펜스 본문만 남긴다."""
        raw = "결과:\n```json\n{\"a\":1}\n```\n끝."
        assert clean_llm_text(raw) == '{"a":1}'

    def test_think_then_fence(self) -> None:
        """think 제거 후 펜스 본문을 남긴다."""
        raw = "<think>x</think>\n```json\n[1,2]\n```"
        assert clean_llm_text(raw) == "[1,2]"


class TestExtractJsonBlock:
    """extract_json_block — 괄호 깊이 추적 추출."""

    def test_object_with_nested_braces(self) -> None:
        """중첩 객체에서 outermost 객체를 정확히 잘라낸다."""
        raw = '앞 설명 {"a":{"b":1},"c":2} 뒤 설명'
        assert extract_json_block(raw) == '{"a":{"b":1},"c":2}'

    def test_braces_inside_string_ignored(self) -> None:
        """문자열 내부의 괄호는 깊이에 반영하지 않는다."""
        raw = '{"text":"여기 } 있음","x":1}'
        assert extract_json_block(raw) == '{"text":"여기 } 있음","x":1}'

    def test_first_of_two_arrays(self) -> None:
        """배열이 둘이면 첫 번째만 추출한다."""
        raw = '[{"q":1}]\n[{"q":2}]'
        assert extract_json_block(raw) == '[{"q":1}]'


class TestLoadsLenient:
    """loads_lenient — 관용 파싱 + 명확한 실패."""

    def test_think_laden_array(self) -> None:
        """Qwen <think> 입력에서 본문 배열을 파싱한다."""
        raw = (
            "<think>5지선다, 정답 1개</think>\n"
            '[{"options":[{"label":"1","is_correct":true}]}]'
        )
        parsed = loads_lenient(raw)
        assert parsed[0]["options"][0]["is_correct"] is True

    def test_trailing_comma_repaired(self) -> None:
        """trailing comma가 있어도 교정 후 파싱한다."""
        raw = '{"correct_answer":"2","explanation":"근거",}'
        assert loads_lenient(raw) == {"correct_answer": "2", "explanation": "근거"}

    def test_latex_backslash_repaired(self) -> None:
        """LaTeX 백슬래시(\\psi)가 섞여도 교정 후 파싱한다."""
        raw = '{"correct_answer":"\\psi 상태","explanation":"근거"}'
        parsed = loads_lenient(raw)
        assert parsed["correct_answer"] == "\\psi 상태"

    def test_garbage_raises(self) -> None:
        """JSON이 전혀 없으면 삼키지 않고 예외를 던진다."""
        with pytest.raises(ValueError):
            loads_lenient("이건 그냥 자연어이고 JSON이 없습니다")

    # ── 3단계: raw 제어문자 복구 (Qwen xgrammar 실측 갭 대응) ─────────────

    def test_raw_newline_in_string_repaired(self) -> None:
        """script_text 안의 raw \\n(0x0A)이 이스케이프돼 파싱 성공한다(Qwen 실측 갭 재현)."""
        raw_lf = "\n"  # xgrammar가 이스케이프 못 한 literal 개행
        voice_json = f'{{"slide_idx": 0, "script_text": "도입 설명{raw_lf}핵심 개념{raw_lf}마무리"}}'
        result = loads_lenient(voice_json)
        assert result["slide_idx"] == 0
        assert "도입 설명" in result["script_text"]
        assert "핵심 개념" in result["script_text"]

    def test_raw_tab_in_string_repaired(self) -> None:
        """script_text 안의 raw \\t(0x09)이 이스케이프돼 파싱 성공한다."""
        raw_tab = "\t"
        voice_json = f'{{"slide_idx": 1, "script_text": "구분:{raw_tab}핵심 설명"}}'
        result = loads_lenient(voice_json)
        assert result["slide_idx"] == 1
        assert "구분:" in result["script_text"]

    def test_raw_cr_in_string_repaired(self) -> None:
        """script_text 안의 raw \\r(0x0D)이 이스케이프돼 파싱 성공한다."""
        raw_cr = "\r"
        voice_json = f'{{"slide_idx": 2, "script_text": "줄1{raw_cr}줄2"}}'
        result = loads_lenient(voice_json)
        assert result["slide_idx"] == 2

    def test_control_char_outside_string_preserved(self) -> None:
        """JSON 구조 공백(문자열 밖 개행)은 건드리지 않는다."""
        # 구조적 줄바꿈을 포함한 pretty-printed JSON — 파싱 성공해야 한다.
        pretty = '{\n  "slide_idx": 3,\n  "script_text": "정상"\n}'
        result = loads_lenient(pretty)
        assert result["slide_idx"] == 3

    def test_already_escaped_newline_not_double_escaped(self) -> None:
        """이미 \\n으로 이스케이프된 경우 이중 이스케이프 없이 그대로 통과한다."""
        already_escaped = '{"script_text": "줄1\\n줄2"}'
        result = loads_lenient(already_escaped)
        assert result["script_text"] == "줄1\n줄2"

    def test_mixed_repairs_trailing_comma_and_raw_newline(self) -> None:
        """trailing comma + raw 개행이 동시에 있어도 복구 후 파싱 성공한다."""
        raw_lf = "\n"
        mixed = f'{{"script_text": "도입{raw_lf}핵심",}}'
        result = loads_lenient(mixed)
        assert "도입" in result["script_text"]

    def test_long_korean_voice_with_embedded_newlines(self) -> None:
        """긴 한국어 script_text(989자급) 안에 raw 개행이 여럿 있어도 복구한다(실측 케이스)."""
        raw_lf = "\n"
        sentence = "이번 화면에서는 핵심 개념을 직관부터 차근차근 설명하고 실수하기 쉬운 지점을 짚어봅시다."
        # 개행으로 이어진 989자급 대본 시뮬레이션
        long_text = raw_lf.join(sentence for _ in range(25))
        voice_json = f'{{"slide_idx": 0, "script_text": "{long_text}"}}'
        result = loads_lenient(voice_json)
        assert result["slide_idx"] == 0
        assert len(result["script_text"]) > 900
