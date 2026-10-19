.PHONY: help test test-unit lint docker run e2e clean

IMAGE ?= mcp-ebiblio:local
PYTHON ?= python3

help:
	@echo "make test       - run the full test suite (hermetic, no credentials)"
	@echo "make test-unit  - alias of make test (used by CI)"
	@echo "make docker     - build the container image"
	@echo "make run        - run the MCP server over stdio in Docker"
	@echo "make e2e        - real end-to-end check against eBiblio (needs credentials)"

test:
	$(PYTHON) -m pytest

test-unit: test

lint:
	$(PYTHON) -m compileall -q src tests

docker:
	docker build -t $(IMAGE) .

run:
	docker run --rm -i \
		--cap-drop=ALL --security-opt=no-new-privileges \
		-v ebiblio-data:/data \
		-e EBIBLIO_USERNAME -e EBIBLIO_PASSWORD \
		-e EBIBLIO_BASE_URL -e EBIBLIO_DATA_DIR \
		$(IMAGE)

e2e:
	$(PYTHON) scripts/e2e_ebiblio.py

clean:
	rm -rf .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
