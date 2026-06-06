"""컴포넌트 병렬 생성 프롬프트 문자열.

parallel_prompts.py에서 프롬프트 텍스트 구성 책임만 떼어낸 모듈이다. 각 컴포넌트
(slides/quizzes/note/assignment/voice)별로 (system, user) 쌍을 만든다. 분량·구조 계약은
기존 단일콜 prompt.py와 동일한 수치 기준을 따르되, 해당 컴포넌트에만 한정한다. 어떤 LLM도
호출하지 않는 순수 함수만 둔다.
"""
from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.parallel_inputs import VoiceBlueprint, build_voice_blueprint
from app.modules.ChapterStudio_V1.pipeline.personalization import personalization_contract

_JSON_RULE = "출력은 단일 JSON 객체 한 개뿐이며 markdown fence·설명문·사고과정·<think> 블록을 금지한다. "
_CJK_BAN_RULE = "한자·중국어 문자 절대 금지, 순수 한글/숫자/영문만 사용한다. "

# 강한 CS 신호 — 이 단어 하나만 있어도 프로그래밍·CS 과목으로 확정한다.
# "함수"·"알고리즘" 같이 수학에서도 흔한 단어는 여기서 제외한다(오분류 방지).
_CS_STRONG_KEYWORDS = (
    "python", "java", "javascript", "c++", "c언어", "프로그래밍", "코딩",
    "자료구조", "컴퓨터", "소프트웨어", "코드", "class", "객체지향",
    "database", "sql", "네트워크 프로그래밍", "코드 작성", "디버깅",
    # 주요 프로그래밍 라이브러리·프레임워크 — 이 단어만 있어도 CS 과목으로 확정한다.
    "numpy", "pandas", "matplotlib", "scipy", "sklearn", "scikit",
    "tensorflow", "pytorch", "keras", "fastapi", "django", "flask",
    "react", "vue", "angular", "nodejs", "typescript", "kotlin", "swift",
    "rust", "golang", "opencv", "langchain", "langgraph",
)

# 약한 CS 신호 — 단독으로는 모호하다("정렬 알고리즘"=CS, "유클리드 호제법 알고리즘"=수학).
# 강한 CS 신호와 공존할 때만 CS로 인정한다.
_CS_WEAK_KEYWORDS = (
    "알고리즘",
    "개발",
)

# 수학·비CS 과목 신호 — 이 단어가 있으면 약한 CS 신호가 있어도 비CS로 본다.
# "함수"는 한국 수학 핵심 단원어이므로 여기로 옮긴다(이차함수·일차함수 등).
_NON_CS_OVERRIDE_KEYWORDS = (
    "수학", "함수", "호제법", "방정식", "부등식", "도형", "기하", "미분", "적분",
    "확률", "통계", "수열", "그래프", "정수", "유리수", "분수", "소인수",
    "물리", "화학", "생물", "지구과학", "역사", "국어", "영어", "문학", "사회",
)


def _is_cs_subject(brief: str) -> bool:
    """brief 문자열로부터 프로그래밍·CS 과목 여부를 판별한다.

    LLM을 호출하지 않는 순수 함수 — 다음 우선순위로 결정한다:
    1) 강한 CS 신호가 있으면 CS로 확정한다.
    2) 비CS(수학·과학·인문) 신호가 있으면 비CS로 본다(약한 CS 신호 무시).
    3) 약한 CS 신호만 있고 비CS 신호가 없으면 CS로 인정한다.

    의도된 동작: "알고리즘"은 약한 CS 신호다. 수학 단원어(수학·호제법·함수 등)가
    함께 없으면 "알고리즘 개론"처럼 CS 강의로 본다. 이는 코딩 메타포를 허용해야 하는
    컴퓨터 알고리즘 강의를 비CS로 오분류하지 않기 위한 의도된 선택이다.
    """
    lower = brief.lower()
    if any(kw in lower for kw in _CS_STRONG_KEYWORDS):
        return True
    # 수학·과학·인문 단원어가 있으면 약한 신호("알고리즘" 등)는 CS로 보지 않는다.
    if any(kw in lower for kw in _NON_CS_OVERRIDE_KEYWORDS):
        return False
    return any(kw in lower for kw in _CS_WEAK_KEYWORDS)


