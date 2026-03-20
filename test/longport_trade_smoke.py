"""
LongPort 交易工具集成烟测：真实请求交易 API，需正确配置 LongPort 环境变量与交易权限。

覆盖全部 trade 工具：
- 查询类：要求 success=true。
- trade_order_detail：若当日有订单则用真实 order_id；否则跳过（不计失败）。
- 写入类（下单/改单/撤单/触价单）：使用无效标的或无效订单号等参数，预期接口拒绝，
  烟测校验「返回结构化 JSON 且 success=false」，不依赖真实成交、不改账户。

环境变量（可选）：
- TRADE_SMOKE_SYMBOL：预估可买烟测用标的，默认 QQQ.US

- 自项目根目录: python -m test.longport_trade_smoke [--test-full]
- 或: python main.py --test-trade [--test-full]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "__LONGPORT_CLI_PLACEHOLDER__")

from longport.openapi import Config as LongPortConfig, TradeContext

from tools import (
    BaseTool,
    TradeAccountBalanceTool,
    TradeCancelOrderTool,
    TradeEstimateBuyLimitTool,
    TradeHistoryOrdersTool,
    TradeOrderDetailTool,
    TradeReplaceOrderTool,
    TradeStockPositionsTool,
    TradeStopOrderTool,
    TradeSubmitOrderTool,
    TradeTodayOrdersTool,
)

# 写入类烟测：无效标的，避免误挂单；若券商仍接受（极小概率），请换更离谱代码。
_ADVERSARIAL_SYMBOL = "ZZZZZZ.INVALID"


def _format_test_output(obj: Any, *, max_chars: Optional[int]) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if max_chars is None or len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n... （共 {len(text)} 字符，已截断；使用 python -m test.longport_trade_smoke --test-full "
        "或 python main.py --test-trade --test-full 查看完整输出）"
    )


def _history_range_params() -> Dict[str, Any]:
    end = datetime.now()
    start = end - timedelta(days=14)
    return {
        "start_at": start.strftime("%Y-%m-%d"),
        "end_at": end.strftime("%Y-%m-%d"),
    }


def _estimate_params() -> Dict[str, Any]:
    sym = os.getenv("TRADE_SMOKE_SYMBOL", "QQQ.US").strip() or "QQQ.US"
    price = os.getenv("TRADE_SMOKE_ESTIMATE_PRICE", "400").strip() or "400"
    return {
        "symbol": sym,
        "order_type": "LO",
        "side": "Buy",
        "price": price,
    }


Scenario = Tuple[str, BaseTool, Dict[str, Any], str]


def run_integration_tests(*, test_full: bool = False) -> int:
    max_chars = None if test_full else 16000
    print("LongPort 交易工具烟测（全工具）\n")
    trade_ctx = TradeContext(LongPortConfig.from_env())
    provider: Callable[[], TradeContext] = lambda: trade_ctx

    strict: List[Scenario] = [
        (
            "trade_account_balance",
            TradeAccountBalanceTool(provider),
            {},
            "expect_success",
        ),
        (
            "trade_stock_positions",
            TradeStockPositionsTool(provider),
            {},
            "expect_success",
        ),
        (
            "trade_today_orders",
            TradeTodayOrdersTool(provider),
            {},
            "expect_success",
        ),
        (
            "trade_history_orders",
            TradeHistoryOrdersTool(provider),
            _history_range_params(),
            "expect_success",
        ),
        (
            "trade_estimate_buy_limit",
            TradeEstimateBuyLimitTool(provider),
            _estimate_params(),
            "expect_success",
        ),
    ]

    adversarial: List[Scenario] = [
        (
            "trade_cancel_order",
            TradeCancelOrderTool(provider),
            {"order_id": "1"},
            "expect_failure",
        ),
        (
            "trade_replace_order",
            TradeReplaceOrderTool(provider),
            {"order_id": "1", "quantity": "1"},
            "expect_failure",
        ),
        (
            "trade_submit_order",
            TradeSubmitOrderTool(provider),
            {
                "symbol": _ADVERSARIAL_SYMBOL,
                "order_type": "LO",
                "side": "Buy",
                "submitted_quantity": "1",
                "time_in_force": "Day",
                "submitted_price": "1",
            },
            "expect_failure",
        ),
        (
            "trade_stop_order",
            TradeStopOrderTool(provider),
            {
                "symbol": _ADVERSARIAL_SYMBOL,
                "order_type": "LIT",
                "side": "Sell",
                "submitted_quantity": "1",
                "time_in_force": "GTC",
                "trigger_price": "100",
                "submitted_price": "99",
            },
            "expect_failure",
        ),
    ]

    failed = 0

    def run_one(name: str, tool: BaseTool, params: Dict[str, Any], mode: str) -> None:
        nonlocal failed
        print("=" * 72)
        print(f"工具名: {name}")
        print(f"模式:   {mode}")
        print(f"参数:   {json.dumps(params, ensure_ascii=False)}")
        try:
            raw = tool.run(params)
            payload = json.loads(raw)
            ok = bool(payload.get("success"))

            if mode == "expect_success":
                if ok:
                    print("状态:   [通过]")
                    print("结果:")
                    print(_format_test_output(payload, max_chars=max_chars))
                else:
                    print("状态:   [失败] 预期成功但失败")
                    print("结果:")
                    print(_format_test_output(payload, max_chars=max_chars))
                    failed += 1
            elif mode == "expect_failure":
                if not ok:
                    print("状态:   [通过]（预期失败，接口/参数被拒）")
                    print("结果:")
                    print(_format_test_output(payload, max_chars=max_chars))
                else:
                    print("状态:   [失败] 预期失败却成功（请检查参数是否误成交）")
                    print("结果:")
                    print(_format_test_output(payload, max_chars=max_chars))
                    failed += 1
            else:
                raise RuntimeError(f"unknown mode: {mode}")
        except Exception as exc:
            print(f"状态:   [失败] 解析或调用异常: {exc}")
            failed += 1
        print()

    for name, tool, params, mode in strict:
        run_one(name, tool, params, mode)

    # 从当日订单取一条做订单详情（真实 order_id）
    today_tool = TradeTodayOrdersTool(provider)
    raw_today = today_tool.run({})
    try:
        today_payload = json.loads(raw_today)
    except json.JSONDecodeError:
        today_payload = {}
    order_id: Optional[str] = None
    if today_payload.get("success"):
        orders = today_payload.get("data") or {}
        if isinstance(orders, dict):
            lst = orders.get("orders") or []
            if lst and isinstance(lst[0], dict):
                order_id = lst[0].get("order_id")

    if order_id:
        run_one(
            "trade_order_detail",
            TradeOrderDetailTool(provider),
            {"order_id": order_id},
            "expect_success",
        )
    else:
        print("=" * 72)
        print("工具名: trade_order_detail")
        print("模式:   skip（当日无订单，无法构造合法 order_id）")
        print()

    for name, tool, params, mode in adversarial:
        run_one(name, tool, params, mode)

    if failed:
        print(f"共 {failed} 项失败")
        return 1
    print("全部通过")
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LongPort 交易工具集成烟测")
    p.add_argument(
        "--test-full",
        action="store_true",
        help="结果 JSON 不截断（订单列表可能较长）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run_integration_tests(test_full=args.test_full))
