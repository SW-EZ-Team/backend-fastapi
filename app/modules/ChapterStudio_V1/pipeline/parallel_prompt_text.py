"""컴포넌트 병렬 생성 프롬프트 문자열.

parallel_prompts.py에서 프롬프트 텍스트 구성 책임만 떼어낸 모듈이다. 각 컴포넌트
(slides/quizzes/note/assignment/voice)별로 (system, user) 쌍을 만든다. 분량·구조 계약은
기존 단일콜 prompt.py와 동일한 수치 기준을 따르되, 해당 컴포넌트에만 한정한다. 어떤 LLM도
호출하지 않는 순수 함수만 둔다.
"""
from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.personalization import personalization_contract

_JSON_RULE = "출력은 단일 JSON 객체 한 개뿐이며 markdown fence·설명문·사고과정·<think> 블록을 금지한다. "
_CJK_BAN_RULE = "한자·중국어 문자 절대 금지, 순수 한글/숫자/영문만 사용한다. "


def slides_prompts(brief: str, outline: str, slide_count: int, template_key: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """슬라이드 배열만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, "슬라이드는 개인화 계약에 맞춰 예시·용어·오개념 교정 단서를 화면에 짧게 배치한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    system = (
        "너는 ChapterStudio_V1의 슬라이드 생성기다. "
        + _JSON_RULE
        + _CJK_BAN_RULE
        + "최상위 키는 slides 하나만 쓴다. "
        f"slides는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "slides[i] 키는 정확히 slide_idx, title, category, narration, visual, checkpoint 여섯 개다. "
        "title(제목)은 해당 슬라이드 내용을 구체적으로 요약한 6~16자 명사구다. "
        "챕터명+번호 형태 금지: '수직선과 정수의 위치 3'처럼 쓰지 말고 '음수끼리의 크기 비교'처럼 핵심 개념을 쓴다. "
        "few-shot title: bad='수직선과 정수의 위치 3', good='음수끼리의 크기 비교'. "
        "html, css, markdown, mermaid, script, 외부 URL을 절대 생성하지 않는다. "
        "category는 text, diagram, math, chart 중 하나만 쓴다. "
        "모든 slide는 category가 text여도 narration을 절대 비우거나 생략하면 실패다. "
        "narration은 화면 본문으로 바로 읽히는 2~4문장, 200~360자이며 해당 슬라이드의 핵심 설명·예시·주의점을 구체적으로 담는다. "
        "여러 슬라이드의 narration·음성대본이 같은 인사말/도입부로 시작하면 실패다. "
        "'안녕하세요. 오늘 우리가...왜 하필...' 같은 정형 인트로 반복 금지. "
        "각 슬라이드는 직전 내용에서 자연스럽게 이어지는 서로 다른 도입으로 시작한다. "
        "인사말은 첫 슬라이드에서만 허용한다. "
        "visual은 {type, data} 객체다. type은 number_line, comparison, step_flow, fraction_bar, concept_map, example_box 중 하나다. "
        "visual.type 선택 가이드: 수의 위치·대소·수직선·절댓값은 number_line, 계산 절차·단계·유도는 step_flow, 두 개념·방법 비교와 오개념 대조는 comparison, 분수·비율은 fraction_bar, 구체 예제+풀이는 example_box, 개념 간 관계 개요는 concept_map이다. "
        "category=text인 슬라이드도 빈 본문이나 추상 설명 금지다. metric-card, comparison-table, flow-strip, example-box 중 하나의 화면 패턴을 visual.data.pattern에 적고, metric-card/example-box는 example_box, comparison-table은 comparison, flow-strip은 step_flow로 렌더 가능한 visual.type에 매핑한다. "
        "concept_map은 남발 금지이며 단원당 1~2개만 쓴다. 같은 visual.type을 연속 사용하지 말고 한 강의에서 최소 3종 이상을 분포시킨다. "
        "중1 수학·수직선·정수 비교·절댓값·분수 단원처럼 수학 단원이면 number_line과 step_flow를 우선 사용하고, 정수 덧셈·크기비교는 concept_map보다 number_line, step_flow, comparison을 먼저 선택한다. "
        "number_line data={min,max,ticks:[{value,label}],points:[{value,label,color}],highlights:[{from,to,label}]} 형식이다. "
        "step_flow data={steps:[{label,detail,result}]} 형식이다. "
        "comparison data={left:{title,items[]},right:{title,items[]},verdict} 형식이다. "
        "fraction_bar data={fractions:[{num,den,label}]} 형식이다. example_box data={problem,steps[],answer} 형식이다. concept_map data={nodes[],edges[]} 형식이다. "
        'few-shot: 정수 -3과 2 크기비교는 visual={"type":"number_line","data":{"min":-5,"max":5,"ticks":[{"value":-5,"label":"-5"},{"value":0,"label":"0"},{"value":5,"label":"5"}],"points":[{"value":-3,"label":"-3","color":"#2A5C7A"},{"value":2,"label":"2","color":"#207B4C"}],"highlights":[{"from":-3,"to":2,"label":"오른쪽 2가 더 큼"}]}}처럼 쓴다. '
        'few-shot text slide: {"slide_idx":1,"title":"오개념 바로잡기","category":"text","narration":"음수 비교에서 가장 많이 하는 실수는 숫자만 보고 8이 3보다 크니까 -8이 -3보다 크다고 생각하는 것입니다. 수직선에서는 오른쪽에 있을수록 큰 수이므로 -3이 -8보다 큽니다. 0에서 멀어지는 정도와 실제 크기 비교를 분리해서 보면 부호가 붙은 수를 더 안정적으로 판단할 수 있습니다.","visual":{"type":"comparison","data":{"pattern":"comparison-table","left":{"title":"잘못된 판단","items":["숫자 8만 보고 -8이 더 크다고 결론","절댓값과 실제 크기를 섞어서 생각"]},"right":{"title":"올바른 판단","items":["수직선에서 더 오른쪽인 -3 선택","0과의 거리는 절댓값 비교에만 사용"]},"verdict":"음수 크기 비교는 수직선 위치가 기준입니다."}},"checkpoint":"-8과 -3 중 더 큰 수와 이유를 말할 수 있는가?"}. '
        "구성은 상황→시각화→비교→오개념 교정→확인 순서를 권장한다. 텍스트 문단만 있는 슬라이드는 실패다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"선택 템플릿: {template_key}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        f"위 역할에 맞춰 슬라이드 {slide_count}개를 구조화 visual 스펙으로 만든다. "
        "화면에는 충분한 narration과 구체적 visual data를 남긴다. narration을 빈 문자열, 한 문장짜리 요약, '시각 자료' 같은 플레이스홀더로 쓰면 실패다. "
        "수학 예시는 실제 숫자·눈금·비교값을 data에 넣어 Python 렌더러가 바로 그릴 수 있게 한다."
    )
    return system, user


def quizzes_prompts(brief: str, outline: str, slide_count: int, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """퀴즈 배열만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="퀴즈는 약점 개념을 직접 겨냥한 진단·교정형 문항을 우선한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    system = (
        "너는 ChapterStudio_V1의 퀴즈 생성기다. "
        + _JSON_RULE
        + "최상위 키는 quizzes 하나만 쓴다. "
        f"quizzes는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "quizzes[i] 키는 정확히 slide_idx, question, choices, answer_idx, difficulty, explanation 여섯 개다. "
        "choices는 문자열 4개 배열, answer_idx는 0~3 정수이며 정답은 한 보기에만 해당한다. "
        "difficulty는 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. Easy/Medium/Hard 금지. "
        "explanation은 120~180자로 정답 이유와 오답 함정을 함께 적고 약점 개념과 연결한다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        f"각 slide_idx마다 그 슬라이드 내용에서만 출제한 퀴즈 1개씩, 총 {slide_count}개를 만든다."
    )
    return system, user


