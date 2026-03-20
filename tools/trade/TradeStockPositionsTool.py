from typing import Any, Dict

from utils.longport_trade_utils import pack_stock_positions_response, validate_symbols_optional

from .LongPortTradeTool import LongPortTradeTool


class TradeStockPositionsTool(LongPortTradeTool):
    name = "trade_stock_positions"
    description = "获取股票持仓，对应 LongPort 资产接口 stock"
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "仅查询指定标的时传入；不传则返回全部（以接口行为为准）",
            },
        },
        "required": [],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbols = validate_symbols_optional(parameters.get("symbols"))
            resp = self.get_trade_context().stock_positions(symbols=symbols)
            return self.success(pack_stock_positions_response(resp))
        except Exception as exc:
            return self.fail(str(exc))
