# Tests for 10km. See the Testing section of AGENTS.md.
IMAGE ?= 10km

.PHONY: test scenarios smoke smoke-host

# Unit and script tests, in parallel (JOBS=N to set the jobs; default: CPU count).
JOBS ?=
test:
	python3 tests/run.py $(if $(JOBS),-j $(JOBS))

# End-to-end scenarios with the fake agent, on this host (part of `make test`).
scenarios:
	python3 -m unittest -v tests/test_scenarios.py

# End-to-end smoke test and scenarios in the container.
smoke:
	docker build -t $(IMAGE) .
	docker run --rm $(IMAGE) sh -c '/opt/10km/tests/smoke.sh && cd /opt/10km && python3 -m unittest -v tests/test_scenarios.py'

# End-to-end smoke test on this host (needs bash, git, jq and python3).
smoke-host:
	tests/smoke.sh
