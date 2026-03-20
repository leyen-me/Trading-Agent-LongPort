from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import pack_static_info, validate_symbols


class QuoteStaticInfoTool(LongPortQuoteTool):
    name = "quote_static_info"
    description = "获取标的基础信息"
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
            result = self.get_quote_context().static_info(symbols)
            return self.success(pack_static_info(result))
        except Exception as exc:
            return self.fail(str(exc))
