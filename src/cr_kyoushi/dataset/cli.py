"""Cyber Range Kyoushi Dataset CLI module"""

import json
import os
import shutil

from datetime import datetime
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import click

from elasticsearch import Elasticsearch
from pydantic import (
    ValidationError,
    parse_obj_as,
)
from ruamel.yaml.parser import ParserError as YamlParserError

from . import LAYOUT
from .config import (
    DatasetConfig,
    ProcessingConfig,
)
from .labels import (
    Labeler,
    LabelException,
    get_label_counts,
)
from .parser import LogstashParser
from .processors import ProcessorPipeline
from .sample import (
    get_sample,
    get_sample_log,
)
from .utils import (
    load_file,
    write_model_to_yaml,
)


ISOTimestamp = click.DateTime(
    [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]
)


class Info:
    """An information object to pass data between CLI functions."""

    def __init__(self):  # Note: This object must have an empty constructor.
        """Create a new instance."""
        self.dataset_dir: Path = Path(".").absolute()
        self.logstash_bin: Path = Path("/usr/share/logstash/bin/logstash")
        self.elasticsearch_url: str = "http://127.0.0.1:9200"


# pass_info is a decorator for functions that pass 'Info' objects.
#: pylint: disable=invalid-name
pass_info = click.make_pass_decorator(Info, ensure=True)


class CliPath(click.Path):
    """A Click path argument that returns a pathlib Path, not a string"""

    def convert(self, value, param, ctx):
        return Path(super().convert(value, param, ctx))


@click.group()
@click.option(
    "--dataset",
    "-d",
    type=CliPath(file_okay=False, writable=True, resolve_path=True),
    default="./",
    show_default=True,
    help="The dataset to process",
)
@click.option(
    "--logstash",
    "-l",
    type=CliPath(dir_okay=False, readable=True, resolve_path=True),
    default="/usr/share/logstash/bin/logstash",
    show_default=True,
    help="The logstash binary to use for parsing",
)
@click.option(
    "--elasticsearch",
    "-e",
    type=click.STRING,
    default="http://127.0.0.1:9200",
    show_default=True,
    help="The connection string for the elasticsearch database",
)
@pass_info
def cli(info: Info, dataset: Path, logstash: Path, elasticsearch: str):
    """Run Cyber Range Kyoushi Dataset."""
    info.dataset_dir = dataset
    info.logstash_bin = logstash
    info.elasticsearch_url = elasticsearch
    # change to dataset directory
    if info.dataset_dir.exists():
        os.chdir(info.dataset_dir)


@cli.command()
@pass_info
def version(info: Info):
    """Get the library version."""
    from .utils import version_info

    click.echo(version_info(cli_info=info))


