# ExCoder 

## About 

This repo hosts the code and data for the following ISSRE 2026 paper:

Retrofitting Code Using LLMs to Support Exceptional Behavior

Authors: [Linghan Zhong](https://about.tongero.com), [Jiyang Zhang](https://jiyangzhang.github.io/), [Jayanth Srinivasa](https://outshift.cisco.com/blog/author/jayanth-srinivasa), [Junyi Jessy Li](https://jessyli.com/), [Milos Gligoric](http://users.ece.utexas.edu/~gligoric/)

```bibtex
@inproceedings{ZhongETA26excoder,
  author = {Zhong, Linghan and Zhang, Jiyang and Srinivasa, Jayanth and Li, Junyi Jessy and Gligoric, Milos},
  title = {Retrofitting Code Using LLMs to Support Exceptional Behavior},
  booktitle = {IEEE International Symposium on Software Reliability Engineering},
  year = {2026},
}
```
## Data

All the data and results generated for the paper are available at
[EngineeringSoftware/Excoder](https://huggingface.co/datasets/EngineeringSoftware/Excoder)
on Hugging Face. Download them into `_work/data` and `_work/results` to
reproduce the paper without re-running the data or experiment pipelines.

`_work/` is the scratch root for everything the pipelines generate. It is
not version controlled and does not ship with the repository, so create it
before the first run:

```bash
mkdir -p _work
```

## Setup

The Docker image brings up Python, Java 8, Maven 3.8.3 and llama.cpp together.
It is the recommended path for the data and experiment pipelines, which build
third-party Maven projects that need exactly those versions.

```bash
docker compose run --rm excoder                              # with GPU
docker compose -f docker-compose.cpu.yml run --rm excoder    # without
```

You land in `/workspace` with the environment active. Export `AZURE_END_POINT`
and `AZURE_API_KEY` beforehand and compose forwards them in.

To install locally instead, with [uv](https://docs.astral.sh/uv/) and Python
3.11:

```bash
uv sync
source .venv/bin/activate
```

That covers the qualitative and paper pipelines. The other two also need:

- **Java 8 and Maven 3.8.3**, to build the subject projects.
- **`llama-server`** from [llama.cpp](https://github.com/ggml-org/llama.cpp) on
  `PATH`, plus a GPU. The local models are served over HTTP.
- **`AZURE_END_POINT` / `AZURE_API_KEY`** for `gpt-5-mini`.
- **`GGUF_DIR`** pointing at a directory for the model weights.

Building the PDF needs `latexmk`, `pdflatex` and `bibtex`.

If you use [direnv](https://direnv.net/), `.envrc` puts the repository paths and
the virtualenv in every shell inside the tree; the pipelines do not need it.

## Running from scratch

Four scripts, each of which runs all of its stages when given no arguments. Pass
`--help` to any of them for the individual stages and options.

### Rebuild the dataset


```bash
scripts/run_data_pipeline.sh --mock    # print the plan, verify the inputs
scripts/run_data_pipeline.sh           # for real
```
### Re-run the experiments

```bash
export GGUF_DIR=/path/to/gguf
scripts/run_experiment_pipeline.sh --mock              # print the plan
scripts/run_experiment_pipeline.sh --download-models   # for real
```

### Generate paper tables

```bash
scripts/run_qualitative_analysis.sh
scripts/run_paper_pipeline.sh
```
