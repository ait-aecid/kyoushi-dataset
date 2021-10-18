"""
This module contains utility functions used with and supporting template rendering
as part of the processing pipeline and labeling rules.
"""

import functools
import re

from datetime import (
    datetime,
    timedelta,
)
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
from jinja2.runtime import Context
from pydantic import parse_obj_as

from .config import DatasetConfig
from .utils import (
    resolve_indices,
    write_config_file,
)


def regex(
    value: str = "",
    pattern: str = "",
    ignorecase: bool = False,
    multiline: bool = False,
    match_type: str = "search",
) -> bool:
    """Expose `re` as a boolean filter using the `search` method by default.
    This is likely only useful for `search` and `match` which already
    have their own filters.

    !!! Note
        Taken from Ansible

    Args:
        value: The string to search in
        pattern: The pattern to search
        ignorecase: If the case should be ignored or not
        multiline: If multiline matching should be used or not
        match_type: The re pattern match type to use

    Returns:
        `True` if a match was found `False` otherwise.
    """
    flags = 0
    if ignorecase:
        flags |= re.I
    if multiline:
        flags |= re.M
    _re = re.compile(pattern, flags=flags)
    return bool(getattr(_re, match_type, "search")(value))


def regex_match(
    value: str, pattern: str = "", ignorecase: bool = False, multiline: bool = False
) -> bool:
    """Perform a `re.match` returning a boolean

    !!! Note
        Taken from Ansible

    Args:
        value: The string to search in
        pattern: The pattern to search
        ignorecase: If the case should be ignored or not
        multiline: If multiline matching should be used or not

    Returns:
        `True` if a match was found `False` otherwise.
    """
    return regex(value, pattern, ignorecase, multiline, "match")


def regex_search(
    value: str, pattern: str = "", ignorecase: bool = False, multiline: bool = False
) -> bool:
    """Perform a `re.search` returning a boolean

    !!! Note
        Taken from Ansible

    Args:
        value: The string to search in
        pattern: The pattern to search
        ignorecase: If the case should be ignored or not
        multiline: If multiline matching should be used or not

    Returns:
        `True` if a match was found `False` otherwise.
    """
    return regex(value, pattern, ignorecase, multiline, "search")


def match_any(value: str, regex_list: List[str]) -> bool:
    """Perform multiple `re.match` and return `True` if at least on match is found.

    Args:
        value: The string to search in
        regex_list: Lis tof patterns to try matching

    Returns:
        `True` if at least one pattern matches `False` otherwise
    """
    return any(re.match(regex, value) for regex in regex_list)


def elastic_dsl_search(
    using: Elasticsearch,
    dataset_name: Optional[str] = None,
    prefix_dataset_name: bool = True,
    index: Optional[Union[Sequence[str], str]] = None,
    **kwargs,
) -> Search:
    """Create an Elasticsearch DSL search object.

    Args:
        using: The elasticsearch client object
        dataset_name: The dataset name
        prefix_dataset_name: If the dataset name should be prefixed to the indices or not
        index: The indices to create the search object for

    Returns:
        Configured elasticsearch DSL search object
    """
    _index = resolve_indices(dataset_name, prefix_dataset_name, index)
    return Search(using=using, index=_index, **kwargs)


def q_all(qry_type: str, **kwargs) -> Q:
    """Create elasticsearch DSL bool term requiring all given terms to be true.

    Args:
        qry_type: The DSL query term type

    Returns:
        The configured DSL query term
    """
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
) -> Dict[str, Any]:
    """Perform an Elasticsearch EQL query.

    Args:
        es: The elasticsearch client object
        body: The EQL query body
        dataset_name: The dataset name
        prefix_dataset_name: If the dataset name should be prefixed to the indices or not
        index: The indices to perform the query on.

    Returns:
        The EQL query result
    """
    _index = resolve_indices(dataset_name, prefix_dataset_name, index)
    eql = EqlClient(es)
    return eql.search(index=_index, body=body)


@contextfunction
def get_context(c: Context) -> Context:
    """Utility function for getting the Jinja2 context.

    Args:
        c: The Jinja2 context

    Returns:
        The Jinja2 context
    """
    return c


def as_datetime(v: str) -> datetime:
    """Utility filter for converting a string to datetime.

    Args:
        v: The string to convert

    Returns:
        Converted datetime object.
    """
    return parse_obj_as(datetime, v)


def create_environment(
    templates_dirs: Optional[Union[Text, Path, List[Union[Text, Path]]]] = None,
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
) -> NativeEnvironment:
    """Create Jinja2 native environment for rendering dataset templates.

    Args:
        templates_dirs: The template directories
        es: The elasticsearch client object
        dataset_config: The dataset configuration

    Returns:
        Jinja2 template environment
    """

    if templates_dirs is None:
        templates_dirs = [
            Path("./templates"),
            Path("./"),
        ]

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

    custom_filters = {
        "as_datetime": as_datetime,
    }

    custom_globals = {
        "context": get_context,
        "datetime": datetime,
        "timedelta": timedelta,
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
        custom_globals["Search"] = search_function
        custom_globals["Q"] = Q
        custom_globals["Q_ALL"] = q_all
        custom_globals["Q_MATCH_ALL"] = functools.partial(q_all, "match")
        custom_globals["Q_TERM_ALL"] = functools.partial(q_all, "term")
        custom_globals["EQL"] = eql_function

    env.tests.update(custom_tests)
    env.filters.update(custom_filters)
    env.globals.update(custom_globals)

    return env


def render_template(
    template: Union[Text, Path],
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
) -> Any:
    """Renders a dataset Jinja2 template string or file.

    Args:
        template: The template string or file
        variables: The context variables to use for rendering
        es: The elasticsearch client object
        dataset_config: The dataset configuration

    Returns:
        The rendered Jinja2 template
    """
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


def render_template_recursive(
    data: Any,
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
) -> Any:
    """Renders a complex object containing Jinja2 templates

    The complex object can be either a string, list or dictionary.
    This function will recurse all sub elements (e.g., dictionary values)
    and render any Jinja2 template strings it finds.

    Args:
        data: The object to render
        variables: The context variables to use for rendering
        es: The elasticsearch client object
        dataset_config: The dataset configuration

    Returns:
        The object with all its Jinja2 templates rendered.
    """

    # handle sub dicts
    if isinstance(data, dict):
        data_rendered = {}
        for key, val in data.items():
            # for sub dicts keys we also allow temp
            key = render_template_recursive(key, variables, es, dataset_config)
            val = render_template_recursive(val, variables, es, dataset_config)
            data_rendered[key] = val
        return data_rendered

    # handle list elements
    if isinstance(data, list):
        return [
            render_template_recursive(val, variables, es, dataset_config)
            for val in data
        ]

    # handle str and template strings
    if isinstance(data, str):
        return render_template(data, variables, es, dataset_config)

    # all other basic types are returned as is
    return data


def write_template(
    src: Path,
    dest: Path,
    variables: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
    dataset_config: Optional[DatasetConfig] = None,
):
    """Render and write a dataset Jinja2 template file.

    Args:
        src: The template source
        dest: The file to write the rendered string to
        variables: The variable context to use for rendering
        es: The elasticsearch client object
        dataset_config: The dataset configuration
    """
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
