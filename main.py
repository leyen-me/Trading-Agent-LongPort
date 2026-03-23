# standard library
from datetime import datetime
import json
import logging
import os
import platform
import sys
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

# 仅跑 TEST_TRADE_ACCOUNT_BALANCE 时不依赖真实 OPENAI_API_KEY（Config 在 import 时校验）
if __name__ == "__main__" and os.environ.get("TEST_TRADE_ACCOUNT_BALANCE"):
    os.environ.setdefault("OPENAI_API_KEY", "unused-for-balance-test-only")

# third party
from openai import OpenAI
from longport.openapi import PushCandlestick, TradeContext, QuoteContext, Config as LongPortConfig, TradeSessions

# self defined
from config import Config
from utils import pack_candlesticks, pack_quotes, parse_adjust_type, parse_period
from utils.longport_trade_utils import pack_orders
from tools import (
    BaseTool,
    QuoteCandlesticksTool,
    QuoteOptionChainExpiryDatesTool,
    QuoteOptionChainInfoByDateTool,
    QuoteRealtimeTool,
    TradingPhilosophyTool,
    TradeAccountBalanceTool,
    TradeCancelOrderTool,
    TradeEstimateBuyLimitTool,
    TradeHistoryOrdersTool,
    TradeOrderDetailTool,
    TradeReplaceOrderTool,
    TradeStockPositionsTool,
    TradeStopOrderTool,
    TradeSubmitOrderTool,
    TradeTodayOrdersTool,
)

_READ_ONLY_TRADE_TOOL_CLASSES = (
    TradeAccountBalanceTool,
    TradeEstimateBuyLimitTool,
    TradeHistoryOrdersTool,
    TradeOrderDetailTool,
    TradeStockPositionsTool,
    TradeTodayOrdersTool,
)
_MUTATING_TRADE_TOOL_CLASSES = (
    TradeCancelOrderTool,
    TradeReplaceOrderTool,
    TradeSubmitOrderTool,
    TradeStopOrderTool,
)


# ==== 日志配置 ====

SCRIPT_DIR = Path(__file__).resolve().parent
TRADING_PHILOSOPHY_FILE = SCRIPT_DIR / "trading_philosophy.md"
_AGENT_DIR = SCRIPT_DIR / ".agent"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_HISTORY_FILE = _AGENT_DIR / "history.json"
_LOG_FILE = _AGENT_DIR / "agent.log"

# 全局变量
trade_ctx: TradeContext = None
quote_ctx: QuoteContext = None
trading_agent = None

day_candlestick_count = 0
daily_market_context: Dict[str, Any] = {}
last_daily_reset_date: Optional[str] = None
last_daily_context_refresh_date: Optional[str] = None
_daily_init_lock = threading.Lock()
_agent_operation_lock = threading.Lock()
post_close_review_timer: Optional[threading.Timer] = None
last_candlestick_monotonic: Optional[float] = None
last_candlestick_trade_date: Optional[str] = None
last_post_close_review_trade_date: Optional[str] = None

PREMARKET_INIT_HOUR = 9
PREMARKET_INIT_MINUTE = 0
DAILY_CONTEXT_4H_COUNT = 8
POST_CLOSE_IDLE_SECONDS = 60 * 60



def _ensure_runtime_storage() -> None:
    """确保 .agent 目录及运行时文件存在。"""
    _AGENT_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.write_text('{"sessions": []}\n', encoding="utf-8")
    _LOG_FILE.touch(exist_ok=True)


_ensure_runtime_storage()

OPENAI_API_KEY = Config.OPENAI_API_KEY
OPENAI_BASE_URL = Config.OPENAI_BASE_URL
OPENAI_MODEL = Config.OPENAI_MODEL
OPENAI_ENABLE_THINKING = Config.OPENAI_ENABLE_THINKING

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=[
        # logging.StreamHandler(), // 将日志输出到控制台
        logging.FileHandler(_LOG_FILE, encoding="utf-8", mode="a"),
    ],
)
logger = logging.getLogger("Agent")


# ==== 运行时配置 ====

ENABLE_COLOR = os.getenv("NO_COLOR") is None and os.getenv("TERM") != "dumb"
ANSI_RESET = "\033[0m"
PLAN_COLOR = "\033[38;5;25m"
EXECUTE_COLOR = "\033[38;5;81m"
INFO_COLOR = "\033[38;5;244m"
REASONING_COLOR = "\033[38;5;242m"


def color_text(text: str, color: str) -> str:
    if not ENABLE_COLOR:
        return text
    return f"{color}{text}{ANSI_RESET}"


def get_display_width(text: str) -> int:
    """计算字符串在等宽终端中的显示宽度。"""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def pad_to_display_width(text: str, target_width: int) -> str:
    """按终端显示宽度右侧补空格。"""
    padding = max(target_width - get_display_width(text), 0)
    return text + (" " * padding)


