from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.chat.message_elements import File, Image, Record
from core.utils.path_utils import get_data_path
from core.utils.tool_utils import BaseTool


def truncate_tool_output(text: str, max_tokens: int) -> str:
    """Bound tool text using an approximate token budget of four UTF-8 bytes each."""
    if max_tokens == 0:
        return text

    max_bytes = max_tokens * 4
    # Each Unicode character occupies at most four UTF-8 bytes.
    if len(text) <= max_tokens:
        return text
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text

    marker = (
        f"\n[Tool output truncated; original size: {len(encoded)} UTF-8 bytes. "
        "Narrow the query or request a smaller range.]\n"
    )
    if len(marker.encode("utf-8")) > max_bytes:
        marker = "[truncated]" if max_bytes >= 11 else "[..]"

    remaining = max_bytes - len(marker.encode("utf-8"))
    head_bytes = (remaining + 1) // 2
    tail_bytes = remaining // 2
    head = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore") if tail_bytes else ""
    return head + marker + tail


@dataclass
class ToolSet:
    """A set of tools"""
    tools: list[BaseTool] = field(default_factory=list)

    def __contains__(self, item):
        for tool in self.tools:
            if tool.name == item:
                return True
        return False

    def add(self, *tools: BaseTool | type[BaseTool]):
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

    attachments: list[Image | Record | File] = field(default_factory=list)

    # Provider-independent image references (``kira_image_ref`` parts) attached
    # to the tool result. The agent executor relocates them into a user message
    # following the tool results (some providers reject image parts in
    # tool-role messages); refs stay compact paths in persisted history and are
    # resolved to image parts per LLM request.
    media_refs: list[dict] = field(default_factory=list)

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
                lines: list[str] = []
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

    def build_content(self, text: str) -> str | list:
        """Return the tool result content, embedding media refs when present.

        Without media refs the content stays a plain string; with them it becomes
        a content part list the agent executor splits into the tool message text
        and a following user message carrying the media.
        """
        if not self.media_refs:
            return text
        return [{"type": "text", "text": text}, *self.media_refs]
