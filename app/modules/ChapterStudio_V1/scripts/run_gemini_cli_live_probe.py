from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_connectors.gemini_cli_live_probe import run_gemini_cli_live_probe  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="ChapterStudio Gemini CLI live probe")
    parser.add_argument(
        "--prompt",
        default="Rust 언어 학습용 강의 생성 파이프라인 연결 상태를 한 문단으로 점검해줘.",
    )
    args = parser.parse_args()
    result = asyncio.run(run_gemini_cli_live_probe(args.prompt))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
