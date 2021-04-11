import functools
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
from elasticsearch.client.eql import EqlClient
from elasticsearch_dsl.query import (
    Q,
    Query,
)
from elasticsearch_dsl.search import Search
from jinja2 import (
    ChoiceLoader,
    FileSystemLoader,
    PackageLoader,
    StrictUndefined,
    Undefined,
    contextfunction,
)
from jinja2.nativetypes import NativeEnvironment

from .config import DatasetConfig
from .utils import (
    resolve_indices,
    write_config_file,
)


def regex(value="", pattern="", ignorecase=False, multiline=False, match_type="search"):
    """Expose `re` as a boolean filter using the `search` method by default.
    This is likely only useful for `search` and `match` which already
    have their own filters.

    !!! Note
        Taken from Ansible
    """
    flags = 0
    if ignorecase:
        flags |= re.I
    if multiline:
        flags |= re.M
    _re = re.compile(pattern, flags=flags)
    return bool(getattr(_re, match_type, "search")(value))


def regex_match(value, pattern="", ignorecase=False, multiline=False):
    """Perform a `re.match` returning a boolean

    !!! Note
        Taken from Ansible
    """
    return regex(value, pattern, ignorecase, multiline, "match")


def regex_search(value, pattern="", ignorecase=False, multiline=False):
    """Perform a `re.search` returning a boolean

    !!! Note
        Taken from Ansible
    """
    return regex(value, pattern, ignorecase, multiline, "search")


def match_any(value: str, regex_list: List[str]) -> bool:
    return any(re.match(regex, value) for regex in regex_list)


def elastic_dsl_search(
    using: Elasticsearch,
    dataset_name: Optional[str] = None,
    prefix_dataset_name: bool = True,
    index: Optional[Union[Sequence[str], str]] = None,
    **kwargs,
) -> Search:
    _index = resolve_indices(dataset_name, prefix_dataset_name, index)
    return Search(using=using, index=_index, **kwargs)


def q_all(qry_type: str, **kwargs) -> Q:
    must = []
    for key, val in kwargs.items():
        if isinstance(val, Query):
            must.append(val)
        else:
            must.append(Q(qry_type, **{key: val}))
    return Q("bool", must=must)


def elastic_eql_search(
    es: Elasticsearch,
    body: Dict[str, Any],
    dataset_name: Optional[str] = None,
    prefix_dataset_name: bool = True,
    index: Optional[Union[Sequence[str], str]] = None,
):
    _index = resolve_indices(dataset_name, prefix_dataset_name, index)
    eql = EqlClient(es)
    return eql.search(index=_index, body=body)


@contextfunction
def get_context(c):
    return c


def create_environment(
    templates_dirs: Union[Text, Path, List[Union[Text, Path]]] = [
        Path("./templates"),
        Path("./"),
    ],
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
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
        "regex": regex,
        "regex_search": regex_search,
        "regex_match": regex_match,
    }

    custom_globals = {
        "context": get_context,
    }

    if es is not None:
        if dataset_config is not None:
            search_function = functools.partial(
                elastic_dsl_search, using=es, dataset_name=dataset_config.name
            )
            eql_function = functools.partial(
                elastic_eql_search, es=es, dataset_name=dataset_config.name
            )
        else:
            search_function = functools.partial(elastic_dsl_search, using=es)
            eql_function = functools.partial(elastic_eql_search, es=es)
        custom_globals["Search"] = search_function  # type: ignore
        custom_globals["Q"] = Q
        custom_globals["Q_ALL"] = q_all  # type: ignore
        custom_globals["Q_MATCH_ALL"] = functools.partial(q_all, "match")  # type: ignore
        custom_globals["Q_TERM_ALL"] = functools.partial(q_all, "term")  # type: ignore
        custom_globals["EQL"] = eql_function  # type: ignore

    env.tests.update(custom_tests)
    env.globals.update(custom_globals)

    return env


def render_template(
    template: Union[Text, Path],
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
) -> Any:
    # get jinja2 environment
    env = create_environment(es=es, dataset_config=dataset_config)

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
    dataset_config: Optional[DatasetConfig] = None,
):
    template_rendered = render_template(src, variables, es, dataset_config)
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
