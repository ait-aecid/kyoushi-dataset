# Contributing

## Packaging and Installation

This project uses [poetry](https://python-poetry.org/) for packaging and dependency management.
So before you can start developing you will have to install `poetry`.
Please refer to the [poetry documentation](https://python-poetry.org/docs/#introduction) on how to install
and use `poetry`.

### Install for development

After you have installed poetry and added your access token you can use it to install a local development clone of the repository using:

```bash
$ poetry install
```

Tests can be run using `poetry` or by using the `Makefile` provided with the project.

```bash
$ poetry run pytest
$ make test
# or if you wish to generate a HTML coverage report
$ make test-html
```

## Code Quality and Formatting

This project uses [pre-commit](https://pre-commit.com/) and various code linters and formatters to
ensure that committed code meets certain quality criteria. Note that these criteria are also checked
by CI pipelines. This means that should you push unchecked code the pipelines will fail!
So it is highly recommend that you install `pre-commit` so that such code does not make it into the the git history.

To make sure that you don't accidentally commit code that does not follow the coding style, you can
install a pre-commit hook that will check that everything is in order:

```bash
$ poetry run pre-commit install
```

The `pre-commit` git hook runs automatically when you try to commit your changes. It will automatically check
and try to format your code. Should your code not conform to the quality criteria or if some re-formatting was
necessary the commit will fail. In such cases verify the formatting changes made by `pre-commit` and fix any other
code quality issues reported by the checks before committing your changes again.

You can also manually run the `pre-commit` hook by issuing the following command.

```bash
$ poetry run pre-commit run --all-files
```

Alternatively you can also use the `Makefile` to run just the quality checks, auto formatting or just specific checks.

```bash
$ make check
$ make format
```

Run `make list` for a full list of available `make` targets.


## Build & View Documentation

This project uses [MkDocs](https://www.mkdocs.org/) for documentation. If you wish to view or edit the docs
you can start a live server by running:

```bash
$ mkdocs serve
```

The live server will automatically detect changes and refresh the documentation.

We also provide convenience `make` targets for building the documentation and starting the live server:

```bash
# build the distributable documentation site
$ make docs
# build a offline viewable documentation site, without web server simply open the index file
# (Note that the search function is disabled with this)
$ make docs-offline
# start the mkdocs live server
$ make docs-serve
```
