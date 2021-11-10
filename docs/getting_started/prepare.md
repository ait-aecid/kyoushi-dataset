# Prepare Dataset (`cr-kyoushi-dataset prepare`)

{%- macro doc_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}

The `prepare` command is used to merge the defined TIM dataset processing configuration with the gathered logs and facts of a TSM.
Additionally it is also used to configure dataset specific options, such as, capture time frame or the dataset name (the command will prompt for these options, but they can also be set as CLI options).

The command will copy both parts into the current work directory using the *Cyber Range Kyoushi* dataset directory layout.

### Cyber Range Kyoushi Dataset Layout

- `dataset.yaml`: The dataset configuration file containing dataset config options (e.g., name)
- `gather`: The gather directory containing collected logs, configs and facts per testbed host.
    - `<host name>`
        - `facts.json`: The facts file containing all gathered facts for the host in JSON format.
        - `configs`: Directory containing all the system and software configuration files gathered from the host.
        - `logs`: Directory containing all the log file gathered from the host.
    - ...
- `processing`: The processing directory containing all the files and configuration for the processing and parsing pipeline.
    - `process.yaml`: The processing pipeline configuration file.
- `rules`: The labeling rules directory containing all *Cyber Range Kyoushi* labeling rules. Note that this directory should only contain rendered labeling rules. Templated labeling rules should be stored in the processing directory and the processing pipeline should be configured to save rendered versions into the rules directory.
- `labels`: The labels directory mirrors the gather directories logs. It is used to store labeling information in NDJSON format and will be populated at the end of the labeling step.
    - `<host name>`
        - `logs`
    - ...

### Example Usage

<figure>
  <a data-fancybox="gallery" href="{{ doc_url("images/prepare-demo.gif") }}">
  <img src="{{ doc_url("images/prepare-demo.gif") }}" alt="cr-kyoushi-dataset prepare CLI demo" />
  <figcaption>cr-kyoushi-dataset prepare demo</figcaption>
  </a>
</figure>