def _coding_metaphor_rule(brief: str) -> str:
    """과목에 따라 코딩 메타포 허용·금지 규칙을 반환한다.

    프로그래밍·CS 과목이 아니면 'class처럼', 'def처럼' 같은 코딩 비유를 금지한다.
    CS 과목이면 빈 문자열을 반환해 기존 규칙을 그대로 유지한다.
    """
    if _is_cs_subject(brief):
        return ""
    return (
        "이 강의는 프로그래밍·CS 과목이 아니므로 코딩·프로그래밍 용어를 비유로 쓰지 않는다 "
        "(예: 'class처럼', 'def처럼', '함수처럼', '변수처럼', '루프처럼', '객체처럼' 금지). "
        "수학·과학·인문 등 해당 과목의 고유 비유만 사용한다. "
    )


def _cs_slides_concrete_rule(brief: str) -> str:
    """프로그래밍·CS 과목 슬라이드에서 구체적 코드·연산·예시 필수 지시를 반환한다.

    비CS 과목이면 빈 문자열을 반환해 기존 슬라이드 규칙을 그대로 유지한다.
    CS 과목이면 각 슬라이드 narration에 추상 메타포가 아닌 실제 코드·값·연산 예시가
    포함되도록 강제한다.
    """
    if not _is_cs_subject(brief):
        return ""
    return (
        "이 강의는 프로그래밍·CS 과목이므로 슬라이드 narration은 추상 비유나 학습 태도 메타포가 아닌 "
        "구체적 코드·연산·실행 결과·API 동작을 포함해야 한다. "
        "예: NumPy 슬라이드라면 'arr[1:3]', 'np.array([1,2,3]).shape', "
        "'arr * 2', 'broadcasting이 가능한 shape 조합' 등 실제 코드·값을 narration에 담는다. "
        "example_box의 problem·steps·answer도 실제 코드와 실행 결과 값으로 채운다. "
        "추상적 관점·태도·비유만 담은 슬라이드는 실패다. "
    )


