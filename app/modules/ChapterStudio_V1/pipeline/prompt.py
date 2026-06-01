from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.frontend_contract import depth_label, teacher_label
from app.modules.ChapterStudio_V1.app.study_templates import frame_contract, study_quality_contract, template_contract
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_contract
from app.modules.ChapterStudio_V1.pipeline.personalization import personalization_contract
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


def build_generation_request(state: ChapterStudioState) -> ChapterAIRequest:
    """상태와 템플릿 계약을 모델이 따를 수 있는 단일 JSON 요청으로 압축한다."""
    slide_count = _state_int(state, "slide_count")
    template_key = _state_text(state, "template_key")
    return ChapterAIRequest(
        system=_system_prompt(slide_count),
        user=_user_prompt(state, slide_count, template_key),
        max_tokens=24000,
        temperature=0.35,
        extra={"slide_count": slide_count, "template_key": template_key},
    )


def _system_prompt(slide_count: int) -> str:
    return (
        "너는 ChapterStudio_V1 프로덕션 강의 생성기다. "
        "응답은 JSON 객체 하나만 출력하고 markdown fence, 설명문, 사고과정, <think> 블록은 금지한다. "
        "최상위 키는 slides, quizzes, note_blocks, assignment, voice_scripts 다섯 개만 쓴다. "
        f"slides, quizzes, voice_scripts는 각각 정확히 {slide_count}개다. "
        "slides[i] 키는 정확히 slide_idx, title, focus, checkpoint, category, html, css 일곱 개다. "
        "category는 text, diagram, code, math, chart, interactive, table 중 하나만 쓰고, "
        "metric-card·flow-strip·comparison-table 같은 시각요소 이름을 category 값으로 쓰면 실패다. "
        # 측정 가능한 분량 기준 — 약한 모델이 한두 문장으로 통과하지 못하게 수치를 명시한다.
        "slides[i].html은 마침표로 끝나는 완전한 한국어 문장 4~7개를 담고, 핵심어만 나열한 조각문장으로 끝내지 않는다. "
        "category별 필수 시각요소: diagram은 <pre class=\"mermaid\">, code는 <pre><code data-lang>, "
        "math는 <div class=\"formula\">, chart는 chart-box data-chart-spec, table은 <table>, "
        "interactive는 <details>를 반드시 1회 이상 넣는다. "
        "mermaid 노드 라벨에는 대괄호 []를 넣지 않고 스택·배열 상태는 괄호()나 쉼표로 표현한다. "
        "라벨에 콜론·괄호 등 특수문자가 있으면 A[\"초기 상태: 빈 스택\"]처럼 라벨 전체를 큰따옴표로 감싸며, 한 노드 라벨은 한 줄로 끝낸다. "
        "quizzes[i] 키는 정확히 slide_idx, question, choices, answer_idx, difficulty, explanation 여섯 개다. "
        "choices는 문자열 4개 배열이고 answer_idx는 0~3 정수이며, 정답은 한 보기에만 해당해야 한다. "
        "difficulty는 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. Easy/Medium/Hard 금지. "
        "quizzes[i].explanation은 120~180자로, 왜 정답인지와 오답 보기가 왜 틀렸는지(오답 함정)를 함께 쓰고, "
        "학습자가 약해지기 쉬운 개념과 연결해 설명한다. "
        "note_blocks[i] 키는 정확히 heading, bullets 두 개이며 title 키를 쓰지 않는다. "
        "note_blocks는 정확히 4개이고 각 block은 bullets를 정확히 3개 가진다. 각 bullet은 45자 이상의 완결 문장이다. "
        "voice_scripts[i] 키는 정확히 slide_idx, script_text 두 개다. "
        "voice_scripts[i].script_text는 슬라이드당 8~12문장, 900~1600자 분량의 과외 선생님 말투 대본이며, "
        "왜 그런지와 구체적 예시를 포함하고, HTML 태그·markdown·괄호 지시문을 넣지 않는다. "
        "assignment는 title, assignment_format, expected_minutes, steps, rubric을 모두 채운다. "
        "모든 html은 section 내부 조각이어야 하며 script 태그와 외부 URL을 쓰지 않는다."
    )


