"""
This module contains labeling rule implementations and utility
functions used during the labeling process
"""

import json
import sys
import warnings

from pathlib import Path
from time import sleep
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Sequence,
    Text,
    Union,
)

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import RequestError as ElasticsearchRequestError
from elasticsearch_dsl import (
    Keyword,
    Mapping,
    Search,
    UpdateByQuery,
)
from elasticsearch_dsl.connections import get_connection
from elasticsearch_dsl.exceptions import UnknownDslObject
from elasticsearch_dsl.response.aggs import Bucket
from elasticsearch_dsl.response.hit import Hit
from pydantic import (
    BaseModel,
    Field,
    root_validator,
    validator,
)
from pydantic.error_wrappers import (
    ErrorWrapper,
    ValidationError,
)

from . import LAYOUT
from .config import DatasetConfig
from .elasticsearch import (
    scan_composite,
    search_eql,
)
from .templates import (
    render_template,
    render_template_recursive,
)
from .utils import resolve_indices


if sys.version_info >= (3, 8):
    from typing import (
        Protocol,
        runtime_checkable,
    )
else:
    from typing_extensions import (
        Protocol,
        runtime_checkable,
    )

UPDATE_SCRIPT = """
boolean updated = false;
String labels_flat = params.labels.join(";");
// this should only happen once when we first encounter a line
if (
    ctx._source.{{ label_object }} == null ||
    ctx._source.{{ label_object }}.list == null ||
    ctx._source.{{ label_object }}.flat == null ||
    ctx._source.{{ label_object }}.rules == null
) {
    ctx._source.{{ label_object }} = [:];
    ctx._source.{{ label_object }}.list = [:];
    ctx._source.{{ label_object }}.flat = [:];
    ctx._source.{{ label_object }}.rules = [];
}
if (ctx._source.{{ label_object }}.flat[params.rule] != labels_flat) {
    ctx._source.{{ label_object }}.list[params.rule] = params.labels;
    ctx._source.{{ label_object }}.flat[params.rule] = labels_flat;
    if (!ctx._source.{{ label_object }}.rules.contains(params.rule)) {
        ctx._source.{{ label_object }}.rules.add(params.rule)
    }
    updated = true;
}
if (!updated) {
    ctx.op = "noop";
}
"""

LABEL_FILTER_SCRIPT = """
boolean found;
for (label in params.labels) {
    // rows that are not labeled do not have the key
    found = false;
    for (rule in doc["{{ label_object }}.rules"]) {
        found = doc["{{ label_object }}.list."+rule].contains(label);
        if (found) {
            break;
        }
    }
    // if found is false here then we did not find the current label
    if (!found) {
        return false;
    }
}
return true;
"""

LABELS_FIELD_SCRIPT = """
doc["{{ label_object }}.rules"].stream()
    .flatMap(l -> doc["{{ label_object }}.list."+l].stream())
    .distinct()
    .sorted()
    .collect(Collectors.toList());
"""

LABELS_AGGREGATES_FIELD_SCRIPT = """
// ensure we only emit each label once
List labels = doc["kyoushi_labels.rules"]
    .stream()
    .flatMap(
        l -> doc["kyoushi_labels.list."+l].stream()
    ).distinct()
    .collect(Collectors.toList());
for (label in labels) {
     emit(label);
}
"""


def create_kyoushi_scripts(
    es: Elasticsearch,
    dataset_name: str,
    label_object: str = "kyoushi_labels",
):
    """Utility function for creating labeling update, filter and field scripts.

    Args:
        es: The elasticsearch client object
        dataset_name: The name of the dataset to create the scripts for.
                      This is used as prefix for script names to ensure
                      different versions of these scripts can exist for
                      different datasets in the same Elasticsearch instance.
        label_object: The name of field to store labeling information in.
    """
    update_script = {
        "script": {
            "description": "Kyoushi Dataset - Update by Query label script",
            "lang": "painless",
            "source": UPDATE_SCRIPT.replace("{{ label_object }}", label_object),
        }
    }
    es.put_script(
        id=f"{dataset_name}_kyoushi_label_update", body=update_script, context="update"
    )

    filter_script = {
        "script": {
            "lang": "painless",
            "source": LABEL_FILTER_SCRIPT.replace("{{ label_object }}", label_object),
        }
    }
    es.put_script(
        id=f"{dataset_name}_kyoushi_label_filter",
        body=filter_script,
        context="filter",
    )

    labels_field = {
        "script": {
            "lang": "painless",
            "source": LABELS_FIELD_SCRIPT.replace("{{ label_object }}", label_object),
        }
    }

    es.put_script(
        id=f"{dataset_name}_kyoushi_label_field",
        body=labels_field,
        context="field",
    )