@cli.command()
@click.option(
    "--gather-dir",
    "-g",
    required=True,
    type=CliPath(file_okay=False, readable=True, resolve_path=True),
    help="The logs and facts gather source directory. This directory will be copied to the dataset directory.",
)
@click.option(
    "--process-dir",
    "-p",
    required=True,
    type=CliPath(file_okay=False, readable=True, resolve_path=True),
    help="The processing source directory (containing the process pipelines, templates and rules.",
)
@click.option(
    "--name",
    type=click.STRING,
    help="The name to use for the dataset (will be prompted if not supplied)",
)
@click.option(
    "--start",
    type=ISOTimestamp,
    help="The the datasets observation start time (will be prompted if not supplied)",
)
@click.option(
    "--end",
    type=ISOTimestamp,
    help="The the datasets observation end time (will be prompted if not supplied)",
)
@click.option(
    "--yes",
    "-y",
    "non_interactive",
    is_flag=True,
    help="Affirm all confirmation prompts (use for non-interactive mode)",
)
@pass_info
def prepare(
    info: Info,
    gather_dir: Path,
    process_dir: Path,
    name: str,
    start: datetime,
    end: datetime,
    non_interactive: bool,
):
    # check if the given dataset dir exist and is not empty
    if info.dataset_dir.exists() and any(info.dataset_dir.iterdir()):
        # abort if the user does not confirm
        non_interactive or click.confirm(
            f"The dataset directory '{info.dataset_dir}' is not empty.\nAre you sure that you want to continue?",
            abort=True,
        )

        # if the user confirmed we delete the directory
        click.echo("Deleting old dataset directory.")
        shutil.rmtree(info.dataset_dir)

    click.echo("Creating dataset directory structure ...")
    # ensure that the dataset directory exists
    os.makedirs(info.dataset_dir, exist_ok=True)

    click.echo("Creating dataset config file ..")
    # create dataset config prompt user if CLI args were not supplied
    dataset_config = DatasetConfig(
        name=name
        or click.prompt(
            "Please enter the name to use for the dataset",
            default=info.dataset_dir.name,
            type=click.STRING,
        ),
        start=start
        or click.prompt(
            "Please enter the datasets observation start time", type=ISOTimestamp
        ),
        end=end
        or click.prompt(
            "Please enter the datasets observation end time", type=ISOTimestamp
        ),
    )
    write_model_to_yaml(dataset_config, info.dataset_dir.joinpath(LAYOUT.CONFIG.value))

    # create rules and labels directory
    os.makedirs(info.dataset_dir.joinpath(LAYOUT.LABELS.value), exist_ok=True)
    os.makedirs(info.dataset_dir.joinpath(LAYOUT.RULES.value), exist_ok=True)

    gather_dest = info.dataset_dir.joinpath(LAYOUT.GATHER.value)
    process_dest = info.dataset_dir.joinpath(LAYOUT.PROCESSING.value)

    click.echo("Copying gathered logs and facts into the dataset ...")
    shutil.copytree(gather_dir, gather_dest)
    click.echo("Copying the processing configuration into the dataset ...")
    shutil.copytree(process_dir, process_dest)
    click.echo(f"Dataset initialized in: {info.dataset_dir}")


@cli.command()
@click.option(
    "--config",
    "-c",
    type=CliPath(exists=True, dir_okay=False, resolve_path=True, readable=True),
    default="./" + LAYOUT.PROCESSING_CONFIG.value,
    help="The processing configuration file (defaults to <dataset dir>/processing/process.yaml)",
)
@click.option(
    "--dataset-config",
    "dataset_cfg_path",
    type=CliPath(exists=True, dir_okay=False, resolve_path=True, readable=True),
    default="./dataset.yaml",
    help="The dataset configuration file (defaults to <dataset dir>/dataset.yaml)",
)
@click.option(
    "--skip-pre",
    "skip_pre",
    is_flag=True,
    help="Skip the pre processing phase",
)
@click.option(
    "--skip-parse",
    "skip_parse",
    is_flag=True,
    help="Skip the parsing phase",
)
@click.option(
    "--skip-post",
    "skip_post",
    is_flag=True,
    help="Skip the post processing phase",
)
@pass_info
@click.pass_context
def process(
    ctx: click.Context,
    info: Info,
    config: Path,
    dataset_cfg_path: Path,
    skip_pre: bool,
    skip_parse: bool,
    skip_post: bool,
):
    """Process the dataset and prepare it for labeling."""

    processing_config = ProcessingConfig.parse_obj(load_file(config))
    dataset_config = DatasetConfig.parse_obj(load_file(dataset_cfg_path))
    es = Elasticsearch([info.elasticsearch_url], timeout=180)

    pipeline_processor = ProcessorPipeline()
    parser = LogstashParser(dataset_config, processing_config.parser, info.logstash_bin)

    if not skip_pre:
        click.echo("Running pre-processors ...")
        pipeline_processor.execute(
            processing_config.pre_processors,
            info.dataset_dir,
            dataset_config,
            processing_config.parser,
            es,
        )
    else:
        click.echo("Skipping pre-processors ...")

    if not skip_parse:
        click.echo("Parsing log files ...")
        # exec logstash
        parser.parse()
    else:
        click.echo("Skipping parseing ...")

    if not skip_post:
        click.echo("Running post-processors ...")
        pipeline_processor.execute(
            processing_config.post_processors,
            info.dataset_dir,
            dataset_config,
            processing_config.parser,
            es,
        )
    else:
        click.echo("Skip post-processors ...")


