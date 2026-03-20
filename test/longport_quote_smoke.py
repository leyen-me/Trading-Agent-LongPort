"""
LongPort 行情工具集成烟测：真实请求 API，需正确配置 LongPort 环境变量与行情权限。

- 自项目根目录: python -m test.longport_quote_smoke [--test-full]
- 或: python main.py --test [--test-full]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# 若未来烟测链路导入到 config，与 main 一致：占位避免校验失败
if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "__LONGPORT_CLI_PLACEHOLDER__")

from longport.openapi import Config as LongPortConfig, QuoteContext

from tools import BaseTool, QuoteCandlesticksTool, QuoteRealtimeTool


def _format_test_output(obj: Any, *, max_chars: Optional[int]) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if max_chars is None or len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n... （共 {len(text)} 字符，已截断；使用 python -m test.longport_quote_smoke --test-full "
        "或 python main.py --test --test-full 查看完整输出）"
    )


def run_integration_tests(*, test_full: bool = False) -> int:
    max_chars = None if test_full else 16000
    print("LongPort 行情工具烟测\n")
    quote_ctx = QuoteContext(LongPortConfig.from_env())
    provider = lambda: quote_ctx
    scenarios: List[tuple[str, BaseTool, Dict[str, Any]]] = [
        (
            "quote_realtime",
            QuoteRealtimeTool(provider),
            {"symbols": ["QQQ.US"]},
        ),
        (
            "quote_candlesticks",
            QuoteCandlesticksTool(provider),
            {"symbol": "TSLA.US", "period": "Day", "count": 5},
        ),
    ]

    failed = 0
    for name, tool, params in scenarios:
        print("=" * 72)
        print(f"工具名: {name}")
        print(f"参数:   {json.dumps(params, ensure_ascii=False)}")
        try:
            raw = tool.run(params)
            payload = json.loads(raw)
            if payload.get("success"):
                print("状态:   [通过]")
                print("结果（工具返回 JSON，已按 success/data/error 结构解析）:")
                print(_format_test_output(payload, max_chars=max_chars))
            else:
                print("状态:   [失败]")
                print("结果:")
                print(_format_test_output(payload, max_chars=max_chars))
                failed += 1
        except Exception as exc:
            print(f"状态:   [失败] 解析或调用异常: {exc}")
            failed += 1
        print()

    if failed:
        print(f"共 {failed} 项失败")
        return 1
    print("全部通过")
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LongPort 行情工具集成烟测")
    p.add_argument(
        "--test-full",
        action="store_true",
        help="结果 JSON 不截断（分时等数据可能很长）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run_integration_tests(test_full=args.test_full))
