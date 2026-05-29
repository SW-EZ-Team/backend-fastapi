"""ExamForge LangGraph 파이프라인."""


def get_compiled_graph():
    """지연 임포트로 AI 커넥터 초기화를 런타임까지 미룬다."""
    from .graph import get_compiled_graph as _get
    return _get()


__all__ = ["get_compiled_graph"]