def note_prompts(brief: str, outline: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """핵심 노트(note_blocks)만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, "노트는 개인화 계약에 맞춰 복습 우선순위와 bullet 예시를 조정한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    system = (
        "너는 ChapterStudio_V1의 핵심 노트 생성기다. "
        + _JSON_RULE
        + "최상위 키는 note_blocks 하나만 쓴다. "
        "note_blocks는 정확히 4개이고 각 block은 heading과 정확히 3개 bullets를 가진다. "
        "note_blocks[i] 키는 정확히 heading, bullets 두 개이며 title 키를 쓰지 않는다. "
        "각 bullet은 45자 이상의 완결 문장이다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        "강의 전체를 복습할 수 있는 핵심 노트 4블록을 만든다."
    )
    return system, user


def assignment_prompts(brief: str, outline: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """과제(assignment)만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="과제는 약점 개념을 훈련하는 과제로 구성한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    system = (
        "너는 ChapterStudio_V1의 과제 생성기다. "
        + _JSON_RULE
        + "최상위 키는 assignment 하나만 쓴다. "
        "assignment는 title, assignment_format, expected_minutes(20~40 정수), steps, rubric을 모두 채운다. "
        "steps와 rubric은 반드시 문자열 배열(list)이며 dict나 객체로 쓰면 실패다. "
        "steps는 3~5개, rubric은 3~5개의 완결 문장이다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        "강의 내용을 직접 적용해 볼 실습 과제 1개를 만든다."
    )
    return system, user


