# Sample Labels (`cr-kyoushi-dataset sample`)

{%- macro image_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}

After a dataset has been both processed and labeled it is often necessary to verify it. As a dataset can contain millions of log lines manual verification of all labeled and unlabeled logs is most of the time impossible. Thus we recommend to verify random samples. For this, the *Cyber Range Kyoushi Dataset* tool provides the `sample` command (see the [CLI Doc]({{ image_url("cli") }})). The command uses Elasticsearch queries with [random function scores](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html#function-random) to sample processed datasets.

!!! Hint
    The `sample` command can also be useful for when debugging during labeling rule development, since
    it can be used to quickly check the logs for which a certain label has been applied.
