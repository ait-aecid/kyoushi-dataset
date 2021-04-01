import copy
import sys

from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Union,
)

from elasticsearch import Elasticsearch
from pydantic import (
    BaseModel,
    Field,
    parse_obj_as,
)

from .templates import (
    render_template,
    write_template,
)
from .utils import load_variables


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


class ProcessorContext(BaseModel):
    variables: Dict[str, Any] = Field(
        {},
        description="Context variables to use during rendering",
        alias="vars",
    )
    variable_files: Union[Path, Dict[str, Path]] = Field(
        {},
        description="Config files to load into the render context",
        alias="var_files",
    )

    _loaded_variables: Optional[Dict[str, Any]] = None
    """The loaded context variables"""

    def load(self) -> Dict[str, Any]:
        if self._loaded_variables is None:
            self._loaded_variables = load_variables(self.variable_files)
            self._loaded_variables.update(self.variables)
        return self._loaded_variables

    class Config:
        underscore_attrs_are_private = True


class Processor(Protocol):
    type_: ClassVar[str]
    context_render_exclude: ClassVar[List[str]]
    context: ProcessorContext
    name: str

    @classmethod
    def render(cls, context: ProcessorContext, data: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def execute(self, es: Optional[Elasticsearch]) -> None:
        ...


@runtime_checkable
class ProcessorContainer(Processor, Protocol):
    def processors(self) -> List[Dict[str, Any]]:
        ...


class ProcessorBase(BaseModel):
    type_: ClassVar[str] = Field(..., description="The processor type")
    context_render_exclude: ClassVar[List[str]] = []
    context: ProcessorContext = Field(
        ProcessorContext(),
        description="The variable context for the processor",
    )
    name: str = Field(..., description="The processors name")
    type_field: str = Field(
        ...,
        description="The processor type as passed in from the config",
        alias="type",
    )

    @classmethod
    def _render(
        cls,
        context: ProcessorContext,
        data: Any,
        es: Optional[Elasticsearch] = None,
    ) -> Any:
        # handle sub dicts
        if isinstance(data, dict):
            data_rendered = {}
            for key, val in data.items():
                # for sub dicts keys we also allow temp
                key = cls._render(context, key, es)
                val = cls._render(context, val, es)
                data_rendered[key] = val
            return data_rendered

        # handle list elements
        if isinstance(data, list):
            return [cls._render(context, val, es) for val in data]

        # handle str and template strings
        if isinstance(data, str):
            return render_template(data, context.load(), es)

        # all other basic types are returned as is
        return data

    @classmethod
    def render(
        cls,
        context: ProcessorContext,
        data: Dict[str, Any],
        es: Optional[Elasticsearch] = None,
    ) -> Dict[str, Any]:
        # handle main dict
        data_rendered = {}
        for key, val in data.items():
            # do not render excluded fields
            if key not in cls.context_render_exclude:
                data_rendered[key] = cls._render(context, val, es)
            else:
                data_rendered[key] = val
        return data_rendered

    def execute(self, es: Optional[Elasticsearch] = None):
        raise NotImplementedError("Incomplete processor implementation!")


ProcessorList = List[ProcessorBase]


class ForEachProcessor(ProcessorBase):
    type_: ClassVar = "foreach"
    context_render_exclude: ClassVar[List[str]] = ["processor"]

    items: List[Any] = Field(
        ...,
        description="List of items to create processors for",
    )
    loop_var: str = Field(
        "item",
        description="The variable name to use for current loops item in the processor context",
    )
    processor: Dict[str, Any] = Field(
        ...,
        description="The processor template config to create multiple instances of",
    )

    def processors(self) -> List[Dict[str, Any]]:
        processors = []
        for item in self.items:
            processor = copy.deepcopy(self.processor)
            # set the loop var
            if "context" in processor:
                context = processor["context"]
            else:
                context = self.context.dict()
                processor["context"] = context

            variables = context.setdefault("vars", {})
            variables[self.loop_var] = item

            processors.append(processor)
        return processors


class PrintProcessor(ProcessorBase):
    type_: ClassVar = "print"
    msg: str = Field(..., description="The message to print")

    def execute(self, es: Optional[Elasticsearch] = None) -> None:
        print(self.msg)


class TemplateProcessor(ProcessorBase):
    type_: ClassVar = "template"

    src: Path = Field(..., description="The template file to render")
    dest: Path = Field(..., description="The destination to save the rendered file to")
    template_context: Optional[ProcessorContext] = Field(
        None,
        description="Optional template context if this is not set the processor context is used instead",
    )

    def execute(self, es: Optional[Elasticsearch] = None) -> None:
        if self.template_context is not None:
            variables = self.template_context.load()
        else:
            variables = self.context.load()

        write_template(self.src, self.dest.absolute(), variables, es)


class CreateDirectoryProcessor(ProcessorBase):
    type_: ClassVar = "mkdir"
    path: Path = Field(..., description="The directory path to create")
    recursive: bool = Field(
        True, description="If all missing parent directories should als be created"
    )

    def execute(self, es: Optional[Elasticsearch] = None) -> None:
        self.path.mkdir(parents=self.recursive, exist_ok=True)


class ProcessorPipeline:
    def __init__(self, processor_map: Dict[str, Any] = {}):
        self.processor_map: Dict[str, Any] = processor_map
        self.processor_map.update(
            {
                PrintProcessor.type_: PrintProcessor,
                TemplateProcessor.type_: TemplateProcessor,
                ForEachProcessor.type_: ForEachProcessor,
                CreateDirectoryProcessor.type_: CreateDirectoryProcessor,
            }
        )
        self.processors: List[Processor] = []
        self.__loaded = False

    def load_processors(
        self,
        data: List[Dict[str, Any]],
        es: Optional[Elasticsearch] = None,
    ):
        # reset in case we error during execution
        self.__loaded = False
        # pre-validate the processor list
        # check if all processors have a name and type
        parse_obj_as(ProcessorList, data)

        # reset processor list ensure that we do not
        # have duplicate processors when calling twice
        self.processors = []

        for p in data:
            # get the processor context and class
            context = p.setdefault("context", {})
            processor_class = self.processor_map[p["type"]]

            # render the processor template and parse it
            p_rendered = processor_class.render(
                context=ProcessorContext.parse_obj(context),
                data=p,
                es=es,
            )
            processor = processor_class.parse_obj(p_rendered)

            if isinstance(processor, ProcessorContainer):
                self.processors.extend(self.load_processors(processor.processors(), es))
            else:
                self.processors.append(processor)
        self.__loaded = True

    def execute(self, es: Optional[Elasticsearch] = None):
        if self.__loaded:
            for p in self.processors:
                print(f"Executing - {p.name} ...")
                p.execute(es=es)
        else:
            raise Exception("Processor not loaded")
