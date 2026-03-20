from typing import Any, Dict

from utils.longport_trade_utils import pack_order_detail, validate_order_id

from .LongPortTradeTool import LongPortTradeTool


class TradeOrderDetailTool(LongPortTradeTool):
    name = "trade_order_detail"
    description = "查询订单详情（含历史明细与费用），对应 LongPort GET /v1/trade/order"
    parameters = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "订单 ID"},
        },
        "required": ["order_id"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            order_id = validate_order_id(parameters.get("order_id"))
            detail = self.get_trade_context().order_detail(order_id=order_id)
            return self.success(pack_order_detail(detail))
        except Exception as exc:
            return self.fail(str(exc))