def print_info_table(rows: List[List[str]]) -> None:
    """用纯文本表格打印启动信息。"""
    normalized_rows = [[str(cell) for cell in row] for row in rows]
    left_width = max(get_display_width(row[0]) for row in normalized_rows)
    right_width = max(get_display_width(row[1]) for row in normalized_rows)
    border = f"+-{'-' * left_width}-+-{'-' * right_width}-"

    print(color_text(border, PLAN_COLOR))
    for left, right in normalized_rows:
        print(
            color_text(f"| {pad_to_display_width(left, left_width)} |", PLAN_COLOR)
            + " "
            + color_text(pad_to_display_width(right, right_width), EXECUTE_COLOR)
        )
    print(color_text(border, PLAN_COLOR))


def print_console_block(title: str, lines: List[str], color: str = INFO_COLOR) -> None:
    """打印带留白和分隔线的终端信息块。"""
    normalized_lines = [str(line) for line in lines]
    title_text = f"[{title}]"
    content_width = max(
        [get_display_width(title_text), *(get_display_width(line) for line in normalized_lines)]
    )
    border = color_text("=" * content_width, color)

    print()
    print(border)
    print(color_text(title_text, color))
    for line in normalized_lines:
        print(line)
    print(border)


DEFAULT_CONTEXT_WINDOW = Config.DEFAULT_CONTEXT_WINDOW
MODEL_CONTEXT_WINDOWS = Config.MODEL_CONTEXT_WINDOWS


@dataclass
class UsageSnapshot:
    """保存一次流式响应中最新的 usage 统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    updated_at: float = field(default_factory=time.time)
    raw: Dict[str, Any] = field(default_factory=dict)


def resolve_model_context_window(model_name: str) -> Optional[int]:
    """返回模型的上下文窗口大小，支持显式配置覆盖。"""
    if Config.OPENAI_CONTEXT_WINDOW is not None:
        return Config.OPENAI_CONTEXT_WINDOW
    return MODEL_CONTEXT_WINDOWS.get(model_name.strip().lower(), DEFAULT_CONTEXT_WINDOW)


def format_percent(numerator: int, denominator: Optional[int]) -> str:
    """格式化占比文本。"""
    if denominator is None or denominator <= 0:
        return "未知"
    percent = (numerator / denominator) * 100
    return f"{percent:.1f}%"


def build_progress_bar(numerator: int, denominator: Optional[int], width: int = 20) -> str:
    """构造终端展示用进度条。"""
    if denominator is None or denominator <= 0:
        return "[????????????????????]"
    ratio = max(0.0, min(numerator / denominator, 1.0))
    filled = int(round(ratio * width))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def get_system_name() -> str:
    """返回标准化后的当前操作系统名称。"""
    system = platform.system().lower()
    if system == "darwin":
        return "macOS"
    if system == "windows":
        return "Windows"
    if system == "linux":
        return "Linux"
    return platform.system() or "Unknown"


# ==== Prompt 模板 ====


def load_trading_philosophy_text() -> str:
    """从 trading_philosophy.md 加载交易思想正文。"""
    try:
        return TRADING_PHILOSOPHY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("未找到或无法读取交易思想文件: %s", TRADING_PHILOSOPHY_FILE)
        return ""


def build_trading_agent_system_prompt() -> str:
    """组装系统提示：固定骨架 + 动态注入 trading_philosophy.md。"""
    philosophy = load_trading_philosophy_text()
    philosophy_xml = (
        escape(philosophy)
        if philosophy
        else "（未加载 trading_philosophy.md，请将该文件放在脚本同目录）"
    )
    return f"""
<system>
  <role>
    你是专注美股日内交易员。
  </role>

  <primary_goal>
    基于实时与历史数据控制风险，在可执行的前提下完成交易相关操作，并如实汇报。
  </primary_goal>

  <trading_philosophy>
{philosophy_xml}
  </trading_philosophy>

  <hard_constraints>
    <rule>你只能调用已注册工具；不要虚构行情、成交或账户状态。</rule>
    <rule>工具失败时不要假装成功；可重试、调整方案，或明确说明失败原因。</rule>
  </hard_constraints>

  <available_tools>
    <group name="更新交易思想">
      <tool>trading_philosophy</tool>
    </group>
    <group name="行情工具">
      <tool>quote_realtime</tool>
      <tool>quote_candlesticks</tool>
      <tool>quote_option_chain_expiry_dates</tool>
      <tool>quote_option_chain_info_by_date</tool>
    </group>
    <group name="交易工具">
      <tool>trade_account_balance</tool>
      <tool>trade_estimate_buy_limit</tool>
      <tool>trade_history_orders</tool>
      <tool>trade_order_detail</tool>
      <tool>trade_stock_positions</tool>
      <tool>trade_today_orders</tool>
      <tool>trade_replace_order</tool>
      <tool>trade_submit_order</tool>
      <tool>trade_cancel_order</tool>
      <tool>trade_stop_order</tool>
    </group>
  </available_tools>

  <tool_call_policy>
    <rule>需要行情或账户信息时先调用相应查询工具，再决策；多步操作在同一轮对话内顺序完成。</rule>
    <rule>未完成必要工具调用前避免冗长臆测性总结。</rule>
    <rule>盘后复盘或修订交易思想时，请使用 trading_philosophy 更新交易思想文件。</rule>
  </tool_call_policy>

  <output_contract>
    <rule>在工具结果已覆盖关键事实后，给出简洁、可核对的结论。</rule>
  </output_contract>
