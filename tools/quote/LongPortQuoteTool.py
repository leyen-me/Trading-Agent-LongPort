from typing import Callable, Optional

from longport.openapi import QuoteContext

from ..BaseTool import BaseTool


class LongPortQuoteTool(BaseTool):
    description = "LongPort 行情工具"

    def __init__(self, quote_context_provider: Callable[[], Optional[QuoteContext]]):
        self.quote_context_provider = quote_context_provider

    def get_quote_context(self) -> QuoteContext:
        ctx = self.quote_context_provider() if callable(self.quote_context_provider) else None
        if ctx is None:
            raise RuntimeError("quote_ctx 尚未初始化，请先执行 init_longport()")
        return ctx
