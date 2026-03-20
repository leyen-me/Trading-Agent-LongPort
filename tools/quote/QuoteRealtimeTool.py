from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import validate_symbols


class QuoteRealtimeTool(LongPortQuoteTool):
    name = "quote_realtime"
    description = "获取标的实时行情"
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标的代码列表，例如 ['700.HK', 'AAPL.US']",
            }
        },
        "required": ["symbols"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbols = validate_symbols(parameters.get("symbols"))
            result = self.get_quote_context().quote(symbols)
            return self.success(self.serialize(result))
        except Exception as exc:
            return self.fail(str(exc))
