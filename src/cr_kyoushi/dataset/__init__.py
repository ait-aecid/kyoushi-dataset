"""Cyber Range Kyoushi Dataset"""
__version__ = "0.1.0"

from enum import Enum


class LAYOUT(str, Enum):
    GATHER = "gather"
    PROCESSING = "processing"
    PROCESSING_CONFIG = "processing/process.yaml"
    LABELS = "labels"
    RULES = "rules"
    CONFIG = "dataset.yaml"
