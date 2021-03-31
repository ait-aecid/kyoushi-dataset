import io
import json

from pathlib import Path
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Dict,
    Text,
    Union,
)

from ruamel.yaml import YAML


if TYPE_CHECKING:
    from .cli import Info
else:
    Info = Any


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


def version_info(cli_info: Info) -> str:
    """Returns formatted version information about the `cr_kyoushi.simulation package`.

    Adapted from
    [Pydantic version.py](https://github.com/samuelcolvin/pydantic/blob/master/pydantic/version.py)
    """
    import platform
    import sys

    from pathlib import Path

    from . import __version__

    info = {
        "cr_kyoushi.dataset version": __version__,
        "install path": Path(__file__).resolve().parent,
        "python version": sys.version,
        "platform": platform.platform(),
    }
    return "\n".join(
        "{:>30} {}".format(k + ":", str(v).replace("\n", " ")) for k, v in info.items()
    )
