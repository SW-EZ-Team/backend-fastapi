"""템플릿 레지스트리 - template_id로 인스턴스를 반환한다."""
from __future__ import annotations

from app.modules.ExamForge_V1.common.errors import TemplateNotFoundError
from .base import ExamTemplate

# 한국어 템플릿
from .korean.multiple_choice_4 import KoreanMC4Template
from .korean.multiple_choice_5 import KoreanMC5Template
from .korean.short_answer import KoreanShortAnswerTemplate
from .korean.descriptive import KoreanDescriptiveTemplate
from .korean.essay import KoreanEssayTemplate
from .korean.true_false import KoreanTrueFalseTemplate
from .korean.fill_blank import KoreanFillBlankTemplate
from .korean.ordering import KoreanOrderingTemplate
from .korean.matching import KoreanMatchingTemplate

# US 템플릿
from .us.multiple_choice_4 import USMC4Template
from .us.multiple_choice_5 import USMC5Template
from .us.true_false import USTrueFalseTemplate
from .us.short_answer import USShortAnswerTemplate
from .us.essay import USEssayTemplate
from .us.fill_blank import USFillBlankTemplate
from .us.matching import USMatchingTemplate
from .us.ordering import USOrderingTemplate

# 전문자격 템플릿
from .professional.engineer_written import EngineerWrittenTemplate
from .professional.engineer_practical import EngineerPracticalTemplate
from .professional.certification_base import CertificationBaseTemplate

_REGISTRY: dict[str, ExamTemplate] = {}


def _register(template: ExamTemplate) -> None:
    """템플릿을 레지스트리에 등록한다."""
    _REGISTRY[template.template_id] = template


# 등록 실행
_register(KoreanMC4Template())
_register(KoreanMC5Template())
_register(KoreanShortAnswerTemplate())
_register(KoreanDescriptiveTemplate())
_register(KoreanEssayTemplate())
_register(KoreanTrueFalseTemplate())
_register(KoreanFillBlankTemplate())
_register(KoreanOrderingTemplate())
_register(KoreanMatchingTemplate())
_register(USMC4Template())
_register(USMC5Template())
_register(USTrueFalseTemplate())
_register(USShortAnswerTemplate())
_register(USEssayTemplate())
_register(USFillBlankTemplate())
_register(USMatchingTemplate())
_register(USOrderingTemplate())
_register(EngineerWrittenTemplate())
_register(EngineerPracticalTemplate())
_register(CertificationBaseTemplate())


def get_template(template_id: str) -> ExamTemplate:
    """template_id로 템플릿 인스턴스를 반환한다."""
    tmpl = _REGISTRY.get(template_id)
    if tmpl is None:
        raise TemplateNotFoundError(
            f"'{template_id}' 템플릿이 등록되지 않았다."
        )
    return tmpl


def list_templates(
    locale: str | None = None,
    category: str | None = None,
) -> list[ExamTemplate]:
    """조건에 맞는 템플릿 목록을 반환한다."""
    results: list[ExamTemplate] = []
    for tmpl in _REGISTRY.values():
        if locale and tmpl.locale != locale:
            continue
        if category and tmpl.category != category:
            continue
        results.append(tmpl)
    return results
