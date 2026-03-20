from typing import Any, Dict

from utils.longport_trade_utils import (
    parse_optional_decimal,
    parse_required_decimal,
    validate_order_id,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeReplaceOrderTool(LongPortTradeTool):
    name = "trade_replace_order"
    description = "修改订单价格或数量，对应 LongPort PUT /v1/trade/order"
    parameters = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "订单 ID"},
            "quantity": {"type": "string", "description": "改单后的数量"},
            "price": {"type": "string", "description": "改单价格，限价类订单必填"},
            "trigger_price": {"type": "string", "description": "LIT/MIT 触发价"},
            "limit_offset": {"type": "string", "description": "TSLPAMT/TSLPPCT 价差"},
            "trailing_amount": {"type": "string", "description": "TSLPAMT 跟踪金额"},
            "trailing_percent": {"type": "string", "description": "TSLPPCT 跟踪百分比"},
            "remark": {"type": "string", "description": "备注，最多 64 字符"},
        },
        "required": ["order_id", "quantity"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            order_id = validate_order_id(parameters.get("order_id"))
            quantity = parse_required_decimal(parameters.get("quantity"), name="quantity")
            price = parse_optional_decimal(parameters.get("price"))
            trigger_price = parse_optional_decimal(parameters.get("trigger_price"))
            limit_offset = parse_optional_decimal(parameters.get("limit_offset"))
            trailing_amount = parse_optional_decimal(parameters.get("trailing_amount"))
            trailing_percent = parse_optional_decimal(parameters.get("trailing_percent"))
            remark = parameters.get("remark")
            remark_s = str(remark).strip() if remark not in (None, "") else None
            self.get_trade_context().replace_order(
                order_id=order_id,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                limit_offset=limit_offset,
                trailing_amount=trailing_amount,
                trailing_percent=trailing_percent,
                remark=remark_s,
            )
            return self.success({})
        except Exception as exc:
            return self.fail(str(exc))
