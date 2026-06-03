from __future__ import annotations

from typing import Union, Type

from .base import BaseTag


class TagSet:
    def __init__(self):
        self._tags: list[BaseTag] = []
        self._root_tags: list[BaseTag] = []

    def __contains__(self, item):
        for t in self._tags:
            if t.name == item:
                return True
        for t in self._root_tags:
            if t.name == item:
                return True
        return False

    def register(self, *tags: Union[BaseTag, Type[BaseTag]]):
        for tag in tags:
            tag_inst = tag
            if isinstance(tag_inst, type) and issubclass(tag, BaseTag):
                tag_inst = tag()
            target = self._root_tags if tag_inst.parent is None else self._tags
            for i, t in enumerate(target):
                if t.name == tag_inst.name:
                    target.pop(i)
                    break
            target.append(tag_inst)

    def unregister(self, *tag_names: str):
        for lst in (self._tags, self._root_tags):
            for i in range(len(lst) - 1, -1, -1):
                if lst[i].name in tag_names:
                    lst.pop(i)

    def get(self, name: str):
        for t in self._tags:
            if t.name == name:
                return t
        for t in self._root_tags:
            if t.name == name:
                return t

    def get_root(self, name: str):
        for t in self._root_tags:
            if t.name == name:
                return t

    def get_all(self):
        return self._tags[:]

    def get_all_root(self):
        return self._root_tags[:]

    def to_prompt(self):
        return "\n".join([t.description for t in self._tags])

    def to_root_prompt(self):
        return "\n".join([t.description for t in self._root_tags])


tag_registry = TagSet()
