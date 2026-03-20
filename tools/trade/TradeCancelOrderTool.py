from typing import Any, Dict

from utils.longport_trade_utils import validate_order_id

from .LongPortTradeTool import LongPortTradeTool


class TradeCancelOrderTool(LongPortTradeTool):
    name = "trade_cancel_order"
    description = "撤销订单，对应 LongPort DELETE /v1/trade/order"
    parameters = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "要撤销的订单 ID"},
        },
        "required": ["order_id"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            order_id = validate_order_id(parameters.get("order_id"))
            self.get_trade_context().cancel_order(order_id)
            return self.success({})
        except Exception as exc:
            return self.fail(str(exc))