</system>
""".strip()


def get_now_time_text() -> str:
    """返回当前本地时间文本，用于注入运行时上下文。"""
    return time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime())


def format_timestamp(timestamp: Any) -> str:
    """将时间戳格式化为本地时间文本。"""
    if not isinstance(timestamp, (int, float)):
        return "未知"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def format_history_message_content(content: Any) -> str:
    """把消息内容格式化为适合导出的文本。"""
    if content is None or content == "":
        return "<empty>"
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2)


def assistant_message_with_reasoning(
    content: str,
    reasoning_parts: List[str],
    *,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """构造 assistant 消息：content 与 reasoning 分字段存储（仅持久化/上下文，见 messages_for_api）。"""
    msg: Dict[str, Any] = {
        "role": "assistant",
        "content": content or "",
    }
    r = "".join(reasoning_parts).strip()
    if r:
        msg["reasoning"] = r
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def messages_for_api(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI Chat Completions 不接受自定义 reasoning 字段，请求前剥掉。"""
    out: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant" and "reasoning" in m:
            out.append({k: v for k, v in m.items() if k != "reasoning"})
        else:
            out.append(m)
    return out


def build_runtime_context_xml(agent_name: str, model_name: str) -> str:
    """构造注入到 system prompt 中的运行时环境信息。"""
    lines = [
        "  <runtime_context>",
        f"    <symbol>{escape(Config.TRADE_SYMBOL)}</symbol>",
        f"    <cycle>{escape(Config.TRADE_CYCLE)}</cycle>",
    ]
    if daily_market_context:
        lines.extend(
            [
                f"    <daily_market_context>{escape(json.dumps(daily_market_context, ensure_ascii=False, separators=(',', ':')))}</daily_market_context>",
            ]
        )
    lines.append("  </runtime_context>")
    return "\n".join(lines)


def _is_after_premarket_init_time(now: datetime) -> bool:
    return (now.hour, now.minute) >= (PREMARKET_INIT_HOUR, PREMARKET_INIT_MINUTE)


def _fetch_daily_market_context() -> Dict[str, Any]:
    """查询每日低频背景信息，供 system prompt 注入。"""
    snapshot: Dict[str, Any] = {
        "symbol": Config.TRADE_SYMBOL,
        "initialized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "four_hour_period": "min_240",
        "four_hour_count": DAILY_CONTEXT_4H_COUNT,
    }

    try:
        quotes = pack_quotes(quote_ctx.quote([Config.TRADE_SYMBOL]))
        snapshot["previous_close"] = quotes[0] if quotes else {"error": "未获取到实时行情"}
    except Exception as exc:
        snapshot["previous_close"] = {"error": str(exc)}

    try:
        rows = quote_ctx.candlesticks(
            Config.TRADE_SYMBOL,
            parse_period("min_240"),
            DAILY_CONTEXT_4H_COUNT,
            parse_adjust_type("NoAdjust"),
        )
        snapshot["recent_4h_candlesticks"] = pack_candlesticks(
            Config.TRADE_SYMBOL,
            rows,
        )["candlesticks"]
    except Exception as exc:
        snapshot["recent_4h_candlesticks"] = {"error": str(exc)}

    return snapshot


def _is_daily_market_context_valid(snapshot: Dict[str, Any]) -> bool:
    """仅当昨收与 4 小时 K 线都成功获取时，才视为有效盘前上下文。"""
    previous_close = snapshot.get("previous_close")
    recent_4h_candlesticks = snapshot.get("recent_4h_candlesticks")
    if not isinstance(previous_close, dict) or previous_close.get("error"):
        return False
    if not isinstance(recent_4h_candlesticks, list) or not recent_4h_candlesticks:
        return False
    return True


