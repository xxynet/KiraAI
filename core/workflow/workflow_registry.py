from typing import Optional
from enum import Enum, auto


class WorkflowType(Enum):
    """workflow type enum"""

    """instant messaging workflow"""
    IM = auto()

    """comment workflow"""
    CMT = auto()

    """feed workflow"""
    FEED = auto()


wf_registry: dict = {
    WorkflowType.IM: {},
    WorkflowType.CMT: {},
    WorkflowType.FEED: {}
}


def register_workflow(name: str, wf_type: WorkflowType):
    def decorator(wf):
        wf_registry[wf_type][name] = wf
        return wf
    return decorator
