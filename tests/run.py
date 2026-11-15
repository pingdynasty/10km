#!/usr/bin/env python3
"""Run the unit tests in parallel subprocesses.

Discovers the tests like `python3 -m unittest discover tests` and runs them in
parallel, each test in its own `python3 -m unittest` process; a class with
setUpClass (or a module with setUpModule) runs as one unit, so shared setup
still runs once. Prints each failure with its output, the ten slowest units and
a summary; exits 1 if any unit fails.

Usage: python3 tests/run.py [-j N] [-v] [pattern ...]
  -j N      parallel jobs (default: the CPU count)
  -v        print every unit as it finishes
  pattern   run only tests whose id contains one of the patterns
            (e.g. test_msm, TestDispatch)

Tests must be safe to run in parallel: temporary roots, no fixed ports or
shared paths.
"""
import argparse
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

TESTS = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(TESTS)

# Modules with slow tests (whole loops with the fake agent, or scripts run as
# subprocesses), slowest first: started first, to keep them off the critical path.
SLOW = ("test_scenarios", "test_curate_scripts", "test_scripts", "test_init")

# A child process: `python3 -m unittest <id>` with tests/ on the path.
CHILD = ("import sys, unittest; sys.path.insert(0, sys.argv[1]); "
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


def discover(patterns=()):
    """The units to run, as unittest ids: a test ("test_msm.MsmTest.test_x"), a
    class with shared setup ("test_x.TestY") or a module that failed to import."""
    sys.path.insert(0, TESTS)
    suite = unittest.defaultTestLoader.discover(TESTS, top_level_dir=TESTS)
    units = []
    for test in iter_tests(suite):
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


def run_unit(unit):
    """Run one unit in its own process: (unit, exit code, output, seconds).
    As with `discover tests`, the working directory is the repo root and tests/
    is the top-level directory."""
    start = time.time()
    p = subprocess.run([sys.executable, "-c", CHILD, TESTS, unit], cwd=CODE,
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
    parser.add_argument("patterns", nargs="*")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("-j must be at least 1")

    units = discover(args.patterns)
    if not units:
        print("no tests found", file=sys.stderr)
        return 1

    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_unit, unit) for unit in order(units)]
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
