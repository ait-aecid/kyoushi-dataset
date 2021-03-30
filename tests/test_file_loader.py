import os

from pathlib import Path
from typing import (
    Any,
    Dict,
    Union,
)

import pytest

from cr_kyoushi.dataset.utils import (
    load_file,
    load_json_file,
    load_yaml_file,
)


FILE_DIR = os.path.dirname(__file__) + "/fixtures"


@pytest.fixture
def data_expected():
    return {
        "int": 10,
        "str": "some string",
        "list": [1, 2, 3],
        "dict": {"foo": "bar"},
    }


@pytest.mark.parametrize(
    "file",
    [
        pytest.param(f"{FILE_DIR}/test.yaml", id="yaml-str"),
        pytest.param(f"{FILE_DIR}/test.yml", id="yml-str"),
        pytest.param(f"{FILE_DIR}/test.json", id="json-str"),
        pytest.param(Path(f"{FILE_DIR}/test.yaml"), id="yaml-path"),
        pytest.param(Path(f"{FILE_DIR}/test.yml"), id="yml-path"),
        pytest.param(Path(f"{FILE_DIR}/test.json"), id="json-path"),
    ],
)
def test_file_loader(file: Union[str, Path], data_expected: Dict[str, Any]):
    data = load_file(file)

    assert data == data_expected


def test_json_load_stream(data_expected: Dict[str, Any]):
    with open(f"{FILE_DIR}/test.json") as f:
        data = load_json_file(f)
        assert data == data_expected


def test_yaml_load_stream(data_expected: Dict[str, Any]):
    with open(f"{FILE_DIR}/test.yaml") as f:
        data = load_yaml_file(f)
        assert data == data_expected
