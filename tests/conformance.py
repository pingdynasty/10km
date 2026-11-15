#!/usr/bin/env python3
"""Conformance: every requirement ID in REQUIREMENTS.md maps to evidence.

The map is split into one file per REQUIREMENTS.md section, in tests/conformance/
(plain Python, loaded by path). Each file sets:

    SECTION = "State Machine"          # the `#`/`##` heading, exactly
    MAP = {
        "R36": "tests/test_msm.py:MsmTest.test_full_cycle",            # a test
        "R1": ("prompts/worker.md", "You carry out one task"),        # a prompt, phrase
        "R5": "prompts/kickoff.md",                                    # a prompt
        "R6": ["tests/test_a.py:A.test_x", "tests/test_b.py:B.test_y"],  # several
    }
    PENDING = {"R37"}                  # not mapped yet: allowed, but reported

Evidence is checked to exist: a test by parsing its module for the class and
method; a prompt by reading it and, if given, finding the phrase (whitespace is
normalised, so phrases may span line breaks).

It fails if an ID in REQUIREMENTS.md is neither mapped nor pending, if evidence is
missing, if a file names an ID that isn't in REQUIREMENTS.md or isn't in its
section, or if an ID appears twice (in one file's MAP and PENDING, or in two
files). PENDING must only shrink: it may hold only IDs up to LAST_PENDABLE, so a
requirement added later must be mapped when it is added.

Run alone to print what is unmapped or pending: python3 tests/conformance.py
"""
import ast
import importlib.util
import os
import re
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(TESTS)
REQUIREMENTS = os.path.join(CODE, "REQUIREMENTS.md")
MAP_DIR = os.path.join(TESTS, "conformance")

# The highest ID when the conformance test was introduced; later IDs can't be pending.
LAST_PENDABLE = 311

HEADING = re.compile(r"^(#{1,2}) (.+?)\s*$")
BOLD_ID = re.compile(r"\*\*(R\d+)\*\*")
CODE_ID = re.compile(r"#\s*(R\d+)\b")
TEST_REF = re.compile(r"^(tests/[\w./-]+\.py):(\w+)\.(\w+)$")


def id_number(rid):
    return int(rid[1:])


def parse_requirements(text):
    """Return ({id: section}, [duplicate ids]) from REQUIREMENTS.md text."""
    ids, dups = {}, []
    section, in_block = None, False
    for line in text.splitlines():
        if line.startswith("```"):
            in_block = not in_block
            continue
        m = HEADING.match(line)
        if m and not in_block:
            section = m.group(2)
            continue
        found = CODE_ID.findall(line) if in_block else BOLD_ID.findall(line)
        for rid in found:
            if rid in ids:
                dups.append(rid)
            ids[rid] = section
    return ids, dups


def load_maps(directory=MAP_DIR):
    """Load every map file: [(path, SECTION, MAP, PENDING)], sorted by path."""
    maps = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(directory, name)
        spec = importlib.util.spec_from_file_location(f"conformance_map_{name[:-3]}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        maps.append((path, getattr(module, "SECTION", None), dict(getattr(module, "MAP", {})),
                     set(getattr(module, "PENDING", set()))))
    return maps


_parsed = {}