@cli.command()
@click.option(
    "--dataset-config",
    "dataset_cfg_path",
    type=CliPath(exists=True, dir_okay=False, resolve_path=True, readable=True),
    default="./dataset.yaml",
    help="The dataset configuration file (defaults to <dataset dir>/dataset.yaml)",
)
@click.option(
    "--label-object",
    "label_object",
    default="kyoushi_labels",
    help="The field to store the labels in",
)
@click.argument(
    "rule_dirs",
    type=str,
    nargs=-1,
)
@click.option(
    "--label/--no-label",
    default=True,
    help="If the labeling rules should be applied or not",
)
@click.option(
    "--write/--no-write",
    default=True,
    help="If the label files should be written or not",
)
@click.option(
    "--write-skip-files",
    "skip_files",
    help=(
        "Optionally a comma separated list of log files to not write labels for."
        "(if this is not set label files will be written for all files with labeled log lines)"
    ),
)
@click.option(
    "--write-exclude-index",
    "-e",
    "exclude",
    help="Comma separated list of indices to explicitly exclude when writing label files",
)
@pass_info
@click.pass_context
def label(
    ctx: click.Context,
    info: Info,
    dataset_cfg_path: Path,
    label_object: str,
    rule_dirs: List[str],
    label: bool,
    write: bool,
    skip_files: str,
    exclude: str,
):
    """Apply the labeling rules to the dataset

    RULE_DIRS The directories from which to load the label rules (defaults to <dataset dir>/rules).
              Relative paths start at the dataset dir.

    Rules are automatically loaded from all *.json, *.yaml, *.yml files in the given rule dirs.

    """
    if len(rule_dirs) <= 0:
        rule_dirs = ["./rules"]

    dataset_config = DatasetConfig.parse_obj(load_file(dataset_cfg_path))
    es = Elasticsearch([info.elasticsearch_url], timeout=180)

    rules: List[Dict[str, Any]] = []

    # iterate through rule dirs and get flattended list of rules
    for d in rule_dirs:
        d_path = Path(d).absolute()
        if d_path.exists():
            rule_files = _get_rule_files(d_path)
            # load rule files
            for rule_file in rule_files:
                try:
                    data = load_file(rule_file)
                    data = parse_obj_as(List[Dict[str, Any]], data)
                    rules.extend(data)
                except (
                    YamlParserError,
                    ValidationError,
                    JSONDecodeError,
                    PermissionError,
                ) as e:
                    raise click.UsageError(f"Reading rule file {rule_file}:\n\n{e}")
        else:
            raise click.UsageError(f"Given rule directory '{d_path}' does not exist")

    labeler = Labeler(
        update_script_id="kyoushi_label_update",
        label_object=label_object,
    )

    try:
        if label:
            labeler.execute(rules, info.dataset_dir, dataset_config, es)
        if write:
            write_index = [f"{dataset_config.name}-*"]
            if exclude is not None:
                write_index.extend(
                    [f"-{dataset_config.name}-{i}" for i in exclude.split(",")]
                )
            _skip_files = skip_files.split(",") if skip_files is not None else []
            labeler.write(
                info.dataset_dir, dataset_config, es, write_index, _skip_files
            )
    except ValidationError as e:
        raise click.UsageError(f"Error while parsing the rules: {e}")
    except LabelException as e:
        print(f"Error while executing the rules: \n{e}")
        raise click.Abort()


def _get_rule_files(directory: Path) -> List[Path]:
    types = ["*.json", "*.yaml", "*.yml"]
    files: List[Path] = []
    for t in types:
        files.extend(directory.glob(t))
    return sorted(files)


