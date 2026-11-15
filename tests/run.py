#!/usr/bin/env python3
"""Run the unit tests in parallel subprocesses.

Discovers the tests like `python3 -m unittest discover tests` and runs them in
parallel, each test in its own `python3 -m unittest` process; a class with
setUpClass (or a module with setUpModule) runs as one unit, so shared setup
still runs once. Prints each failure with its output, the ten slowest units and
a summary; exits 1 if any unit fails.

Usage: python3 tests/run.py [-j N] [-v] [--agent] [pattern ...]
  -j N      parallel jobs (default: the CPU count)
  -v        print every unit as it finishes
  --agent   run the opt-in agent tests in tests/agent/ instead (they may launch
            a real agent harness and spend credits; see tests/agent/README.md)
  pattern   run only tests whose id contains one of the patterns
            (e.g. test_msm, TestDispatch)

Tests must be safe to run in parallel: temporary roots, no fixed ports or
shared paths. Each test process imports tests/testenv.py first: the test config,
in which agent commands fail unless the test sets a fake, and none of the
caller's loop settings. The default run never includes tests/agent/. The runner
builds one template loop repo per run, which tests copy rather than build their
own (testenv.loop_repo()).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import testenv  # noqa: E402  (the test environment, before any test module)

CODE = os.path.dirname(TESTS)
AGENT_TESTS = os.path.join(TESTS, "agent")  # opt-in: tests that run real agents

# Modules with slow tests (whole loops with the fake agent, or scripts run as
# subprocesses), by measured seconds per unit, slowest first: started first, so the
# run ends on short units and the long ones stay off the critical path.
SLOW = ("test_metrics_e2e", "test_scenarios", "test_scenarios_more", "test_curate_scripts",
        "test_curate", "test_requirements_curator", "test_requirements_auditor",
        "test_requirements_dispatch", "test_scripts", "test_loop", "test_requirements_loop",
        "test_metrics", "test_init")

# A child process: `python3 -m unittest <id>` with the test directory and tests/
# on the path, in the test environment (tests/testenv.py).
CHILD = ("import sys, unittest; sys.path[:0] = [sys.argv[3], sys.argv[1]]; import testenv; "
         "unittest.main(module=None, argv=['unittest', sys.argv[2]])")


def iter_tests(suite):
    """The test cases in a (nested) suite."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def shared_setup(cls):
    """True if a class or its module has setup that its tests share."""
    module = sys.modules.get(cls.__module__)
    return (cls.setUpClass.__func__ is not unittest.TestCase.setUpClass.__func__
            or hasattr(module, "setUpModule"))


def discover(patterns=(), start=TESTS):
    """The units to run, as unittest ids: a test ("test_msm.MsmTest.test_x"), a
    class with shared setup ("test_x.TestY") or a module that failed to import.
    start is tests/ (the default suite, never tests/agent/) or AGENT_TESTS."""
    sys.path[:0] = [start, TESTS]
    suite = unittest.defaultTestLoader.discover(start, top_level_dir=start)
    units = []
    for test in iter_tests(suite):
        if start == TESTS and test.id().startswith("agent."):
            continue  # opt-in only, even if tests/agent/ becomes a package
        cls = type(test)
        if cls.__name__ == "_FailedTest":  # an import error: run the module to show it
            unit = test.id().split(".")[-1]
        elif shared_setup(cls):
            unit = f"{cls.__module__}.{cls.__qualname__}"
        else:
            unit = test.id()
        if patterns and not any(p in test.id() for p in patterns):
            continue
        if unit not in units:
            units.append(unit)
    return units


def order(units):
    """Units of slow modules first, in discovery order otherwise."""
    def rank(item):
        index, unit = item
        module = unit.split(".")[0]
        return (SLOW.index(module) if module in SLOW else len(SLOW), index)
    return [unit for _, unit in sorted(enumerate(units), key=rank)]


def run_unit(unit, top=TESTS):
    """Run one unit in its own process: (unit, exit code, output, seconds).
    As with `discover tests`, the working directory is the repo root and top
    (tests/, or tests/agent/) is the top-level directory."""
    start = time.time()
    p = subprocess.run([sys.executable, "-c", CHILD, TESTS, unit, top], cwd=CODE,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, stdin=subprocess.DEVNULL)
    return unit, p.returncode, p.stdout, time.time() - start


def counts(output):
    """(tests run, skipped) from a unittest report."""
    ran = skipped = 0
    for line in output.splitlines():
        if line.startswith("Ran "):
            ran = int(line.split()[1])
        if "skipped=" in line:
            skipped = int(line.split("skipped=")[1].split(")")[0].split(",")[0])
    return ran, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the unit tests in parallel.")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--agent", action="store_true",
                        help="run the opt-in agent tests (tests/agent/) instead")
    parser.add_argument("patterns", nargs="*")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("-j must be at least 1")

    top = AGENT_TESTS if args.agent else TESTS
    units = discover(args.patterns, top) if os.path.isdir(top) else []
    if not units:
        if args.agent and not args.patterns:
            print("no agent tests in tests/agent/")
            return 0
        print("no tests found", file=sys.stderr)
        return 1

    start = time.time()
    results = []
    with tempfile.TemporaryDirectory(prefix="10km-run-") as tmp, \
            ThreadPoolExecutor(max_workers=args.jobs) as pool:
        template = os.path.join(tmp, "loop")
        testenv.make_template(template)
        os.environ[testenv.TEMPLATE_VAR] = template  # tests copy it: testenv.loop_repo()
        futures = [pool.submit(run_unit, unit, top) for unit in order(units)]
        for future in as_completed(futures):
            unit, rc, output, seconds = future.result()
            results.append((unit, rc, output, seconds))
            if rc != 0:
                print(f"FAIL {unit} ({seconds:.1f}s)\n{output.rstrip()}\n", flush=True)
            elif args.verbose:
                print(f"ok   {unit} ({seconds:.1f}s)", flush=True)
    wall = time.time() - start

    failed = sorted(unit for unit, rc, _, _ in results if rc != 0)
    ran = sum(counts(out)[0] for _, _, out, _ in results)
    skipped = sum(counts(out)[1] for _, _, out, _ in results)
    print("Slowest:")
    for unit, _, _, seconds in sorted(results, key=lambda r: -r[3])[:10]:
        print(f"  {seconds:6.1f}s  {unit}")
    print(f"Ran {ran} tests in {len(results)} processes, {args.jobs} jobs, {wall:.1f}s"
          f" (skipped {skipped}).")
    if failed:
        print(f"FAILED ({len(failed)}): {' '.join(failed)}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
