from typing import Any, Dict

from utils.longport_trade_utils import (
    parse_optional_decimal,
    parse_order_side,
    parse_order_type,
    scalar_to_json,
    validate_symbol,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeEstimateBuyLimitTool(LongPortTradeTool):
    name = "trade_estimate_buy_limit"
    description = "预估最大可买/可卖数量（现金与融资），对应 LongPort /v1/trade/estimate/buy_limit"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "标的代码，如 700.HK、AAPL.US"},
            "order_type": {"type": "string", "description": "订单类型，如 LO、MO、LIT"},
            "side": {"type": "string", "description": "Buy 或 Sell（卖空预估仅部分市场支持）"},
            "price": {"type": "string", "description": "预估价格，可选"},
            "currency": {"type": "string", "description": "结算货币，可选"},
            "order_id": {"type": "string", "description": "改单场景下的订单 ID，可选"},
            "fractional_shares": {
                "type": "boolean",
                "description": "是否按碎股预估，可选，默认 false",
            },
        },
        "required": ["symbol", "order_type", "side"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            order_type = parse_order_type(parameters.get("order_type"))
            side = parse_order_side(parameters.get("side"))
            price = parse_optional_decimal(parameters.get("price"))
            currency = (
                str(parameters["currency"]).strip()
                if parameters.get("currency") not in (None, "")
                else None
            )
            order_id = (
                str(parameters["order_id"]).strip()
                if parameters.get("order_id") not in (None, "")
                else None
            )
            frac = parameters.get("fractional_shares")
            fractional = bool(frac) if frac is not None else False
            ctx = self.get_trade_context()
            resp = ctx.estimate_max_purchase_quantity(
                symbol=symbol,
                order_type=order_type,
                side=side,
                price=price,
                currency=currency,
                order_id=order_id,
                fractional_shares=fractional,
            )
            data = {
                "cash_max_qty": scalar_to_json(resp.cash_max_qty),
                "margin_max_qty": scalar_to_json(resp.margin_max_qty),
            }
            return self.success(data)
        except Exception as exc:
            return self.fail(str(exc))
