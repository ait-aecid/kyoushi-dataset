from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)

from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search
from elasticsearch_dsl.query import Range
from elasticsearch_dsl.response.hit import Hit


def get_sample(
    es: Elasticsearch,
    label_filter_script_id: str,
    labels: Optional[List[str]],
    files: Optional[List[str]] = None,
    index: Union[List[str], str, None] = None,
    label_object: str = "kyoushi_labels",
    size: int = 10,
    seed: Optional[int] = None,
    seed_field: str = "_seq_no",
    start: Union[str, datetime, float, None] = None,
    stop: Union[str, datetime, float, None] = None,
) -> List[Hit]:
    search = Search(using=es, index=index)

    # use random score to get a random sampling
    random_score = {"seed": seed, "field": seed_field} if seed is not None else {}
    search = search.query("function_score", random_score=random_score)
    search = search.sort("_score").extra(size=size)

    if labels is None or len(labels) == 0:
        # if we are given no labels to search for we explicitly return
        # only log rows without any labels
        search = search.exclude("exists", field=f"{label_object}.rules")
    else:
        # if we got a label then we filter for it using our script search filter
        search = search.filter(
            "script",
            script={"id": label_filter_script_id, "params": {"labels": labels}},
        )

    time_range = {}

    if start is not None:
        time_range["gte"] = start

    if stop is not None:
        time_range["lte"] = stop

    if len(time_range) > 0:
        search = search.filter(Range(**{"@timestamp": time_range}))

    if files is not None and len(files) > 0:
        search = search.filter(
            "bool", should=[{"match": {"log.file.path": f}} for f in files]
        )

    search = search.source(
        [
            "@timestamp",
            "log",
            f"{label_object}.list",
            f"{label_object}.rules",
            "type",
            "_score",
            "_seq_no",
        ]
    )

    return search.execute().hits


def _get_closest(
    es: Elasticsearch,
    related: str,
    timestamp: Union[int, float, str],
    scale: str = "5d",
) -> Optional[Hit]:
    search = Search(using=es, index=related)

    search = search.query(
        "function_score",
        functions=[{"linear": {"@timestamp": {"origin": timestamp, "scale": scale}}}],
        score_mode="multiply",
        boost_mode="multiply",
    )

    hits = (
        search.sort({"_score": "desc", "log.file.line": "asc"})
        .extra(size=1)
        .execute()
        .hits
    )

    if len(hits) < 1:
        return None

    return hits[0]


def get_sample_log(
    es: Elasticsearch,
    sample: Hit,
    label: str,
    gather_dir: Path,
    before: int = 5,
    after: int = 5,
    related: Optional[List[str]] = None,
    index: Union[List[str], str, None] = None,
) -> Dict[str, Any]:
    path = Path(sample.log.file.path)
    line_no = sample.log.file.line
    start = max(0, line_no - before)
    end = line_no + after

    before_lines: List[str] = []
    sample_line: str
    after_lines: List[str] = []

    # read the sample line and the requested surrounding lines
    with open(path, "r") as f:
        for i, line in enumerate(f, 1):
            if i >= start and i < line_no:
                before_lines.append(line)
            elif i == line_no:
                sample_line = line
            elif i > line_no and i <= end:
                after_lines.append(line)
            elif i > end:
                break
    _related: List[Dict[str, Any]] = []
    if related is not None:
        for rel in related:
            closest: Optional[Hit] = _get_closest(
                es=es, related=rel, timestamp=sample["@timestamp"]
            )
            if closest is not None and closest.log.file.path != str(path):
                if closest is not None:
                    _related.append(
                        {
                            "path": str(
                                Path(closest.log.file.path).relative_to(gather_dir)
                            ),
                            "line_no": closest.log.file.line,
                            "timestamp": closest["@timestamp"],
                        }
                    )

    return {
        "label": label,
        "rules": list(sample.kyoushi_labels.rules)
        if "kyoushi_labels" in sample
        else [],
        "path": str(path.relative_to(gather_dir)),
        "line_no": line_no,
        "before": before_lines,
        "line": sample_line,
        "after": after_lines,
        "related": _related,
    }
