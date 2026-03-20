# standard library
import json
from typing import Any, Dict


class BaseTool:
    """所有工具的统一抽象基类。"""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def run(self, parameters: Dict[str, Any]) -> str:
        raise NotImplementedError

    def success(self, data: Any) -> str:
        return json.dumps(
            {"success": True, "data": data, "error": None},
            ensure_ascii=False,
        )

    def fail(self, msg: str) -> str:
        return json.dumps(
            {"success": False, "data": None, "error": msg},
            ensure_ascii=False,
        )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }