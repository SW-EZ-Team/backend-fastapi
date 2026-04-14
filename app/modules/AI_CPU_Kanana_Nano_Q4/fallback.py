"""Kanana 실패 시 안전한 Jinja2 템플릿 캡션."""
from jinja2 import Template

# 이름/약점/마감 여부에 따라 분기하는 Jinja2 템플릿
# 이름 생략 허용(v3 정책) — 어색하면 자동으로 빠짐
_TMPL = Template(
    "{% if name %}{{ name }}아, {% endif %}"
    "오늘 {{ assignment }} 같이 해보자! "
    "{% if weakness %}{{ weakness }} 부분만 한 번만 더 짚어주면 돼. {% endif %}"
    "{% if deadline %}{{ deadline }}까지야, 할 수 있어!{% else %}할 수 있어!{% endif %}"
)


def render_jinja_caption(
    *, student_name, assignment_name, weakness=None, deadline=None
) -> str:
    """Jinja2 템플릿으로 안전한 폴백 캡션을 생성한다.

    항상 100자 이내를 보장하며, 초과 시 99자에서 말줄임표로 자른다.
    """
    text = _TMPL.render(
        name=student_name,
        assignment=assignment_name,
        weakness=weakness,
        deadline=deadline,
    ).strip()
    # 100자 초과 시 말줄임표 처리 (최대 길이 보장)
    if len(text) > 100:
        text = text[:99] + "…"
    return text