def apply_labels_by_update_dsl(
    update: UpdateByQuery,
    script_params: Dict[str, Any],
    update_script_id: str,
    check_interval: float = 0.5,
) -> int:
    """Utility function for applying labels based on a DSL query object.

    The function takes a update by query object and uses the Cyber Range Kyoushi
    label update script to apply the given labels to all matching rows. This
    function is blocking as it waits for the process to complete.

    Args:
        update: The update by query object containing the DSL query.
        script_params: The parameters for the label update script.
        update_script_id: The label update script to use
        check_interval: The amount in time between the status checks.

    Returns:
        The number of updated rows.
    """
    # refresh=True is important so that consecutive rules
    # have a consitant state
    es: Elasticsearch = get_connection(update._using)

    # add update script
    update = update.script(id=update_script_id, params=script_params)

    # run update task
    task = update.params(refresh=True, wait_for_completion=False).execute().task
    task_info = es.tasks.get(task_id=task)

    while not task_info["completed"]:
        sleep(check_interval)
        task_info = es.tasks.get(task_id=task)

    with warnings.catch_warnings():
        # ToDo: Elasticsearch (7.12) does not provide any API to delete update by query tasks
        #       The only option is to delete the document directly this will be deprecated
        #       and as such gives warnings. For now we ignore these and wait for elasticsearch
        #       to provide an API for it.
        warnings.simplefilter("ignore")
        es.delete(index=".tasks", doc_type="task", id=task)
    return task_info["response"]["updated"]


def apply_labels_by_query(
    es: Elasticsearch,
    query: Dict[str, Any],
    script_params: Dict[str, Any],
    update_script_id: str,
    index: Union[List[str], str] = "_all",
    check_interval: float = 0.5,
) -> int:
    """Utility function for applying labels based on a DSL query.

    Args:
        es: The elasticsearch client object
        query: The DSL query dict
        script_params: The parameters for the label update script.
        update_script_id: The label update script to use
        index: The indices to query
        check_interval: The amount in time between the status checks.

    Returns:
        The number of updated rows.
    """
    update = UpdateByQuery(using=es, index=index)
    update = update.update_from_dict(query)
    return apply_labels_by_update_dsl(
        update, script_params, update_script_id, check_interval
    )


def get_label_counts(
    es: Elasticsearch,
    index: Union[List[str], str, None] = None,
    label_object: str = "kyoushi_labels",
) -> List[Bucket]:
    """Utility function for getting number of rows per label.

    Args:
        es: The elasticsearch client object
        index: The indices to get the information for
        label_object: The field containing the label information

    Returns:
        List of result buckets
    """
    # disable request cache to ensure we always get latest info
    search_labels = Search(using=es, index=index).params(request_cache=False)
    runtime_mappings = {
        "labels": {
            "type": "keyword",
            "script": LABELS_AGGREGATES_FIELD_SCRIPT,
        }
    }
    search_labels = search_labels.extra(runtime_mappings=runtime_mappings)

    # setup aggregations
    search_labels.aggs.bucket(
        "labels",
        "composite",
        sources=[{"label": {"terms": {"field": "labels"}}}],
    )

    search_labels.aggs["labels"].bucket("file", "terms", field="log.file.path")

    return scan_composite(search_labels, "labels")


class LabelException(Exception):
    """Generic exception for errors during labeling phase."""


@runtime_checkable
class Rule(Protocol):
    """Interface definition for labeling rules."""

    type_: ClassVar[str]
    """The unique rule type."""

    id_: str
    """The rule id."""

    labels: List[str]
    """List of labels to apply on rule match."""

    description: Optional[str]
    """Free text description of the rule."""

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the configured rule and assigns the labels to all matching rows.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the rule was applied to
        """
        ...

    def update_params(self) -> Dict[str, Any]:
        """Gets the update script parameters required for this rule.

        Returns:
            The update script parameters.
        """
        ...


class RuleBase(BaseModel):
    """Pydantic base model for labeling rules.

    This class can be extended to define custom labeling rules.
    """

    type_: ClassVar[str] = Field(..., description="The rule type")
    type_field: str = Field(
        ...,
        description="The rule type as passed in from the config",
        alias="type",
    )
    id_: str = Field(
        ...,
        description="The unique rule id",
        alias="id",
    )
    labels: List[str] = Field(
        ...,
        description="The list of labels to apply to log lines matching this rule",
    )
    description: Optional[str] = Field(
        None, description="An optional description for the rule"
    )

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the configured rule and assigns the labels to all matching rows.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the rule was applied to
        """

        raise NotImplementedError()

    def update_params(self) -> Dict[str, Any]:
        """Gets the update script parameters required for this rule.

        Returns:
            The update script parameters.
        """

        return {
            "rule": self.id_,
            "labels": self.labels,
        }

    @validator("labels", each_item=True)
    def validate_label_no_semicolon(cls, val: str) -> str:
        """Validator ensuring label names do not contain `;`.

        Args:
            val: A single label

        Returns:
            The validated label
        """
        assert ";" not in val, f"Labels must not contain semicolons, but got '{val}'"
        return val


