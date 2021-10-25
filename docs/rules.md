# Labeling Rules

On this page you can learn about the various labeling rules available with Cyber Range Kyoushi Dataset.

## DSL Query Rule (`elasticsearch.query`)

::: cr_kyoushi.dataset.labels:UpdateByQueryRule
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
            - "!apply"
            - "!update_params"

## EQL Sequence Rule (`elasticsearch.sequence`)

::: cr_kyoushi.dataset.labels:EqlSequenceRule
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
            - "!apply"
            - "!update_params"
            - "!query"

## DSL Sub Query Rule (`elasticsearch.sub_query`)

::: cr_kyoushi.dataset.labels:UpdateSubQueryRule
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
            - "!apply"
            - "!update_params"

## DSL Parent Query Rule (`elasticsearch.parent_query`)

::: cr_kyoushi.dataset.labels:UpdateParentQueryRule
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
            - "!apply"
            - "!update_params"
