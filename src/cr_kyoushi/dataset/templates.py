from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Text,
    Union,
)

from elasticsearch import Elasticsearch
from jinja2 import (
    FileSystemLoader,
    StrictUndefined,
    Undefined,
)
from jinja2.nativetypes import NativeEnvironment


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


def render_template(
    template: Union[Text, Path],
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
) -> Any:
    # get jinja2 environment
    env = create_environment(es=es)

    # convert strings to template
    if isinstance(template, Path):
        _template = env.get_template(str(template))
    else:
        _template = env.from_string(template)

    value = _template.render(**variables)

    if isinstance(value, Undefined):
        value._fail_with_undefined_error()
    return value


def write_template(
    src: Path,
    dest: Path,
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
):
    template_rendered = render_template(src, variables, es)

    with open(dest, "w") as dest_file:
        dest_file.write(template_rendered)
    # render template and write to file
