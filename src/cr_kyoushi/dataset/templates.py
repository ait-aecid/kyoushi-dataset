import re

from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Text,
    Union,
)

from elasticsearch import Elasticsearch
from jinja2 import (
    ChoiceLoader,
    FileSystemLoader,
    PackageLoader,
    StrictUndefined,
    Undefined,
    contextfunction,
)
from jinja2.nativetypes import NativeEnvironment

from .utils import write_config_file


def match_any(value: str, regex_list: List[str]) -> bool:
    return any(re.match(regex, value) for regex in regex_list)


@contextfunction
def get_context(c):
    return c


def create_environment(
    templates_dirs: Union[Text, Path, List[Union[Text, Path]]] = [
        Path("./templates"),
        Path("./"),
    ],
    es: Optional[Elasticsearch] = None,
) -> NativeEnvironment:
    env_loader = ChoiceLoader(
        [
            FileSystemLoader(templates_dirs),
            PackageLoader("cr_kyoushi.dataset", "templates"),
        ]
    )
    env = NativeEnvironment(
        loader=env_loader,
        undefined=StrictUndefined,
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
    )
    custom_tests = {
        "match_any": match_any,
    }

    custom_globals = {
        "context": get_context,
    }

    env.tests.update(custom_tests)
    env.globals.update(custom_globals)

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
    if (
        # mappings are converted to json or yaml
        isinstance(template_rendered, Mapping)
        # lists are also converted to json
        or (
            # need to exclude str types as they are also sequences
            not isinstance(template_rendered, Text)
            and isinstance(template_rendered, Sequence)
        )
    ):
        write_config_file(template_rendered, dest)
    # everything else is coerced to string and written as is
    else:
        with open(dest, "w") as dest_file:
            dest_file.write(str(template_rendered))