def initialize_trading_day_if_needed(*, force: bool = False) -> bool:
    """每日 09:00 后执行一次日切，并在成功时刷新低频市场背景。"""
    global day_candlestick_count, daily_market_context
    global last_daily_reset_date, last_daily_context_refresh_date
    if quote_ctx is None or trading_agent is None:
        return False

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if not force and not _is_after_premarket_init_time(now):
        return False

    did_reset = False
    did_refresh_context = False
    refresh_error = False

    with _daily_init_lock:
        needs_reset = force or last_daily_reset_date != today
        needs_context_refresh = force or last_daily_context_refresh_date != today

        if not needs_reset and not needs_context_refresh:
            return False

        if needs_reset:
            day_candlestick_count = 0
            daily_market_context = {}
            last_daily_reset_date = today
            _cancel_post_close_review_timer()
            did_reset = True

        if needs_context_refresh:
            snapshot = _fetch_daily_market_context()
            if _is_daily_market_context_valid(snapshot):
                daily_market_context = snapshot
                last_daily_context_refresh_date = today
                did_refresh_context = True
            else:
                refresh_error = True
                logger.warning("盘前上下文刷新失败，稍后会继续重试: %s", snapshot)

        if did_reset:
            with _agent_operation_lock:
                trading_agent.reset_conversation()
        elif did_refresh_context:
            with _agent_operation_lock:
                trading_agent._reload_system_prompt_from_disk()

    if did_reset:
        lines = [
            f"日期: {today}",
            "已清空 agent 上下文并重置日内 K 线计数。",
        ]
        if did_refresh_context:
            lines.append(f"已加载昨收与最近 {DAILY_CONTEXT_4H_COUNT} 根 4 小时 K 线到运行时上下文。")
        elif refresh_error:
            lines.append("盘前上下文刷新失败，当前已清空旧上下文，后续会在盘中继续重试。")
        print_console_block("Daily Init", lines, color=PLAN_COLOR)
        logger.info("已完成每日日切: %s", today)
        return True

    if did_refresh_context:
        print_console_block(
            "Daily Context Refreshed",
            [
                f"日期: {today}",
                f"已补充加载昨收与最近 {DAILY_CONTEXT_4H_COUNT} 根 4 小时 K 线到运行时上下文。",
            ],
            color=PLAN_COLOR,
        )
        logger.info("已补充刷新每日盘前上下文: %s", today)
        return True

    return False


def _cancel_post_close_review_timer() -> None:
    """取消已有的收盘复盘定时器。"""
    global post_close_review_timer
    if post_close_review_timer is not None:
        post_close_review_timer.cancel()
        post_close_review_timer = None


def _build_post_close_review_prompt(trade_date_text: str) -> str:
    """构造收盘后自动复盘提示。"""
    return f"""
检测到 {trade_date_text} 交易日已经连续 {POST_CLOSE_IDLE_SECONDS // 60} 分钟未收到新的确认K线，可视为已收盘。

请执行一次简洁、事实优先的收盘复盘：
1. 判断今天更接近趋势日、区间日还是过渡日。
2. 总结 5 分钟结构演化、关键价位与 4 小时语境的关系。
3. 查询并总结今日订单、成交/撤单/拒单等执行结果。
4. 评估今天的执行是否符合 trading_philosophy。
5. 给出下一个交易日最值得关注的观察点。

只有在确有必要修订交易思想时，才调用 trading_philosophy 工具覆盖写入完整文件；否则不要改文件。
""".strip()


def _run_post_close_review_if_idle(expected_trade_date: str) -> None:
    """若指定交易日 1 小时未再收到新 K 线，则触发复盘。"""
    global post_close_review_timer, last_post_close_review_trade_date

    with _daily_init_lock:
        post_close_review_timer = None
        if last_candlestick_trade_date != expected_trade_date:
            return
        if last_post_close_review_trade_date == expected_trade_date:
            return
        last_seen_at = last_candlestick_monotonic

    if last_seen_at is None:
        return
    if time.monotonic() - last_seen_at < POST_CLOSE_IDLE_SECONDS:
        return

    with _agent_operation_lock:
        if last_post_close_review_trade_date == expected_trade_date:
            return
        print_console_block(
            "Post Close Review",
            [
                f"交易日: {expected_trade_date}",
                f"已连续 {POST_CLOSE_IDLE_SECONDS // 60} 分钟未收到新的确认K线，开始自动复盘。",
            ],
            color=PLAN_COLOR,
        )
        trading_agent.chat(_build_post_close_review_prompt(expected_trade_date))
        last_post_close_review_trade_date = expected_trade_date


def _refresh_post_close_review_timer(trade_date_text: str) -> None:
    """收到新 K 线后重置收盘复盘定时器。"""
    global post_close_review_timer, last_candlestick_monotonic, last_candlestick_trade_date

    with _daily_init_lock:
        last_candlestick_monotonic = time.monotonic()
        last_candlestick_trade_date = trade_date_text
        _cancel_post_close_review_timer()
        post_close_review_timer = threading.Timer(
            POST_CLOSE_IDLE_SECONDS,
            _run_post_close_review_if_idle,
            args=(trade_date_text,),
        )
        post_close_review_timer.daemon = True
        post_close_review_timer.start()


