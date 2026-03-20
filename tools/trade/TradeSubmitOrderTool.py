from typing import Any, Dict

from utils.longport_trade_utils import (
    parse_optional_date,
    parse_optional_decimal,
    parse_order_side,
    parse_order_type,
    parse_outside_rth,
    parse_required_decimal,
    parse_time_in_force,
    scalar_to_json,
    validate_symbol,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeSubmitOrderTool(LongPortTradeTool):
    name = "trade_submit_order"
    description = "委托下单（限价、市价、条件单、跟踪止损等），对应 LongPort POST /v1/trade/order"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "标的代码"},
            "order_type": {"type": "string", "description": "LO、MO、LIT、MIT、TSLPPCT 等"},
            "side": {"type": "string", "description": "Buy 或 Sell"},
            "submitted_quantity": {"type": "string", "description": "委托数量"},
            "time_in_force": {"type": "string", "description": "Day、GTC、GTD"},
            "submitted_price": {"type": "string", "description": "委托价；限价/增强限价等必填"},
            "trigger_price": {"type": "string", "description": "LIT/MIT 触发价"},
            "limit_offset": {"type": "string", "description": "TSLPAMT/TSLPPCT 指定价差"},
            "trailing_amount": {"type": "string", "description": "TSLPAMT 跟踪金额"},
            "trailing_percent": {"type": "string", "description": "TSLPPCT 跟踪涨跌幅（百分比数值）"},
            "expire_date": {"type": "string", "description": "GTD 或长期单到期日 YYYY-MM-DD"},
            "outside_rth": {
                "type": "string",
                "description": "美股盘前盘后：RTH_ONLY、ANY_TIME、OVERNIGHT",
            },
            "remark": {"type": "string", "description": "备注，最多 64 字符"},
        },
        "required": ["symbol", "order_type", "side", "submitted_quantity", "time_in_force"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            order_type = parse_order_type(parameters.get("order_type"))
            side = parse_order_side(parameters.get("side"))
            qty = parse_required_decimal(
                parameters.get("submitted_quantity"), name="submitted_quantity"
            )
            tif = parse_time_in_force(parameters.get("time_in_force"))
            submitted_price = parse_optional_decimal(parameters.get("submitted_price"))
            trigger_price = parse_optional_decimal(parameters.get("trigger_price"))
            limit_offset = parse_optional_decimal(parameters.get("limit_offset"))
            trailing_amount = parse_optional_decimal(parameters.get("trailing_amount"))
            trailing_percent = parse_optional_decimal(parameters.get("trailing_percent"))
            expire_date = parse_optional_date(parameters.get("expire_date"))
            outside_rth = parse_outside_rth(parameters.get("outside_rth"))
            remark = parameters.get("remark")
            remark_s = str(remark).strip() if remark not in (None, "") else None

            ctx = self.get_trade_context()
            # 市价类常见不需要 submitted_price；限价类由券商侧校验
            resp = ctx.submit_order(
                symbol,
                order_type,
                side,
                qty,
                tif,
                submitted_price=submitted_price,
                trigger_price=trigger_price,
                limit_offset=limit_offset,
                trailing_amount=trailing_amount,
                trailing_percent=trailing_percent,
                expire_date=expire_date,
                outside_rth=outside_rth,
                remark=remark_s,
            )
            return self.success({"order_id": resp.order_id})
        except Exception as exc:
            return self.fail(str(exc))
