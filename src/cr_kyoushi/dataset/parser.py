"""This module defines a python interface for using Logstash as a dataset parser."""

import signal
import subprocess

from pathlib import Path
from types import FrameType
from typing import (
    Callable,
    Optional,
    Union,
)

from .config import (
    DatasetConfig,
    LogstashParserConfig,
)


class LogstashParser:
    def __init__(
        self,
        dataset_config: DatasetConfig,
        parser_config: LogstashParserConfig,
        logstash: Path,
    ):
        self.dataset_config: DatasetConfig = dataset_config
        self.parser_config: LogstashParserConfig = parser_config
        self.logstash = logstash
        self._child: Optional[subprocess.Popen] = None
        self._sigint_handler: Union[
            Callable[[signal.Signals, FrameType], None], int, signal.Handlers, None
        ] = None

    def parse(self):
        args = [
            str(self.logstash.absolute()),
            "--path.settings",
            str(self.parser_config.settings_dir.absolute()),
        ]

        if self.parser_config.log_level is not None:
            args.extend(["--log.level", self.parser_config.log_level])

        self.proc = subprocess.Popen(args)

        self.proc.wait()

    def _register_signal_handler(self):
        self._sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._kill_child_process)

    def _kill_child_process(self, signum, frame):
        self.proc.kill()
        self.proc.wait()
        if self._sigint_handler is not None and not isinstance(
            self._sigint_handler, int
        ):
            self._sigint_handler(signum, frame)