@cli.command()
@click.option(
    "--dataset-config",
    "dataset_cfg_path",
    type=CliPath(exists=True, dir_okay=False, resolve_path=True, readable=True),
    default="./dataset.yaml",
    help="The dataset configuration file (defaults to <dataset dir>/dataset.yaml)",
)
@click.option(
    "--label-object",
    "label_object",
    default="kyoushi_labels",
    help="The field to store the labels in",
)
@click.option(
    "--label",
    "-l",
    "label",
    help="The label to get sample log lines for (if this is not set then unlabeled log lines will be sampled)",
)
@click.option(
    "--from-timestamp",
    "from_timestamp",
    type=ISOTimestamp,
    help="Optional minium timestamp for log rows to consider",
)
@click.option(
    "--until-timestamp",
    "until_timestamp",
    type=ISOTimestamp,
    help="Optional maximum timestamp for log rows to consider",
)
@click.option(
    "--files",
    "-f",
    "files",
    help=(
        "Optionally a comma separated list of files to get sample log lines from "
        "(if this is not set all files matching the label option will be drawn from)."
    ),
)
@click.option(
    "--related",
    "-r",
    "related",
    help=(
        "Optionally a comma separated list of elasticsearch indices for which to include the log line, "
        "that is closest (based on the timestamp) to the selected sample, as meta information. "
        "Given indices are prefixed with the dataset name."
    ),
)
@click.option(
    "--default-label",
    "default_label",
    default="normal",
    help="The label to assign to unlabeled log row (e.g., when --label is not used)",
)
@click.option(
    "--index",
    "-i",
    "index",
    help="Comma separated list of indices to consider for sampling",
)
@click.option(
    "--exclude-index",
    "-e",
    "exclude",
    help="Comma separated list of indices to explicitly exclude from the sampling",
)
@click.option(
    "--seed",
    "-s",
    help="The random seed to use for the sampling query",
)
@click.option(
    "--seed-field",
    "seed_field",
    default="_seq_no",
    help="The field to use for the elasticsearch random score",
)
@click.option(
    "--list",
    "list_only",
    is_flag=True,
    help="Only list the available labels with their log line counts as JSON array",
)
@click.argument("size", type=click.INT, default=10)
@pass_info
@click.pass_context
def sample(
    ctx: click.Context,
    info: Info,
    dataset_cfg_path: Path,
    label_object: str,
    label: Optional[str],
    from_timestamp: Optional[datetime],
    until_timestamp: Optional[datetime],
    files: Optional[str],
    related: Optional[str],
    default_label: str,
    index: Optional[str],
    exclude: Optional[str],
    seed: Optional[int],
    seed_field: str,
    list_only: bool,
    size: int,
):
    dataset_config = DatasetConfig.parse_obj(load_file(dataset_cfg_path))
    es = Elasticsearch([info.elasticsearch_url], timeout=180)

    _index = (
        [f"{dataset_config.name}-{i}" for i in index.split(",")]
        if index is not None
        else [f"{dataset_config.name}-*"]
    )

    if exclude is not None:
        _index.extend([f"-{dataset_config.name}-{i}" for i in exclude.split(",")])

    if list_only:
        # rune composite query to get all labels
        buckets = get_label_counts(es, index=_index, label_object=label_object)
        print(json.dumps([b.to_dict() for b in buckets]))
    else:

        _label = [label] if label is not None else []
        _files = files.split(",") if files is not None else []
        _related = (
            [f"{dataset_config.name}-{r}" for r in related.split(",")]
            if related is not None
            else []
        )

        lines = get_sample(
            es,
            label_filter_script_id=f"{dataset_config.name}_kyoushi_label_filter",
            labels=_label,
            files=_files,
            index=_index,
            label_object=label_object,
            size=size,
            seed=seed,
            seed_field=seed_field,
            start=from_timestamp,
            stop=until_timestamp,
        )

        samples = [
            get_sample_log(
                es,
                line,
                label if label is not None else default_label,
                info.dataset_dir.joinpath(LAYOUT.GATHER.value),
                related=_related,
                index=_index,
            )
            for line in lines
        ]
        print(json.dumps(samples, indent=4))
