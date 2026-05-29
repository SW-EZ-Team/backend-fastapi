"""입력 텍스트를 다양한 형식에서 읽어 섹션 목록으로 변환하는 어댑터."""
from __future__ import annotations

import re

# 마크다운 헤딩 패턴: # ~ ######
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
# 코드블록 시작/끝 구분자
_CODE_FENCE = "```"
# 테이블 행 패턴: |로 시작
_TABLE_LINE_RE = re.compile(r"^\s*\|")
# 각주 패턴: [^숫자]:
_FOOTNOTE_RE = re.compile(r"^\s*\[\^[^\]]+\]:")
# 빈 줄 2개 이상으로 섹션 구분
_BLANK_SECTION_RE = re.compile(r"\n{2,}")


def read_text_input(raw_text: str) -> list[dict]:
    """순수 텍스트를 섹션 목록으로 변환.

    빈 줄이 2개 이상 연속되면 새 섹션으로 나눈다.
    """
    parts = _BLANK_SECTION_RE.split(raw_text)
    sections: list[dict] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        sections.append({"title": "", "text": text, "level": 0, "skip": False})
    return sections


def read_markdown_input(md_text: str) -> list[dict]:
    """마크다운 텍스트를 섹션 목록으로 변환.

    # 헤딩은 섹션 제목, 코드블록·테이블·각주는 skip=True로 표시.
    """
    lines = md_text.splitlines()
    sections: list[dict] = []
    # 현재 섹션 누적 버퍼
    current_title = ""
    current_level = 0
    current_lines: list[str] = []
    in_code_block = False

    def _flush() -> None:
        """버퍼에 쌓인 내용을 섹션으로 확정."""
        text = "\n".join(current_lines).strip()
        if not text:
            return
        sections.append(
            {
                "title": current_title,
                "text": text,
                "level": current_level,
                "skip": False,
            }
        )

    for line in lines:
        # 코드블록 토글 처리
        if line.strip().startswith(_CODE_FENCE):
            in_code_block = not in_code_block
            # 코드블록은 별도 skip 섹션으로 격리
            if in_code_block:
                _flush()
                current_lines = []
            else:
                code_text = "\n".join(current_lines).strip()
                if code_text:
                    sections.append(
                        {
                            "title": "",
                            "text": code_text,
                            "level": 0,
                            "skip": True,
                        }
                    )
                current_lines = []
                current_title = ""
                current_level = 0
            continue

        if in_code_block:
            current_lines.append(line)
            continue

        # 각주는 skip 섹션
        if _FOOTNOTE_RE.match(line):
            _flush()
            sections.append({"title": "", "text": line.strip(), "level": 0, "skip": True})
            current_lines = []
            continue

        # 테이블 행은 skip 섹션에 누적
        if _TABLE_LINE_RE.match(line):
            _flush()
            current_lines = [line]
            # 다음 줄도 테이블인지 연속 확인을 위해 skip 섹션으로 바로 확정
            sections.append({"title": "", "text": line.strip(), "level": 0, "skip": True})
            current_lines = []
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            # 이전 섹션 확정
            _flush()
            current_lines = []
            current_level = len(heading_match.group(1))
            current_title = heading_match.group(2).strip()
            continue

        current_lines.append(line)

    # 마지막 섹션 처리
    _flush()
    return sections


def read_file_input(file_content: str, filename: str) -> list[dict]:
    """파일 확장자에 따라 적절한 파서를 호출해 섹션 목록 반환."""
    if filename.endswith(".md"):
        return read_markdown_input(file_content)
    return read_text_input(file_content)


def detect_encoding(raw_bytes: bytes) -> str:
    """바이트 시퀀스에서 인코딩을 감지한다.

    외부 라이브러리 없이 순수 휴리스틱으로 판별:
    UTF-8 BOM → UTF-8 → EUC-KR → latin-1 순으로 시도.
    """
    # UTF-8 BOM (EF BB BF) 우선 체크
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # UTF-8 디코드 시도
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    # EUC-KR 시도 (한국어 레거시 인코딩)
    try:
        raw_bytes.decode("euc-kr")
        return "euc-kr"
    except UnicodeDecodeError:
        pass
    # 최후 수단: latin-1은 모든 바이트 값을 허용
    return "latin-1"
