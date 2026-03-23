SOURCE_DIR := ./src
CACHE_DIR := ./.cache
VENV_DIR := ./.venv


.PHONY: clean lint format test help env cov build install
.DEFAULT_GOAL := help


##@ Help
help: ## Display this message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development
env: ## Activate the development environment
	@poetry env activate

install: ## Install the development environment if it doesn't exists
	@poetry install
	@poetry run pre-commit install --hook-type commit-msg --hook-type pre-push --hook-type pre-commit

##@ Quality
lint: ## Check code style with ruff
	@poetry run pre-commit run --all-files

test: ## Run tests using pytest
	@poetry run pytest -v -s
	@poetry run pytest --cov=${SOURCE_DIR}

clean: ## Clean temporary files and build artifacts
	@rm --force --recursive "${CACHE_DIR}"
	@rm --force --recursive __pycache__ .pytest_cache .mypy_cache *.pyc .DS_Store
	@poetry run pre-commit clean
	@poetry run pre-commit gc
#@rm -rf ~/.cache/pre-commit/

build: test
	@poetry build
