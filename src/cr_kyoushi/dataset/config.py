from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
)

from pydantic import (
    BaseModel,
    Field,
    validator,
)


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
    log_dir: Path = Field(
        Path("processing/logstash/logs"),
        description="The directory logstash should use for logging",
    )
    data_dir: Path = Field(
        Path("processing/logstash/data"),
        description="The directory logstash should use for persistent data (e.g., sincedb).",
    )


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
