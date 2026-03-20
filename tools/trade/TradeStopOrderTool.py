from typing import Any, Dict

from longport.openapi import OrderType

from utils.longport_trade_utils import (
    parse_optional_date,
    parse_optional_decimal,
    parse_order_side,
    parse_outside_rth,
    parse_required_decimal,
    parse_time_in_force,
    validate_symbol,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeStopOrderTool(LongPortTradeTool):
    name = "trade_stop_order"
    description = (
        "止盈/止损等到价单：使用触价限价 LIT 或触价市价 MIT 提交条件单（底层为 trade_submit_order 同一接口）。"
        "示例：持仓止损卖出可设 side=Sell、order_type=LIT、trigger_price=触发价、submitted_price=触发后限价。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "标的代码"},
            "order_type": {
                "type": "string",
                "description": "LIT（触价限价）或 MIT（触价市价）",
            },
            "side": {"type": "string", "description": "Buy 或 Sell"},
            "submitted_quantity": {"type": "string", "description": "委托数量"},
            "time_in_force": {"type": "string", "description": "Day、GTC、GTD；止损/止盈常用 GTC"},
            "trigger_price": {"type": "string", "description": "触发价格（必填）"},
            "submitted_price": {
                "type": "string",
                "description": "LIT 时必填：触发后以该限价委托；MIT 不要填",
            },
            "expire_date": {"type": "string", "description": "GTD 时必填到期日 YYYY-MM-DD"},
            "outside_rth": {"type": "string", "description": "美股：RTH_ONLY、ANY_TIME、OVERNIGHT"},
            "remark": {"type": "string", "description": "备注"},
        },
        "required": [
            "symbol",
            "order_type",
            "side",
            "submitted_quantity",
            "time_in_force",
            "trigger_price",
        ],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            raw_ot = str(parameters.get("order_type", "")).strip().upper()
            if raw_ot == "LIT":
                ot = OrderType.LIT
            elif raw_ot == "MIT":
                ot = OrderType.MIT
            else:
                raise ValueError("order_type 仅支持 LIT 或 MIT")

            symbol = validate_symbol(parameters.get("symbol"))
            side = parse_order_side(parameters.get("side"))
            qty = parse_required_decimal(
                parameters.get("submitted_quantity"), name="submitted_quantity"
            )
            tif = parse_time_in_force(parameters.get("time_in_force"))
            trigger_price = parse_required_decimal(
                parameters.get("trigger_price"), name="trigger_price"
            )
            submitted_price = parse_optional_decimal(parameters.get("submitted_price"))
            if ot is OrderType.LIT and submitted_price is None:
                raise ValueError("LIT 订单必须提供 submitted_price（触发后的限价）")
            if ot is OrderType.MIT and submitted_price is not None:
                raise ValueError("MIT 订单不应提供 submitted_price")

            expire_date = parse_optional_date(parameters.get("expire_date"))
            outside_rth = parse_outside_rth(parameters.get("outside_rth"))
            remark = parameters.get("remark")
            remark_s = str(remark).strip() if remark not in (None, "") else None

            resp = self.get_trade_context().submit_order(
                symbol,
                ot,
                side,
                qty,
                tif,
                submitted_price=submitted_price,
                trigger_price=trigger_price,
                expire_date=expire_date,
                outside_rth=outside_rth,
                remark=remark_s,
            )
            return self.success({"order_id": resp.order_id})
        except Exception as exc:
            return self.fail(str(exc))
