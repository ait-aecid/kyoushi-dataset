"""Cyber Range Kyoushi Dataset"""
__version__ = "0.0.0"

from enum import Enum


class LAYOUT(str, Enum):
    GATHER = "gather"
    PROCESSING = "processing"
    LABELS = "labels"
    RULES = "rules"
