"""Kanana OCR 후처리 프롬프트 빌더 + LaTeX 보호 아톰.

probe 검증된 프롬프트(creation 억제 + 반복구 제거)를 기반으로 하되,
preserve_latex=True 일 때 수식 블록을 플레이스홀더로 치환해 LLM 에 전달한 뒤
결과에서 플레이스홀더를 원본 수식으로 되돌린다. 이렇게 해야 한국어 교정이
수식 토큰을 망가뜨리는 사고가 원천 차단된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 수식 블록 탐지 정규식 — 순서가 중요하다 (긴 것 먼저 소비해야 중첩 오인 방지).
# 1) \[ ... \] 디스플레이 블록
# 2) \( ... \) 인라인 블록
# 3) $$ ... $$ 디스플레이 달러
# 4) $ ... $ 인라인 달러 (최소 매칭)
# 각 패턴을 non-greedy 로 잡아 여러 수식이 나란히 있어도 하나씩 분리된다.
_LATEX_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\\\[(.+?)\\\]", "display_bracket"),
    (r"\\\((.+?)\\\)", "inline_paren"),
    (r"\$\$(.+?)\$\$", "display_dollar"),
    (r"(?<!\\)\$(.+?)(?<!\\)\$", "inline_dollar"),
)

# 플레이스홀더 템플릿 — 한글·영문·기호가 섞여도 LLM 이 건드리지 않을
# 확실한 토큰. 숫자 index 로 원본 수식과 1:1 매핑한다.
_PLACEHOLDER = "[[MATH_{idx}]]"
_PLACEHOLDER_PATTERN = re.compile(r"\[\[MATH_(\d+)\]\]")


@dataclass
class LatexMasked:
    """마스킹 결과 + 복원 테이블을 한 묶음으로 넘긴다."""

    masked_text: str
    originals: list[str]

    def restore(self, corrected_text: str) -> str:
        """LLM 출력의 플레이스홀더를 원본 수식으로 복원한다.

        LLM 이 플레이스홀더를 누락했거나 오자로 바꿨으면 해당 인덱스는 복원 실패
        — 그 경우에도 교정 결과는 유지하고, 수식만 빈 문자열로 탈락시킨다.
        (raw 재삽입은 할루시네이션 의심 케이스를 더 키울 수 있어서 보류.)
        """
        def _sub(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            if 0 <= idx < len(self.originals):
                return self.originals[idx]
            return ""
        return _PLACEHOLDER_PATTERN.sub(_sub, corrected_text)


def mask_latex(text: str) -> LatexMasked:
    """수식 블록을 플레이스홀더로 교체한 텍스트와 원본 리스트를 반환한다.

    순서: 디스플레이 → 인라인, 백슬래시 → 달러 사인.
    같은 인덱스로 여러 타입이 섞여도 '발견 순서 = 리스트 인덱스' 규약이라 안전.
    """
    originals: list[str] = []
    masked = text
    # 같은 문자열을 여러 패턴이 순차로 훑도록 한다. 각 패턴이 자기 차례에
    # 남아있는 모든 매치를 플레이스홀더로 치환한다.
    for pattern, _kind in _LATEX_PATTERNS:
        compiled = re.compile(pattern, re.DOTALL)

        def _replace(match: re.Match[str]) -> str:
            # 클로저로 originals 공유 — 인덱스가 자동 증가
            originals.append(match.group(0))
            return _PLACEHOLDER.format(idx=len(originals) - 1)

        masked = compiled.sub(_replace, masked)
    return LatexMasked(masked_text=masked, originals=originals)


def build_chat_messages(
    ocr_text: str,
    preserve_latex: bool,
    language_hint: str,
) -> tuple[list[dict[str, str]], LatexMasked | None]:
    """Kanana chat template 용 messages 배열과 마스킹 상태를 반환한다.

    preserve_latex=True 면 수식 블록을 플레이스홀더로 치환한 텍스트를 LLM 에 넣고,
    프롬프트에 '플레이스홀더는 그대로 둬라' 지시를 추가한다.
    preserve_latex=False 면 마스킹 없이 원문 그대로 전달.
    """
    masked: LatexMasked | None = None
    body = ocr_text
    latex_rule = ""
    if preserve_latex:
        masked = mask_latex(ocr_text)
        if masked.originals:
            body = masked.masked_text
            latex_rule = (
                " 문장 안의 [[MATH_N]] 토큰은 수식이므로 절대 변형하지 말고 "
                "있는 그대로 둔다."
            )
        else:
            # 수식 미발견 — 마스킹 테이블이 비어 있으므로 기본 경로로 동작
            masked = None
    lang_word = "한국어" if language_hint == "ko" else f"{language_hint} 문서"
    system = (
        f"너는 OCR 후처리 교정기다. 입력은 {lang_word} 문서를 OCR 로 추출한 결과다. "
        "오타·띄어쓰기·반복구(동일 단어가 10회 이상 반복된 구간)를 교정해라. "
        "추정 불가 부분은 [?] 로 표시해라. 창작 금지, 원문에 없는 내용 추가 금지. "
        "교정 결과만 출력하고 부가 설명·머리말은 생략한다." + latex_rule
    )
    user = f"[OCR raw]\n{body}\n\n[교정 결과]\n"
    return (
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        masked,
    )
