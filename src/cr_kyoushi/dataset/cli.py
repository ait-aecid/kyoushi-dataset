import os
import shutil

from datetime import datetime
from pathlib import Path

import click

from elasticsearch import Elasticsearch

from . import LAYOUT
from .config import (
    DatasetConfig,
    ProcessingConfig,
)
from .processors import ProcessorPipeline
from .utils import (
    load_file,
    write_model_to_yaml,
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
@pass_info
@click.pass_context
def process(
    ctx: click.Context,
    info: Info,
    config: Path,
    dataset_cfg_path: Path,
):
    """Process the dataset and prepare it for labeling.

    CONFIG: The processing configuration file.
    """

    processing_config = ProcessingConfig.parse_obj(load_file(config))
    dataset_config = DatasetConfig.parse_obj(load_file(dataset_cfg_path))
    es = Elasticsearch([info.elasticsearch_url])

    pipeline_processor = ProcessorPipeline()

    click.echo("Running pre-processors ...")
    pipeline_processor.execute(
        processing_config.pre_processors,
        info.dataset_dir,
        dataset_config,
        processing_config.parser,
        es,
    )

    click.echo("Parsing log files ...")
    # exec logstash

    click.echo("Running post-processors ...")
    pipeline_processor.execute(
        processing_config.post_processors,
        info.dataset_dir,
        dataset_config,
        processing_config.parser,
        es,
    )


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
    type=click.DateTime(),
    help="The the datasets observation start time (will be prompted if not supplied)",
)
@click.option(
    "--end",
    type=click.DateTime(),
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
            "Please enter the datasets observation start time", type=click.DateTime()
        ),
        end=end
        or click.prompt(
            "Please enter the datasets observation end time", type=click.DateTime()
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
