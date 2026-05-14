from __future__ import annotations

from app.modules.ChapterStudio_V1.app.reference_books.retrieval import compact_text
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext, ReferenceBookHit


def reference_context_prompt(context: ReferenceBookContext | None) -> str:
    """LLM 생성 프롬프트에 넣을 참고도서 발췌 블록을 만든다."""
    if context is None or not context.has_hits():
        return ""

    source = context.source_title or "사용자 참고도서"
    lines = [
        "참고도서 발췌(OCR 기반, page 번호 유지):",
        f"- 출처: {source}",
    ]
    for hit in context.hits[:5]:
        lines.append(f"- p.{hit.page}: {_shorten(hit.snippet, 260)}")
    lines.append(
        "사용 규칙: 암기노트, 과제, 음성대본에서 필요한 경우 p.번호를 자연스럽게 인용한다. "
        "참고도서가 제공된 강의에서는 note_blocks의 각 블록마다 최소 2개 bullet에 p.번호를 넣어 책 위치와 복습 포인트를 직접 연결한다. "
        "발췌를 통째로 복사하지 말고 강의 관점과 실전 풀이 차이로 풀어쓴다. "
        "발췌에 없는 내용은 페이지 근거가 있는 것처럼 쓰지 않는다."
    )
    return "\n".join(lines)


def reference_note_bullet(context: ReferenceBookContext | None, index: int = 0) -> str:
    """암기노트 bullet 끝에 붙일 참고도서 페이지 안내를 만든다."""
    hit = _pick_hit(context, index)
    if hit is None:
        return ""
    return (
        f"참고도서 연결: p.{hit.page}의 '{_shorten(hit.snippet, 120)}' 부분을 다시 읽으면 "
        "이 강의의 핵심 문장을 책 문맥으로 고정하기 좋다."
    )


def reference_voice_sentence(context: ReferenceBookContext | None, slide_idx: int) -> str:
    """슬라이드별 음성대본 끝에 붙일 참고도서 안내 문장을 만든다."""
    hit = _pick_hit(context, slide_idx)
    if hit is None:
        return ""
    return (
        f" 헷갈리면 참고도서 p.{hit.page}의 관련 문단을 한 번 더 읽고, "
        "책의 설명을 지금 강의 관점으로 다시 말해보세요."
    )


def reference_assignment_step(context: ReferenceBookContext | None) -> str:
    """과제 step에 붙일 참고도서 기반 확인 활동을 만든다."""
    hit = _pick_hit(context, 0)
    if hit is None:
        return ""
    return f"참고도서 p.{hit.page}를 다시 읽고, 책 설명과 이번 강의 관점이 어떻게 다른지 3문장으로 비교한다."


def _pick_hit(context: ReferenceBookContext | None, index: int) -> ReferenceBookHit | None:
    if context is None or not context.has_hits():
        return None
    return context.hits[index % len(context.hits)]


def _shorten(value: str, limit: int) -> str:
    text = compact_text(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 4)].rstrip()} ..."
