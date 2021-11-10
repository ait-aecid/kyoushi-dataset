# Label Dataset (`cr-kyoushi-dataset label`)

{%- macro doc_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}

The final dataset processing step is the application of labels to log events. The *Cyber Range Kyoushi Dataset* tool implements this step through the `label` command. This command reads **rendered** labeling rules and applies them to the dataset by executing the labeling logic (e.g., Elasticsearch queries) and applying the given labels to the returned log rows. Note for this to be possible all templated labeling rules must be rendered during the post-processing phase of the `process` command.

The *Cyber Range Kyoushi Dataset* tool implements four labeling rule types that can be used to configure how and which logs are labeled. See [Labeling rules]({{ doc_url("rules") }}) for an overview and example rules. Note that should the four provided labeling rule types not be sufficient for labeling a certain dataset, new rules implementing different labeling logic can be added.