def slides_prompts(brief: str, outline: str, slide_count: int, template_key: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """슬라이드 배열만 생성하는 (system, user) 프롬프트를 만든다.

    plan-first 슬롯 오더: outline에는 슬롯별 visual_type이 단일값으로 이미 확정되어 있다.
    AI는 구조(type·개수·인덱스)가 아닌 데이터(title·narration·visual.data)만 채운다.
    """
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, "슬라이드는 개인화 계약에 맞춰 예시·용어·오개념 교정 단서를 화면에 짧게 배치한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    system = (
        "너는 ChapterStudio_V1의 슬라이드 생성기다. "
        + _JSON_RULE
        + _CJK_BAN_RULE
        + "최상위 키는 slides 하나만 쓴다. "
        f"slides는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "slides[i] 키는 정확히 slide_idx, title, category, narration, visual, checkpoint 여섯 개다. "
        # plan-first 핵심 강제: visual.type은 outline에서 슬롯별로 단일값으로 확정됨
        "중요: 각 slide의 visual.type은 아래 '확정 슬라이드 플랜'에 명시된 visual_type(고정·변경불가) 값 그대로만 써야 한다. "
        "다른 type으로 바꾸거나 생략하면 즉시 실패다. visual.data는 해당 type의 스펙에 맞게 채운다. "
        "title(제목)은 해당 슬라이드 내용을 구체적으로 요약한 6~16자 명사구다. "
        "챕터명+번호 형태 금지: '수직선과 정수의 위치 3'처럼 쓰지 말고 '음수끼리의 크기 비교'처럼 핵심 개념을 쓴다. "
        "few-shot title: bad='수직선과 정수의 위치 3', good='음수끼리의 크기 비교'. "
        "html, css, markdown, mermaid, script, 외부 URL을 절대 생성하지 않는다. "
        "category는 text, diagram, math, chart 중 하나만 쓴다. "
        "모든 slide는 category가 text여도 narration을 절대 비우거나 생략하면 실패다. "
        "narration은 화면 본문으로 바로 읽히는 2~4문장, 200~360자이며 해당 슬라이드의 핵심 설명·예시·주의점을 구체적으로 담는다. "
        "각 슬롯의 narration 길이는 outline에 명시된 범위를 준수한다. "
        "여러 슬라이드의 narration·음성대본이 같은 인사말/도입부로 시작하면 실패다. "
        "'안녕하세요. 오늘 우리가...왜 하필...' 같은 정형 인트로 반복 금지. "
        "각 슬라이드는 직전 내용에서 자연스럽게 이어지는 서로 다른 도입으로 시작한다. "
        "인사말은 첫 슬라이드에서만 허용한다. "
        "visual은 {type, data} 객체다. 기본 type은 number_line, comparison, step_flow, fraction_bar, concept_map, example_box 중 하나이며, category=text에서는 metric-card, comparison-table도 허용한다. "
        "visual.type 선택 가이드: 수의 위치·대소·수직선·절댓값은 number_line, 계산 절차·단계·유도는 step_flow, 두 개념·방법 비교와 오개념 대조는 comparison, 분수·비율은 fraction_bar, 구체 예제+풀이는 example_box, 개념 간 관계 개요는 concept_map이다. "
        "category=text인 슬라이드는 narration만으로 끝내면 실패이며 시각요소 marker가 되는 visual을 반드시 포함한다. "
        "category=text인 슬라이드는 visual.type을 metric-card, comparison-table, example_box 중 하나로 고른다. "
        "metric-card는 핵심 기준 카드, comparison-table은 오개념/정답 대조표, example_box는 구체 예제+풀이 카드로만 쓴다. "
        "concept_map은 남발 금지이며 단원당 1~2개만 쓴다. 같은 visual.type을 연속 사용하지 말고 한 강의에서 최소 3종 이상을 분포시킨다. "
        "중1 수학·수직선·정수 비교·절댓값·분수 단원처럼 수학 단원이면 number_line과 step_flow를 우선 사용한다. "
        "number_line data={min,max,ticks:[{value,label}],points:[{value,label,color}],highlights:[{from,to,label}]} 형식이다. "
        "step_flow data={steps:[{label,detail,result}]} 형식이다. "
        "comparison data={left:{title,items[]},right:{title,items[]},verdict} 형식이다. "
        "fraction_bar data={fractions:[{num,den,label}]} 형식이다. "
        "example_box data={problem,steps[],answer} 형식이다. "
        "concept_map data={nodes[],edges[]} 형식이다. "
        "metric-card data={title,value,caption} 형식이다. "
        "comparison-table data={left:{title,items[]},right:{title,items[]},verdict} 형식이다. "
        'few-shot: 정수 -3과 2 크기비교는 visual={"type":"number_line","data":{"min":-5,"max":5,"ticks":[{"value":-5,"label":"-5"},{"value":0,"label":"0"},{"value":5,"label":"5"}],"points":[{"value":-3,"label":"-3","color":"#2A5C7A"},{"value":2,"label":"2","color":"#207B4C"}],"highlights":[{"from":-3,"to":2,"label":"오른쪽 2가 더 큼"}]}}처럼 쓴다. '
        'few-shot text slide: {"slide_idx":1,"title":"오개념 바로잡기","category":"text","narration":"음수 비교에서 가장 많이 하는 실수는 숫자만 보고 8이 3보다 크니까 -8이 -3보다 크다고 생각하는 것입니다. 수직선에서는 오른쪽에 있을수록 큰 수이므로 -3이 -8보다 큽니다. 0에서 멀어지는 정도와 실제 크기 비교를 분리해서 보면 부호가 붙은 수를 더 안정적으로 판단할 수 있습니다.","visual":{"type":"comparison-table","data":{"left":{"title":"잘못된 판단","items":["숫자 8만 보고 -8이 더 크다고 결론","절댓값과 실제 크기를 섞어서 생각"]},"right":{"title":"올바른 판단","items":["수직선에서 더 오른쪽인 -3 선택","0과의 거리는 절댓값 비교에만 사용"]},"verdict":"음수 크기 비교는 수직선 위치가 기준입니다."}},"checkpoint":"-8과 -3 중 더 큰 수와 이유를 말할 수 있는가?"}. '
        "텍스트 문단만 있는 슬라이드는 실패다.\n"
        + _coding_metaphor_rule(brief)
        + _cs_slides_concrete_rule(brief)
        + f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"선택 템플릿: {template_key}\n"
        f"확정 슬라이드 플랜(visual_type 고정·개수 고정·인덱스 고정 — 데이터만 채울 것):\n{outline}\n"
        f"{personalization}\n"
        f"위 플랜의 각 슬롯을 slide_idx 순서대로 정확히 {slide_count}개 생성한다. "
        "각 슬롯의 visual.type은 플랜에 명시된 값 그대로 사용한다(변경 불가). "
        "화면에는 충분한 narration과 구체적 visual data를 남긴다. "
        "text 슬라이드도 metric-card, comparison-table, example_box 중 하나의 visual marker를 반드시 남긴다. "
        "narration을 빈 문자열, 한 문장짜리 요약, '시각 자료' 같은 플레이스홀더로 쓰면 실패다. "
        "narration은 플랜에 명시된 글자 범위를 지킨다. "
        "수학 예시는 실제 숫자·눈금·비교값을 data에 넣어 Python 렌더러가 바로 그릴 수 있게 한다."
    )
    return system, user