def _user_prompt(state: ChapterStudioState, slide_count: int, template_key: str) -> str:
    reference_block = _optional_state_text(state, "reference_context_prompt")
    return (
        f"강의 요청: {_state_text(state, 'enriched_brief')}\n"
        f"원주제: {_state_text(state, 'topic')}\n"
        f"자료 모드: {_optional_state_text(state, 'source_mode') or 'topic'}\n"
        f"PDF 파일명: {_optional_state_text(state, 'pdf_file_name') or '없음'}\n"
        f"학습 기간: {_state_int(state, 'duration_days')}일\n"
        f"난이도: {depth_label(_optional_state_text(state, 'depth') or 'normal')}\n"
        f"튜터: {teacher_label(_optional_state_text(state, 'teacher') or 'owl')}\n"
        f"튜터 조절값: tone={_state_int(state, 'tone')}, pace={_state_int(state, 'pace')}, "
        f"depth={_state_int(state, 'tutor_depth')}, socratic={_state_int(state, 'socratic')}\n"
        f"{_personalization_block(state)}\n"
        f"참고도서 컨텍스트:\n{reference_block or '제공된 참고도서 없음'}\n"
        f"슬라이드 수: {slide_count}\n"
        f"선택 템플릿: {template_key}\n"
        f"템플릿 계약: {template_contract(template_key)}\n"
        f"튜터 설계 계약: {blueprint_contract(template_key)}\n"
        f"확정 슬라이드 역할:\n{_outline_contract(state)}\n"
        f"슬라이드 프레임:\n{frame_contract(template_key)}\n"
        f"품질 계약: {study_quality_contract()}\n"
        "각 슬라이드는 한국어 1:1 과외 말투로 만들고, 화면에는 핵심 시각자료와 짧은 설명을 둔다. "
        "긴 설명은 voice_scripts에 넣는다. "
        # 측정 가능한 분량 기준 — 정성 표현 대신 수치로 품질 하한을 고정한다.
        "각 slide.html 본문에는 마침표로 끝나는 완전한 한국어 문장 4~7개를 넣고, 본문 설명은 200~360자 안에서 끝낸다. "
        "각 quiz.explanation은 120~180자로, 정답 이유와 오답 함정을 함께 적고 약점 개념과 연결한다. "
        "note_blocks는 정확히 4개이며 각 block은 heading과 정확히 3개 bullets를 가진다. 각 bullet은 45자 이상 완결 문장이다. "
        "각 voice_scripts[i].script_text는 8~12문장, 900~1600자로 쓰고, 화면에 없는 깊은 설명(직관 설명, 실수하기 쉬운 지점, "
        "바로 해볼 미니연습)을 자연스러운 존댓말 한 문단으로 담는다. HTML·markdown·괄호 지시문을 넣지 않는다. "
        "assignment는 title, assignment_format, expected_minutes(20~40 정수), steps, rubric을 모두 포함한다. "
        "응답 JSON은 Pydantic strict 검증을 통과해야 한다.\n"
        f"{_format_anchor()}"
    )


