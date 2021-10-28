# Getting Started

{%- macro image_url(url) %}
{%- if config.site_url|length -%}
{{ config.site_url }}{{ url }}
{%- else -%}
{{ fix_url(url) }}
{%- endif -%}
{%- endmacro %}

The Cyber Range Kyoushi Dataset tool implements the **processing layer** for the *Kyoushi* model-driven IDS dataset generation and labeling framework as described by [Frank [Frank21]](#Frank21) and shown in Figure 1. Dataset definition and generation are handled by the *Model*, *Testbed* and *Data Collection* layers.

<figure>
  <a data-fancybox="gallery" href="{{ image_url("images/system.png") }}">
  <img src="{{ image_url("images/system.png") }}" alt="Cyber Range Kyoushi System Layers" />
  <figcaption>Figure 1: Cyber Range Kyoushi System Layers</figcaption>
  </a>
</figure>

The *processing layer* takes a raw dataset (logs and facts) and model definition as input for processing to create IDS labels for the log events contained in the dataset. This is done in a 5 step processes implemented by the Cyber Range Kyoushi Dataset tool:

1. Prepare
2. Process
    1. Pre-Process
    2. Parse
    3. Post-Process
3. Label

Additionally the tool also implements a CLI command that can be used for sampling a labeled Kyoushi dataset (also see the [CLI reference]({{ image_url("cli") }})).

#### References

<a name="Frank21"></a><p>Frank21: Frank, M. Quality improvement of labels for model-driven benchmark data generation for intrusion detection systems. (2021) doi:[0.34726/HSS.2021.82646](https://doi.org/10.34726/HSS.2021.82646). </p>
