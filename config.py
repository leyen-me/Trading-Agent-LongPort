import os
from pathlib import Path
from typing import Any


def format_bool(s: str):
    """将字符串转换为布尔值"""
    return s.lower() in ("true", "1", "yes", "on")


def format_list(s: str):
    """将字符串转换为列表，使用逗号分隔"""
    return s.split(",")


def _optional_int(key: str):
    """读取可选整数配置，无效或≤0 返回 None"""
    v = os.getenv(key, "")
    if not v:
        return None
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except ValueError:
        return None


def _parse_model_context_windows(s: str) -> dict:
    """解析模型上下文窗口覆盖，格式：model1:size1,model2:size2"""
    if not s or not str(s).strip():
        return {}
    result = {}
    for part in str(s).split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            try:
                result[k] = int(v)
            except ValueError:
                pass
    return result

def _require_config(key: str, value: Any) -> str:
    """校验必填配置，缺失时抛出异常。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"缺少必填配置 {key}，请设置环境变量。")
    return str(value).strip()

class Config:
    """
    配置类，从环境变量加载各项参数。
    """
    # OpenAI 客户端 base_url，兼容 openai 库
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    # OpenAI 客户端 api_key
    OPENAI_API_KEY = _require_config("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    # 模型名称，与 OPENAI_API_MODEL 二选一
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", os.getenv("OPENAI_API_MODEL", "gpt-4o-mini"))
    # 工作目录
    WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(Path.cwd().resolve()))).expanduser().resolve()
    # 是否启用思考模式（部分模型支持）
    OPENAI_ENABLE_THINKING = format_bool(os.getenv("OPENAI_ENABLE_THINKING", "true"))
    # 上下文窗口大小覆盖，留空则使用默认或模型内置
    OPENAI_CONTEXT_WINDOW = _optional_int("OPENAI_CONTEXT_WINDOW") or _optional_int("MODEL_CONTEXT_WINDOW")
    # 默认上下文窗口大小
    DEFAULT_CONTEXT_WINDOW = int(os.getenv("DEFAULT_CONTEXT_WINDOW", "200000"))
    # 模型特定上下文窗口，格式：model1:size1,model2:size2
    MODEL_CONTEXT_WINDOWS = _parse_model_context_windows(os.getenv("MODEL_CONTEXT_WINDOW_OVERRIDES", "minimax-m2.5:204800,minimax-m2.5-highspeed:204800"))
    # 交易标的
    TRADE_SYMBOL = os.getenv("TRADE_SYMBOL", "QQQ")
    # 交易周期
    TRADE_CYCLE = os.getenv("TRADE_CYCLE", "min_5")