from typing import (
    Any,
    Dict,
    List,
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
