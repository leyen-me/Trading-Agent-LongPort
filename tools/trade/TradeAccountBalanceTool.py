from typing import Any, Dict

from utils.longport_trade_utils import pack_account_balance

from .LongPortTradeTool import LongPortTradeTool


class TradeAccountBalanceTool(LongPortTradeTool):
    name = "trade_account_balance"
    description = "获取账户资金信息，对应 LongPort 资产接口 account"
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
            return self.success([pack_account_balance(b) for b in rows])
        except Exception as exc:
            return self.fail(str(exc))
