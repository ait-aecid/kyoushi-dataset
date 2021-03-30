# This file is originally from
# https://github.com/python-poetry/poetry

# Licensed under the MIT license:
# http://www.opensource.org/licenses/MIT-license
# Copyright (c) 2018 Sébastien Eustace

PY_SRC := src/cr_kyoushi tests/


.PHONY: docs

# lists all available targets
list:
	@sh -c "$(MAKE) -p no_targets__ | \
		awk -F':' '/^[a-zA-Z0-9][^\$$#\/\\t=]*:([^=]|$$)/ {\
			split(\$$1,A,/ /);for(i in A)print A[i]\
		}' | grep -v '__\$$' | grep -v 'make\[1\]' | grep -v 'Makefile' | sort"
# required for list
no_targets__:

clean: clean-docs
	@rm -rf build dist .eggs *.egg-info
	@rm -rf .benchmarks .coverage coverage.xml htmlcov report.xml .tox
	@find . -type d -name '.mypy_cache' -exec rm -rf {} +
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '*pytest_cache*' -exec rm -rf {} +
	@find . -type f -name "*.py[co]" -exec rm -rf {} +

clean-docs:
	@rm -rf site

# install all dependencies
setup: setup-python

# test your application (tests in the tests/ directory)
test:
	@poetry run pytest --cov=src/cr_kyoushi/dataset --cov-config .coveragerc --cov-report xml --cov-report term tests/ -sq

test-html:
	@poetry run pytest --cov=src/cr_kyoushi/dataset --cov-config .coveragerc --cov-report html --cov-report term tests/ -sq

test-junit:
	@poetry run pytest --junitxml=report.xml --cov=src/cr_kyoushi/dataset --cov-config .coveragerc --cov-report xml --cov-report term tests/ -sq

release: build

version:
ifdef rule
	@poetry version $(rule)
	@sed -i -E "s/(__version__ =) \"(.+)\"/\1 \"$$(poetry version -s)\"/g" src/cr_kyoushi/dataset/__init__.py
	@git add src/cr_kyoushi/dataset/__init__.py
	@git add pyproject.toml
	@git commit -m "Bump version to $$(poetry version -s)"
	@git tag -a "$$(poetry version -s)" -m "version $$(poetry version -s)"
	@echo "Currently on branch: $$(git rev-parse --abbrev-ref HEAD)"
	@echo "Please verify changes and then: \n\tgit push\n\tgit push origin $$(poetry version -s)"
else
	@poetry version
endif

build:
	@poetry build

publish:
	@poetry publish

wheel:
	@poetry build -v

# quality checks
check: check-black check-flake8 check-isort check-mypy check-safety  ## Check it all!

check-black:  ## Check if code is formatted nicely using black.
	@poetry run black --check $(PY_SRC)

check-flake8:  ## Check for general warnings in code using flake8.
	@poetry run flake8 $(PY_SRC)

check-isort:  ## Check if imports are correctly ordered using isort.
	@poetry run isort -c $(PY_SRC)

check-mypy: ## check mypi typing
	@poetry run mypy $(PY_SRC)

check-pylint:  ## Check for code smells using pylint.
	@poetry run pylint $(PY_SRC)

check-safety:  ## Check for vulnerabilities in dependencies using safety.
	@poetry show --no-dev |  \
		awk '{printf"%s==%s\n",$$1,$$2}' | \
		poetry run safety check --stdin --full-report 2>/dev/null

# linting/formating
format: clean lint-black lint-isort

lint-black:  ## Lint the code using black.
	@poetry run black $(PY_SRC)

lint-isort:  ## Sort the imports using isort.
	@poetry run isort $(PY_SRC)

# documentation commands

docs:
	@poetry run mkdocs build

docs-offline:
	@poetry run mkdocs build --no-directory-urls

docs-serve:
	@poetry run mkdocs serve
