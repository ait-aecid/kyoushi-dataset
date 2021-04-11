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
    Union,
)

from elasticsearch import Elasticsearch
from elasticsearch_dsl import UpdateByQuery
from elasticsearch_dsl.connections import get_connection
from elasticsearch_dsl.exceptions import UnknownDslObject
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

from .config import DatasetConfig
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
if (ctx._source[params.label_object] == null) {
    ctx._source[params.label_object] = [:];
}
if (
    ctx._source[params.label_object][params.rule] == null ||
    ctx._source[params.label_object][params.rule].size() != params.labels.size() ||
    !ctx._source[params.label_object][params.rule].containsAll(params.labels)
) {
    ctx._source[params.label_object][params.rule] = params.labels;
    updated = true;
}
if (!updated) {
    ctx.op = "noop";
}
"""


def create_update_script(es: Elasticsearch, id_: str = "kyoushi_label_update"):
    body = {
        "script": {
            "description": "Kyoushi Dataset - Update by Query label script",
            "lang": "painless",
            "source": UPDATE_SCRIPT,
        }
    }
    es.put_script(id=id_, body=body, context="update")


def apply_labels_by_update_dsl(
    update: UpdateByQuery,
    check_interval: float = 0.5,
) -> int:
    # refresh=True is important so that consecutive rules
    # have a consitant state
    es: Elasticsearch = get_connection(update._using)
    task = update.params(refresh=True, wait_for_completion=False).execute().task
    task_info = es.tasks.get(task)
    while not task_info["completed"]:
        sleep(check_interval)
        task_info = es.tasks.get(task)

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
    update = UpdateByQuery(using=es, index=index)
    update = update.update_from_dict(query)
    update = update.script(id=update_script_id, params=script_params)
    return apply_labels_by_update_dsl(update, check_interval)


@runtime_checkable
class Rule(Protocol):
    type_: ClassVar[str]
    id_: str
    labels: List[str]
    description: Optional[str]

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        ...

    def update_params(self, label_object: str) -> Dict[str, Any]:
        ...


class RuleBase(BaseModel):
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
        raise NotImplementedError()

    def update_params(self, label_object: str) -> Dict[str, Any]:
        return {
            "label_object": label_object,
            "rule": self.id_,
            "labels": self.labels,
        }


class RuleList(BaseModel):
    __root__: List[RuleBase]

    def __iter__(self):
        return iter(self.__root__)

    def __getitem__(self, item):
        return self.__root__[item]

    @root_validator
    def check_rule_ids_uniq(
        cls, values: Dict[str, List[RuleBase]]
    ) -> Dict[str, List[RuleBase]]:
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
    type_: ClassVar[str] = "noop"

    def apply(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
        update_script_id: str,
        label_object: str,
    ) -> int:
        return 0


class UpdateByQueryRule(RuleBase):
    type_: ClassVar[str] = "elasticsearch.query"
    index: Optional[Union[List[str], str]] = Field(
        None,
        description="The indices to query (by default prefixed with the dataset name)",
    )

    query: Union[List[Dict[str, Any]], Dict[str, Any]] = Field(
        ...,
        description="The query/s to use for identifying log lines to apply the tags to.",
    )
    filter_: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(
        None,
        description="The filter/s to limit queried to documents to only those that match the filters",
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
            "This is a convenience setting as per default all dataset indices start with this prefix."
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

        for q in self.query:
            update = update.query(q)
        for f in self.filter_:
            update = update.filter(f)
        for e in self.exclude:
            update = update.exclude(e)

        update = update.script(
            id=update_script_id, params=self.update_params(label_object)
        )

        result = apply_labels_by_update_dsl(update)

        return result

    @validator("query")
    def validate_queries(
        cls, value: Union[List[Dict[str, Any]], Dict[str, Any]], values: Dict[str, Any]
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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


class Labeler:
    def __init__(
        self,
        rule_types: Dict[str, Any] = {},
        update_script_id: str = "kyoushi_label_update",
        label_object: str = "kyoushi_labels",
    ):
        self.rule_types: Dict[str, Any] = rule_types
        # default rule types
        self.rule_types.update(
            {
                NoopRule.type_: NoopRule,
                UpdateByQueryRule.type_: UpdateByQueryRule,
            }
        )
        self.update_script_id: str = update_script_id
        self.label_object: str = label_object

    def execute(
        self,
        rules: List[Dict[str, Any]],
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        es: Elasticsearch,
    ):
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

        # ensure update script exists
        create_update_script(es, self.update_script_id)

        # start labeling process
        for rule in rule_objects:
            updated = rule.apply(
                dataset_dir,
                dataset_config,
                es,
                self.update_script_id,
                self.label_object,
            )
            print(f"Rule {rule.id_} applied labels: {rule.labels} to {updated} lines.")
