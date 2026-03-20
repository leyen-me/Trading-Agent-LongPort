from typing import Any, Dict

from utils.longport_trade_utils import pack_account_balance

from .LongPortTradeTool import LongPortTradeTool


class TradeAccountBalanceTool(LongPortTradeTool):
    name = "trade_account_balance"
    description = (
        "Account balance summary: net_assets, available (cash in chosen currency), buy_power. "
        "Optional currency (e.g. USD, HKD) filters the API response and selects which cash_infos "
        "row is used for available; omit to use the account's primary currency."
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
            currency = str(cur).strip() if cur not in (None, "") else None
            rows = self.get_trade_context().account_balance(currency=currency)
            return self.success(
                [
                    pack_account_balance(b, available_currency=currency)
                    for b in rows
                ]
            )
        except Exception as exc:
            return self.fail(str(exc))
