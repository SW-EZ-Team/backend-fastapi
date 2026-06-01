from __future__ import annotations

from pathlib import Path

from app.modules.ChapterStudio_V1.deploy.modal_kanana_app import _max_tokens_for_text


def test_modal_kanana_app_declares_awq_vllm_args() -> None:
    source = _source()

    assert 'APP_NAME = os.environ.get("KANANA_MODAL_APP_NAME", "kanana2-typofix")' in source
    assert "NotoriousH2/kanana-2-30b-a3b-instruct-2601-awq-w4a16" in source
    assert '"--quantization",' in source
    assert '"compressed-tensors",' in source
    assert '"--trust-remote-code",' in source
    assert '"--max-model-len",' in source
    assert '"--gpu-memory-utilization",' in source
    assert 'gpu="B200:1"' in source


def test_modal_kanana_max_tokens_keeps_reasonable_bounds() -> None:
    assert _max_tokens_for_text("짧은 문장") == len("짧은 문장") + 512
    assert _max_tokens_for_text("가" * 5000) == 4096


def _source() -> str:
    return Path("app/modules/ChapterStudio_V1/deploy/modal_kanana_app.py").read_text(encoding="utf-8")
