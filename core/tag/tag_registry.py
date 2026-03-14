from __future__ import annotations

from typing import Union, Type

from .base import BaseTag


class TagSet:
    def __init__(self):
        self._tags: list[BaseTag] = []

    def __contains__(self, item):
        for t in self._tags:
            if t.name == item:
                return True
        return False

    def register(self, *tags: Union[BaseTag, Type[BaseTag]]):
        for tag in tags:
            tag_inst = tag
            if isinstance(tag_inst, type) and issubclass(tag, BaseTag):
                tag_inst = tag()
            for i, t in enumerate(self._tags):
                if t.name == tag_inst.name:
                    self._tags.pop(i)
            self._tags.append(tag_inst)

    def unregister(self, *tag_names: str):
        for i in range(len(self._tags) - 1, -1, -1):
            if self._tags[i].name in tag_names:
                self._tags.pop(i)

    def get(self, name: str):
        for t in self._tags:
            if t.name == name:
                return t

    def get_all(self):
        return self._tags[:]

    def to_prompt(self):
        return "\n".join([t.description for t in self._tags])


tag_registry = TagSet()
