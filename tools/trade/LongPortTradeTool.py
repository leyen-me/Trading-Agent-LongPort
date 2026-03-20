from typing import Callable, Optional

from longport.openapi import TradeContext

from ..BaseTool import BaseTool


class LongPortTradeTool(BaseTool):
    description = "LongPort 交易工具"

    def __init__(self, trade_context_provider: Callable[[], Optional[TradeContext]]):
        self.trade_context_provider = trade_context_provider

    def get_trade_context(self) -> TradeContext:
        ctx = self.trade_context_provider() if callable(self.trade_context_provider) else None
        if ctx is None:
            raise RuntimeError("trade_ctx 尚未初始化，请先执行 init_longport()")
        return ctx
