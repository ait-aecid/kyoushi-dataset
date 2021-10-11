import importlib.resources as pkg_resources
import io
import json
import os
import shutil

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Dict,
    List,
    Optional,
    Sequence,
    Text,
    Union,
)

from pydantic import BaseModel
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


def write_yaml_file(data: Any, path: Union[Text, Path]):
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    # first serialize to json and realod as simple data
    # and then load serialized data and dump it as yaml
    # we have to do this since model.dict() would not serialize sub-models
    with open(path, "w") as f:
        yaml.dump(data, f)


def write_model_to_yaml(model: BaseModel, path: Union[Text, Path]):
    model_json = json.loads(model.json())
    write_yaml_file(model_json, path)


def write_json_file(data: Any, path: Union[Text, Path]):
    with open(path, "w") as f:
        if isinstance(data, BaseModel):
            f.write(data.json())
        else:
            json.dump(data, f)


def write_config_file(data: Any, path: Union[Text, Path]):
    if isinstance(path, Text):
        path = Path(path)

    ext = path.suffix
    if ext == ".yaml" or ext == ".yml":
        write_yaml_file(data, path)
    # unless yaml ext are defined we always write json
    else:
        write_json_file(data, path)


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


def create_dirs(directories: List[Path], always: bool = False):
    for d in directories:
        if always or not d.exists():
            os.makedirs(d, exist_ok=always)


def copy_package_file(package: str, file: str, dest: Path, overwrite: bool = False):
    if overwrite or not dest.exists():
        with pkg_resources.path(package, file) as pkg_file:
            shutil.copy(pkg_file, dest.absolute())


def remove_first_lines(path: Union[Text, Path], n: int, inclusive=False):
    """Removes the first lines up until `n`

    In inclusive mode the nth line is also deleted otherwise
    only the lines before the nth line are delted.

    Args:
        path: The path to the file
        n: The "nth" line
        inclusive: If the nth line should be deleted as well or not
    """
    if not inclusive:
        n -= 1

    if n <= 0:
        # nothing to do here
        return

    with open(path, "rb") as original, NamedTemporaryFile("wb", delete=False) as temp:
        # skip the first n iterations
        for i in range(n):
            next(original)
        # now start the iterator at our new first line
        for line in original:
            temp.write(line)
    # replace old file with new file
    shutil.move(temp.name, path)


def truncate_file(path: Union[Text, Path], last_line: int):
    """Truncates file to be only `last_line` long.

    Args:
        path: The file to truncate
        last_line: The new last line
    """
    with open(path, "rb+") as f:
        # read up to the last line
        for i in range(last_line):
            f.readline()
        # and then truncate the file to the current pointer
        f.truncate()


def trim_file(
    path: Union[Text, Path],
    start_line: Optional[int],
    last_line: Optional[int],
):
    if last_line is not None and start_line is not None and start_line > 1:
        print(f"Trimming file: {path} to be {start_line} - {last_line}")
    # first truncate the file
    # so we don't have to adjust for new max line count
    if last_line is not None:
        truncate_file(path, last_line)

    # remove all lines before the start line
    if start_line is not None:
        remove_first_lines(path, start_line, inclusive=False)


def resolve_indices(
    dataset_name: Optional[str] = None,
    prefix_dataset_name: bool = True,
    index: Optional[Union[Sequence[str], str]] = None,
) -> Optional[Union[Sequence[str], str]]:
    if not prefix_dataset_name or dataset_name is None:
        # if prefix is disabled or we do not have a dataset name
        # use index as is
        return index
    elif index is None:
        # no index then simply query whole dataset
        return f"{dataset_name}-*"
    elif isinstance(index, Text):
        # prefix single index
        return f"{dataset_name}-{index}"
    # prefix index list
    return [f"{dataset_name}-{i}" for i in index]
