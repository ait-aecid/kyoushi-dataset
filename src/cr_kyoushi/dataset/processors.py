"""
This module contains the base definitions of dataset pipeline processors and also
the core processors shipped with the Cyber Range Kyoushi Dataset package.
"""


import copy
import gzip
import shutil
import sys

from datetime import datetime
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
from elasticsearch.client.cluster import ClusterClient
from elasticsearch.client.indices import IndicesClient
from elasticsearch.client.ingest import IngestClient
from elasticsearch_dsl.query import Range
from elasticsearch_dsl.response.aggs import Bucket
from elasticsearch_dsl.search import Search
from elasticsearch_dsl.update_by_query import UpdateByQuery
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
from .elasticsearch import (
    get_transport_variables,
    scan_composite,
)
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
    trim_file,
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
    """Processor context model

    This model is used to configure the variable context
    used for rendering a processor. It is possible to either
    define variables directly (`variables`) or load them from
    variable files (`variable_files`).
    """

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
        """Load the configured context variables into a combined dict.

        The loaded context variables are cached so that variable files
        are only read on the first call of `load()`.

        Returns:
            A single dict containing all context variables.
        """
        if self._loaded_variables is None:
            self._loaded_variables = load_variables(self.variable_files)
            self._loaded_variables.update(self.variables)
        return self._loaded_variables

    class Config:
        underscore_attrs_are_private = True


class Processor(Protocol):
    """Cyber Range Kyoushi Dataset processor interface

    For the Cyber Range Kyoushi Dataset tool processors are used
    during the pre and post processing phase. A processor class exposes
    configuration variables and is executed to achieve a certain task
    during the processing phases. They work similar to Ansible modules
    and it is possible to use Jinja2 templates and context
    variable to define partial configuration.

    Example:
        ```yaml
          - name: Render foo template
            type: template
            context:
            vars:
                foo: bar
            var_files: gather/server/foo-bar.yaml
            src: processing/templates/foo.yaml.j2
            dest: processing/bar.yaml.j2
        ```
    """

    type_: ClassVar[str]
    context_render_exclude: ClassVar[List[str]]
    context: ProcessorContext
    name: str

    @classmethod
    def render(cls, context: ProcessorContext, data: Dict[str, Any]) -> Dict[str, Any]:
        """Renders all template strings of a processor.

        Args:
            context: The processors context variables
            data: The raw templated processor configuration.

        Returns:
            The rendered processor configuration.
        """
        ...

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        """Executes the processor.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """


@runtime_checkable
class ProcessorContainer(Processor, Protocol):
    """Cyber Range Kyoushi Dataset processor container interface

    This interface definition defines the API used for
    classes implementing processor container types.
    """

    def processors(self) -> List[Dict[str, Any]]:
        """Returns a list of processors contained in this container.

        Returns:
            List of processors
        """
        ...


class ProcessorBase(BaseModel):
    """Pydantic base model of Cyber Range Kyoushi Dataset processor.

    Use this base model to implement processors it ensures that
    rendering and data loading is done correctly.
    """

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
        """Sub method used for the recursive processor rendering.

        Args:
            context: The processor context
            data: The current data element
            es: The elasticsearch client object

        Returns:
            The rendered data element
        """
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
        """Renders all template strings of a processor.

        Args:
            context: The processors context variables
            data: The raw templated processor configuration.

        Returns:
            The rendered processor configuration.
        """
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
        """Executes the processor.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        raise NotImplementedError("Incomplete processor implementation!")


ProcessorList = List[ProcessorBase]
"""Type alias for a list of processors"""


class ForEachProcessor(ProcessorBase):
    """For each processor

    This is a special processor container allowing for the
    dynamic creation of a list of processor based on a list
    of items.

    Example:
        ```yaml
        - name: Render labeling rules
          type: foreach
          # processing/templates/rules
          items:
            - src: 0_auth.yaml.j2
              dest: 0_auth.yaml
            - src: apache.yaml.j2
              dest: apache.yaml
            - src: audit.yaml.j2
              dest: audit.yaml
            - src: openvpn.yaml.j2
              dest: openvpn.yaml
          processor:
            type: template
            name: Rendering labeling rule {{ item.src }}
            template_context:
              var_files:
                attacker: processing/config/attacker/attacker.yaml
                escalate: processing/config/attacker/escalate.yaml
                foothold: processing/config/attacker/foothold.yaml
                servers: processing/config/servers.yaml
            src: "processing/templates/rules/{{ item.src }}"
            dest: "rules/{{ item.dest }}"
        ```
    """

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
        """Create a list of processors for each item.

        Returns:
            List of processors based on the given items and
            processor template.
        """
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

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ):
        """Executes the processor.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        raise NotImplementedError("Incomplete processor implementation!")


