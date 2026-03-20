from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import (
    pack_candlesticks,
    parse_adjust_type,
    parse_date,
    parse_datetime,
    parse_period,
    parse_trade_session,
    validate_count,
    validate_symbol,
)


class QuoteHistoryCandlesticksTool(LongPortQuoteTool):
    name = "quote_history_candlesticks"
    description = "获取标的历史 K 线"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "标的代码，例如 700.HK"},
            "period": {
                "type": "string",
                "description": "K 线周期，例如 Day、Week、Month、Min_1、Min_5、Min_15",
            },
            "adjust_type": {
                "type": "string",
                "description": "复权类型，可选 NoAdjust、ForwardAdjust，默认 NoAdjust",
            },
            "query_mode": {
                "type": "string",
                "description": "查询模式，可选 offset、date",
            },
            "forward": {
                "type": "boolean",
                "description": "offset 模式下是否向最新数据方向查询，默认 false",
            },
            "count": {
                "type": "integer",
                "description": "offset 模式下返回数量，范围 1-1000，默认 10",
            },
            "anchor_datetime": {
                "type": "string",
                "description": "offset 模式锚点时间，支持 YYYY-MM-DD、YYYYMMDD、YYYY-MM-DD HH:MM",
            },
            "start_date": {
                "type": "string",
                "description": "date 模式开始日期，支持 YYYY-MM-DD 或 YYYYMMDD",
            },
            "end_date": {
                "type": "string",
                "description": "date 模式结束日期，支持 YYYY-MM-DD 或 YYYYMMDD",
            },
            "trade_session": {
                "type": "string",
                "description": "可选值：Intraday、All",
            },
        },
        "required": ["symbol", "period", "query_mode"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            period = parse_period(parameters.get("period"))
            adjust_type = parse_adjust_type(parameters.get("adjust_type", "NoAdjust"))
            query_mode = str(parameters.get("query_mode", "")).strip().lower()
            trade_session = parse_trade_session(parameters.get("trade_session"))
            ctx = self.get_quote_context()

            if query_mode == "offset":
                forward = bool(parameters.get("forward", False))
                count = validate_count(parameters.get("count", 10))
                anchor_time = parse_datetime(parameters.get("anchor_datetime"))
                if trade_session is None:
                    rows = ctx.history_candlesticks_by_offset(
                        symbol,
                        period,
                        adjust_type,
                        forward,
                        count,
                        anchor_time,
                    )
                else:
                    rows = ctx.history_candlesticks_by_offset(
                        symbol,
                        period,
                        adjust_type,
                        forward,
                        count,
                        anchor_time,
                        trade_session,
                    )
                return self.success(pack_candlesticks(symbol, rows))

            if query_mode == "date":
                start_date = parse_date(parameters.get("start_date"))
                end_date = parse_date(parameters.get("end_date"))
                if trade_session is None:
                    rows = ctx.history_candlesticks_by_date(
                        symbol,
                        period,
                        adjust_type,
                        start_date,
                        end_date,
                    )
                else:
                    rows = ctx.history_candlesticks_by_date(
                        symbol,
                        period,
                        adjust_type,
                        start_date,
                        end_date,
                        trade_session,
                    )
                return self.success(pack_candlesticks(symbol, rows))

            raise ValueError("query_mode 不合法，可选值为 offset、date")
        except Exception as exc:
            return self.fail(str(exc))
