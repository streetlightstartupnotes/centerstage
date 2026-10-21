"""Retired compatibility entry points for the old roster-order name assignment.

That algorithm assigned a roster's first name to the most visible track. It did
not identify a person. Keep these calls explicit failures so old agents cannot
silently regenerate or apply its cached labels. Use /annotations with evidence.
"""
from .智能识别引擎 import SmartIdentifier

MESSAGE = '旧版按名单顺序分配姓名的功能已停用；使用带明确人物来源依据的 annotations 接口。'


def auto_identify_members(job, manager):
    raise ValueError(MESSAGE)


def apply_names_to_frames(job, identifier):
    raise ValueError(MESSAGE)
