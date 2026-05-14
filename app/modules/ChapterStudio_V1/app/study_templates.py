from __future__ import annotations

from app.modules.ChapterStudio_V1.app.template_catalog import build_templates
from app.modules.ChapterStudio_V1.app.template_selector import TemplateDecision, choose_template
from app.modules.ChapterStudio_V1.app.template_types import SlideFrame, StudyTemplate, TemplateOption
from app.modules.ChapterStudio_V1.app.template_visuals import visual_contract, visual_options, visual_spec

_TEMPLATES = build_templates()


def get_template(template: str) -> StudyTemplate:
    """알 수 없는 템플릿은 안전한 기본 템플릿으로 고정한다."""
    return _TEMPLATES.get(template, _TEMPLATES["concept_code"])


def select_template(template: str, topic: str) -> StudyTemplate:
    """자동 추천이면 주제 키워드로 학습 패턴 템플릿을 고른다."""
    if template != "auto":
        return get_template(template)
    return get_template(select_template_decision(topic).key)


def select_template_decision(topic: str) -> TemplateDecision:
    """자동 추천 근거를 agent trace에 남길 수 있게 결정 객체를 반환한다."""
    return choose_template(topic, _AUTO_RULES)


def template_contract(template: str) -> str:
    """사용자가 고른 템플릿을 학습 설계 계약으로 바꾼다."""
    return get_template(template).contract


def template_options() -> list[TemplateOption]:
    """프론트 select가 그대로 쓸 수 있는 템플릿 목록이다."""
    options: list[TemplateOption] = [{"value": "auto", "label": "자동 추천"}]
    options.extend({"value": item.key, "label": item.label} for item in _TEMPLATES.values())
    return options


def template_keys() -> list[str]:
    """테스트와 문서 검증에서 템플릿 key 목록을 확인한다."""
    return list(_TEMPLATES)


def frame_contract(template: str) -> str:
    """슬라이드별 역할과 필수 요소를 프롬프트 문장으로 압축한다."""
    lines = []
    for frame in get_template(template).frames:
        required = ", ".join(frame.must_have)
        lines.append(f"slide {frame.slide_idx}: category={frame.category}, 역할={frame.role}, 필수={required}")
    return "\n".join(lines)


def study_quality_contract() -> str:
    """5장 테스트 강의 안에서 깊이 있는 학습이 가능하게 하는 공통 기준이다."""
    return (
        "각 슬라이드는 책 요약이 아니라 과외식으로 학습목표, 배경 철학, 핵심 설명, 작동 방식, 작은 예시, 반례, 적용 기준, 자가점검 질문을 분리한다. "
        "사용자가 화면 하나만 봐도 왜 중요한지, 무엇을 먼저 봐야 하는지, 어디서 실수하는지 이해할 만큼 충분한 문장량을 유지한다. "
        "짧은 실습은 슬라이드 안 활동이며 퀴즈와 절대 합치지 않는다. "
        "code 카테고리는 코드와 해석을 포함하고 주요 키워드, 함수, 변수 구분이 가능해야 한다. "
        "note_blocks는 주제의 이유, 기본 철학, 생각의 관점, 오해 바로잡기, 복습 루틴 중 3개 이상을 포함한다. "
        "quizzes는 5개 별도 산출물이며 기억, 이해, 적용, 함정 교정을 고르게 포함한다. "
        "assignment는 과제 형식, 예상 소요시간, 20분 안에 끝낼 수 있는 심화 과제 절차, 채점 기준을 제공하고, voice_scripts는 슬라이드마다 5~7문장 과외 말투로 핵심 전환을 설명한다."
    )


