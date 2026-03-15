from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union, Type
import os

from core.utils.tool_utils import BaseTool
from core.utils.path_utils import get_data_path
from core.chat.message_elements import Image, Record, File


@dataclass
class ToolSet:
    """A set of tools"""
    tools: list[BaseTool] = field(default_factory=list)

    def __contains__(self, item):
        for tool in self.tools:
            if tool.name == item:
                return True
        return False

    def add(self, *tools: Union[BaseTool, Type[BaseTool]]):
        for tool in tools:
            if isinstance(tool, type):
                tool_inst = tool()
            elif isinstance(tool, BaseTool):
                tool_inst = tool
            else:
                continue
            for i, t in enumerate(self.tools):
                if t.name == tool.name:
                    self.tools.pop(i)
            self.tools.append(tool_inst)

    def remove(self, *tool_names: str):
        for i, t in enumerate(self.tools):
            if t.name in tool_names:
                self.tools.pop(i)

    def get(self, tool_name: str):
        for tool in self.tools:
            if tool.name == tool_name:
                return tool

    def to_list(self):
        tool_list = []
        for tool in self.tools:
            tool_list.append({
                "type": "function",
                "function": tool.get_schema()
            })
        return tool_list


@dataclass
class ToolResult:
    """tool result, support text, image and file result"""

    text: str = ""

    attachments: list[Union[Image, Record, File]] = field(default_factory=list)

    result_str: str = field(default="", init=False, repr=False)

    async def assemble_result(self):
        attachments_text = ""
        if self.attachments:
            data_root = os.path.abspath(str(get_data_path()))
            normalized_paths: list[str] = []
            for att in self.attachments:
                if not hasattr(att, "to_path"):
                    continue
                try:
                    path = await att.to_path()
                except Exception:
                    continue
                if not path:
                    continue
                abs_path = os.path.abspath(str(path))
                if os.path.isabs(abs_path) and abs_path.startswith(data_root):
                    rel_to_data = os.path.relpath(abs_path, start=data_root)
                    file_string = os.path.join("data", rel_to_data).replace("\\", "/")
                else:
                    file_string = abs_path.replace("\\", "/")
                normalized_paths.append(file_string)

            if normalized_paths:
                lines: list[str] = list()
                lines.append(
                    "Tool result contains attachments. "
                    "To send them, use the <file> tag in <msg>, "
                    "and put ONE of the following paths inside each <file> tag:"
                )
                lines.extend(normalized_paths)
                attachments_text = "\n".join(lines)

        res_text = (
            self.text if self.text else "",
            "\n--- Attachments ---\n" if attachments_text else "",
            attachments_text,
        )
        self.result_str = "".join(res_text)
        return self.result_str