class RuleList(BaseModel):
    """Model definition of a list of labeling rules."""

    __root__: List[RuleBase]
    """The root type"""

    def __iter__(self):
        return iter(self.__root__)

    def __getitem__(self, item):
        return self.__root__[item]

    @root_validator
    def check_rule_ids_uniq(
        cls, values: Dict[str, List[RuleBase]]
    ) -> Dict[str, List[RuleBase]]:
        """Validator for ensuring that rule IDs are unique.

        Args:
            values: The model dictionary

        Returns:
            The validated model dictionary
        """
        duplicates = set()
        temp = []
        if "__root__" in values:
            for r in values["__root__"]:
                if r.id_ in temp:
                    duplicates.add(r.id_)
                else:
                    temp.append(r.id_)
            assert (
                len(duplicates) == 0
            ), f"Rule IDs must be uniq, but got duplicates: {duplicates}"
        return values


class NoopRule(RuleBase):
    """A noop rule that does absolutely nothing."""

    type_: ClassVar[str] = "noop"

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the NoopRule i.e., does nothing.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            Always returns 0 since nothing happens.
        """
        return 0


class QueryBase(BaseModel):
    """Base model for DSL query based labeling rules"""

    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    query: Union[List[Dict[str, Any]], Dict[str, Any]] = Field(
        ...,
        description=(
            "The query/s to use for identifying log lines to apply the tags to."
        ),
    )
    filter_: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(
        None,
        description=(
            "The filter/s to limit queried to documents to "
            "only those that match the filters"
        ),
        alias="filter",
    )
    exclude: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(
        None,
        description="Similar to filters, but used to exclude results",
    )

    indices_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. "
            "This is a convenience setting as per default all dataset indices start "
            "with this prefix."
        ),
    )

    @validator("query")
    def validate_queries(
        cls, value: Union[List[Dict[str, Any]], Dict[str, Any]], values: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Validator checking DSL syntax

        Args:
            value: The DSL query
            values: The model dictionary

        Raises:
            ValidationError: Should the given query be invalid

        Returns:
            The validated query
        """
        # temporary update by query object used to validate the input queries
        _temp = UpdateByQuery()
        errors = []
        if not isinstance(value, List):
            value = [value]
        for i, query in enumerate(value):
            try:
                _temp = _temp.query(query)
            except (TypeError, UnknownDslObject, ValueError) as e:
                errors.append(ErrorWrapper(e, (i,)))
        if len(errors) > 0:
            raise ValidationError(errors, UpdateByQueryRule)
        return value

    @validator("filter_")
    def validate_filter(
        cls, value: Union[List[Dict[str, Any]], Dict[str, Any]], values: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Validator to check the DSL query filter syntax

        Args:
            value: The DSL filter
            values: The model dictionary

        Raises:
            ValidationError: Should the filter not be valid

        Returns:
            The validated filter
        """
        # temporary update by query object used to validate the input filters
        _temp = UpdateByQuery()
        errors = []
        if not isinstance(value, List):
            value = [value]
        for i, filter_ in enumerate(value):
            try:
                _temp = _temp.filter(filter_)
            except (TypeError, UnknownDslObject, ValueError) as e:
                errors.append(ErrorWrapper(e, (i,)))
        if len(errors) > 0:
            raise ValidationError(errors, UpdateByQueryRule)
        return value

    @validator("exclude")
    def validate_exclude(
        cls, value: Union[List[Dict[str, Any]], Dict[str, Any]], values: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Validator to check the DSL query exclude syntax

        Exclude is simply a negative filter clause i.e.,
        not (DSL QUERY).

        Args:
            value: The DSL exclude
            values: The model dictionary

        Raises:
            ValidationError: Should the exclude not be valid

        Returns:
            The validated exclude
        """
        # temporary update by query object used to validate the input excludes
        _temp = UpdateByQuery()
        errors = []
        if not isinstance(value, List):
            value = [value]
        for i, exclude in enumerate(value):
            try:
                _temp = _temp.exclude(exclude)
            except (TypeError, UnknownDslObject, ValueError) as e:
                errors.append(ErrorWrapper(e, (i,)))
        if len(errors) > 0:
            raise ValidationError(errors, UpdateByQueryRule)
        return value


class UpdateByQueryRule(RuleBase, QueryBase):
    """Applies labels based on a simple Elasticsearch DSL query.

    Example:
        ```yaml
        - type: elasticsearch.query
          id: attacker.foothold.vpn.ip
          labels:
            - attacker_vpn
            - foothold
          description: >-
            This rule applies the labels to all openvpn log rows that have
            the attacker server as source ip and are within the foothold phase.
          index:
            - openvpn-vpn
          filter:
            range:
            "@timestamp":
                # foothold phase start
                gte: "2021-03-23 20:31:00+00:00"
                # foothold phase stop
                lte: "2021-03-23 21:13:52+00:00"
          query:
            - match:
                source.ip: '192.42.0.255'
        ```
    """

    type_: ClassVar[str] = "elasticsearch.query"
    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the labels to all rows matching the DSL query.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the labels were applied to.
        """
        index: Optional[Union[Sequence[str], str]] = resolve_indices(
            dataset_config.name, self.indices_prefix_dataset, self.index
        )
        update = UpdateByQuery(using=es, index=index)

        # ensure we have lists
        if not isinstance(self.query, List):
            self.query = [self.query]
        if not isinstance(self.filter_, List):
            self.filter_ = [self.filter_] if self.filter_ is not None else []
        if not isinstance(self.exclude, List):
            self.exclude = [self.exclude] if self.exclude is not None else []

        # exclude already correctly labeled rows from the result set
        update = update.exclude(
            "term",
            **{f"{label_object}.flat.{self.id_}": ";".join(self.labels)},
        )

        for _query in self.query:
            update = update.query(_query)
        for _filter in self.filter_:
            update = update.filter(_filter)
        for _exclude in self.exclude:
            update = update.exclude(_exclude)

        result = apply_labels_by_update_dsl(
            update, self.update_params(), update_script_id
        )

        return result


def render_query_base(hit: Hit, query: QueryBase) -> QueryBase:
    """Utility function for rendering sub or parent query.

    Args:
        hit: The Elasticsearch query result row to render for.
        query: The templated query definition.

    Returns:
        The rendered DSL query
    """
    variables = {"HIT": hit}

    # render the index var
    if isinstance(query.index, str):
        query.index = render_template(query.index, variables)
    elif isinstance(query.index, Sequence):
        query.index = [render_template(i, variables) for i in query.index]

    # ensure we have lists
    if not isinstance(query.query, List):
        query.query = [query.query]
    if not isinstance(query.filter_, List):
        query.filter_ = [query.filter_] if query.filter_ is not None else []
    if not isinstance(query.exclude, List):
        query.exclude = [query.exclude] if query.exclude is not None else []

    query.query = [
        render_template_recursive(_query, variables) for _query in query.query
    ]
    query.filter_ = [
        render_template_recursive(_filter, variables) for _filter in query.filter_
    ]
    query.exclude = [
        render_template_recursive(_exclude, variables) for _exclude in query.exclude
    ]

    return query


class UpdateSubQueryRule(RuleBase, QueryBase):
    """Labeling rule that labels the results of multiple sub queries.

    This labeling rule first executes a base query to retrieve information.
    It then renders and executes a templated sub query for each row retrieved
    from the base query. The result rows of these dynamically generated sub queries
    are then labled.

    !!! Note
        The sub query uses Jinja2 syntax for templating. The information retrieved
        by the base query can be accessed through the `HIT` variable.

    Example:
        ```yaml
        - type: elasticsearch.sub_query
          id: attacker.foothold.apache.access_dropped
          labels:
            - attacker_http
            - foothold
          description: >-
            This rule tries to match attacker requests that we where unable to
            match to a labeled response with access log entries. Such cases can
            happen if the corresponding response gets lost in the network or
            otherwise is not sent.
          index:
            - pcap-attacker_0
          # obligatory match all
          query:
            - term:
                destination.ip: "172.16.0.217"
          filter:
            - term:
                event.category: http
            - term:
                event.action: request
            # we are looking for requests that have not been marked as attacker http yet
            # most likely they did not have a matching response due to some network error
            # or timeout
            - bool:
                must_not:
                - script:
                    script:
                        id: test_dataset_kyoushi_label_filter
                        params:
                        labels: [attacker_http]
          sub_query:
            index:
              - apache_access-intranet_server
            query:
              - term:
                  url.full: "{{ HIT.url.full }}"
              - term:
                  source.address: "172.16.100.151"
            filter:
              - range:
                  "@timestamp":
                    # the access log entry should be after the request, but since the access log
                    # does not have microseconds we drop them here as well
                    gte: "{{ (HIT['@timestamp'] | as_datetime).replace(microsecond=0) }}"
                    # the type of error we are looking for should create an access log entry almost immediately
                    # se we keep the time frame short
                    lte: "{{ ( HIT['@timestamp'] | as_datetime).replace(microsecond=0) + timedelta(seconds=1) }}"
        ```

    """

    type_: ClassVar[str] = "elasticsearch.sub_query"
    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    sub_query: QueryBase = Field(
        ...,
        description=(
            "The templated sub query to use to apply the labels. "
            "Executed for each hit of the parent query."
        ),
    )

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the labels to all rows matching the created sub queries.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the labels were applied to.
        """
        index: Optional[Union[Sequence[str], str]] = resolve_indices(
            dataset_config.name, self.indices_prefix_dataset, self.index
        )

        search = Search(using=es, index=index )

        # ensure we have lists
        if not isinstance(self.query, List):
            self.query = [self.query]
        if not isinstance(self.filter_, List):
            self.filter_ = [self.filter_] if self.filter_ is not None else []
        if not isinstance(self.exclude, List):
            self.exclude = [self.exclude] if self.exclude is not None else []

        # exclude already correctly labeled rows from the result set
        search = search.exclude(
            "term",
            **{f"{label_object}.flat.{self.id_}": ";".join(self.labels)},
        )

        for _query in self.query:
            search = search.query(_query)
        for _filter in self.filter_:
            search = search.filter(_filter)
        for _exclude in self.exclude:
            search = search.exclude(_exclude)

        result = 0
        for hit in search.params(scroll='30m').scan():
            # make deep copy of sub query so we can template it
            sub_query = self.sub_query.copy(deep=True)

            # render the subquery
            sub_query = render_query_base(hit, sub_query)

            sub_rule = UpdateByQueryRule(
                type="elasticsearch.query",
                id=self.id_,
                labels=self.labels,
                description=self.description,
                index=sub_query.index,
                query=sub_query.query,
                filter=sub_query.filter_,
                exclude=sub_query.exclude,
                indices_prefix_dataset=sub_query.indices_prefix_dataset,
            )
            result += sub_rule.apply(
                dataset_dir, dataset_config, es, update_script_id, label_object
            )
        return result


class UpdateParentQueryRule(RuleBase, QueryBase):
    """Applies the labels to all rows of a base query for which
    a parent query returns results.

    This labeling rule first executes a base query to retrieve rows we might want
    to apply labels to. It then renders and executes a templated parent query
    for each retrieved row. The parent queries are then used to indicate if
    the initial result row should be labeled or not. By default result rows of the
    base query are labeled if the corresponding parent query returns at leas *one*
    row. It is possible to configure this minimum number e.g., to require at least
    two results.

    !!! Note
        The sub query uses Jinja2 syntax for templating. The information retrieved
        by the base query can be accessed through the `HIT` variable.

    Example:
        ```yaml
        - type: elasticsearch.parent_query
          id: attacker.foothold.apache.error_access
          labels:
            - attacker_http
            - foothold
          description: >-
            This rule looks for unlabeled error messages resulting from VPN server
            traffic within the attack time and tries to match it to an already labeled
            access log row.
          index:
            - apache_error-intranet_server
          query:
            match:
            source.address: "172.16.100.151"
          filter:
            # use script query to match only entries that
            # are not already tagged for as attacker http in the foothold phase
            - bool:
                must_not:
                - script:
                    script:
                        id: test_dataset_kyoushi_label_filter
                        params:
                        labels: [attacker_http]
          parent_query:
            index:
              - apache_access-intranet_server
            query:
              - term:
                  url.full: "{{ HIT.url.full }}"
              - term:
                  source.address: "{{ HIT.source.address }}"
            # we are looking for parents that are labeled as attacker http
              - bool:
                  must:
                    - script:
                        script:
                          id: test_dataset_kyoushi_label_filter
                          params:
                            labels: [attacker_http]
            filter:
              - range:
                # parent must be within +-1s of potential child
                  "@timestamp":
                     gte: "{{ (HIT['@timestamp'] | as_datetime) - timedelta(seconds=1) }}"
                     lte: "{{ ( HIT['@timestamp'] | as_datetime) + timedelta(seconds=1) }}"
        ```

    """

    type_: ClassVar[str] = "elasticsearch.parent_query"
    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    parent_query: QueryBase = Field(
        ...,
        description="The templated parent query to check if the labels should be applied to a query hit.",
    )

    min_match: int = Field(
        1,
        description="The minimum number of parent matches needed for the main query to be labeled.",
    )

    max_result_window: int = Field(
        10000,
        description="The max result window allowed on the elasticsearch instance",
    )

    def check_parent(
        self,
        parent_query: QueryBase,
        min_match: int,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
    ) -> bool:
        """Executes a parent query and returns if there were enough result rows.

        Args:
            parent_query: The parent query to execute
            min_match: The minimum number of result rows required
            dataset_config: The dataset configuration
            es: The elasticsearch client object

        Returns:
            `True` if the query returned >= min_match rows and `False` otherwise.
        """
        index: Optional[Union[Sequence[str], str]] = resolve_indices(
            dataset_config.name, parent_query.indices_prefix_dataset, parent_query.index
        )
        search = Search(using=es, index=index)

        # ensure we have lists
        if not isinstance(parent_query.query, List):
            parent_query.query = [parent_query.query]
        if not isinstance(parent_query.filter_, List):
            parent_query.filter_ = (
                [parent_query.filter_] if parent_query.filter_ is not None else []
            )
        if not isinstance(parent_query.exclude, List):
            parent_query.exclude = (
                [parent_query.exclude] if parent_query.exclude is not None else []
            )

        for _query in parent_query.query:
            search = search.query(_query)
        for _filter in parent_query.filter_:
            search = search.filter(_filter)
        for _exclude in parent_query.exclude:
            search = search.exclude(_exclude)

        return search.execute().hits.total.value >= min_match

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the labels to result from the base query for which a parent was found.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the labels were applied to.
        """
        index: Optional[Union[Sequence[str], str]] = resolve_indices(
            dataset_config.name, self.indices_prefix_dataset, self.index
        )
        search = Search(using=es, index=index)

        # ensure we have lists
        if not isinstance(self.query, List):
            self.query = [self.query]
        if not isinstance(self.filter_, List):
            self.filter_ = [self.filter_] if self.filter_ is not None else []
        if not isinstance(self.exclude, List):
            self.exclude = [self.exclude] if self.exclude is not None else []

        # exclude already correctly labeled rows from the result set
        search = search.exclude(
            "term",
            **{f"{label_object}.flat.{self.id_}": ";".join(self.labels)},
        )

        for _query in self.query:
            search = search.query(_query)
        for _filter in self.filter_:
            search = search.filter(_filter)
        for _exclude in self.exclude:
            search = search.exclude(_exclude)

        result = 0
        update_map: Dict[str, List[str]] = {}
        _i = 0
        for hit in search.scan():
            _i += 1
            # make deep copy of parent query so we can template it
            parent_query = self.parent_query.copy(deep=True)

            # render the subquery
            parent_query = render_query_base(hit, parent_query)

            if self.check_parent(parent_query, self.min_match, dataset_config, es):
                update_map.setdefault(hit.meta.index, []).append(hit.meta.id)

        # add labels to each event per index
        for _index, ids in update_map.items():
            # split the update requests into chunks of at most max result window
            update_chunks = [
                ids[i : i + self.max_result_window]
                for i in range(0, len(ids), self.max_result_window)
            ]
            for chunk in update_chunks:
                update = UpdateByQuery(using=es, index=_index).query(
                    "ids", values=chunk
                )
                # apply labels to events
                result += apply_labels_by_update_dsl(
                    update, self.update_params(), update_script_id
                )

        return result


class EqlQueryBase(BaseModel):
    """Pydantic model representing an EQL query"""

    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    by: Optional[Union[List[str], str]] = Field(
        None, description="Optional global sequence by fields"
    )

    max_span: Optional[str] = Field(
        None,
        description=(
            "Optional max time span in which a sequence "
            "must occur to be considered a match"
        ),
    )

    until: Optional[str] = Field(
        None,
        description=(
            "Optional until event marking the end of valid sequences. "
            "The until event will not be labeled."
        ),
    )

    sequences: List[str] = Field(
        ...,
        description="Event sequences to search. Must contain at least two events.",
    )

    filter_: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(
        None,
        description=(
            "The filter/s to limit queried to documents to "
            "only those that match the filters"
        ),
        alias="filter",
    )

    event_category_field: str = Field(
        "event.category",
        description="The field used to categories events",
    )

    timestamp_field: str = Field(
        "@timestamp",
        description="The field containing the event timestamp",
    )

    tiebreaker_field: Optional[str] = Field(
        None,
        description=(
            "(Optional, string) Field used to sort hits with the "
            "same timestamp in ascending order."
        ),
    )

    batch_size: int = Field(
        1000,
        description=(
            "The amount of sequences to update with each batch. "
            "Cannot be bigger than `max_result_window`"
        ),
    )

    max_result_window: int = Field(
        10000,
        description="The max result window allowed on the elasticsearch instance",
    )

    indices_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. "
            "This is a convenience setting as per default all dataset indices start "
            "with this prefix."
        ),
    )

    def query(self) -> str:
        """Converts the EQL query object into an EQL query string.

        Returns:
            The query in EQL syntax
        """
        query = "sequence"

        if self.by is not None:
            if isinstance(self.by, Text):
                query += f" by {self.by}"
            elif len(self.by) > 0:
                query += f" by {', '.join(self.by)}"

        if self.max_span is not None:
            query += f" with maxspan={self.max_span}"

        for sequence in self.sequences:
            query += f"\n  {sequence}"

        if self.until is not None:
            query += f"\nuntil {self.until}"
        return query

    @validator("filter_")
    def validate_filter(
        cls, value: Union[List[Dict[str, Any]], Dict[str, Any]], values: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        # temporary update by query object used to validate the input filters
        _temp = Search()
        errors = []
        if not isinstance(value, List):
            value = [value]
        for i, filter_ in enumerate(value):
            try:
                _temp = _temp.query(filter_)
            except (TypeError, UnknownDslObject, ValueError) as e:
                errors.append(ErrorWrapper(e, (i,)))
        if len(errors) > 0:
            raise ValidationError(errors, UpdateByQueryRule)
        return value

    @validator("sequences")
    def validate_at_least_two(cls, value: List[str]) -> List[str]:
        assert (
            len(value) > 1
        ), "Need at least 2 sequences! Use `elasticsearch.query` if you only want 1 event."
        return value


class EqlSequenceRule(RuleBase, EqlQueryBase):
    """Applies labels to a sequence of log events defined by an EQL query.

    This labeling rule is defined as an
    [EQL query](https://www.elastic.co/guide/en/elasticsearch/reference/master/eql.html).
    Using this syntax it is possible to define a sequence of related events and retrieve
    them. All events part of retrieved sequences are then labeled.

    Example:
        ```yaml
        - type: elasticsearch.sequence
          id: attacker.webshell.upload.seq
          labels: [webshell_upload]
          description: >-
            This rule labels the web shell upload step by matching the 3 step sequence
            within the foothold phase.
          index:
            - apache_access-intranet_server
          # since we do these requests very fast
          # we need the line number as tie breaker
          tiebreaker_field: log.file.line
          by: source.address
          max_span: 2m
          filter:
            range:
              "@timestamp":
                # foothold phase start
                gte: "2021-03-23 20:31:00+00:00"
                # foothold phase stop
                lte: "2021-03-23 21:13:52+00:00"
          sequences:
            - '[ apache where event.action == "access" and url.original == "/" ]'
            - '[ apache where event.action == "access" and url.original == "/?p=5" ]'
            - '[ apache where event.action == "access" and http.request.method == "POST" and url.original == "/wp-admin/admin-ajax.php" ]'
        ```
    """

    type_: ClassVar[str] = "elasticsearch.sequence"

    def _make_body(self, label_object: str):
        filter_ = Search()

        # ensure filter is a list
        if not isinstance(self.filter_, List):
            self.filter_ = [self.filter_] if self.filter_ is not None else []

        # exclude already correctly labeled rows from the result set
        filter_ = filter_.query(
            "bool",
            must_not=[
                {"term": {f"{label_object}.flat.{self.id_}": ";".join(self.labels)}}
            ],
        )

        for _filter in self.filter_:
            filter_ = filter_.query(_filter)

        # since we add our label exclusion we always have a query object in filter_
        filter_query = filter_.to_dict()["query"]
        query = self.query()

        body = {
            "query": query,
            "size": int(self.max_result_window / len(self.sequences)),
            # set fetch size bigger than size, but at most max_result_window
            "fetch_size": min(int(self.batch_size * 1.5), self.max_result_window),
            "event_category_field": self.event_category_field,
            "timestamp_field": self.timestamp_field,
        }
        if len(filter_query) > 0:
            body["filter"] = filter_query

        if self.tiebreaker_field is not None:
            body["tiebreaker_field"] = self.tiebreaker_field

        return body

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        """Applies the labels to all events part of retrieved sequences.

        Args:
            dataset_dir: The dataset base directory
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            update_script_id: The label update script ID
            label_object: The field used to store label information

        Returns:
            The number of rows the labels were applied to.
        """
        index: Optional[Union[Sequence[str], str]] = resolve_indices(
            dataset_config.name, self.indices_prefix_dataset, self.index
        )

        body = self._make_body(label_object)

        updated = 0
        # as of elk 7.12 of there is no way to ensure we get all even through the EQL api
        # (there is no scan or search after like for the DSL API)
        # so manually search in batches for sequences with events that are not labeled yet
        # we stop only when we do not get any results anymore i.e., all events have been labeled
        # this is obviously not the most efficient approach but its the best we can do for now
        while True:
            hits = search_eql(es, index, body)
            if hits["total"]["value"] > 0:
                index_ids: Dict[str, List[str]] = {}
                # we have to sort the events by indices
                # because ids are only guranteed to be uniq per index
                for sequence in hits["sequences"]:
                    for event in sequence["events"]:
                        index_ids.setdefault(event["_index"], []).append(event["_id"])
                # add labels to each event per index
                for _index, ids in index_ids.items():
                    # split the update requests into chunks of at most max result window
                    update_chunks = [
                        ids[i : i + self.max_result_window]
                        for i in range(0, len(ids), self.max_result_window)
                    ]
                    for chunk in update_chunks:
                        update = UpdateByQuery(using=es, index=_index).query(
                            "ids", values=chunk
                        )
                        # apply labels to events
                        updated += apply_labels_by_update_dsl(
                            update, self.update_params(), update_script_id
                        )
            else:
                # end loop once we do not find new events anymore
                break

        return updated


class Labeler:
    """Cyber Range Kyoushi labeler

    This class is used to configure and execute
    the labeling process.
    """

    def __init__(
        self,
        rule_types: Dict[str, Any] = {},
        update_script_id: str = "kyoushi_label_update",
        label_object: str = "kyoushi_labels",
    ):
        """
        Args:
            rule_types : Dictionary containing all available labeling rule types.
            update_script_id: The Elasticsearch ID for the update script.
            label_object: The field to store labels in.
        """
        self.rule_types: Dict[str, Any] = rule_types
        # default rule types
        self.rule_types.update(
            {
                NoopRule.type_: NoopRule,
                UpdateByQueryRule.type_: UpdateByQueryRule,
                UpdateSubQueryRule.type_: UpdateSubQueryRule,
                UpdateParentQueryRule.type_: UpdateParentQueryRule,
                EqlSequenceRule.type_: EqlSequenceRule,
            }
        )
        self.update_script_id: str = update_script_id
        self.label_object: str = label_object

    def add_label_object_mapping(
        self,
        es: Elasticsearch,
        dataset_name: str,
        rules: List[Rule],
    ):
        """Utility function for adding the field definitions for the label field.

        Args:
            es: The elasticsearch client object.
            dataset_name: The name of the dataset.
            rules: List of all to be applied rules.
        """
        root = Mapping()
        flat = {}
        list_ = {}

        for rule in rules:
            flat[rule.id_] = Keyword()
            list_[rule.id_] = Keyword(multi=True)

        properties = {
            "flat": {
                "properties": flat,
            },
            "list": {
                "properties": list_,
            },
            "rules": {"type": "keyword"},
        }
        root.field(self.label_object, "object", properties=properties)
        es.indices.put_mapping(index=f"{dataset_name}-*", body=root.to_dict())

    def _get_label_files(
        self,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        index: List[str],
        skip_files: List[str],
    ) -> List[str]:
        """Get all dataset files containing rows that have been labled.

        Args:
            dataset_config: The dataset configuration.
            es: The elasticsearch client object
            index: The indices to consider
            skip_files: Files to ignore

        Returns:
            List of files which contain at least one row with a label.
        """
        # disable request cache to ensure we always get latest info
        search_lines = Search(using=es, index=index).params(request_cache=False)

        search_lines = search_lines.filter("exists", field=f"{self.label_object}.rules")

        # setup aggregations
        search_lines.aggs.bucket(
            "files",
            "composite",
            sources=[{"path": {"terms": {"field": "log.file.path"}}}],
        )

        # use custom scan function to ensure we get all the buckets
        return [
            h.key.path
            for h in scan_composite(search_lines, "files")
            if h.key.path not in skip_files
        ]

    def _write_file(self, search_labeled: Search, label_file_path: Path):
        """Utility function for writing label files.

        Args:
            search_labeled: Elasticsearch DSL search object used to retrieve labeled rows.
            label_file_path: The path to write the label file to
        """
        label_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(label_file_path, "w") as label_file:
            for hit in search_labeled.scan():
                labels: Dict[str, List[str]] = {}
                for rule in hit[self.label_object].rules:
                    for label in hit[self.label_object].list[rule]:
                        rules = labels.setdefault(label, [])
                        rules.append(rule)

                hit_info = {
                    "line": hit.log.file.line,
                    "labels": list(labels.keys()),
                    "rules": labels,
                }
                if "multiline" in hit.log.file:
                    hit_info["multiline"] = hit.log.file.multiline

                label_file.write(f"{json.dumps(hit_info)}\n")

    def write(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        index: List[str],
        skip_files: List[str],
    ):
        """Write labeles stored in the database to the file system.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            es: The elasticsearch client object
            index: The indices to consider
            skip_files: The files to ignore
        """
        files = self._get_label_files(dataset_config, es, index, skip_files)

        for current_file in files:
            # disable request cache to ensure we always get latest info
            search_labeled = Search(using=es, index=f"{dataset_config.name}-*").params(
                request_cache=False, preserve_order=True
            )
            search_labeled = search_labeled.filter(
                "exists", field=f"{self.label_object}.rules"
            ).filter("term", log__file__path=current_file)

            search_labeled = search_labeled.sort({"log.file.line": "asc"})

            base_path = dataset_dir.joinpath(LAYOUT.GATHER.value)
            label_path = dataset_dir.joinpath(LAYOUT.LABELS.value)

            label_file_path = label_path.joinpath(
                Path(current_file).relative_to(base_path)
            )
            print(f"Start writing {current_file}")
            self._write_file(search_labeled, label_file_path)

    def execute(
        self,
        rules: List[Dict[str, Any]],
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
    ):
        """Parse and apply all labeling rules.

        !!! Note
            This function only write labels to the database.
            The resulting labels can be written to the file system
            using the `write(...)` function of the labeler.

        Args:
            rules: The unparsed list of labeling rules.
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            es: The elasticsearch client object

        Raises:
            ValidationError: If a labeling rule or configuration is invalid
            LabelException: If an error occurs while applying a labeling rule
        """
        # validate the general rule list
        RuleList.parse_obj(rules)

        # convert and validate rule types
        rule_objects: List[Rule] = []
        errors: List[ErrorWrapper] = []
        for r in rules:
            try:
                rule_objects.append(self.rule_types[r["type"]].parse_obj(r))
            except ValidationError as e:
                errors.append(ErrorWrapper(e, r["id"]))
        if len(errors) > 0:
            raise ValidationError(errors, RuleList)

        # create mappings for rule label fields
        # we need to do this since EQL queries cannot check existence of non mapped fields
        self.add_label_object_mapping(es, dataset_config.name, rule_objects)

        # ensure update script exists
        create_kyoushi_scripts(es, dataset_config.name, self.label_object)

        # start labeling process
        for rule in rule_objects:
            try:
                print(f"Applying rule {rule.id_} ...")
                updated = rule.apply(
                    dataset_dir,
                    dataset_config,
                    es,
                    f"{dataset_config.name}_{self.update_script_id}",
                    self.label_object,
                )
                print(
                    f"Rule {rule.id_} applied labels: {rule.labels} to {updated} lines."
                )
            except ElasticsearchRequestError as e:
                raise LabelException(f"Error executing rule '{rule.id_}'", e)