def voice_prompt(
    brief: str, slide_title: str, slide_focus: str, slide_summary: str, slide_idx: int, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "", previous_title: str = ""
) -> tuple[str, str]:
    """슬라이드 1개의 음성대본만 생성하는 (system, user) 프롬프트를 만든다.

    xgrammar가 minLength를 완전히 강제하지 못하는 실측을 보완하기 위해 프롬프트에 구체적
    분량(900~1600자)과 4단 구조를 명시해 모델이 충분한 길이를 스스로 지키게 한다.
    """
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="음성대본은 약점 개념을 더 천천히·예시 많이 설명하고 오개념을 짚는다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    intro_rule = _voice_intro_rule(slide_idx, previous_title)
    previous_line = _previous_slide_line(previous_title)
    system = (
        "너는 ChapterStudio_V1의 음성대본 생성기다. "
        + _JSON_RULE
        + _CJK_BAN_RULE
        + "키는 정확히 slide_idx, script_text 두 개다. "
        # 분량 하한을 숫자로 못 박고 4단 구조를 강제 — xgrammar minLength 미강제 보완.
        "script_text는 반드시 900~1600자 범위여야 한다(900자 미만이면 실패로 간주한다). "
        "분량 기준: ① 도입(이 개념이 왜 중요한지 배경 2~3문장) ② 핵심 설명(개념·원리 3~4문장) "
        "③ 구체적 예시·직관(한 번에 이해되는 사례 2~3문장) ④ 마무리 복습(다음 화면 연결·자가점검 1~2문장). "
        "총 8~12문장, 과외 선생님 자연스러운 존댓말 한 문단으로 완성한다. "
        "화면에 없는 깊은 설명·실수하기 쉬운 지점·바로 해볼 미니연습을 포함한다. "
        "여러 슬라이드가 같은 인사말/도입부로 시작하면 실패다. "
        "900자 미만의 짧은 대본(한두 문장 나열)은 절대 허용되지 않는다. "
        "HTML 태그·markdown·괄호 지시문을 넣지 않는다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"대상 슬라이드: slide_idx={slide_idx} / 제목={slide_title} / 초점={slide_focus}\n"
        f"화면 요약: {slide_summary}\n"
        f"{previous_line}"
        f"{personalization}\n"
        f"{intro_rule}\n"
        "위 슬라이드의 음성대본을 900~1600자 범위로 만든다. "
        "도입→핵심설명→구체예시→마무리복습 순서를 지킨다. "
        f"slide_idx는 반드시 {slide_idx}로 고정한다."
    )
    return system, user


def _voice_intro_rule(slide_idx: int, previous_title: str) -> str:
    if slide_idx == 0:
        return "첫 슬라이드이므로 짧은 인사말은 가능하지만, 바로 핵심 상황으로 들어간다."
    if previous_title:
        return f"첫 슬라이드가 아니므로 인사말을 쓰지 말고, 직전 화면 '{previous_title}'에서 이어지는 한 문장으로 시작한다."
    return "첫 슬라이드가 아니므로 인사말과 '안녕하세요. 오늘 우리가...왜 하필...'식 정형 도입을 쓰지 말고 직전 흐름을 이어 시작한다."


def _previous_slide_line(previous_title: str) -> str:
    if not previous_title:
        return ""
    return f"직전 슬라이드 주제: {previous_title}\n"


def _personalization(
    weak_points: str,
    audience_level: str,
    tone: int,
    pace: int,
    tutor_depth: int,
    socratic: int,
    learning_goal: str,
    component_rule: str = "",
    *,
    weak_rule: str = "",
    use_formal_speech: bool = True,
    use_emoji: bool = False,
    tutor_name: str = "",
    tutor_tagline: str = "",
) -> str:
    return personalization_contract(
        weak_points=weak_points,
        audience_level=audience_level,
        tone=tone,
        pace=pace,
        tutor_depth=tutor_depth,
        socratic=socratic,
        learning_goal=learning_goal,
        use_formal_speech=use_formal_speech,
        use_emoji=use_emoji,
        tutor_name=tutor_name,
        tutor_tagline=tutor_tagline,
        component_rule=component_rule,
        weak_component_rule=weak_rule,
    )


def clean_raw_voice_text(text: str) -> str:
    """raw 텍스트 폴백용 — think·fence 제거 후 앞뒤 따옴표·마크다운 잔재를 걷어낸다.

    Qwen이 JSON 대신 대본 자체를 반환할 때 script_text로 쓸 수 있는 깨끗한 텍스트를 만든다.
    clean_llm_text가 think 블록·코드펜스를 제거하고, 이후 앞뒤 큰따옴표만 추가 제거한다.
    """
    from common.llm_output import clean_llm_text  # 지역 import — 순환 방지
    cleaned = clean_llm_text(text).strip()
    # JSON 문자열 리터럴처럼 앞뒤가 따옴표로 감싸인 경우 벗겨낸다.
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    return cleaned


__all__ = [
    "assignment_prompts",
    "clean_raw_voice_text",
    "note_prompts",
    "quizzes_prompts",
    "slides_prompts",
    "voice_prompt",
]
