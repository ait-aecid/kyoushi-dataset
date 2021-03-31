import io
import json

from pathlib import Path
from typing import (
    IO,
    Any,
    BinaryIO,
    Dict,
    Text,
    Union,
)

from ruamel.yaml import YAML


StreamType = Union[BinaryIO, IO[str], io.StringIO]
StreamTextType = Union[StreamType, Text]


def load_yaml_file(file: Union[StreamTextType, Path]) -> Any:
    yaml = YAML(typ="safe")

    return yaml.load(file)


def load_json_file(file: Union[StreamTextType, Path]) -> Any:
    if isinstance(file, Text) or isinstance(file, Path):
        with open(file, "r") as f:
            return json.load(f)
    return json.load(file)


def load_file(file: Union[Text, Path]) -> Any:
    if isinstance(file, Text):
        file = Path(file)

    ext = file.suffix
    if ext == ".json":
        return load_json_file(file)
    elif ext == ".yaml" or ext == ".yml":
        return load_yaml_file(file)
    raise NotImplementedError(f"No file loader supported for {ext} files")


def load_variables(sources: Union[Path, Dict[str, Union[Path]]]):
    if isinstance(sources, dict):
        variables = {}
        for key, path in sources.items():
            variables[key] = load_file(path)
        return variables
    else:
        return load_file(sources)