def quizzes_prompts(brief: str, outline: str, slide_count: int, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str, use_formal_speech: bool = True, use_emoji: bool = False, tutor_name: str = "", tutor_tagline: str = "", is_default_tutor: bool = True, voice_sample_url: str = "") -> tuple[str, str]:
    """퀴즈 배열만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="퀴즈는 약점 개념을 직접 겨냥한 진단·교정형 문항을 우선한다.", use_formal_speech=use_formal_speech, use_emoji=use_emoji, tutor_name=tutor_name, tutor_tagline=tutor_tagline)
    cs_subject_rule = _quiz_cs_rule(brief)
    system = (
        "너는 ChapterStudio_V1의 퀴즈 생성기다. "
        + _JSON_RULE
        + "최상위 키는 quizzes 하나만 쓴다. "
        f"quizzes는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "quizzes[i] 키는 정확히 slide_idx, question, choices, answer_idx, difficulty, explanation 여섯 개다. "
        "choices는 문자열 4개 배열, answer_idx는 0~3 정수이며 정답은 한 보기에만 해당한다. "
        "difficulty는 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. Easy/Medium/Hard 금지. "
        "difficulty 분포: 전체 문항 중 기억·이해는 최대 40%로 제한하고 나머지 60% 이상은 적용·함정 교정·실전 판단·오해 중 하나여야 한다. "
        "explanation은 120~180자로 정답 이유와 오답 함정을 함께 적고 약점 개념과 연결한다. "
        # 메타·태도 질문 명시 금지
        "절대 금지 — 다음 유형의 문항을 생성하지 않는다: "
        "(1) 강의·학습 태도·관점 문항: '이 강의에서 강조한 관점은', '바람직한 학습자 반응은', "
        "'잘 이해한 학습자의 말은', '확장 질문 단계에서 바람직한 반응은', "
        "'강의 끝 점검에서 이해한 학습자가 할 말은' 같이 학습 메타·태도·강의 구조를 묻는 문항. "
        "(2) 슬라이드 역할·구조 문항: 도입·본론·마무리 등 강의 구성 자체를 묻는 문항. "
        "퀴즈는 반드시 학습 주제 자체의 지식·개념·적용·계산을 측정해야 한다. "
        "보기(choices)는 개념 혼동을 유발하는 그럴듯한 오답으로 구성해 실제 이해 없이는 풀 수 없게 한다. "
        # 발문(question 필드) 어투 규칙 — 비문·구어체 제거
        # QA에서 '고르봐', '골라봐요', '선택해봐요' 등 비문이 반복 관찰됨.
        # question 필드는 narration 말투 규칙(~봐요 등)을 따르지 않으며
        # 표준 시험 발문 형식만 허용한다.
        "question 발문 형식 규칙: "
        "퀴즈 발문은 표준 시험 한국어 형식으로만 작성한다. "
        "허용 형식 예시: '다음 중 ~인 것은?', '~에 대한 설명으로 옳은 것은?', "
        "'~로 가장 적절한 것은?', '~의 결과로 옳은 것은?', '~에 해당하지 않는 것은?'. "
        "절대 금지 형식: '~고르봐', '~골라봐요', '~선택해봐요', '~골라보세요', '~고르봐요' — "
        "봐/봐요/봐요로 끝나는 발문은 비문이므로 퀴즈 question 필드에 일절 사용하지 않는다. "
        "question 필드는 항상 의문형('~것은?'·'~인가?')이나 명령형('~고르시오'·'~선택하시오')으로 끝낸다. "
        + cs_subject_rule
        + f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할(role은 슬라이드 구조 참고용이며 퀴즈 내용과 무관 — 주제 지식만 출제):\n{outline}\n"
        f"{personalization}\n"
        f"각 slide_idx마다 그 슬라이드의 구체적 학습 내용(개념·연산·동작·사례)에서만 출제한 퀴즈 1개씩, 총 {slide_count}개를 만든다. "
        "role(도입/확장 질문/강의 끝 점검 등)은 슬라이드 구조 표시일 뿐이며 퀴즈에서 언급하거나 '학습자 반응'을 묻는 문항으로 쓰지 않는다."
    )
    return system, user


def _quiz_cs_rule(brief: str) -> str:
    """프로그래밍·CS 과목이면 퀴즈에 코드·연산·출력 기반 문항 요구 지시를 반환한다.

    비CS 과목이면 빈 문자열을 반환한다. 슬라이드 메타포 규칙과 동일한 판별 함수를 재사용한다.
    """
    if not _is_cs_subject(brief):
        return ""
    return (
        "이 강의는 프로그래밍·CS 과목이므로 퀴즈 문항은 다음 유형을 우선한다: "
        "① 코드 출력 예측(실행 결과 고르기), "
        "② 연산·인덱싱·슬라이싱 결과 계산, "
        "③ shape·dtype·브로드캐스팅 가능 여부 판단, "
        "④ 함수·메서드 동작 결과 고르기, "
        "⑤ 오류(TypeError·IndexError 등) 발생 여부 판단. "
        "추상적 설명만 묻는 문항은 금지하고 실제 코드·값을 문항에 포함한다. "
    )


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
    brief: str,
    slide_title: str,
    slide_focus: str,
    slide_summary: str,
    slide_idx: int,
    *,
    weak_points: str,
    audience_level: str,
    tone: int,
    pace: int,
    tutor_depth: int,
    socratic: int,
    learning_goal: str,
    use_formal_speech: bool = True,
    use_emoji: bool = False,
    tutor_name: str = "",
    tutor_tagline: str = "",
    is_default_tutor: bool = True,
    voice_sample_url: str = "",
    previous_title: str = "",
) -> tuple[str, str]:
    """슬라이드 1개의 음성대본을 plan-first 슬롯 오더로 생성하는 (system, user) 프롬프트.

    블루프린트(코드 결정)가 섹션 수·role·순서·길이 범위·intro 모드를 확정하고,
    AI는 각 슬롯의 text만 채운다. AI가 섹션 개수/순서를 임의로 정하지 못한다.
    """
    personalization = _personalization(
        weak_points,
        audience_level,
        tone,
        pace,
        tutor_depth,
        socratic,
        learning_goal,
        weak_rule="음성대본은 약점 개념을 더 천천히·예시 많이 설명하고 오개념을 짚는다.",
        use_formal_speech=use_formal_speech,
        use_emoji=use_emoji,
        tutor_name=tutor_name,
        tutor_tagline=tutor_tagline,
    )
    blueprint = build_voice_blueprint(slide_idx, previous_title)
    previous_line = _previous_slide_line(previous_title)
    slot_spec = _build_slot_spec(blueprint)
    system = (
        "너는 ChapterStudio_V1의 음성대본 생성기다. "
        + _JSON_RULE
        + _CJK_BAN_RULE
        # plan-first 구조 강제: 섹션 수·role·순서는 코드가 이미 결정했다. AI는 text만 채운다.
        + "최상위 키는 정확히 slide_idx, sections 두 개다. "
        "sections는 반드시 아래 명세한 순서대로 4개 role 슬롯을 가진다(섹션 수·순서 변경 불가). "
        "각 슬롯은 role, text 두 키만 가진다. "
        "HTML 태그·markdown·괄호 지시문을 넣지 않는다. "
        "여러 슬라이드가 같은 인사말/도입부로 시작하면 실패다. "
        "한자·중국어 문자 절대 금지, 순수 한글/숫자/영문만 사용한다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"대상 슬라이드: slide_idx={slide_idx} / 제목={slide_title} / 초점={slide_focus}\n"
        f"화면 요약: {slide_summary}\n"
        f"{previous_line}"
        f"{personalization}\n"
        f"아래 4개 섹션 슬롯을 순서대로 채워라(섹션 수·순서·role 변경 불가):\n"
        f"{slot_spec}\n"
        f"slide_idx는 반드시 {slide_idx}로 고정한다."
    )
    return system, user


def _build_slot_spec(blueprint: VoiceBlueprint) -> str:
    """블루프린트로부터 프롬프트 내 섹션 슬롯 명세 텍스트를 만든다.

    각 슬롯에 최소 분량을 강하게 명시해 첫 패스 미달을 방지한다.
    최소 분량 미달 시 해당 슬롯을 거부·재생성하므로 반드시 채워야 함을 명시한다.
    """
    lines: list[str] = []
    for sec in blueprint.sections:
        mode_note = ""
        if sec.role == "intro" and sec.intro_mode is not None:
            if sec.intro_mode == "greeting":
                mode_note = " [greeting 모드: 짧은 인사 후 바로 핵심 상황 진입]"
            else:
                mode_note = " [bridge 모드: 인사말 금지, 직전 화면에서 자연스럽게 이어지는 한 문장으로 시작]"
        # 길이 강제 지시 — 최소 분량 미달 시 거부됨을 명시해 첫 패스 순응률을 높인다
        length_mandate = (
            f"반드시 {sec.min_chars}자 이상 {sec.max_chars}자 이하로 작성한다 "
            f"— {sec.min_chars}자 미만이면 이 슬롯은 거부되어 재생성된다"
        )
        lines.append(
            f"- role={sec.role}{mode_note}: {sec.instruction} "
            f"({length_mandate})"
        )
    return "\n".join(lines)


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
