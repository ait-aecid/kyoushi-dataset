"""This module contains general purpose utility functions."""

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
    """Parse and load a YAML file.

    Args:
        file: The file stream or path to load

    Returns:
        The loaded data
    """
    yaml = YAML(typ="safe")

    return yaml.load(file)


def load_json_file(file: Union[StreamTextType, Path]) -> Any:
    """Parse and load a JSON file

    Args:
        file: The file stream or path to load

    Returns:
        The loaded data
    """
    if isinstance(file, (Text, Path)):
        with open(file, "r") as f:
            return json.load(f)
    return json.load(file)


def load_file(file: Union[Text, Path]) -> Any:
    """Load data from a file (either JSON or YAML)

    The function will check the file extensions
     - .json
     - .yaml
     - .yml
    and will try to load using the respective parses.
    Any other file extension and file format will produce
    an error.

    Args:
        file: The file stream or path to load

    Raises:
        NotImplementedError: If the file format is not supported.

    Returns:
        The loaded data
    """
    if isinstance(file, Text):
        file = Path(file)

    ext = file.suffix
    if ext == ".json":
        return load_json_file(file)
    elif ext in (".yaml", ".yml"):
        return load_yaml_file(file)
    raise NotImplementedError(f"No file loader supported for {ext} files")


def write_yaml_file(data: Any, path: Union[Text, Path]):
    """Serialize data into a YAML file

    Args:
        data: The data to write
        path: The file path to write to
    """
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    with open(path, "w") as f:
        yaml.dump(data, f)


def write_model_to_yaml(model: BaseModel, path: Union[Text, Path]):
    """Serialize a Pydantic model into a YAML file

    Args:
        model: The Pydantic model
        path: The file to write to
    """
    # first serialize to json and reload as simple data
    # and then load serialized data and dump it as yaml
    # we have to do this since model.dict() would not serialize sub-models
    model_json = json.loads(model.json())
    write_yaml_file(model_json, path)


def write_json_file(data: Any, path: Union[Text, Path]):
    """Serialize data into a JSON file

    Args:
        data: The data to serialize
        path: The file to write to
    """
    with open(path, "w") as f:
        if isinstance(data, BaseModel):
            f.write(data.json())
        else:
            json.dump(data, f)


def write_config_file(data: Any, path: Union[Text, Path]):
    """Serialize config data into a file.

    Depending on the given destinations path file extension
    either YAML or JSON serialization is used (defaults to JSON).

    Args:
        data: The data to serialize
        path: The file to write to
    """
    if isinstance(path, Text):
        path = Path(path)

    ext = path.suffix
    if ext in (".yaml", ".yml"):
        write_yaml_file(data, path)
    # unless yaml ext are defined we always write json
    else:
        write_json_file(data, path)


def load_variables(sources: Union[Path, Dict[str, Union[Path]]]) -> Any:
    """Loads variables from variable files.

    Args:
        sources: The variable file/s to load

    Returns:
        The loaded variables
    """
    if isinstance(sources, dict):
        variables = {}
        for key, path in sources.items():
            variables[key] = load_file(path)
        return variables

    return load_file(sources)


def version_info(cli_info: Info) -> str:
    """Returns formatted version information about the `cr_kyoushi.simulation package`.

    Adapted from
    [Pydantic version.py](https://github.com/samuelcolvin/pydantic/blob/master/pydantic/version.py)

    Args;
        cli_info: The CLI info object

    Returns:
        A formated string showing CLI tool information
    """
    import platform
    import sys

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
    """Creates the given list of directories.

    Args:
        directories: The directories to create
        always: If the directories can already exist or not
    """
    for d in directories:
        if always or not d.exists():
            os.makedirs(d, exist_ok=always)


def copy_package_file(package: str, file: str, dest: Path, overwrite: bool = False):
    """Copies a package distributed file to some path.

    Args:
        package: The package of the file to copy
        file: The file to copy
        dest: The path to copy the file to
        overwrite: If the destination path should be overwritten or not
    """
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
    """Trim a file to the given start and end lines.

    Removes all lines before the `start_line` and after the
    `last_line`. If either of the values is omitted the very first
    or last line is used by default.

    Args:
        path: The file to trim
        start_line: The start line number
        last_line: The last line number
    """
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
    """Resolves a given list of indices prefixing the dataset name if necessary.

    Args:
        dataset_name: The dataset name
        prefix_dataset_name: If the dataset name should be prefixed or not
        index: The indices to process

    Returns:
        The prepared indices
    """
    if not prefix_dataset_name or dataset_name is None:
        # if prefix is disabled or we do not have a dataset name
        # use index as is
        return index

    if index is None:
        # no index then simply query whole dataset
        return f"{dataset_name}-*"

    if isinstance(index, Text):
        # prefix single index
        return f"{dataset_name}-{index}"

    # prefix index list
    return [f"{dataset_name}-{i}" for i in index]