def _format_anchor() -> str:
    """완전히 채워진 슬라이드·퀴즈·voice 한 묶음을 형식 앵커(few-shot)로 제공한다.

    분량·구조를 글로만 지시하면 약한 모델이 1~2문장으로 통과하므로, 합격 수준의 한 예시를
    실제 JSON 조각으로 보여 준다. 내용 주제는 무관하며 형식·분량 기준만 따른다.
    """
    return (
        "형식 예시(주제만 다를 뿐 이 분량·구조를 따른다):\n"
        '{"slides":[{"slide_idx":0,"title":"이진 탐색의 직관","focus":"약점인 경계 처리를 다잡는다",'
        '"checkpoint":"lo<=hi 종료 조건을 스스로 설명할 수 있는가","category":"diagram",'
        '"html":"<section><h2>이진 탐색은 절반씩 후보를 지웁니다.</h2>'
        '<p>정렬된 배열에서 가운데 값을 보고 한쪽 절반을 통째로 버립니다.</p>'
        '<p>그래서 비교 횟수가 n이 아니라 log n으로 줄어듭니다.</p>'
        '<pre class=\\"mermaid\\">flowchart LR; A[lo,hi 설정]-->B[mid 계산]-->C{target 비교}</pre>'
        '<p>여기서 자주 틀리는 지점은 lo와 hi의 갱신을 mid+1, mid-1로 정확히 나누는 부분입니다.</p></section>",'
        '"css":""}],'
        '"quizzes":[{"slide_idx":0,"question":"이진 탐색의 종료 조건으로 옳은 것은?",'
        '"choices":["lo<hi","lo<=hi","lo==mid","hi==0"],"answer_idx":1,"difficulty":"함정 교정",'
        '"explanation":"lo<=hi여야 후보가 한 개 남은 경우까지 검사합니다. 오답 함정은 lo<hi로 두어 마지막 한 칸을 놓치는 실수이며, '
        '경계 처리 약점과 직접 연결됩니다."}],'
        '"voice_scripts":[{"slide_idx":0,"script_text":"자, 이번 화면에서는 이진 탐색이 왜 빠른지 직관부터 잡아 봅시다. '
        '정렬된 배열이 핵심인데요, 가운데 값을 한 번 보면 찾는 값이 그보다 큰지 작은지 바로 알 수 있죠. 그러면 나머지 절반은 볼 필요도 없이 버립니다. '
        '이게 반복되니까 후보가 절반, 또 절반으로 줄어서 비교 횟수가 로그 단위로 작아지는 거예요. 여기서 많이들 헷갈리는 지점이 경계 처리입니다. '
        'lo와 hi를 갱신할 때 mid를 그대로 두면 무한 루프에 빠지기 쉬워요. 그래서 작을 땐 lo를 mid 더하기 1, 클 땐 hi를 mid 빼기 1로 정확히 나눠 줘야 합니다. '
        '실전에서는 lo가 hi보다 커지는 순간을 종료 신호로 보면 안전합니다. 한 번 멈춰서, 후보가 딱 한 개 남았을 때 그 값을 검사하는지 머릿속으로 그려 보세요. '
        '마지막으로 다음 화면에서는 이 경계 조건을 코드로 직접 확인해 보겠습니다."}]}\n'
    )


def _personalization_block(state: ChapterStudioState) -> str:
    """단일콜 경로도 병렬 경로와 같은 개인화 계약을 사용한다."""
    return personalization_contract(
        weak_points=_optional_state_text(state, "weak_points"),
        audience_level=_optional_state_text(state, "audience_level") or "일반 학습자",
        tone=_state_int(state, "tone"),
        pace=_state_int(state, "pace"),
        tutor_depth=_state_int(state, "tutor_depth"),
        socratic=_state_int(state, "socratic"),
        learning_goal=_optional_state_text(state, "learning_goal") or "핵심 개념 이해와 실습",
        use_formal_speech=_optional_state_bool(state, "use_formal_speech", True),
        use_emoji=_optional_state_bool(state, "use_emoji", False),
        tutor_name=_optional_state_text(state, "tutor_name"),
        tutor_tagline=_optional_state_text(state, "tutor_tagline"),
    )


def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{key} 문자열이 필요하다.")
    return value


def _optional_state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if isinstance(value, str):
        return value
    return ""


def _optional_state_bool(state: ChapterStudioState, key: str, default: bool) -> bool:
    value = state.get(key)
    return value if isinstance(value, bool) else default


def _outline_contract(state: ChapterStudioState) -> str:
    value = state.get("slide_outline")
    if not isinstance(value, list) or not value:
        return "슬라이드 역할 목록 없음"
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            required = item.get("must_have")
            must_have = ", ".join(required) if _is_str_list(required) else ""
            lines.append(
                f"slide {item.get('slide_idx')}: category={item.get('category')}, "
                f"role={item.get('role')}, must_have={must_have}"
            )
    return "\n".join(lines) or "슬라이드 역할 목록 없음"


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["build_generation_request"]
