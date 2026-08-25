PYTHON ?= python3

.PHONY: test test-integration test-docker

test:
	$(PYTHON) -m pytest -m "not integration"

test-integration:
	$(PYTHON) -m pytest -m integration -v

test-docker:
	docker build -f Dockerfile.test -t aegis-oj-sandbox-tests .
	docker run --rm --network none --security-opt seccomp=unconfined aegis-oj-sandbox-tests
