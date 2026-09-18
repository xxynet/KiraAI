from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union, Type

from core.utils.tool_utils import BaseTool
from core.utils.path_utils import get_data_path
from core.chat.message_elements import Image, Record, File


def _stage_file_to_temp(abs_path: str) -> Optional[str]:
    """Copy an attachment living outside the data root into data/temp.

    The <file> tag send policy only delivers files under data/files,
    data/temp or the configured extra read paths, so a foreign path (e.g. an
    MCP ``file:///`` resource) is staged under data/temp and the staged
    relative path is advertised to the LLM instead of the original. Returns
    the ``data/temp/...`` path of the copy, or None when the source is
    missing or cannot be copied.
    """
    try:
        if not os.path.isfile(abs_path):
            return None
        temp_dir = get_data_path() / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        staged_name = f"{uuid.uuid4().hex[:8]}-{Path(abs_path).name}"
        shutil.copyfile(abs_path, temp_dir / staged_name)
        return f"data/temp/{staged_name}"
    except OSError:
        return None


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
        name_set = set(tool_names)
        self.tools = [t for t in self.tools if t.name not in name_set]

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
                    staged = await asyncio.to_thread(_stage_file_to_temp, abs_path)
                    if not staged:
                        continue
                    file_string = staged
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