class PrintProcessor(ProcessorBase):
    """Debug processor that simply prints a message.

    Example:
        ```yaml
        - name: Print Hello World
          type: print
          msg: Hello World
        ```
    """

    type_: ClassVar = "print"
    msg: str = Field(..., description="The message to print")

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        """Print the `msg`

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        print(self.msg)


class TemplateProcessor(ProcessorBase):
    """Processor for rendering template files.

    In addition to the normal processor context it
    is also possible to define a `template_context`.
    If `template_context` is defined it will be used for
    rendering the template otherwise the normal processor
    context will be used.

    Example:
        ```yaml
        - type: template
          name: Rendering labeling rule {{ item.src }}
          template_context:
            var_files:
            attacker: processing/config/attacker/attacker.yaml
            escalate: processing/config/attacker/escalate.yaml
            foothold: processing/config/attacker/foothold.yaml
            servers: processing/config/servers.yaml
          src: "processing/templates/rules/{{ item.src }}"
          dest: "rules/{{ item.dest }}"
        ```
    """

    type_: ClassVar = "template"

    src: Path = Field(..., description="The template file to render")
    dest: Path = Field(..., description="The destination to save the rendered file to")
    template_context: Optional[ProcessorContext] = Field(
        None,
        description=(
            "Optional template context if this is not set "
            "the processor context is used instead"
        ),
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        """Load and render the template file.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        if self.template_context is not None:
            variables = self.template_context.load()
        else:
            variables = self.context.load()

        variables["DATASET_DIR"] = dataset_dir
        variables["DATASET"] = dataset_config
        variables["PARSER"] = parser_config

        write_template(self.src, self.dest.absolute(), variables, es, dataset_config)


