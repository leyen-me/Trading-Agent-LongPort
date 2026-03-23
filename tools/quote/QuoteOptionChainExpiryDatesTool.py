from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import pack_option_expiry_dates, validate_symbol


class QuoteOptionChainExpiryDatesTool(LongPortQuoteTool):
    name = "quote_option_chain_expiry_dates"
    description = "获取标的的期权链到期日列表"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，ticker.region 格式，例如 AAPL.US、700.HK",
            }
        },
        "required": ["symbol"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            rows = self.get_quote_context().option_chain_expiry_date_list(symbol)
            return self.success(pack_option_expiry_dates(rows))
        except Exception as exc:
            return self.fail(str(exc))
