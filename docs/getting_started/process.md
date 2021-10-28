# Process Dataset (`cr-kyoushi-dataset process`)

{%- macro image_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}