class CreateDirectoryProcessor(ProcessorBase):
    """Processor for creating file directories.

    Example:
        ```yaml
        - name: Ensure processing config directory exists
          type: mkdir
          path: processing/config
        ```
    """

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
        """Execute the processor and create the directory.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        self.path.mkdir(parents=self.recursive, exist_ok=True)


class GzipProcessor(ProcessorBase):
    """Processor for decompressing gzip files.

    It is possible to either define a `glob` of gzip files
    or a `path` to a single gzip file. If a `glob` is defined
    it is resolved relative to the defined `path` (default=`<dataset dir>`).

    Example:
        ```yaml
        - name: Decompress all GZIP logs
          type: gzip
          path: gather
          glob: "*/logs/**/*.gz"
        ```
    """

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
        """Execute the processor and decompress the files.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
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
    """Processor for converting PCAP files to ndjson format.

    This processor uses tshark to convert PCAP files to
    a line based JSON format (`ek` output).

    Example:
        ```yaml
        - name: Convert attacker pcap to elasticsearch json
          type: pcap.elasticsearch
          pcap: gather/attacker_0/logs/ait.aecid.attacker.wpdiscuz/traffic.pcap
          dest: gather/attacker_0/logs/ait.aecid.attacker.wpdiscuz/traffic.json
          tls_keylog: gather/attacker_0/logs/ait.aecid.attacker.wpdiscuz/premaster.txt
          read_filter: "tcp or udp or icmp"
        ```
    """

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

    remove_filtered: bool = Field(
        True, description="Remove filtered fields from the event dicts."
    )

    packet_summary: bool = Field(
        True, description="If the packet summaries should be included (-P option)."
    )
    packet_details: bool = Field(
        True,
        description=(
            "If the packet details should be included, "
            "when packet_summary=False then details are always included (-V option)."
        ),
    )
    read_filter: Optional[str] = Field(
        None,
        description=(
            "The read filter to use when reading the "
            "pcap file useful to reduce the number of packets (-Y option)"
        ),
    )
    protocol_match_filter: Optional[str] = Field(
        None,
        description=(
            "Display filter for protocols and their fields (-J option)."
            "Parent and child nodes are included for all matches "
            "lower level protocols must be added explicitly."
        ),
    )
    protocol_match_filter_parent: Optional[str] = Field(
        None,
        description=(
            "Display filter for protocols and their fields. "
            "Only partent nodes are included (-j option)."
        ),
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
        """Execute the processor and convert the pcap file.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
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
                self.remove_filtered,
                self.packet_summary,
                self.packet_details,
                self.read_filter,
                self.protocol_match_filter,
                self.protocol_match_filter_parent,
            )


class ComponentTemplateCreateProcessor(ProcessorBase):
    """Processor for creating Elasticsearch index component templates.

    This processor can be used to create Elasticsearch
    index component templates. To prepare the Elasticsearch instance
    for the parsing phase. See the
    [index templates doc](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-templates.html)
    for more details.

    Example:
        ```yaml
        - name: Add pcap component template
          type: elasticsearch.component_template
          template: processing/logstash/pcap-component-template.json
          template_name: pcap
        ```
    """

    type_: ClassVar = "elasticsearch.component_template"
    template: FilePath = Field(
        ..., description="The index component template to add to elasticsearch"
    )
    template_name: str = Field(
        ..., description="The name to use for the index component template"
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
        """Execute the processor and configure Elasticsearch index component template.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        template_data = load_file(self.template)

        ies = ClusterClient(es)

        ies.put_component_template(
            name=self.template_name,
            body=template_data,
            create=self.create_only,
        )


class TemplateCreateProcessor(ProcessorBase):
    """Processor for configuring Elasticsearch index templates.

    This processor can be used to configure Elasticsearch
    index templates. To prepare the Elasticsearch instance
    for the parsing phase. See the
    [index templates doc](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-templates.html)
    for more details.

    Example:
        ```yaml
        - name: Add pcap index mapping
          type: elasticsearch.template
          template: processing/logstash/pcap-index-template.json
          template_name: pcap
          index_patterns: ["pcap-*"]
        ```
    """

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
    indices_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. This "
            "is a convenience setting as per default all dataset indices start with this prefix."
        ),
    )
    priority: int = Field(
        100,
        description="The priority to assign to this index template (higher values take precedent).",
    )

    composed_of: Optional[List[str]] = Field(
        None,
        description="Optional list of component templates the index template should be composed of.",
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
        """Execute the processor and configure Elasticsearch index template.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        template_data = load_file(self.template)

        # configure the index patterns
        if self.index_patterns is not None:
            template_data["index_patterns"] = (
                # if prefix is on add the prefix to all patterns
                [f"{dataset_config.name}-{p}" for p in self.index_patterns]
                if self.indices_prefix_dataset
                # else add list as is
                else self.index_patterns
            )

        # set template priority to given value
        template_data["priority"] = self.priority

        if self.composed_of is not None:
            template_data["composed_of"] = self.composed_of

        ies = IndicesClient(es)

        ies.put_index_template(
            name=self.template_name,
            body=template_data,
            create=self.create_only,
        )


class LegacyTemplateCreateProcessor(ProcessorBase):
    """Processor for configuring Elasticsearch legacy index templates.

    This processor can be used to configure Elasticsearch
    index templates. To prepare the Elasticsearch instance
    for the parsing phase. See the
    [legacy index templates doc](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-templates-v1.html)
    for more details.

    Example:
        ```yaml
        - name: Add pcap index mapping
          type: elasticsearch.legacy_template
          template: processing/logstash/pcap-index-template.json
          template_name: pcap
          index_patterns: ["pcap-*"]
        ```
    """

    type_: ClassVar = "elasticsearch.legacy_template"
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
    indices_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. This "
            "is a convenience setting as per default all dataset indices start with this prefix."
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
        """Execute the processor and configure Elasticsearch index template.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        template_data = load_file(self.template)

        # configure the index patterns
        if self.index_patterns is not None:
            template_data["index_patterns"] = (
                # if prefix is on add the prefix to all patterns
                [f"{dataset_config.name}-{p}" for p in self.index_patterns]
                if self.indices_prefix_dataset
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


class IngestCreateProcessor(ProcessorBase):
    """Processor for creating Elasticsearch ingest pipelines.

    This processor can be used to create Elasticsearch ingest pipelines
    for parsing log event. The log file parsing can then be configured
    to use the pipelines for upstream parsing instead of local Logstash
    parsing.

    Example:
        ```yaml
        - name: Add auditd ingest pipeline to elasticsearch
          type: elasticsearch.ingest
          ingest_pipeline: processing/logstash/auditd-ingest.yml
          ingest_pipeline_id: auditd-logs
        ```
    """

    type_: ClassVar = "elasticsearch.ingest"
    ingest_pipeline: FilePath = Field(
        ..., description="The ingest pipeline to add to elasticsearch"
    )
    ingest_pipeline_id: str = Field(
        ..., description="The id to use for the ingest pipeline"
    )

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        """Execute the processor and configure Elasticsearch ingest pipeline.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        pipeline_data = load_file(self.ingest_pipeline)

        ies = IngestClient(es)

        ies.put_pipeline(id=self.ingest_pipeline_id, body=pipeline_data)


class LogstashSetupProcessor(ProcessorBase):
    """Logstash parser setup processor.

    This processor is used to create all the configuration
    files required for the Logstash parser (e.g., input and filter configs).
    Unless you provide a static Logstash parsing configuration you must
    invoke this processor at somepoint during the pre-processing phase.

    !!! Note
        The processor only does the basic setup any Logstash parsing
        filters used for processing specific log events must be prepared
        separately.

    Example:
        ```yaml
        - name: Setup logstash pipeline
          type: logstash.setup
          context:
            var_files:
              servers: processing/config/servers.yaml
          servers: "{{ servers }}"
        ```
    """

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
        description=(
            "The name of the log outputs config file. "
            "(relative to the pipeline config dir)"
        ),
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

    use_legacy_template: bool = Field(
        False,
        description="If the output config should use the legacy index template or the modern index template",
    )

    index_template_template: Path = Field(
        Path("ecs-template.json.j2"),
        description=(
            "The template to use for the elasticsearch "
            "dataset index patterns index template"
        ),
    )

    legacy_index_template_template: Path = Field(
        Path("legacy-ecs-template.json.j2"),
        description=(
            "The template to use for the elasticsearch "
            "dataset legacy index patterns index template"
        ),
    )

    servers: Dict[str, Any] = Field(
        ...,
        description="Dictionary of servers and their log configurations",
    )

    @validator("servers", each_item=True)
    def validate_servers(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the server logs configuration.

        Args:
            v: A single log configuration element

        Returns:
            The validated and parsed log configuration element
        """
        assert "logs" in v, "Each server must have a logs configuration"
        v["logs"] = parse_obj_as(List[LogstashLogConfig], v["logs"])
        return v

    @validator("servers", each_item=True)
    def default_server_timezone(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that each log config entry has a timezone or set default.

        Args:
            v: A single log configuration element

        Returns:
            The validated and parsed log configuration element
        """
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
        """Execute the processor and configure Logstash

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """

        variables = self.context.load()
        variables.update(
            {
                "DATASET_DIR": dataset_dir,
                "DATASET": dataset_config,
                "PARSER": parser_config,
                "servers": self.servers,
                "USE_LEGACY_TEMPLATE": self.use_legacy_template,
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

        # write legacy index template
        write_template(
            self.legacy_index_template_template,
            parser_config.settings_dir.joinpath(
                f"{dataset_config.name}-legacy-index-template.json"
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


class TrimProcessor(ProcessorBase):
    """Processor for trimming log files to a defined time frame.

    This processor can be used to remove all log lines outside
    of defined dataset observation times.

    !!! Note
        Currently only support simple time frames with a single
        start and end time.

    Example:
        ```yaml
        - name: Trim server logs to observation time
          type: dataset.trim
          context:
          var_files:
            groups: processing/config/groups.yaml
          # we only want to trim the logs of servers that will be part
          # of the IDS dataset
          indices:
            - attacker_0-*
        ```
    """

    type_: ClassVar = "dataset.trim"
    start: Optional[datetime] = Field(
        None,
        description="The start time to trim the logs to (defaults to dataset start)",
    )
    end: Optional[datetime] = Field(
        None,
        description="The end time to trim the logs to (defaults to dataset end)",
    )
    indices: Optional[List[str]] = Field(
        None, description="The log indices to trim (defaults to `<dataset>-*`)"
    )

    exclude: List[str] = Field(
        [],
        description=(
            "Indices to exclude from triming. "
            "This will overwrite/exclude indices from any patterns supplied in `indices`"
        ),
    )

    indices_prefix_dataset: bool = Field(
        True,
        description=(
            "If set to true the `<DATASET.name>-` is automatically prefixed to each pattern. This "
            "is a convenience setting as per default all dataset indices start with this prefix."
        ),
    )

    def get_doc_stats(self, es: Elasticsearch, index: List[str]) -> List[Bucket]:
        """Get a list of unique log file paths.

        Args:
            es: The elasticsearch client object
            index: The indices to get the data for

        Returns:
            List of log file paths.
        """
        # disable request cache to ensure we always get latest info
        search_lines = Search(using=es, index=index).params(request_cache=False)

        # setup aggregations
        search_lines.aggs.bucket(
            "files",
            "composite",
            sources=[{"path": {"terms": {"field": "log.file.path"}}}],
        )

        # use custom scan function to ensure we get all the buckets
        return scan_composite(search_lines, "files")

    def get_line_stats(self, es: Elasticsearch, index: List[str]) -> List[Bucket]:
        """Retrieve minimum and maximum line numbers for the log files.

        Args:
            es: The elasticsearch client object
            index: The indices to get the stats for

        Returns:
            List of min and max line numbers per file
        """
        # disable request cache to ensure we always get latest info
        search_lines = Search(using=es, index=index).params(request_cache=False)

        # setup aggregations
        search_lines.aggs.bucket(
            "files",
            "composite",
            sources=[{"path": {"terms": {"field": "log.file.path"}}}],
        )
        search_lines.aggs["files"].metric("min_line", "min", field="log.file.line")
        search_lines.aggs["files"].metric("max_line", "max", field="log.file.line")
        # use custom scan function to ensure we get all the buckets
        return scan_composite(search_lines, "files")

    def execute(
        self,
        dataset_dir: Path,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        es: Elasticsearch,
    ) -> None:
        """Execute the processor and trim the log files.

        Args:
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
        if self.indices is None:
            # if not explicitly set use dataset root indices pattern
            indices = [f"{dataset_config.name}-*"]
        else:
            indices = (
                # if given and prefix flag is True add dataset name prefix
                [f"{dataset_config.name}-{ind}" for ind in self.indices]
                if self.indices_prefix_dataset
                else
                # otherwise use as is
                indices
            )

        exclude = (
            # add negative match indicator '-' and dataset name prefix
            [f"-{dataset_config.name}-{exc}" for exc in self.exclude]
            if self.indices_prefix_dataset
            # add negative match indicator only
            else [f"-{exc}" for exc in self.exclude]
        )
        start = self.start or dataset_config.start
        end = self.end or dataset_config.end
        # exclude must be after indices for negative patterns to work as expected
        index = indices + exclude

        # get documents before trim
        docs_before = {
            bucket.key.path: bucket.doc_count
            for bucket in self.get_line_stats(es, index)
        }

        remove = Search(using=es, index=index)
        # setup trim range filter
        # start >= @timestamp < end
        valid_range = Range(**{"@timestamp": {"gte": start, "lt": end}})

        # remove all elements outside of range i.e., `not` valid_range
        remove = remove.filter(~valid_range)
        # refresh="true" is important to ensure consecutive queries
        # use up to date information
        print(remove.params(refresh="true", request_cache=False).delete().to_dict())

        # lines after trim
        lines_after = self.get_line_stats(es, index)

        # trim each file
        for bucket in lines_after:
            first_line = int(bucket.min_line.value)
            last_line: Optional[int] = int(bucket.max_line.value)
            if docs_before[bucket.key.path] - (first_line - 1) == last_line:
                # if our last line is already correct we set it to None and skip truncate
                # since truncating requires us to read up to the truncate point
                last_line = None

            trim_file(bucket.key.path, first_line, last_line)
            # delete entry for this file so we later can detect if a file must be deleted completely
            del docs_before[bucket.key.path]

        # any file that still has a docs before entry
        # does not have any logs within the trim range and thus should be deleted
        for path in docs_before.keys():
            print(
                f"Removing {path} as it does not have any log lines within the observation time."
            )
            # delete the file
            Path(path).unlink()

        # update entries in elastic search
        update_lines = UpdateByQuery(using=es, index=index)
        # adjust map for shifting line numbers in the db to start at our new min line
        adjust_map = {
            bucket.key.path: int(bucket.min_line.value - 1)
            for bucket in lines_after
            # only include paths that need actual changing
            if int(bucket.min_line.value - 1) > 0
        }

        # we only have entries to update if the adjust map is non empty
        if len(adjust_map) > 0:
            # pre filter our update query to only include file paths we
            # want to update
            update_lines = update_lines.filter(
                "terms",
                log__file__path=list(adjust_map.keys()),
            )

            # ToDO might be better as async query due to threat of timeouts
            # (i.e., update_lines.to_dict() and then use low level async API)
            update_lines.script(
                lang="painless",
                # subtract matching the entries log file path
                source="ctx._source.log.file.line -= params[ctx._source.log.file.path]",
                params=adjust_map,
            ).execute()


class ProcessorPipeline:
    """The Cyber Range Kyoushi Dataset processing pipeline implementation.

    This class is used to configure, parse and execute the pre and post
    processing steps.
    """

    def __init__(self, processor_map: Optional[Dict[str, Any]] = None):
        """
        Args:
            processor_map: Dict of processors to execute
        """

        if processor_map is None:
            processor_map = {}

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
                ComponentTemplateCreateProcessor.type_: ComponentTemplateCreateProcessor,
                TemplateCreateProcessor.type_: TemplateCreateProcessor,
                LegacyTemplateCreateProcessor.type_: LegacyTemplateCreateProcessor,
                IngestCreateProcessor.type_: IngestCreateProcessor,
                TrimProcessor.type_: TrimProcessor,
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
        """Executes the processor pipeline by running all the configured processors.

        Args:
            data: The raw processor information
            dataset_dir: The dataset path
            dataset_config: The dataset configuration
            parser_config: The dataset parser configuration
            es: The elasticsearch client object
        """
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
