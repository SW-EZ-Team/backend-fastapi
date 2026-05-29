"""시험 유형 템플릿 모듈."""
from .base import ExamTemplate
from .registry import get_template, list_templates
from .catalog import (
    allocation_contract,
    exam_paper_options,
    get_template_spec,
    list_template_specs,
    template_contract,
    template_options,
)
from .paper import (
    paper_template_contract,
    paper_template_options,
    question_frame,
    select_paper_template,
)

__all__ = [
    "ExamTemplate",
    "get_template",
    "list_templates",
    "get_template_spec",
    "list_template_specs",
    "template_contract",
    "allocation_contract",
    "template_options",
    "exam_paper_options",
    "question_frame",
    "select_paper_template",
    "paper_template_contract",
    "paper_template_options",
]
