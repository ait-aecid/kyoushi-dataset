# Label Dataset (`cr-kyoushi-dataset label`)

{%- macro doc_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}
