"""This module contains Elasticsearch related utility functions"""

from time import sleep
from typing import (
    Any,
    Dict,
    List,
    Sequence,
    Union,
)

from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search
from elasticsearch_dsl.response.aggs import Bucket


def get_transport_variables(es: Elasticsearch) -> Dict[str, Any]:
    if es.transport.hosts is not None and len(es.transport.hosts) > 0:
        # get the first host
        host = es.transport.hosts[0]

        # these we can always set
        host_variables = {
            "ELASTICSEARCH_HOST": f"{host['host']}:{host.get('port', 80)}",
            "ELASTICSEARCH_SSL": host.get("use_ssl", False),
        }
        if "http_auth" in host:
            # split RFC http auth into user and password pair
            (
                host_variables["ELASTICSEARCH_USER"],
                host_variables["ELASTICSEARCH_PASSWORD"],
            ) = host["http_auth"].split(":", 1)

        if "url_prefix" in host:
            host_variables["ELASTICSEARCH_HOST_PATH"] = host["url_prefix"]

        return host_variables
    raise TypeError("Uninitialized elasticsearch client!")


def scan_composite(search: Search, name: str) -> List[Bucket]:
    # ensure that we do not get documents for no reason
    search = search.extra(size=0)
    buckets = []
    while True:
        # need to disable cache or the API will keep returning the same result
        result = search.execute(ignore_cache=True)
        buckets.extend(result.aggregations[name].buckets)
        if "after_key" not in result.aggregations[name]:
            # no after key indicates we got everything
            return buckets
        else:
            # resume query after the key
            search.aggs[name].after = result.aggregations[name].after_key


def search_eql(
    es: Elasticsearch,
    index: Union[Sequence[str], str, None],
    body: Dict[str, Any],
    check_interval: float = 0.5,
) -> Dict[str, Any]:
    result = es.eql.search(index=index, body=body, wait_for_completion_timeout="0s")
    result_id = None
    while result["is_running"]:
        result_id = result["id"]
        sleep(check_interval)
        result = es.eql.get_status(id=result_id)

    # if result id is not none then we have a async request and have
    # to retrieve the actual result and delete the async data
    if result_id is not None:
        result = es.eql.get(id=result_id)
        # delete the async request once we have its data
        es.eql.delete(id=result_id)

    return result["hits"]