def _classes(path):
    """{class: {method names}} for a test module, parsed (never imported)."""
    if path not in _parsed:
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        _parsed[path] = {node.name: {n.name for n in node.body
                                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                         for node in tree.body if isinstance(node, ast.ClassDef)}
    return _parsed[path]


def _normalise(text):
    return " ".join(text.split())


def check_evidence(evidence):
    """Return a list of problems with one evidence entry (empty if it exists)."""
    if isinstance(evidence, list):
        if not evidence:
            return ["empty evidence list"]
        return [p for e in evidence for p in check_evidence(e)]
    phrase = None
    if isinstance(evidence, tuple):
        if len(evidence) != 2 or not all(isinstance(x, str) for x in evidence):
            return [f"bad evidence {evidence!r}: use (prompt, phrase)"]
        evidence, phrase = evidence
    if not isinstance(evidence, str):
        return [f"bad evidence {evidence!r}"]
    m = TEST_REF.match(evidence)
    if m:
        if phrase is not None:
            return [f"{evidence}: phrases are for prompts only"]
        rel, cls, method = m.groups()
        path = os.path.join(CODE, rel)
        if not os.path.isfile(path):
            return [f"{evidence}: no file {rel}"]
        classes = _classes(path)
        if cls not in classes:
            return [f"{evidence}: no class {cls} in {rel}"]
        if method not in classes[cls]:
            return [f"{evidence}: no method {method} in {cls}"]
        return []
    if re.match(r"^prompts/[\w.-]+\.md$", evidence):
        path = os.path.join(CODE, evidence)
        if not os.path.isfile(path):
            return [f"{evidence}: no such prompt"]
        if phrase is not None:
            with open(path) as f:
                if _normalise(phrase) not in _normalise(f.read()):
                    return [f"{evidence}: phrase not found: {phrase!r}"]
        return []
    return [f"bad evidence {evidence!r}: use tests/<file>.py:Class.method or prompts/<file>.md"]


def check(requirements_text=None, maps=None):
    """Check the map against REQUIREMENTS.md. Returns a dict with lists:
    errors, unmapped (neither mapped nor pending), pending, mapped."""
    if requirements_text is None:
        with open(REQUIREMENTS) as f:
            requirements_text = f.read()
    ids, dups = parse_requirements(requirements_text)
    maps = load_maps() if maps is None else maps
    errors = [f"REQUIREMENTS.md: {rid} appears more than once" for rid in dups]
    sections = {s for s in ids.values()}
    seen, mapped, pending = {}, set(), set()
    files_by_section = {}
    for path, section, mapping, pend in maps:
        name = os.path.relpath(path, CODE)
        if section not in sections:
            errors.append(f"{name}: SECTION {section!r} is not a section with IDs")
        elif section in files_by_section:
            errors.append(f"{name}: section {section!r} is also in {files_by_section[section]}")
        else:
            files_by_section[section] = name
        for rid in list(mapping) + sorted(pend, key=lambda r: (len(r), r)):
            if rid in seen:
                errors.append(f"{name}: {rid} is also in {seen[rid]}")
                continue
            seen[rid] = name
            if rid not in ids:
                errors.append(f"{name}: {rid} is not in REQUIREMENTS.md")
            elif ids[rid] != section:
                errors.append(f"{name}: {rid} belongs to section {ids[rid]!r}")
        for rid, evidence in mapping.items():
            errors += [f"{name}: {rid}: {p}" for p in check_evidence(evidence)]
            mapped.add(rid)
        for rid in pend:
            if rid in ids and id_number(rid) > LAST_PENDABLE:
                errors.append(f"{name}: {rid} is newer than R{LAST_PENDABLE} and can't be "
                              "pending: map it")
            pending.add(rid)
    order = sorted(ids, key=id_number)
    unmapped = [rid for rid in order if rid not in mapped and rid not in pending]
    for rid in unmapped:
        errors.append(f"{rid} ({ids[rid]}) is not mapped: add it to the map file for its "
                      "section in tests/conformance/")
    return {"errors": errors, "unmapped": unmapped,
            "pending": [rid for rid in order if rid in pending],
            "mapped": [rid for rid in order if rid in mapped], "total": len(ids)}


def main():
    result = check()
    print(f"{len(result['mapped'])} of {result['total']} requirement IDs mapped, "
          f"{len(result['pending'])} pending, {len(result['unmapped'])} unmapped")
    if result["pending"]:
        print("Pending: " + " ".join(result["pending"]))
    for error in result["errors"]:
        print("ERROR: " + error)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