def with_runtime_context(
    base_prompt: str,
    *,
    agent_name: str,
    model_name: str,
) -> str:
    """把运行时上下文插入到 system XML 中，保持单一 <system> 根节点。"""
    runtime_context_xml = build_runtime_context_xml(agent_name, model_name)
    return base_prompt.replace("</system>", f"{runtime_context_xml}\n</system>", 1)


class PlanHistoryStore:
    """负责持久化交易 Agent 的上下文历史。"""

    def __init__(self, storage_path: Path = _HISTORY_FILE) -> None:
        self.storage_path = storage_path
        self._sessions: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            content = self.storage_path.read_text(encoding="utf-8").strip()
            raw = {"sessions": []} if not content else json.loads(content)
        except Exception:
            logger.exception("加载 history.json 失败")
            return

        sessions = raw.get("sessions") if isinstance(raw, dict) else None
        if not isinstance(sessions, list):
            logger.warning("history.json 格式无效，已忽略")
            return

        self._sessions = [item for item in sessions if isinstance(item, dict)]

    def clear_all(self) -> None:
        """清空所有历史会话。"""
        self._sessions.clear()
        self._save()

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sessions": self._sessions}
        temp_path = self.storage_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.storage_path)

    def _copy_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(messages, ensure_ascii=False))

    def _find_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        for session in self._sessions:
            if session.get("id") == session_id:
                return session
        return None

    def start_session(self, agent_name: str, messages: List[Dict[str, Any]]) -> str:
        now = time.time()
        session_id = str(uuid.uuid4())
        self._sessions.append(
            {
                "id": session_id,
                "agent_name": agent_name,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "message_count": len(messages),
                "messages": self._copy_messages(messages),
            }
        )
        self._save()
        return session_id

    def sync_session(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        *,
        status: Optional[str] = None,
    ) -> None:
        session = self._find_session(session_id)
        if session is None:
            raise KeyError(f"history session not found: {session_id}")

        session["messages"] = self._copy_messages(messages)
        session["message_count"] = len(messages)
        session["updated_at"] = time.time()
        if status is not None:
            session["status"] = status
        self._save()

    def archive_session(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        self.sync_session(session_id, messages, status="archived")

    def list_sessions(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(self._sessions, ensure_ascii=False))


class BaseAgent:
    """封装带工具调用能力的基础 Agent。"""
    def __init__(
        self,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        agent_name: str = "助手",
        temperature: float = 1,
        top_p: float = 0.95,
    ):
        self.model = model or OPENAI_MODEL
        self.agent_name = agent_name
        self.agent_color = INFO_COLOR
        self.temperature = temperature
        self.top_p = top_p
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=300.0,
        )
        self.tools: List[BaseTool] = []
        self.system_prompt = system_prompt or "You are a helpful assistant."
        self.base_messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]
        self.messages: List[Dict[str, Any]] = list(self.base_messages)
        self.latest_usage: Optional[UsageSnapshot] = None

    def register_tool(self, tool: BaseTool) -> None:
        self.tools.append(tool)

    def get_tools(self) -> List[Dict[str, Any]]:
        return [{"type": "function", "function": tool.to_dict()} for tool in self.tools]

    def get_context_window(self) -> Optional[int]:
        """返回当前模型的上下文窗口大小。"""
        return resolve_model_context_window(self.model)

    def get_usage_snapshot(self) -> Optional[UsageSnapshot]:
        """返回最近一次流式请求记录到的 usage。"""
        return self.latest_usage

    def get_usage_report_lines(self) -> List[str]:
        """生成 usage 报告文本。"""
        usage = self.get_usage_snapshot()
        if usage is None:
            return ["当前还没有 usage 数据，请先完成至少一次对话。"]

        context_limit = self.get_context_window()
        context_percent = format_percent(usage.prompt_tokens, context_limit)
        total_percent = format_percent(usage.total_tokens, context_limit)
        lines = [
            f"模型：{self.model}",
            f"当前上下文：{usage.prompt_tokens} tokens",
            (
                "上下文占用："
                f"{usage.prompt_tokens} / {context_limit if context_limit else '未知'} "
                f"({context_percent}) {build_progress_bar(usage.prompt_tokens, context_limit)}"
            ),
            f"本轮输出：{usage.completion_tokens} tokens",
            f"当前总计：{usage.total_tokens} tokens",
            (
                "总占用："
                f"{usage.total_tokens} / {context_limit if context_limit else '未知'} "
                f"({total_percent}) {build_progress_bar(usage.total_tokens, context_limit)}"
            ),
            f"更新时间：{format_timestamp(usage.updated_at)}",
        ]
        return lines

    def _usage_to_dict(self, usage: Any) -> Dict[str, Any]:
        """尽量把 SDK usage 对象转成普通字典。"""
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return json.loads(json.dumps(usage, ensure_ascii=False))
        for attr in ("model_dump", "dict"):
            method = getattr(usage, attr, None)
            if callable(method):
                try:
                    data = method()
                except TypeError:
                    continue
                if isinstance(data, dict):
                    return json.loads(json.dumps(data, ensure_ascii=False))
        return {
            key: value
            for key, value in vars(usage).items()
            if not key.startswith("_") and not callable(value)
        }

    def _int_from_usage(self, raw_usage: Dict[str, Any], key: str) -> int:
        """安全读取 usage 中的整数值。"""
        value = raw_usage.get(key, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def update_usage_snapshot(self, usage: Any) -> None:
        """从流式 chunk 中提取 usage，并覆盖最近一次统计。"""
        raw_usage = self._usage_to_dict(usage)
        if not raw_usage:
            return
        self.latest_usage = UsageSnapshot(
            prompt_tokens=self._int_from_usage(raw_usage, "prompt_tokens"),
            completion_tokens=self._int_from_usage(raw_usage, "completion_tokens"),
            total_tokens=self._int_from_usage(raw_usage, "total_tokens"),
            updated_at=time.time(),
            raw=raw_usage,
        )

    def execute_tool(self, name: str, args_json: str) -> str:
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            return "参数 JSON 解析失败"
        tool = next((t for t in self.tools if t.name == name), None)
        if not tool:
            return f"未找到工具：{name}"
        return tool.run(args)

    def format_tool_result(self, result: str, max_len: int = 600) -> str:
        try:
            payload = json.loads(result)
        except Exception:
            text = result.strip()
        else:
            if isinstance(payload, dict) and "success" in payload:
                if payload.get("success"):
                    text = json.dumps(
                        {"success": True, "data": payload.get("data")},
                        ensure_ascii=False,
                    )
                else:
                    text = json.dumps(
                        {"success": False, "error": payload.get("error")},
                        ensure_ascii=False,
                    )
            else:
                text = json.dumps(payload, ensure_ascii=False)

        text = text.strip()
        if not text:
            return "<empty>"
        if len(text) <= max_len:
            return text
        return text[:max_len] + "...<truncated>"

    def _coerce_stream_text(self, value: Any) -> str:
        """将 SDK 流式字段尽量规整为可直接打印的文本。"""
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""

        parts: List[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if isinstance(text, str) and text:
                parts.append(text)
        return "".join(parts)

    def get_reasoning_delta_text(self, delta: Any) -> str:
        """优先提取 reasoning_content；终端回显见 chat()，并会合并进 assistant content 以写入历史。"""
        for attr in ("reasoning_content", "reasoning"):
            text = self._coerce_stream_text(getattr(delta, attr, None))
            if text:
                return text
        return ""

    def reset_conversation(self) -> None:
        """将当前会话恢复到仅含 system prompt 的初始状态。"""
        self.messages = list(self.base_messages)
        self.latest_usage = None

    def chat(
        self,
        message: str,
        *,
        silent: bool = False,
        reset_history: bool = False,
        stop_after_tool_names: Optional[List[str]] = None,
    ) -> str:
        """
        silent: 为 True 时不向用户打印任何内容（用于内部/无界面调用）
        """
        if reset_history:
            self.reset_conversation()

        stop_after_tool_names = set(stop_after_tool_names or [])
        self.messages.append({"role": "user", "content": message})
        tools = self.get_tools()
        api_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "stream": True,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream_options": {"include_usage": True, "continuous_usage_stats": True},
        }
        if not OPENAI_ENABLE_THINKING:
            api_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }
        if tools:
            api_kwargs["tools"] = tools
            api_kwargs["tool_choice"] = "auto"

        while True:
            api_kwargs["messages"] = messages_for_api(self.messages)
            stream = self.client.chat.completions.create(**api_kwargs)

            content_parts: List[str] = []
            reasoning_parts: List[str] = []
            tool_call_acc: Dict[str, Dict[str, str]] = {}
            last_tool_call_id: Optional[str] = None

            if not silent:
                print(
                    f"\n{color_text(f'{self.agent_name}：', self.agent_color)}",
                    end="",
                    flush=True,
                )
            tool_call_started = False  # 是否已输出过工具调用前缀
            reasoning_started = False
            answer_started = False
            for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    self.update_usage_snapshot(usage)

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                logger.info(delta)

                reasoning_text = self.get_reasoning_delta_text(delta)
                if reasoning_text:
                    reasoning_parts.append(reasoning_text)
                if reasoning_text and not silent:
                    if not reasoning_started:
                        print(
                            "\n"
                            + color_text("【思考】", REASONING_COLOR)
                            + " ",
                            end="",
                            flush=True,
                        )
                        reasoning_started = True
                    print(
                        color_text(reasoning_text, REASONING_COLOR),
                        end="",
                        flush=True,
                    )

                if hasattr(delta, "content") and delta.content:
                    content_parts.append(delta.content)
                    if not silent:
                        if reasoning_started and not answer_started:
                            print(
                                "\n"
                                + color_text("【回答】", self.agent_color)
                                + " ",
                                end="",
                                flush=True,
                            )
                            answer_started = True
                        print(delta.content, end="", flush=True)

                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc in delta.tool_calls:
                        tc_id = tc.id or last_tool_call_id
                        if tc_id is None:
                            continue
                        last_tool_call_id = tc_id
                        if tc_id not in tool_call_acc:
                            tool_call_acc[tc_id] = {
                                "id": tc_id,
                                "name": "",
                                "arguments": "",
                            }
                            if not silent:
                                if reasoning_started and not answer_started:
                                    print("\n", end="", flush=True)
                                    answer_started = True
                                if not tool_call_started:
                                    print("【工具调用】", end="", flush=True)
                                    tool_call_started = True
                                else:
                                    print("\n【工具调用】", end="", flush=True)
                        if tc.function:
                            if tc.function.name:
                                tool_call_acc[tc_id]["name"] += tc.function.name
                                if not silent:
                                    print(tc.function.name, end="", flush=True)
                            if tc.function.arguments:
                                tool_call_acc[tc_id][
                                    "arguments"
                                ] += tc.function.arguments
                                if not silent:
                                    print(tc.function.arguments, end="", flush=True)

            full_content = "".join(content_parts)

            if tool_call_acc:
                if not silent:
                    print()  # 工具调用流式输出后换行
                tool_calls_list = [
                    {
                        "id": data["id"],
                        "type": "function",
                        "function": {
                            "name": data["name"],
                            "arguments": data["arguments"],
                        },
                    }
                    for data in tool_call_acc.values()
                ]
                self.messages.append(
                    assistant_message_with_reasoning(
                        full_content,
                        reasoning_parts,
                        tool_calls=tool_calls_list,
                    )
                )
                for call in tool_calls_list:
                    result = self.execute_tool(
                        call["function"]["name"],
                        call["function"]["arguments"],
                    )
                    if not silent:
                        print(
                            f"【工具结果】{call['function']['name']} -> "
                            f"{self.format_tool_result(result)}",
                            flush=True,
                        )
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": result,
                        }
                    )
                if any(
                    call["function"]["name"] in stop_after_tool_names
                    for call in tool_calls_list
                ):
                    if not silent:
                        print()
                    return full_content
                continue

            if full_content or reasoning_parts:
                self.messages.append(
                    assistant_message_with_reasoning(full_content, reasoning_parts)
                )
                if not silent:
                    print()  # 流式输出后换行
                return full_content

            # 空响应时避免死循环
            logger.warning("API 返回空响应")
            return ""


