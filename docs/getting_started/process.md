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

The parser configuration is used to configure how the Logstash parser is executed. That is you can use it to define some of the command line arguments used to run Logstash. The more complex configuration options, such as, [Logstash filter](https://www.elastic.co/guide/en/logstash/current/filter-plugins.html) configurations must be done through normal Logstash configuration syntax. By default Logstash will use the `<dataset>/processing/logstash` directory as its main directory for storing both configuration files and runtime data (e.g., log files), but this behavior can be change by setting the appropriate parser options. See the [`Logstash Parser Configuration Model`][cr_kyoushi.dataset.config.LogstashParserConfig] for details on the available options.

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

The pre-processing phase can be used to prepare your raw dataset for parsing and data storage with Logstash and Elasticsearch. This could, for example, involve converting a binary data type (e.g., network captures in PCAP format) into a text format that can be processed by Logstash. See the [processors reference]({{ image_url("processors") }}) for an overview of processors.

## Parsing

Below we will give a brief introduction on how to configure the way raw log data is parsed into structured data. As the *Cyber Range Kyoushi Dataset* tool uses Logstash as its parsing component and Elasticsearch for storage we recommend to consult the [Logstash](https://www.elastic.co/guide/en/logstash/current/index.html) and [Elasticsearch](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html) documentation for more extensive explanations of available features and configurations.

The *Cyber Range Kyoushi Dataset* tool basically supports two ways of configuring and processing log dissection. Either [Logstash filters](https://www.elastic.co/guide/en/logstash/current/filter-plugins.html) processed by Logstash or using [Elasticsearch ingest pipelines
](https://www.elastic.co/guide/en/elasticsearch/reference/current/ingest.html).

### Logstash Filters

[Logstash filters](https://www.elastic.co/guide/en/logstash/current/filter-plugins.html) can be used to parse log data directly with Logstash. See the Logstash documentation for an overview of available filters. Filters must be configured in Logstash conf files (default conf dir `<dataset>/processing/logstash/conf.d/`) in so called `filter` blocks. The below example shows a [`grok`](https://www.elastic.co/guide/en/logstash/current/plugins-filters-grok.html) filter used to dissect OpenVPN logs.

```ruby
filter {
  if [type] == "openvpn" {
    grok {
      match => {
        "message" => [
          "%{OPENVPN_BASE} peer info: %{OPENVPN_PEER_INFO}",
          "%{OPENVPN_BASE} VERIFY EKU %{GREEDYDATA:[openvpn][verify][eku][status]}",
          "%{OPENVPN_BASE} VERIFY KU %{GREEDYDATA:[openvpn][verify][ku][status]}",
          "%{OPENVPN_BASE} VERIFY %{DATA:[openvpn][verify][status]}: depth=%{NONNEGINT:[openvpn][verify][depth]:int}, %{GREEDYDATA:[openvpn][peer][cert][info]}",
          "%{OPENVPN_BASE} (?<message>MULTI: Learn: %{IP:[destination][ip]} -> %{OPENVPN_USER}/%{OPENVPN_CONNECTION})",
          "%{OPENVPN_BASE} (?<message>MULTI: primary virtual IP for %{OPENVPN_USER}/%{OPENVPN_CONNECTION}: %{IP:[destination][ip]})",
          "%{OPENVPN_BASE} (?<message>MULTI_sva: pool returned IPv4=%{OPENVPN_POOL_RETURN:[openvpn][pool][return][ipv4]}, IPv6=%{OPENVPN_POOL_RETURN:[openvpn][pool][return][ipv6]})",
          "%{OPENVPN_BASE} (?<message>MULTI: new connection by client '%{USERNAME:[openvpn][peer][duplicate]}' will cause previous active sessions by this client to be dropped.  Remember to use the --duplicate-cn option if you want multiple clients using the same certificate or username to concurrently connect.)",
          "%{OPENVPN_BASE} %{OPENVPN_PUSH:message}",
          "%{OPENVPN_BASE} %{OPENVPN_SENT_CONTROL:message}",
          "%{OPENVPN_BASE} %{OPENVPN_DATA_CHANNEL:message}",
          "%{OPENVPN_BASE} \[UNDEF\] %{GREEDYDATA:message}",
          "%{OPENVPN_BASE} \[%{OPENVPN_USER}\] %{GREEDYDATA:message}",
          "%{OPENVPN_BASE} %{GREEDYDATA:message}"
        ]
      }

      pattern_definitions => {
          "OPENVPN_PUSH" => "(PUSH: %{GREEDYDATA:[openvpn][push][message]})"
          "OPENVPN_SENT_CONTROL" => "(SENT CONTROL \[%{USERNAME:[openvpn][control][user]}\]: '%{DATA:[openvpn][control][message]}' \(status=%{INT:[openvpn][control][status]:int}\))"
          "OPENVPN_DATA_CHANNEL" => "(%{NOTSPACE:[openvpn][data][channel]} Data Channel: %{GREEDYDATA:[openvpn][data][message]})"
          "OPENVPN_POOL_RETURN" => "(%{IP:[openvpn][pool][returned]}|\(Not enabled\))"
          "OPENVPN_TIMESTAMP" => "%{YEAR}-%{MONTHNUM2}-%{MONTHDAY} %{TIME}"
          "OPENVPN_USER" => "%{USERNAME:[source][user][name]}"
          "OPENVPN_CONNECTION" => "(%{IP:[source][ip]}:%{POSINT:[source][port]:int})"
          "OPENVPN_PEER_INFO" => "%{GREEDYDATA:[openvpn][peer][info][field]}=%{GREEDYDATA:[openvpn][peer][info][value]}"
          "OPENVPN_BASE" => "%{OPENVPN_TIMESTAMP:timestamp}( %{OPENVPN_USER}/)?(\s?%{OPENVPN_CONNECTION})?"
      }
      overwrite => ["message"]
    }
  }
}

```

### Ingest Pipelines

In contrast to Logstash filters which are directly processed by Logstash using an ingest pipeline means that log data is parsed upon *ingestion* into Elasticsearch. Ingest pipelines use so [ingest processors](https://www.elastic.co/guide/en/elasticsearch/reference/current/processors.html) for parsing log data. There are many different types of ingest processors available, please consult the Elasticsearch documentation for more details. The below code shows a simple pipeline definition (in YAML notation) using only a single [`grok`](https://www.elastic.co/guide/en/elasticsearch/reference/master/grok-processor.html) processor.

```yaml
description: Pipeline for parsing Linux auditd logs
processors:
- grok:
    field: message
    pattern_definitions:
      AUDIT_TYPE: "type=%{NOTSPACE:auditd.log.record_type}"
      AUDIT_NODE: "node=%{IPORHOST:auditd.log.node} "
      AUDIT_PREFIX: "^(?:%{AUDIT_NODE})?%{AUDIT_TYPE} msg=audit\\(%{NUMBER:auditd.log.epoch}:%{NUMBER:auditd.log.sequence}\\):(%{DATA})?"
      AUDIT_KEY_VALUES: "%{WORD}=%{GREEDYDATA}"
      ANY: ".*"
    patterns:
    - "%{AUDIT_PREFIX} %{AUDIT_KEY_VALUES:auditd.log.kv} old auid=%{NUMBER:auditd.log.old_auid}
      new auid=%{NUMBER:auditd.log.new_auid} old ses=%{NUMBER:auditd.log.old_ses}
      new ses=%{NUMBER:auditd.log.new_ses}"
    - "%{AUDIT_PREFIX} %{AUDIT_KEY_VALUES:auditd.log.kv} msg=['\"]([^=]*\\s)?%{ANY:auditd.log.sub_kv}['\"]"
    - "%{AUDIT_PREFIX} %{AUDIT_KEY_VALUES:auditd.log.kv}"
    - "%{AUDIT_PREFIX}"
    - "%{AUDIT_TYPE} %{AUDIT_KEY_VALUES:auditd.log.kv}"
```

To configure logs to use an ingest pipeline you have to set the log config to add the `@metadata.pipeline` field (assuming the Logstash Setup processor is used).

```yaml
add_field:
  "[@metadata][pipeline]": "auditd-logs"
```

Note that you also have to use the [`Ingest Pipeline processor`][cr_kyoushi.dataset.processors.IngestCreateProcessor] as part of your pre-processing configuration to setup the pipeline before the parsing phase.


### Index Templates

While by default Elasticsearch will try to automatically create correct field mappings (i.e., type definitions) for the data fields created through the parsing process, but this is not very efficient if there are many different fields or fields for which Elasticsearch would produce an incorrect mapping. Also when using Eql Sequence Rules all referenced fields must have a defined field mapping or otherwise the underlying EQL query will result in an error. This can be problematic if one of the reference fields is optional (i.e., might not occur in all dataset instances) no automatic field mapping would be created. Thus it is recommend to pre-define the index field mappings using [index templates](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-templates-v1.html). Each of the created index template files must be imported using the [`Index Template processor`][cr_kyoushi.dataset.processors.TemplateCreateProcessor] during the pre-processing phase.

## Post Processing

The post-processing phase occurs after all logs have been parsed and stored in a structured data format in Elasticsearch. Thus [processors]({{ image_url("processors") }}) configured to be executed in the post-processing phase can use log data stored in Elasticsearch as configuration input or as part of Jinja2 template logic. This can be done through the special query objects [`Search`][cr_kyoushi.dataset.templates.elastic_dsl_search] and [`EQL`][cr_kyoushi.dataset.templates.elastic_eql_search] exposed as part of the Jinja2 template context. These query objects can be used to execute [Elasticsearch DSL queries](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html) ([`Search`][cr_kyoushi.dataset.templates.elastic_dsl_search]) or [EQL queries](https://www.elastic.co/guide/en/elasticsearch/reference/current/eql-syntax.html) ([`EQL`][cr_kyoushi.dataset.templates.elastic_eql_search]). The code snippet below shows example usage for both query objects. Note that the query body is read from a context variable for brevities sake.

{% raw %}
```jinja
{%- set wp_cracked = Search(index="kyoushi-attacker_0")
                            .query(queries.escalate.wp_cracked)
                            .source(["@timestamp"]).extra(size=1)
                            .execute().hits.hits
-%}
{%- set vpn_disconnect = EQL(
                              index="kyoushi-attacker_0",
                              body=queries.escalate.vpn_disconnect
                         )["hits"]["sequences"][0]["events"]
-%}
```
{% endraw %}

Additionally we also expose the following query objects, which can be used to define DSL queries to be executed by [`Search`][cr_kyoushi.dataset.templates.elastic_dsl_search].
See the  for more details.

- `Q`: Can be used to define arbitrary DSL queries.
- `Q_ALL`: Can be used to define a DSL query with multiple search terms using the same operator (e.g., `match`) connected by `and` clauses.
- `Q_MATCH_ALL`: Same as `Q_ALL`, but the operator is always `match`.
- `Q_TERM_ALL`: Same as `Q_ALL`, but the operator is always `term`.

!!! Hint
    Also see the Elasticsearch DSL Python API [search](https://elasticsearch-dsl.readthedocs.io/en/latest/search_dsl.html) and [queries](https://elasticsearch-dsl.readthedocs.io/en/latest/search_dsl.html#queries) doc for more details on the query object `Search`, `Q`, `Q_ALL`, `Q_MATCH_ALL` and `Q_TERM_ALL`.