_AUTO_RULES: dict[str, tuple[str, ...]] = {
    "person_profile": ("인물", "사람", "학자", "과학자", "통계학자", "작가", "철학자", "개발자", "로널드", "피셔", "뉴턴", "다윈", "튜링", "아인슈타인", "biography"),
    "statistics_inference": ("통계학", "회귀", "분산", "표본", "p-value", "유의성", "statistics"),
    "research_method": ("논문", "연구", "방법론", "가설", "실험설계", "재현성"),
    "physics_model": ("물리", "역학", "전자기", "양자", "상대성", "힘", "physics"),
    "astronomy_space": ("천문", "우주", "행성", "별", "블랙홀", "은하", "astronomy"),
    "earth_science": ("지구과학", "지진", "화산", "판 구조론", "암석", "해류", "기상"),
    "environment_sustainability": ("환경", "기후", "탄소", "생태", "지속가능", "오염"),
    "economics_model": ("경제", "시장", "수요", "공급", "인플레이션", "금리", "economics"),
    "psychology_behavior": ("심리", "행동", "인지", "동기", "강화", "학습심리"),
    "sociology_culture": ("사회", "문화", "제도", "계층", "권력", "젠더"),
    "geography_region": ("지리", "지역", "도시", "인구", "공간", "지도"),
    "engineering_design": ("공학", "기계", "설계", "제어", "로봇", "제조"),
    "electronics_signal": ("전자", "회로", "신호", "전압", "전류", "주파수"),
    "media_literacy": ("뉴스", "미디어", "콘텐츠", "프레임", "가짜뉴스", "정보검증"),
    "health_lifestyle": ("건강", "운동", "영양", "수면", "생활습관", "예방"),
    "chem_reaction": ("화학", "반응", "몰", "산화", "환원", "chemistry"),
    "bio_system": ("생명", "세포", "유전", "dna", "단백질", "biology"),
    "clinical_reasoning": ("의학", "의과", "임상", "증상", "진단", "환자", "병리"),
    "concept_code": ("python", "코딩", "프로그래밍", "langgraph", "fastapi"),
    "algorithm_trace": ("알고리즘", "자료구조", "코딩테스트", "algorithm"),
    "system_design": ("시스템", "아키텍처", "분산", "scale", "infra"),
    "language_pattern": ("문법", "영어", "일본어", "중국어", "관계대명사", "who", "which", "grammar", "language"),
    "vocab_memory": ("단어", "어휘", "vocab", "암기어"),
    "reading_argument": ("독해", "논증", "주장", "근거", "reading"),
    "history_timeline": ("역사", "시대", "전쟁", "왕조", "history"),
    "law_policy": ("법", "정책", "규정", "조항", "계약"),
    "business_strategy": ("경영", "마케팅", "창업", "사업", "비즈니스"),
    "creative_critique": ("예술", "음악", "미술", "디자인", "작품"),
    "writing_structure": ("글쓰기", "에세이", "보고서", "작문", "논술"),
    "data_analysis": ("데이터", "통계", "그래프", "분석", "확률"),
    "math_reasoning": ("수학", "수식", "미적분", "기하", "대수"),
    "lab_protocol": ("실험", "프로토콜", "측정", "오차"),
    "exam_focus": ("시험", "기출", "수능", "자격증", "평가"),
    "visual_storyboard": ("스토리보드", "장면", "흐름 그림", "시각 스토리"),
    "infographic_summary": ("인포그래픽", "요약 이미지", "핵심 수치", "한 화면"),
    "code_visual_walkthrough": ("코드 시각", "코드 추적", "실행 흐름", "토큰 색상"),
    "reference_navigation": ("참고도서", "페이지", "교재", "다시 읽", "문제 풀"),
    "exam_visual_drill": ("시각 드릴", "함정 선지", "오답 제거", "판별표"),
    "memory_drill": ("암기", "외우", "회상", "flashcard"),
}


__all__ = [
    "SlideFrame",
    "StudyTemplate",
    "frame_contract",
    "get_template",
    "select_template",
    "select_template_decision",
    "study_quality_contract",
    "template_contract",
    "template_keys",
    "template_options",
    "visual_contract",
    "visual_options",
    "visual_spec",
]
