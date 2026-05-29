"""프로그래밍 과목 품질 게이트 보조 함수."""
from __future__ import annotations

import re

_PROGRAMMING_KEYWORDS = (
    "rust", "python", "java", "javascript", "typescript", "c++", "c#",
    "코드", "프로그래밍", "함수", "컴파일", "소유권", "빌림", "trait",
    "fn ", "let ", "mut ", "match ", "impl ", "struct ", "enum ",
)
_CODE_START_RE = re.compile(r"^\s*(fn|trait|impl|struct|enum|let|match)\b")


def looks_like_programming_source(text: str) -> bool:
    """입력 자료가 코드/프로그래밍 과목인지 보수적으로 판정한다."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in _PROGRAMMING_KEYWORDS)


def has_code_snippets(questions: list[dict]) -> bool:
    """최종 문항 중 코드 블록으로 렌더링 가능한 예제가 있는지 확인한다."""
    return any(bool(q.get("code_snippet")) for q in questions)


def programming_generation_clause(source_text: str) -> str:
    """프로그래밍 자료일 때 생성 프롬프트에 붙일 코드 예시 지시문을 만든다."""
    if not looks_like_programming_source(source_text):
        return ""
    return (
        "- 프로그래밍/코드 주제에서는 제공된 코드 예제의 결과, 오류 원인, "
        "사용 위치를 묻는 문항을 최소 1개 포함하시오.\n"
        "- JSON의 stem/options/correct_answer 문자열 안에는 원본 코드, 백틱, "
        "따옴표가 포함된 코드 조각, 줄바꿈 코드를 직접 쓰지 마시오. "
        "코드는 시스템이 원문에서 별도 첨부한다.\n"
        "- 코드가 필요한 문항은 '아래 코드에서', '제공된 코드 예제에서'처럼 "
        "자연어로만 지칭하시오."
    )


def attach_source_code_if_needed(questions: list[dict], source_text: str) -> list[dict]:
    """모델 JSON을 깨지 않도록 원본 자료 코드 예시를 안전하게 첨부한다."""
    if not looks_like_programming_source(source_text) or has_code_snippets(questions):
        return questions
    snippet = extract_source_code_snippet(source_text)
    if not snippet or not questions:
        return questions
    enriched = [q.copy() for q in questions]
    enriched[0]["code_snippet"] = snippet
    return enriched


def extract_source_code_snippet(source_text: str, max_lines: int = 12) -> str:
    """원본 자료에서 첫 번째 짧은 코드 예시를 추출한다."""
    lines = source_text.splitlines()
    for start, line in enumerate(lines):
        if _CODE_START_RE.search(line):
            return "\n".join(_collect_code_lines(lines[start:], max_lines)).strip()
    return ""


def _collect_code_lines(lines: list[str], max_lines: int) -> list[str]:
    """빈 줄 전까지 코드로 보이는 줄을 수집한다."""
    collected: list[str] = []
    for line in lines:
        if collected and not line.strip():
            break
        collected.append(line)
        if len(collected) >= max_lines:
            break
    return collected
