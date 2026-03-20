# standard library
import argparse
import json
import logging
import os
import platform
import sys
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 在导入 config（会校验 OPENAI_API_KEY）之前：--test / --help 不依赖真实 OpenAI
if __name__ == "__main__" and any(
    flag in sys.argv for flag in ("--test", "--test-full", "--help", "-h")
):
    os.environ.setdefault("OPENAI_API_KEY", "__LONGPORT_CLI_PLACEHOLDER__")

# third party
from openai import OpenAI
from longport.openapi import TradeContext, QuoteContext, Config as LongPortConfig

# self defined
from config import Config
from tools import (
    BaseTool,
    QuoteCandlesticksTool,
    QuoteRealtimeTool,
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

# PlanAgent 仅注册只读 LongPort 工具；ExecuteAgent = 只读 + 下列改单类
_PLAN_READ_ONLY_TRADE_TOOL_CLASSES = (
    TradeAccountBalanceTool,
    TradeEstimateBuyLimitTool,
    TradeHistoryOrdersTool,
    TradeOrderDetailTool,
    TradeStockPositionsTool,
    TradeTodayOrdersTool,
)
_EXECUTE_MUTATING_TRADE_TOOL_CLASSES = (
    TradeCancelOrderTool,
    TradeReplaceOrderTool,
    TradeSubmitOrderTool,
    TradeStopOrderTool,
)


# ==== 日志配置 ====

SCRIPT_DIR = Path(__file__).resolve().parent
_AGENT_DIR = SCRIPT_DIR / ".agent"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_HISTORY_FILE = _AGENT_DIR / "history.json"
_LOG_FILE = _AGENT_DIR / "agent.log"
_TASK_FILE = _AGENT_DIR / "task.json"

# 全局变量
trade_ctx: TradeContext = None
quote_ctx: QuoteContext = None


def _ensure_runtime_storage() -> None:
    """确保 .agent 目录及运行时文件存在。"""
    _AGENT_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.write_text('{"sessions": []}\n', encoding="utf-8")
    _LOG_FILE.touch(exist_ok=True)
    if not _TASK_FILE.exists():
        _TASK_FILE.write_text("[]\n", encoding="utf-8")


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

PLAN_AGENT_SYSTEM_PROMPT = """
<system>
  <role>
    你是任务规划 Agent（PlanAgent）。
    你负责理解需求、拆分任务，并持续推动任务完成。
  </role>

  <primary_goal>
    生成清晰、可执行的任务列表，并把需要落地的请求推进到完成。
  </primary_goal>

  <hard_constraints>
    <rule>你只能直接调用自己已注册的工具。</rule>
    <rule>不要重复创建已存在的任务，不要反复规划同一件事。</rule>
    <rule>你只能使用只读工具查询行情、资金、持仓与订单信息；不得下单、改单、撤单或提交条件/止损单。任何会改变交易状态的操作必须写入任务，由 ExecuteAgent 执行。</rule>
  </hard_constraints>

  <available_tools>
    <tool>task_plan</tool>
    <tool>execute_next_task</tool>
    <tool>quote_realtime</tool>
    <tool>quote_candlesticks</tool>
    <tool>trade_account_balance</tool>
    <tool>trade_estimate_buy_limit</tool>
    <tool>trade_history_orders</tool>
    <tool>trade_order_detail</tool>
    <tool>trade_stock_positions</tool>
    <tool>trade_today_orders</tool>
  </available_tools>

  <tool_call_policy>
    <rule>当你确认要拆分任务时，只调用一次 task_plan。</rule>
    <rule>如果当前会话里已经存在未完成的 request，不要再次调用 task_plan；应继续调用 execute_next_task 推进当前 request。</rule>
    <rule>调用 task_plan 时必须提供 request_summary，用一句简洁中文概括本轮目标。</rule>
    <rule>创建任务后，应转入执行和汇总，而不是重复规划。</rule>
  </tool_call_policy>

  <execution_handoff>
    <rule>创建任务后调用 execute_next_task，把待办任务逐个交给 ExecuteAgent 执行。</rule>
    <rule>当 execute_next_task 返回还有待办任务时，继续调用 execute_next_task；当没有待办任务时，再汇总最终结果。</rule>
  </execution_handoff>

  <output_contract>
    <rule>未开始规划时，不要假装已经执行过任务。</rule>
    <rule>任务仍在推进时，优先继续调用工具，而不是提前写大段总结。</rule>
    <rule>只有当没有待办任务时，才做最终汇总。</rule>
  </output_contract>
</system>
"""

EXECUTE_AGENT_SYSTEM_PROMPT = """
<system>
  <role>
    你是任务执行 Agent（ExecuteAgent）。
    你负责消费单个任务、实际执行操作，并反馈最终结果。
  </role>

  <primary_goal>
    在不猜测、不偷懒、不虚构结果的前提下，尽最大可能把当前任务真实完成，并正确回写任务状态。
  </primary_goal>

  <hard_constraints>
    <rule>不要假装执行过未执行的操作。</rule>
    <rule>如果工具返回失败，不要假装成功；应根据现状重试、换策略，或如实失败。</rule>
    <rule>任务状态查询应使用 read_tasks 工具。</rule>
  </hard_constraints>

  <available_tools>
    <tool>read_tasks</tool>
    <tool>update_task</tool>
    <tool>quote_realtime</tool>
    <tool>quote_candlesticks</tool>
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
  </available_tools>

  <completion_rules>
    <rule>当任务完成时，必须调用 update_task，并将 status 设为 "done"。</rule>
    <rule>如果任务失败，必须调用 update_task，并将 status 设为 "failed"。</rule>
    <rule>不要在未调用 update_task 的情况下就认为任务已经结束。</rule>
  </completion_rules>

  <output_contract>
    <rule>调用 update_task 后，提供简短清晰的执行结果。</rule>
  </output_contract>
</system>
"""


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


def build_runtime_context_xml(agent_name: str, model_name: str) -> str:
    """构造注入到 system prompt 中的运行时环境信息。"""
    return "\n".join(
        [
            "  <runtime_context>",
            f"    <agent_name>{escape(agent_name)}</agent_name>",
            f"    <model>{escape(model_name)}</model>",
            f"    <now_time>{escape(get_now_time_text())}</now_time>",
            f"    <script_dir>{escape(str(SCRIPT_DIR))}</script_dir>",
            f"    <task_file>{escape(str(_TASK_FILE))}</task_file>",
            f"    <log_file>{escape(str(_LOG_FILE))}</log_file>",
            "  </runtime_context>",
        ]
    )


def with_runtime_context(
    base_prompt: str,
    *,
    agent_name: str,
    model_name: str,
) -> str:
    """把运行时上下文插入到 system XML 中，保持单一 <system> 根节点。"""
    runtime_context_xml = build_runtime_context_xml(agent_name, model_name)
    return base_prompt.replace("</system>", f"{runtime_context_xml}\n</system>", 1)


@dataclass
class TaskRecord:
    """单个任务的持久化记录。"""
    id: str
    description: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "pending"
    result: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_storage_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "TaskRecord":
        return cls(
            id=data["id"],
            description=data["description"],
            request_id=data.get("request_id", request_id),
            session_id=data.get("session_id", session_id),
            status=data.get("status", "pending"),
            result=data.get("result"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class RequestRecord:
    """单次用户请求的持久化记录。"""

    id: str
    session_id: Optional[str] = None
    summary: str = ""
    user_input: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tasks: List[TaskRecord] = field(default_factory=list)

    def compute_status(self) -> str:
        if not self.tasks:
            return "pending"
        if any(task.status == "running" for task in self.tasks):
            return "running"
        if any(task.status == "pending" for task in self.tasks):
            return "pending"
        if any(task.status == "failed" for task in self.tasks):
            return "failed"
        return "done"

    def has_active_tasks(self) -> bool:
        return any(task.status in {"pending", "running"} for task in self.tasks)

    def to_storage_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "summary": self.summary,
            "user_input": self.user_input,
            "status": self.compute_status(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tasks": [
                task.to_storage_dict()
                for task in sorted(self.tasks, key=lambda item: item.created_at)
            ],
        }


class TaskStore:
    """负责加载、保存和管理请求与任务状态。"""

    def __init__(self, storage_path: Path = _TASK_FILE) -> None:
        self.storage_path = storage_path
        self._requests: Dict[str, RequestRecord] = {}
        self._tasks: Dict[str, TaskRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            content = self.storage_path.read_text(encoding="utf-8").strip()
            raw = {"requests": []} if not content else json.loads(content)
        except Exception:
            logger.exception("加载 task.json 失败")
            return

        self._requests.clear()
        self._tasks.clear()

        if isinstance(raw, list):
            self._load_legacy_tasks(raw)
            return

        requests = raw.get("requests") if isinstance(raw, dict) else None
        if not isinstance(requests, list):
            logger.warning("task.json 格式无效，已忽略")
            return

        for item in requests:
            if not isinstance(item, dict):
                continue
            request_id = str(item.get("id", "")).strip() or str(uuid.uuid4())[:8]
            request = RequestRecord(
                id=request_id,
                session_id=item.get("session_id"),
                summary=str(item.get("summary", "")).strip(),
                user_input=item.get("user_input"),
                created_at=item.get("created_at", time.time()),
                updated_at=item.get("updated_at", time.time()),
            )
            raw_tasks = item.get("tasks")
            if not isinstance(raw_tasks, list):
                raw_tasks = []
            for raw_task in raw_tasks:
                if not isinstance(raw_task, dict):
                    continue
                try:
                    task = TaskRecord.from_dict(
                        raw_task,
                        request_id=request.id,
                        session_id=request.session_id,
                    )
                except KeyError:
                    continue
                request.tasks.append(task)
                self._tasks[task.id] = task
            self._requests[request.id] = request

    def _load_legacy_tasks(self, raw_tasks: List[Any]) -> None:
        legacy_groups: Dict[Optional[str], List[TaskRecord]] = {}
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            try:
                task = TaskRecord.from_dict(item)
            except KeyError:
                continue
            legacy_groups.setdefault(task.session_id, []).append(task)

        for session_id, tasks in legacy_groups.items():
            if not tasks:
                continue
            tasks.sort(key=lambda item: item.created_at)
            now = time.time()
            request = RequestRecord(
                id=f"legacy-{tasks[0].id}",
                session_id=session_id,
                summary="历史任务迁移（缺少原始请求摘要）",
                created_at=min((task.created_at for task in tasks), default=now),
                updated_at=max((task.updated_at for task in tasks), default=now),
            )
            for task in tasks:
                task.request_id = request.id
                request.tasks.append(task)
                self._tasks[task.id] = task
            self._requests[request.id] = request

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "requests": [
                request.to_storage_dict()
                for request in sorted(
                    self._requests.values(), key=lambda item: item.created_at
                )
            ]
        }
        temp_path = self.storage_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.storage_path)

    def reset(self) -> None:
        self._requests.clear()
        self._tasks.clear()
        self._save()

    def _iter_tasks(
        self,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[TaskRecord]:
        tasks = sorted(self._tasks.values(), key=lambda task: task.created_at)
        if request_id is not None:
            tasks = [task for task in tasks if task.request_id == request_id]
        if session_id is None:
            return tasks
        return [task for task in tasks if task.session_id == session_id]

    def _iter_requests(self, session_id: Optional[str] = None) -> List[RequestRecord]:
        requests = sorted(self._requests.values(), key=lambda item: item.created_at)
        if session_id is None:
            return requests
        return [request for request in requests if request.session_id == session_id]

    def _find_reusable_request(
        self,
        session_id: Optional[str],
        request_summary: str,
        user_input: Optional[str],
    ) -> Optional[RequestRecord]:
        for request in reversed(self._iter_requests(session_id)):
            if request.summary != request_summary:
                continue
            if (request.user_input or None) != (user_input or None):
                continue
            if request.has_active_tasks():
                return request
        return None

    def _build_task_dict(self, task: TaskRecord) -> Dict[str, Any]:
        data = task.to_dict()
        request = self._requests.get(task.request_id or "")
        data["request_summary"] = request.summary if request else ""
        data["user_input"] = request.user_input if request else None
        return data

    def get_task_dict(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.get(task_id)
        if task is None:
            return None
        return self._build_task_dict(task)

    def _build_request_dict(self, request: RequestRecord) -> Dict[str, Any]:
        return {
            "id": request.id,
            "session_id": request.session_id,
            "summary": request.summary,
            "user_input": request.user_input,
            "status": request.compute_status(),
            "created_at": request.created_at,
            "updated_at": request.updated_at,
            "tasks": [self._build_task_dict(task) for task in self._iter_tasks(request_id=request.id)],
        }

    def get_active_request(self, session_id: Optional[str] = None) -> Optional[RequestRecord]:
        for request in self._iter_requests(session_id):
            if request.has_active_tasks():
                return request
        return None

    def has_active_request(self, session_id: Optional[str] = None) -> bool:
        return self.get_active_request(session_id) is not None

    def create_tasks(
        self,
        raw_tasks: List[Any],
        session_id: Optional[str] = None,
        request_summary: str = "",
        user_input: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        created: List[Dict[str, Any]] = []
        normalized_summary = str(request_summary).strip()
        normalized_user_input = str(user_input).strip() if user_input is not None else None
        request = self._find_reusable_request(
            session_id,
            normalized_summary,
            normalized_user_input,
        )
        created_request = False
        if request is None:
            now = time.time()
            request = RequestRecord(
                id=str(uuid.uuid4())[:8],
                session_id=session_id,
                summary=normalized_summary,
                user_input=normalized_user_input,
                created_at=now,
                updated_at=now,
            )
            self._requests[request.id] = request
            created_request = True

        for raw_task in raw_tasks:
            if isinstance(raw_task, dict):
                description = str(raw_task.get("description", "")).strip()
            else:
                description = str(raw_task).strip()

            if not description:
                continue

            if any(
                task.description == description for task in request.tasks
            ):
                continue

            task = TaskRecord(
                id=str(uuid.uuid4())[:8],
                description=description,
                request_id=request.id,
                session_id=session_id,
            )
            self._tasks[task.id] = task
            request.tasks.append(task)
            request.updated_at = time.time()
            created.append(self._build_task_dict(task))

        if created_request and not request.tasks:
            self._requests.pop(request.id, None)
        self._save()
        return created

    def list_tasks(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self._build_task_dict(task) for task in self._iter_tasks(session_id)]

    def list_requests(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self._build_request_dict(request) for request in self._iter_requests(session_id)]

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def get_request(self, request_id: str) -> Optional[RequestRecord]:
        return self._requests.get(request_id)

    def get_next_pending(self, session_id: Optional[str] = None) -> Optional[TaskRecord]:
        active_request = self.get_active_request(session_id)
        if active_request is None:
            return None
        for task in self._iter_tasks(session_id, request_id=active_request.id):
            if task.status == "pending":
                return task
        return None

    def pending_tasks(
        self,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            self._build_task_dict(task)
            for task in self._iter_tasks(session_id, request_id=request_id)
            if task.status == "pending"
        ]

    def completed_tasks(
        self,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            self._build_task_dict(task)
            for task in self._iter_tasks(session_id, request_id=request_id)
            if task.status in {"done", "failed"}
        ]

    def has_active_tasks(self, session_id: Optional[str] = None) -> bool:
        return any(
            task.status in {"pending", "running"}
            for task in self._iter_tasks(session_id)
        )

    def update_task(
        self, task_id: str, status: str, result: Optional[str] = None
    ) -> Dict[str, Any]:
        if status not in TASK_STATUS:
            raise ValueError("invalid status")

        task = self.get(task_id)
        if not task:
            raise KeyError("task not found")

        task.status = status
        if result is not None:
            task.result = result
        task.updated_at = time.time()
        request = self.get_request(task.request_id or "")
        if request is not None:
            request.updated_at = task.updated_at
        self._save()
        return self._build_task_dict(task)


class PlanHistoryStore:
    """负责持久化 PlanAgent 的上下文历史。"""

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
            return ["当前还没有 usage 数据，请先让 PlanAgent 完成至少一次对话。"]

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
        """优先提取 reasoning_content，仅用于终端回显，不写入上下文。"""
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
        silent: 为 True 时不向用户打印任何内容（用于 exec_agent 内部执行，反馈给 plan_agent）
        """
        if reset_history:
            self.reset_conversation()

        stop_after_tool_names = set(stop_after_tool_names or [])
        self.messages.append({"role": "user", "content": message})
        tools = self.get_tools()
        api_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
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
            stream = self.client.chat.completions.create(**api_kwargs)

            content_parts: List[str] = []
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
                    {
                        "role": "assistant",
                        "content": full_content or "",
                        "tool_calls": tool_calls_list,
                    }
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

            if full_content:
                self.messages.append({"role": "assistant", "content": full_content})
                if not silent:
                    print()  # 流式输出后换行
                return full_content

            # 空响应时避免死循环
            logger.warning("API 返回空响应")
            return ""


# ==== Plan Agent ====

TASK_STATUS = ["pending", "running", "done", "failed"]


class TaskPlanTool(BaseTool):
    """向任务存储写入规划后的任务列表。"""
    def __init__(
        self,
        task_store: TaskStore,
        session_id_provider: Optional[Callable[[], Optional[str]]] = None,
        request_input_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.task_store = task_store
        self.session_id_provider = session_id_provider
        self.request_input_provider = request_input_provider

    name = "task_plan"
    description = "Create tasks"

    parameters = {
        "type": "object",
        "properties": {
            "request_summary": {"type": "string"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}},
                    "required": ["description"],
                },
            }
        },
        "required": ["request_summary", "tasks"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        session_id = (
            self.session_id_provider() if callable(self.session_id_provider) else None
        )
        user_input = (
            self.request_input_provider() if callable(self.request_input_provider) else None
        )
        active_request = self.task_store.get_active_request(session_id)
        if active_request is not None:
            return self.fail(
                "active request exists; continue executing current request before creating a new task plan"
            )
        created = self.task_store.create_tasks(
            parameters["tasks"],
            session_id=session_id,
            request_summary=str(parameters.get("request_summary", "")).strip(),
            user_input=user_input,
        )
        return self.success(created)


class TaskUpdateTool(BaseTool):
    """更新任务执行状态和结果。"""
    def __init__(
        self,
        task_store: TaskStore,
        result_enricher: Optional[Callable[[str, str, Optional[str]], Optional[str]]] = None,
    ):
        self.task_store = task_store
        self.result_enricher = result_enricher

    name = "update_task"

    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["pending", "running", "done", "failed"],
            },
            "result": {"type": "string"},
        },
        "required": ["task_id", "status"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:

        try:
            result = parameters.get("result")
            if callable(self.result_enricher):
                result = self.result_enricher(
                    parameters["task_id"],
                    parameters["status"],
                    result,
                )
            updated = self.task_store.update_task(
                task_id=parameters["task_id"],
                status=parameters["status"],
                result=result,
            )
            return self.success(updated)
        except KeyError:
            return self.fail("task not found")
        except ValueError:
            return self.fail("invalid status")


class ReadTasksTool(BaseTool):
    """按当前会话读取任务信息。"""

    def __init__(
        self,
        task_store: TaskStore,
        session_id_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.task_store = task_store
        self.session_id_provider = session_id_provider

    name = "read_tasks"
    description = "Read current session tasks"

    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
        },
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        session_id = (
            self.session_id_provider() if callable(self.session_id_provider) else None
        )
        task_id = parameters.get("task_id")

        if task_id:
            task = self.task_store.get(task_id)
            if task is None or task.session_id != session_id:
                return self.fail("task not found")
            task_data = self.task_store.get_task_dict(task.id)
            if task_data is None:
                return self.fail("task not found")
            return self.success(task_data)

        return self.success(self.task_store.list_requests(session_id=session_id))


def execute_single_task(
    exec_agent: "ExecuteAgent",
    task_store: TaskStore,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """取出一个待执行任务，并交给 ExecuteAgent 处理。"""
    task = task_store.get_next_pending(session_id=session_id)
    if task is None:
        return {"executed": False, "task": None}

    task_store.update_task(task.id, "running")
    print(color_text(f"\n[执行中] {task.description}", EXECUTE_COLOR))
    request = task_store.get_request(task.request_id or "")
    request_summary = request.summary.strip() if request and request.summary else "未记录"
    request_user_input = request.user_input.strip() if request and request.user_input else ""

    previous_task_lines: List[str] = []
    for previous in task_store.completed_tasks(
        session_id=session_id,
        request_id=task.request_id,
    ):
        result = (previous.get("result") or "").strip()
        if len(result) > 200:
            result = result[:200] + "..."
        previous_task_lines.append(
            f"- [{previous['status']}] {previous['description']}"
            + (f" | 结果：{result}" if result else "")
        )

    previous_task_summary = "\n".join(previous_task_lines) or "无"

    task_prompt = (
        f"任务ID：{task.id}\n"
        f"请求ID：{task.request_id or '未记录'}\n"
        f"用户目标摘要：{request_summary}\n"
        + (f"用户原始输入：{request_user_input}\n" if request_user_input else "")
        + f"任务描述：{task.description}\n\n"
        + f"已完成任务摘要：\n{previous_task_summary}\n\n"
        + "你正在延续同一个项目，请基于上述已完成任务继续执行。\n"
        + "任务状态只以本任务输入和 update_task 工具为准。\n"
        + "执行完成后请调用 update_task 更新最终状态。调用后不要继续长篇总结。"
    )

    exec_agent.active_session_id = session_id
    exec_agent.active_task_id = task.id
    try:
        result = exec_agent.chat(
            task_prompt,
            silent=False,
            reset_history=False,
            stop_after_tool_names=["update_task"],
        )
    except Exception as e:
        logger.exception("执行任务失败: %s", task.description)
        result = f"执行异常：{e}"
        task_store.update_task(task.id, "failed", result=result)
    finally:
        exec_agent.active_session_id = None
        exec_agent.active_task_id = None

    latest_task = task_store.get(task.id)
    if latest_task and latest_task.status == "running":
        task_store.update_task(task.id, "done", result=result)
        latest_task = task_store.get(task.id)
    elif latest_task and not latest_task.result:
        task_store.update_task(task.id, latest_task.status, result=result)
        latest_task = task_store.get(task.id)

    if latest_task is None:
        raise RuntimeError(f"task disappeared: {task.id}")

    print(
        color_text(
            f"[任务结束] {latest_task.description} -> {latest_task.status}",
            EXECUTE_COLOR,
        )
    )
    latest_task_data = task_store.get_task_dict(task.id)
    return {"executed": True, "task": latest_task_data}


class PlanAgent(BaseAgent):
    """负责理解需求、拆解任务并驱动执行流程。"""
    """
    1. 与用户直接交互的 PlanAgent， 用户不会直接与 ExecuteAgent 交互
    2. 理解用户需求，使用只读工具查看行情、资金与持仓等。做出规划并生成任务列表。
    3. 分配任务给 ExecuteAgent 执行。
    4. ExecuteAgent 执行任务，直到子任务完成。并反馈任务进度。
    5. 当子任务完成时，PlanAgent 主动汇报任务完成情况。
    6. 当所有子任务完成时，PlanAgent 主动汇报任务完成情况。
    """

    def __init__(
        self,
        task_store: TaskStore,
        history_store: Optional[PlanHistoryStore] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        system_prompt = system_prompt or with_runtime_context(
            PLAN_AGENT_SYSTEM_PROMPT,
            agent_name="PlanAgent",
            model_name=model or OPENAI_MODEL,
        )
        super().__init__(
            model,
            system_prompt,
            agent_name="PlanAgent",
            temperature=0.3,
            top_p=0.85,
        )
        self.agent_color = PLAN_COLOR
        self.task_store = task_store
        self.history_store = history_store or PlanHistoryStore()
        self.current_user_request_input: Optional[str] = None
        self.current_session_id = self.history_store.start_session(
            self.agent_name,
            self.messages,
        )
        self.register_tool(
            TaskPlanTool(
                task_store,
                session_id_provider=lambda: self.current_session_id,
                request_input_provider=lambda: self.current_user_request_input,
            )
        )
        qp = lambda: quote_ctx
        tp = lambda: trade_ctx
        self.register_tool(QuoteRealtimeTool(qp))
        self.register_tool(QuoteCandlesticksTool(qp))
        for tool_cls in _PLAN_READ_ONLY_TRADE_TOOL_CLASSES:
            self.register_tool(tool_cls(tp))

    def reset_conversation(self) -> None:
        """重置上下文，并为 PlanAgent 开启新的历史会话。"""
        if hasattr(self, "current_session_id"):
            self.history_store.archive_session(self.current_session_id, self.messages)
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
    ) -> str:
        self.current_user_request_input = message
        try:
            return super().chat(
                message,
                silent=silent,
                reset_history=reset_history,
                stop_after_tool_names=stop_after_tool_names,
            )
        finally:
            self.history_store.sync_session(self.current_session_id, self.messages)
            self.current_user_request_input = None

# ==== Execute Agent ====


class ExecuteAgent(BaseAgent):
    """负责消费单个任务并落地执行。"""
    def __init__(
        self,
        task_store: TaskStore,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        system_prompt = system_prompt or with_runtime_context(
            EXECUTE_AGENT_SYSTEM_PROMPT,
            agent_name="ExecuteAgent",
            model_name=model or OPENAI_MODEL,
        )
        super().__init__(
            model,
            system_prompt,
            agent_name="ExecuteAgent",
            temperature=0.6,
            top_p=0.9,
        )
        self.agent_color = EXECUTE_COLOR
        self.task_store = task_store
        self.active_session_id: Optional[str] = None
        self.active_task_id: Optional[str] = None
        self.register_tool(
            ReadTasksTool(
                task_store,
                session_id_provider=lambda: self.active_session_id,
            )
        )
        self.register_tool(TaskUpdateTool(task_store))
        qp = lambda: quote_ctx
        tp = lambda: trade_ctx
        self.register_tool(QuoteRealtimeTool(qp))
        self.register_tool(QuoteCandlesticksTool(qp))
        for tool_cls in _PLAN_READ_ONLY_TRADE_TOOL_CLASSES:
            self.register_tool(tool_cls(tp))
        for tool_cls in _EXECUTE_MUTATING_TRADE_TOOL_CLASSES:
            self.register_tool(tool_cls(tp))

    def reset_conversation(self) -> None:
        """重置上下文与当前任务运行期状态。"""
        super().reset_conversation()
        self.active_task_id = None


# ==== 任务分发工具 ====


class ExecuteNextTaskTool(BaseTool):
    """把下一个待办任务分发给 ExecuteAgent。"""
    def __init__(
        self,
        task_store: TaskStore,
        exec_agent: ExecuteAgent,
        session_id_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.task_store = task_store
        self.exec_agent = exec_agent
        self.session_id_provider = session_id_provider

    name = "execute_next_task"
    description = "Dispatch next pending task to ExecuteAgent"
    parameters = {"type": "object", "properties": {}}

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            session_id = (
                self.session_id_provider() if callable(self.session_id_provider) else None
            )
            result = execute_single_task(
                self.exec_agent,
                self.task_store,
                session_id=session_id,
            )
            return self.success(result)
        except Exception as e:
            return self.fail(str(e))





def init_longport():
    global trade_ctx, quote_ctx
    trade_ctx = TradeContext(LongPortConfig.from_env())
    quote_ctx = QuoteContext(LongPortConfig.from_env())


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading Agent (LongPort)")
    parser.add_argument(
        "--test",
        action="store_true",
        help="运行 LongPort 行情工具集成烟测后退出（实现见 test/longport_quote_smoke.py）",
    )
    parser.add_argument(
        "--test-trade",
        action="store_true",
        help="运行 LongPort 交易工具集成烟测后退出（只读接口，见 test/longport_trade_smoke.py）",
    )
    parser.add_argument(
        "--test-full",
        action="store_true",
        help="与 --test / --test-trade 联用：结果 JSON 不截断",
    )
    return parser.parse_args()


def main() -> None:
    init_longport()
    
    task_store = TaskStore()
    exec_agent = ExecuteAgent(task_store)
    plan_agent = PlanAgent(task_store)
    plan_agent.register_tool(
        ExecuteNextTaskTool(
            task_store,
            exec_agent,
            session_id_provider=lambda: plan_agent.current_session_id,
        )
    )
    plan_agent.chat("你好，我现在还有多少钱")

if __name__ == "__main__":
    main()