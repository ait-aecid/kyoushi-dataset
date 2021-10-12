"""This module contains all configuration model definitions."""

import sys

from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)

from pydantic import (
    BaseModel,
    Field,
    validator,
)


if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


class ObservationConfig(BaseModel):
    pass


class DatasetConfig(BaseModel):
    name: str = Field(
        ...,
        description="The name of the dataset. This is for example used as part of the elasticsearch index.",
    )
    start: datetime = Field(
        ...,
        description="The start time of the observation period.",
    )
    end: datetime = Field(
        ...,
        description="The end time of the observation period.",
    )


class LogstashParserConfig(BaseModel):
    settings_dir: Path = Field(
        Path("processing/logstash"),
        description="The logstash settings directory containing the logstash.yml (use for `path.settings`).",
    )

    conf_dir: Path = Field(
        None,
        description="The path to the logstash pipeline config (defaults to <settings_dir>/conf.d)",
    )

    log_level: Optional[str] = Field(
        None, description="The log level to pass to the logstash cli"
    )

    log_dir: Path = Field(
        Path("processing/logstash/log"),
        description="The directory logstash should use for logging",
    )

    completed_log: Path = Field(
        None,
        description="The logstash file input completed log (defaults to <log_dir>/file-completed.log",
    )

    data_dir: Path = Field(
        Path("processing/logstash/data"),
        description="The directory logstash should use for persistent data (e.g., sincedb).",
    )

    parsed_dir: Path = Field(
        None,
        description="The directory to save the parsed log files in, when save_parsed=true for any log. (defaults to <dataset>/parsed)",
    )

    save_parsed: bool = Field(
        False,
        description="If the log files should be saved to the disk after parsing. Is overridden by log.save_parsed.",
    )

    @validator("completed_log", pre=True, always=True)
    def default_completed_log(cls, v, *, values, **kwargs):
        return v or values["log_dir"].joinpath("file-completed.log")

    @validator("conf_dir", pre=True, always=True)
    def default_conf_dir(cls, v, *, values, **kwargs):
        return v or values["settings_dir"].joinpath("conf.d")

    @validator("parsed_dir", pre=True, always=True)
    def default_parsed_dir(cls, v, *, values, **kwargs):
        return v or Path("parsed")


class ProcessingConfig(BaseModel):
    pre_processors: List[Dict[str, Any]] = Field(
        [],
        description="The processors to apply to the dataset before parsing and publishing the log data to elasticsearch.",
    )
    parser: LogstashParserConfig = Field(
        LogstashParserConfig(),
        description="The logstash parser configuration.",
    )
    post_processors: List[Dict[str, Any]] = Field(
        [],
        description="The processors to apply to the dataset after parsing and publishing the log data to elasticsearch.",
    )

    @validator("pre_processors", "post_processors", each_item=True)
    def check_processor_required_fields(cls, val):
        assert "name" in val, "A processor must have a name"
        assert (
            "type" in val
        ), f"A processor must have a type, but {val['name']} has none"
        return val


class LogstashLogConfig(BaseModel):
    type: str = Field(
        ...,
        description="The type to tag the log input with.",
    )
    codec: Union[str, Dict[str, Dict[str, Any]]] = Field(
        "plain",
        description="The file codec to use for reading.",
    )
    path: Union[str, List[str]] = Field(
        ...,
        description="The log file path/s to read.",
    )
    save_parsed: Optional[bool] = Field(
        None,
        description="If this log should be saved to the disk after parsing. (Overrides parser.save_parsed)",
    )
    exclude: Union[str, List[str]] = Field(
        [],
        description="Glob/s to exclude from reading.",
    )
    file_sort_direction: Literal["asc", "desc"] = Field(
        "desc",
        description="The sort direction for multiple files.",
    )
    file_chunk_size: Optional[int] = Field(
        None,
        description=(
            "The size of the chunks to read from the file (in bytes). "
            "Default is 32kb set this to a higher value if your log file contains very long lines."
        ),
    )

    delimiter: Optional[str] = Field(
        None,
        description="The newline delimiter (does not work for compressed files).",
    )
    tags: List[str] = Field(
        [],
        description="The tags to assign to each log event for this log source.",
    )
    add_field: Dict[str, Any] = Field(
        {},
        description="A dict of fields to add to each log event.",
    )