# ==== TradingAgent ====


class TradingAgent(BaseAgent):
    """日内交易：在同一对话内完成查询与下单。"""

    def __init__(
        self,
        history_store: Optional[PlanHistoryStore] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        system_prompt = system_prompt or with_runtime_context(
            build_trading_agent_system_prompt(),
            agent_name="TradingAgent",
            model_name=model or OPENAI_MODEL,
        )
        super().__init__(
            model,
            system_prompt,
            agent_name="TradingAgent",
            temperature=0.4,
            top_p=0.88,
        )
        self.agent_color = PLAN_COLOR
        self.history_store = history_store or PlanHistoryStore()
        self.current_session_id = self.history_store.start_session(
            self.agent_name,
            self.messages,
        )
        qp = lambda: quote_ctx
        tp = lambda: trade_ctx
        self.register_tool(TradingPhilosophyTool(TRADING_PHILOSOPHY_FILE))
        self.register_tool(QuoteRealtimeTool(qp))
        self.register_tool(QuoteCandlesticksTool(qp))
        self.register_tool(QuoteOptionChainExpiryDatesTool(qp))
        self.register_tool(QuoteOptionChainInfoByDateTool(qp))
        for tool_cls in _READ_ONLY_TRADE_TOOL_CLASSES:
            self.register_tool(tool_cls(tp))
        for tool_cls in _MUTATING_TRADE_TOOL_CLASSES:
            self.register_tool(tool_cls(tp))

    def _reload_system_prompt_from_disk(self) -> None:
        """从磁盘重建 system（含最新 trading_philosophy.md 与运行时上下文）。

        若当前 messages 首条为 system，则原地替换，以保留后续对话历史。
        """
        self.system_prompt = with_runtime_context(
            build_trading_agent_system_prompt(),
            agent_name=self.agent_name,
            model_name=self.model,
        )
        self.base_messages = [{"role": "system", "content": self.system_prompt}]
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": self.system_prompt}

    def reset_conversation(self) -> None:
        """重置上下文，并开启新的历史会话；并从磁盘重载 system。"""
        if hasattr(self, "current_session_id"):
            self.history_store.archive_session(self.current_session_id, self.messages)
        self._reload_system_prompt_from_disk()
        super().reset_conversation()
        self.current_session_id = self.history_store.start_session(
            self.agent_name,
            self.messages,
        )

    def chat(
        self,
        message: str,
        *,
        silent: bool = False,
        reset_history: bool = False,
        stop_after_tool_names: Optional[List[str]] = None,
        reload_system_prompt: bool = True,
    ) -> str:
        """无人值守场景下默认每次调用前刷新 system；若需省 IO 可设 reload_system_prompt=False。

        reset_history=True 时由 reset_conversation() 内重载，此处不再重复。"""
        if reload_system_prompt and not reset_history:
            self._reload_system_prompt_from_disk()
        try:
            return super().chat(
                message,
                silent=silent,
                reset_history=reset_history,
                stop_after_tool_names=stop_after_tool_names,
            )
        finally:
            self.history_store.sync_session(self.current_session_id, self.messages)



def _build_trade_snapshot_text(trigger_symbol: str) -> str:
    """将账户交易状态压缩成适合 prompt 的 JSON 摘要。"""
    snapshot: Dict[str, Any] = {"trigger_symbol": trigger_symbol}

    try:
        orders = pack_orders(trade_ctx.today_orders())
        snapshot["orders"] = {
            "count": len(orders),
            "items": [
                {
                    "order_id": order["order_id"],
                    "status": order["status"],
                    "side": order["side"],
                    "quantity": order["quantity"],
                    "executed_quantity": order["executed_quantity"],
                    "price": order["price"],
                    "symbol": order["symbol"],
                }
                for order in orders[-5:]
            ],
        }
    except Exception as exc:
        snapshot["orders"] = {"error": str(exc)}

    snapshot["positions_notice"] = "未注入持仓信息：当前仅接入 stock_positions，无法准确代表衍生品持仓。"

    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


def on_candlestick(symbol: str, event: PushCandlestick):

    global day_candlestick_count
    if not event.is_confirmed:
        return

    initialize_trading_day_if_needed()
    trade_date_text = event.candlestick.timestamp.strftime("%Y-%m-%d")
    _refresh_post_close_review_timer(trade_date_text)
    day_candlestick_count += 1

    NEW_CANDLESTICK_TEXT = f"""
    【时间】：{event.candlestick.timestamp.strftime("%Y-%m-%d %H:%M:%S")}，当前是今日的第{day_candlestick_count}根K线。
    【OHLC】：{event.candlestick.open} {event.candlestick.high} {event.candlestick.low} {event.candlestick.close}
    【成交量】：{event.candlestick.volume}
    """
    TRADE_SNAPSHOT_TEXT = f"【当前交易状态摘要】：{_build_trade_snapshot_text(symbol)}"
    with _agent_operation_lock:
        trading_agent.chat(NEW_CANDLESTICK_TEXT + "\n" + TRADE_SNAPSHOT_TEXT)

def main() -> None:
    global trade_ctx, quote_ctx, trading_agent
    quote_ctx = QuoteContext(LongPortConfig.from_env())
    trade_ctx = TradeContext(LongPortConfig.from_env())
    trading_agent = TradingAgent()
    initialize_trading_day_if_needed()

    quote_ctx.set_on_candlestick(on_candlestick)
    quote_ctx.subscribe_candlesticks(Config.TRADE_SYMBOL, parse_period(Config.TRADE_CYCLE), TradeSessions.Intraday)


def _test_trade_account_balance_tool() -> None:
    """
    调试 trade_account_balance：打印 SDK 原始 AccountBalance 与工具输出。
    用法：TEST_TRADE_ACCOUNT_BALANCE=1 python main.py
    """
    global trade_ctx
    cfg = LongPortConfig.from_env()
    trade_ctx = TradeContext(cfg)
    tool = TradeAccountBalanceTool(lambda: trade_ctx)
    raw_rows = trade_ctx.account_balance()
    print("=== [account_balance] 原始 SDK 返回 ===")
    for i, b in enumerate(raw_rows):
        print(f"  [{i}] account currency={b.currency!r} net_assets={b.net_assets} "
              f"total_cash={b.total_cash} buy_power={b.buy_power}")
        for ci in b.cash_infos:
            print(
                f"      cash_infos: {ci.currency!r} available_cash={ci.available_cash} "
                f"frozen_cash={ci.frozen_cash} settling_cash={ci.settling_cash}"
            )
    print("=== [trade_account_balance] 工具无 currency ===")
    print(tool.run({}))
    for ccy in ("USD", "HKD", "CNH"):
        print(f"=== [trade_account_balance] currency={ccy} ===")
        print(tool.run({"currency": ccy}))


if __name__ == "__main__":
    if os.environ.get("TEST_TRADE_ACCOUNT_BALANCE"):
        _test_trade_account_balance_tool()
        sys.exit(0)
    main()
    while True:
        time.sleep(1)