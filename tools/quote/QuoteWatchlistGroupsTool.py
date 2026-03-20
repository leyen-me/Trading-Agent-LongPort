from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool


class QuoteWatchlistGroupsTool(LongPortQuoteTool):
    name = "quote_watchlist_groups"
    description = "获取自选股分组"
    parameters = {"type": "object", "properties": {}}

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            result = self.get_quote_context().watchlist()
            return self.success(self.serialize(result))
        except Exception as exc:
            return self.fail(str(exc))
