# Process Dataset (`cr-kyoushi-dataset process`)

{%- macro image_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}

Before a dataset can be labeled we have to process the *raw* unstructured information into a format on which we can easily apply reasoning logic (i.e., the labeling rules). The *Cyber Range Kyoushi* framework implements this process through the *Cyber Range Kyoushi Dataset* CLI tools `process` command. The command implements a 3 step processing pipeline

1. Pre-Process
2. Parse
3. Post-Process

to first prepare raw datasets processing, then parse the log events using [Logstash](https://www.elastic.co/logstash/) to store structured data in an [Elasticsearch](https://www.elastic.co/elasticsearch/) database. Finally use the generated knowledge base to make final adjustments (e.g., trimming the dataset to only relevant time frames) and rendering the labeling rules. While the *parse* step is handled by the third party software Logstash the *pre-* and *post-processing* steps are implemented by the *Dataset* tool directly. For these so called `Processors` are used to configure and perform specific processing actions (e.g., decompressing GZip files, rendering templates, etc.).

Configuration of processing pipeline (i.e., the `processors` and the Logstash parser) is done through in the `processing/process.yaml`. The `processing` directory also contains all other extra configuration, context, template, etc. files and information necessary to process raw datasets created as results of instantiating a *TIM* and executing the resulting *TSM*.


## Configuration

As mentioned above `pipeline.yml` defines the three step processing pipeline. For this each step has its own configuration key i.e.,

- `pre_processors`: The list of `processors` to sequentially execute during the pre-processing step.
- `parser`: Is the *Cyber Range Kyoushi Dataset* logstash parser configuration (i.e., how logstash should be executed). See [below](#parser-config) for details.
- `post_processors`: The list of `processors` to sequentially execute during the post-processing step.
### Processors

A `processor` is similar to an [Ansible](https://www.ansible.com/) module. That is a `processor` is represented by a partially [Jinja2](https://jinja.palletsprojects.com/en/3.0.x/) templatable [YAML](https://yaml.org/) configuration and is used to execute specific actions on a system. Meaning a `processor` is used to define what and how an action should be executed. The `pre_processors` and `post_processors` configuration each define a list of``processors` that should be executed in the defined order during the `pre-processing` and `post-processing` steps respectively.

Not all actions necessary for processing a dataset can be defined statically, in some cases it might be necessary to execute specific actions based on the dataset contents. For example, if you want to render a specific file for each command executed by a simulated attacker (information that can only be obtained after the raw dataset has been created). To support this and similar use cases the `processor` configs can contain `Jinja2` template strings making it possible to define partial processing pipeline configurations that are dynamically rendered during pipeline execution.

Every `processor` has at least the following basic configuration fields in addition to any specific fields, i.e., configuration specific to the processor action.

- `type`: This is a special field used to indicate the `processor` that is being configured e.g., setting it to `print` would result in executing the Print-Processor.
- `name`: A textual description of the action that should be achieved by executing the configured processor. This is used to ensure that each processor configuration entry has a minimum documentation as well as for outputting the current state during execution.
- `context`: The template render context to use for rendering any Jinja2 template string used as part of the processor definition. It is possible to either define inline variables or load them from YAML or JSON files.
    - `variables`: Dictionary of context variables to use during processor rendering.
    - `variable_files`: Dictionary of var files containing context variables to use during processor rendering.

!!! Note
    Context `variables` and the contents of `variable_files` are merged into a single `context` dictionary.
    Variable files take override inline variables and the priority between variable files is based on their
    dictionary position i.e., variable files defined first are overridden by those defined later.

!!! Hint
    See the [Dataset Processors]({{ image_url("processors") }}) section for a list of all `processors` shipped as part of the
    *Cyber Range Kyoushi Dataset* tool.



### Parser Config


### Example Config

The below example `process.yml` shows the configuration for a processing pipeline with 1 pre-processor, 1 post-processor and a parser configured to print debug output.

!!! Warning
    The shown configuration is just a bare minimum configuration example and
    does not configure any meaning full dataset processing on its own.

Both shown processor use Jinja2 and the `context` field to define partial configurations that are rendered dynamically during pipeline execution.


{%- raw %}
```yaml
pre_processors:
  - name: Prepare server facts
    type: template
    context:
      var_files: processing/config/groups.yaml
    template_context:
      vars:
        exclude_groups: ["Region.*", "envvars.*", "instance-.*", "meta-.*", "nova"]
        exclude_interfaces: ["lo", 'tun\d*']
        servers: "{{ all }}"
      var_files: |
       {
       {% for server in all %}
        "server_logs": "processing/config/logs.yaml",
        "{{ server }}": "gather/{{ server }}/facts.json"{% if not loop.last %},{% endif %}
       {% endfor %}
       }
    src: processing/templates/servers.json.j2
    dest: processing/config/servers.yaml
parser:
  settings_dir: processing/logstash
  conf_dir: processing/logstash/conf.d
  log_level: debug
  log_dir: processing/logstash/log
  completed_log: processing/logstash/log/file-completed.log
  data_dir: processing/logstash/data
  parsed_dir: parsed
  save_parsed: false
post_processors:
  - name: Trim server logs to observation time
    type: dataset.trim
    context:
      var_files:
        groups: processing/config/groups.yaml
    indices: |
      [
      {% for server in groups["servers"] %}
        "*-{{ server }}"{% if not loop.last %},{% endif %}
      {% endfor %}
      ]
```
{%- endraw %}

## Pre Processing


## Parsing

### Logstash Filters

### Index Templates

### Ingest Pipelines

## Post Processing
