from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Text,
    Union,
)

from elasticsearch import Elasticsearch
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
)
from jinja2.nativetypes import NativeEnvironment

from .utils import load_file


def load_variables(sources: Union[Path, Dict[str, Union[Path]]]):
    if isinstance(sources, dict):
        variables = {}
        for key, path in sources.items():
            variables[key] = load_file(path)
        return variables
    else:
        return load_file(sources)


def create_environment(
    templates_dirs: Union[Text, Path, List[Union[Text, Path]]] = [
        Path("./templates"),
        Path("./"),
    ],
    es: Optional[Elasticsearch] = None,
) -> NativeEnvironment:
    env = NativeEnvironment(
        loader=FileSystemLoader(templates_dirs),
        undefined=StrictUndefined,
    )
    return env
