# standard library
from pathlib import Path
from typing import Any, Dict


from .BaseTool import BaseTool


def _atomic_write_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


class TradingPhilosophyTool(BaseTool):
    """
    读写与 main.py 同目录的 trading_philosophy.md；仅该固定路径，不接受用户传入路径。
    """

    name = "trading_philosophy"
    description = (
        "用 content 直接整文件覆盖 trading_philosophy.md（与系统提示中 trading_philosophy 区块同源）。"
        "适合在盘后复盘或策略修订后输出新的完整版本。"
        "注意：写入磁盘后，下一次发起 chat 时会自动从文件刷新 system。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "新的完整 trading_philosophy.md 内容。",
            },
        },
        "required": ["content"],
    }

    def __init__(self, file_path: Path) -> None:
        self._path = file_path.resolve()

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            raw = parameters.get("content")
            if raw is None:
                return self.fail("content 参数不能为空")
            content = str(raw)
            if not content.strip():
                return self.fail("content 参数不能为空")

            path = self._path
            _atomic_write_utf8(path, content)
            return self.success(
                {
                    "path": str(path),
                    "bytes_written": len(content.encode("utf-8")),
                }
            )
        except OSError as exc:
            return self.fail(str(exc))
        except Exception as exc:
            return self.fail(str(exc))
