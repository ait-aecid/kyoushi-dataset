from typing import (
    Any,
    Dict,
)

from elasticsearch import Elasticsearch


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
