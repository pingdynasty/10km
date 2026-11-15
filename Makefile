# Tests for 10km. See the Testing section of AGENTS.md.
IMAGE ?= 10km

.PHONY: test smoke smoke-host

# Unit and script tests.
test:
	python3 -m unittest discover tests

# End-to-end smoke test in the container.
smoke:
	docker build -t $(IMAGE) .
	docker run --rm $(IMAGE) /opt/10km/tests/smoke.sh

# End-to-end smoke test on this host (needs bash, git, jq and python3).
smoke-host:
	tests/smoke.sh
