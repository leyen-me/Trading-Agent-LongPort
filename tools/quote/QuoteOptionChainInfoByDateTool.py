from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import pack_option_chain_info_by_date, validate_expiry_date, validate_symbol


class QuoteOptionChainInfoByDateTool(LongPortQuoteTool):
    name = "quote_option_chain_info_by_date"
    description = "获取指定到期日下期权链的各行权价及 CALL/PUT 标的代码"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，ticker.region 格式，例如 AAPL.US",
            },
            "expiry_date": {
                "type": "string",
                "description": "期权到期日，例如 2023-01-20 或 20230120",
            },
        },
        "required": ["symbol", "expiry_date"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            expiry = validate_expiry_date(parameters.get("expiry_date"))
            rows = self.get_quote_context().option_chain_info_by_date(symbol, expiry)
            return self.success(pack_option_chain_info_by_date(rows))
        except Exception as exc:
            return self.fail(str(exc))
