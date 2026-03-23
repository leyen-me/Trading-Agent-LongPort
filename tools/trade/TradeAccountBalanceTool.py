from typing import Any, Dict

from config import Config
from utils.longport_trade_utils import pack_account_balance

from .LongPortTradeTool import LongPortTradeTool


class TradeAccountBalanceTool(LongPortTradeTool):
    name = "trade_account_balance"
    description = (
        "Account balance summary: net_assets, available (cash in chosen currency), buy_power. "
        "Optional currency (e.g. USD, HKD) sets LongPort account_balance(currency=...) so all "
        "figures are in that currency; if omitted, uses DEFAULT_ACCOUNT_BALANCE_CURRENCY (env, default USD) "
        "so net_assets/available/buy_power stay in one consistent currency."
    )
    parameters = {
        "type": "object",
        "properties": {
            "currency": {
                "type": "string",
                "description": "筛选币种，可选，如 USD、HKD",
            },
        },
        "required": [],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            cur = parameters.get("currency")
            if cur not in (None, ""):
                currency = str(cur).strip().upper()
            else:
                currency = Config.DEFAULT_ACCOUNT_BALANCE_CURRENCY
            rows = self.get_trade_context().account_balance(currency=currency)
            return self.success(
                [
                    pack_account_balance(b, available_currency=currency)
                    for b in rows
                ]
            )
        except Exception as exc:
            return self.fail(str(exc))
