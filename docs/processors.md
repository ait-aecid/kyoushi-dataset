# Dataset Processors

On this page you can learn about the various dataset processors available with Cyber Range Kyoushi Dataset.

## Util and Debug

### Console Print (`print`)

::: cr_kyoushi.dataset.processors:PrintProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

## File Manipulation

### Create Directory (`mkdir`)

::: cr_kyoushi.dataset.processors:CreateDirectoryProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### GZip Decompress (`gzip`)

::: cr_kyoushi.dataset.processors:GzipProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### File Template (`template`)

::: cr_kyoushi.dataset.processors:TemplateProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### File Trimming (`trim`)

::: cr_kyoushi.dataset.processors:TrimProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"
            - "!^get_doc_stats"
            - "!^get_line_stats"

### PCAP Conversion (`pcap.elasticsearch`)

::: cr_kyoushi.dataset.processors:PcapElasticsearchProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

## Elasticsearch

### Elasticsearch ingest pipeline (`elasticsearch.ingest`)

::: cr_kyoushi.dataset.processors:IngestCreateProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### Elasticsearch Index Template (`elasticsearch.template`)

::: cr_kyoushi.dataset.processors:TemplateCreateProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### Elasticsearch Index Component Template (`elasticsearch.component_template`)

::: cr_kyoushi.dataset.processors:ComponentTemplateCreateProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

### Elasticsearch Legacy Index Template (`elasticsearch.legacy_template`)

::: cr_kyoushi.dataset.processors:LegacyTemplateCreateProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"

## Logstash

### Logstash setup (`logstash.setup`)

::: cr_kyoushi.dataset.processors:LogstashSetupProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"
            - "!^default_server_timezone"
            - "!^validate_servers"

## Data Flow and Logic

### ForEach Loop (`foreach`)

::: cr_kyoushi.dataset.processors:ForEachProcessor
    rendering:
        show_root_heading: false
        show_source: false
        show_root_toc_entry: false
        heading_level: 4
    selection:
        inherited_members: yes
        filters:
            - "!^_[^_]"
            - "!^__values__"
            - "!^fields"
            - "!__class__"
            - "!__config__"
            - "!^Config$"
            - "!^execute"
            - "!^name"
            - "!^context"
            - "!^type_field"
            - "!^processors"
