import copy
import gzip
import shutil
import sys

from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Dict,
    Iterable,
    List,
    Optional,
    Union,
)

from elasticsearch import Elasticsearch
from elasticsearch.client.indices import IndicesClient
from pydantic import (
    BaseModel,
    Field,
    FilePath,
    parse_obj_as,
    validator,
)

from .config import (
    DatasetConfig,
    LogstashLogConfig,
    LogstashParserConfig,
)
from .elasticsearch import get_transport_variables
from .pcap import convert_pcap_to_ecs
from .templates import (
    render_template,
    write_template,
)
from .utils import (
    copy_package_file,
    create_dirs,
    load_file,
    load_variables,
)


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

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
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
        es: Elasticsearch,
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
        es: Elasticsearch,
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

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ):
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

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        print(self.msg)


class TemplateProcessor(ProcessorBase):
    type_: ClassVar = "template"

    src: Path = Field(..., description="The template file to render")
    dest: Path = Field(..., description="The destination to save the rendered file to")
    template_context: Optional[ProcessorContext] = Field(
        None,
        description="Optional template context if this is not set the processor context is used instead",
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        if self.template_context is not None:
            variables = self.template_context.load()
        else:
            variables = self.context.load()

        variables["DATASET_DIR"] = dataset_dir
        variables["DATASET"] = dataset_config
        variables["PARSER"] = parser_config

        write_template(self.src, self.dest.absolute(), variables, es)


class CreateDirectoryProcessor(ProcessorBase):
    type_: ClassVar = "mkdir"
    path: Path = Field(..., description="The directory path to create")
    recursive: bool = Field(
        True, description="If all missing parent directories should als be created"
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        self.path.mkdir(parents=self.recursive, exist_ok=True)


class GzipProcessor(ProcessorBase):
    type_: ClassVar = "gzip"
    path: Path = Field(
        Path("."),
        description="The base path to search for the gzipped files.",
    )
    glob: Optional[str] = Field(None, description="The file glob expression to use")

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        files: Iterable
        if self.glob is None:
            files = [self.path]
        else:
            files = self.path.glob(self.glob)
        for gzip_file in files:
            with gzip.open(gzip_file, "rb") as f_in:
                # with suffix replaces .gz ending
                with open(gzip_file.with_suffix(""), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            # delete the gzip file
            gzip_file.unlink()


class PcapElasticsearchProcessor(ProcessorBase):
    type_: ClassVar = "pcap.elasticsearch"
    pcap: FilePath = Field(..., description="The pcap file to convert")
    dest: Path = Field(..., description="The destination file")
    tls_keylog: Optional[FilePath] = Field(
        None, description="TLS keylog file to decrypt TLS on the fly."
    )
    tshark_bin: Optional[FilePath] = Field(
        None,
        description="Path to your tshark binary (searches in common paths if not supplied)",
    )
    remove_index_messages: bool = Field(
        True,
        description=(
            "If the elasticsearch bulk API index messages should be stripped from the output file. "
            "Useful when using logstash or similar instead of the bulk API."
        ),
    )
    packet_summary: bool = Field(
        True, description="If the packet summaries should be included (-P option)."
    )
    packet_details: bool = Field(
        True,
        description="If the packet details should be included, when packet_summary=False then details are always included (-V option).",
    )
    read_filter: Optional[str] = Field(
        None,
        description="The read filter to use when reading the pcap file useful to reduce the number of packets (-Y option)",
    )
    protocol_match_filter: Optional[str] = Field(
        None,
        description=(
            "Display filter for protocols and their fields (-J option)."
            "Parent and child nodes are included for all matches lower level protocols must be added explicitly."
        ),
    )
    protocol_match_filter_parent: Optional[str] = Field(
        None,
        description="Display filter for protocols and their fields. Only partent nodes are included (-j option).",
    )

    create_destination_dirs: bool = Field(
        True,
        description="If the processor should create missing destination parent directories",
    )

    force: bool = Field(
        False,
        description="If the pcap should be created even when the destination file already exists.",
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        if self.create_destination_dirs:
            # create destination parent directory if it does not exist
            self.dest.parent.mkdir(parents=True, exist_ok=True)

        if self.force or not self.dest.exists():
            # convert the file
            convert_pcap_to_ecs(
                self.pcap,
                self.dest,
                self.tls_keylog,
                self.tshark_bin,
                self.remove_index_messages,
                self.packet_summary,
                self.packet_details,
                self.read_filter,
                self.protocol_match_filter,
                self.protocol_match_filter_parent,
            )


class TemplateCreateProcessor(ProcessorBase):
    type_: ClassVar = "elasticsearch.template"
    template: FilePath = Field(
        ..., description="The index template to add to elasticsearch"
    )
    template_name: str = Field(
        ..., description="The name to use for the index template"
    )
    index_patterns: Optional[List[str]] = Field(
        None,
        description=(
            "The index patterns the template should be applied to. "
            "If this is not set then the index template file must contain this information already!"
        ),
    )
    patterns_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. "
            "This is a convenience setting as per default all dataset indices start with this prefix."
        ),
    )
    order: int = Field(
        100,
        description="The order to assign to this index template (higher values take precedent).",
    )

    create_only: bool = Field(
        False,
        description="If true then an existing template with the given name will not be replaced.",
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        template_data = load_file(self.template)

        # configure the index patterns
        if self.index_patterns is not None:
            template_data["index_patterns"] = (
                # if prefix is on add the prefix to all patterns
                [f"{dataset_config.name}-{p}" for p in self.index_patterns]
                if self.patterns_prefix_dataset
                # else add list as is
                else self.index_patterns
            )

        ies = IndicesClient(es)

        ies.put_template(
            name=self.template_name,
            body=template_data,
            create=self.create_only,
            order=self.order,
        )


class LogstashSetupProcessor(ProcessorBase):
    type_: ClassVar = "logstash.setup"

    input_config_name: str = Field(
        "input.conf",
        description="The name of the log inputs config file. (relative to the pipeline config dir)",
    )

    input_template: Path = Field(
        Path("input.conf.j2"),
        description="The template to use for the file input plugin configuration",
    )

    output_config_name: str = Field(
        "output.conf",
        description="The name of the log outputs config file. (relative to the pipeline config dir)",
    )

    output_template: Path = Field(
        Path("output.conf.j2"),
        description="The template to use for the file output plugin configuration",
    )

    pre_process_name: str = Field(
        "0000_pre_process.conf",
        description=(
            "The file name to use for the pre process filters config. "
            "This is prefixed with 0000_ to ensure that the filters are run first."
        ),
    )

    pre_process_template: Path = Field(
        Path("pre_process.conf.j2"),
        description="The template to use for the file output plugin configuration",
    )

    logstash_template: Path = Field(
        Path("logstash.yml.j2"),
        description="The template to use for the logstash configuration",
    )

    piplines_template: Path = Field(
        Path("pipelines.yml.j2"),
        description="The template to use for the logstash pipelines configuration",
    )

    index_template_template: Path = Field(
        Path("ecs-template.json.j2"),
        description="The template to use for the elasticsearch dataset index patterns index template",
    )

    servers: Dict[str, Any] = Field(
        ...,
        description="Dictionary of servers and their log configurations",
    )

    @validator("servers", each_item=True)
    def validate_servers(cls, v):
        assert "logs" in v, "Each server must have a logs configuration"
        v["logs"] = parse_obj_as(List[LogstashLogConfig], v["logs"])
        return v

    @validator("servers", each_item=True)
    def default_server_timezone(cls, v):
        if "timezone" not in v:
            v["timezone"] = "UTC"
        return v

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:

        variables = self.context.load()
        variables.update(
            {
                "DATASET_DIR": dataset_dir,
                "DATASET": dataset_config,
                "PARSER": parser_config,
                "servers": self.servers,
            }
        )
        # add elasticsearch connection variables
        variables.update(get_transport_variables(es))

        # create all logstash directories
        create_dirs(
            [
                parser_config.settings_dir,
                parser_config.conf_dir,
                parser_config.data_dir,
                parser_config.log_dir,
            ]
        )

        # copy jvm and log4j config to settings dir if they don't exist
        copy_package_file(
            "cr_kyoushi.dataset.files",
            "jvm.options",
            parser_config.settings_dir.joinpath("jvm.options"),
        )
        copy_package_file(
            "cr_kyoushi.dataset.files",
            "log4j2.properties",
            parser_config.settings_dir.joinpath("log4j2.properties"),
        )

        # write logstash configuration
        write_template(
            self.logstash_template,
            parser_config.settings_dir.joinpath("logstash.yml"),
            variables,
            es,
        )

        # write pipelines configuration
        write_template(
            self.piplines_template,
            parser_config.settings_dir.joinpath("pipelines.yml"),
            variables,
            es,
        )

        # write index template
        write_template(
            self.index_template_template,
            parser_config.settings_dir.joinpath(
                f"{dataset_config.name}-index-template.json"
            ),
            variables,
            es,
        )

        # write input configuration
        write_template(
            self.input_template,
            parser_config.conf_dir.joinpath(self.input_config_name),
            variables,
            es,
        )

        # write output configuration
        write_template(
            self.output_template,
            parser_config.conf_dir.joinpath(self.output_config_name),
            variables,
            es,
        )

        # write pre process configuration
        write_template(
            self.pre_process_template,
            parser_config.conf_dir.joinpath(self.pre_process_name),
            variables,
            es,
        )


class ProcessorPipeline:
    def __init__(self, processor_map: Dict[str, Any] = {}):
        self.processor_map: Dict[str, Any] = processor_map
        self.processor_map.update(
            {
                PrintProcessor.type_: PrintProcessor,
                TemplateProcessor.type_: TemplateProcessor,
                ForEachProcessor.type_: ForEachProcessor,
                CreateDirectoryProcessor.type_: CreateDirectoryProcessor,
                GzipProcessor.type_: GzipProcessor,
                LogstashSetupProcessor.type_: LogstashSetupProcessor,
                PcapElasticsearchProcessor.type_: PcapElasticsearchProcessor,
                TemplateCreateProcessor.type_: TemplateCreateProcessor,
            }
        )

    def execute(
        self,
        data: List[Dict[str, Any]],
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ):
        # reset in case we error during execution
        self.__loaded = False
        # pre-validate the processor list
        # check if all processors have a name and type
        parse_obj_as(ProcessorList, data)

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
                print(f"Expanding processor container - {processor.name} ...")
                self.execute(
                    processor.processors(),
                    dataset_dir,
                    dataset_config,
                    parser_config,
                    es,
                )
            else:
                print(f"Executing - {processor.name} ...")
                processor.execute(dataset_dir, dataset_config, parser_config, es)
