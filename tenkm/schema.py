"""tenkm.schema: generate loopstate.schema.json from the State block of REQUIREMENTS.md.

    python3 -m tenkm.schema           write loopstate.schema.json
    python3 -m tenkm.schema --check   exit 1 if the committed file is out of date

The State block is the code block under `### State`. Each entry is a name, an
optional `# Rnn` comment and a `{ field: type, ... }` body. Types:

- `number`, `string`, `boolean`; `time` (an ISO 8601 date-time); `uuid`
- `a|b|c`: one of those values; `type|null`: that type, or null
- `{ ... }`: an object; `[{ ... }]`: a list of objects
- a field without a type (`{ shortname, instructions }`): any value

Records (Loop, Session, ...) are what msm returns: every field is present, and
fields not yet set are null. Command inputs (`cycle create`, `cycle curate`)
list the fields a call takes.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "REQUIREMENTS.md")
SCHEMA = os.path.join(ROOT, "loopstate.schema.json")

SCALARS = {
    "number": {"type": "number"},
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
    "time": {"type": "string", "format": "date-time"},
    "uuid": {"type": "string", "format": "uuid"},
}
TOKEN = re.compile(r"\s*(?:(#[^\n]*)|([{}\[\]:,|])|([A-Za-z_][\w]*))")


def state_block(text):
    """The code block under `### State` in the requirements text."""
    match = re.search(r"^### State\s*\n```[^\n]*\n(.*?)^```", text, re.M | re.S)
    if not match:
        raise ValueError("no ### State code block in REQUIREMENTS.md")
    return match.group(1)


def tokens(block):
    """(kind, value) pairs: 'comment', 'punct' or 'word'."""
    pos, out = 0, []
    block = block.rstrip()
    while pos < len(block):
        match = TOKEN.match(block, pos)
        if not match:
            raise ValueError(f"unexpected text in State block: {block[pos:pos + 20]!r}")
        comment, punct, word = match.groups()
        out.append(("comment", comment[1:].strip()) if comment else
                   ("punct", punct) if punct else ("word", word))
        pos = match.end()
    return out


class Parser:
    """A recursive-descent parser over the State block's tokens."""

    def __init__(self, toks):
        self.toks = list(toks)
        self.i = 0

    def peek(self):
        """The next non-comment token, or ("end", None) at the end."""
        while self.i < len(self.toks) and self.toks[self.i][0] == "comment":
            self.i += 1
        return self.toks[self.i] if self.i < len(self.toks) else ("end", None)

    def take(self, value=None):
        """Consume the next token, checking its value if given."""
        tok = self.peek()
        if tok[0] == "end" or (value is not None and tok[1] != value):
            raise ValueError(f"State block: expected {value or 'a token'}, got {tok}")
        self.i += 1
        return tok[1]

    def entries(self):
        """[(name, requirement IDs, body)] for every entry in the block."""
        out = []
        while self.peek()[0] != "end":
            start, words = self.i, []
            while self.peek()[1] != "{":
                words.append(self.take())
            body = self.object()
            ids = [r for kind, value in self.toks[start:self.i] if kind == "comment"
                   for r in re.findall(r"R\d+", value)]
            out.append((" ".join(words), ids, body))
        return out

    def object(self):
        """`{ field[: type], ... }` as an ordered list of (field, type or None)."""
        self.take("{")
        fields = []
        while self.peek()[1] != "}":
            name = self.take()
            kind = None
            if self.peek()[1] == ":":
                self.take(":")
                kind = self.type()
            fields.append((name, kind))
            if self.peek()[1] == ",":
                self.take(",")
        self.take("}")
        return fields

    def type(self):
        """A type: ('object', fields), ('list', fields) or ('words', [alternatives])."""
        if self.peek()[1] == "{":
            return ("object", self.object())
        if self.peek()[1] == "[":
            self.take("[")
            fields = self.object()
            self.take("]")
            return ("list", fields)
        words = [self.take()]
        while self.peek()[1] == "|":
            self.take("|")
            words.append(self.take())
        return ("words", words)


def to_schema(kind, nullable=False):
    """The JSON Schema for a parsed type (None: any value)."""
    if kind is None:
        return {}
    form, value = kind
    if form == "object":
        schema = object_schema(value, nullable)
    elif form == "list":
        schema = {"type": "array", "items": object_schema(value, False)}
    else:
        nullable = nullable or "null" in value
        words = [w for w in value if w != "null"]
        if len(words) == 1 and words[0] in SCALARS:
            schema = dict(SCALARS[words[0]])
        else:
            if any(w in SCALARS for w in words):
                raise ValueError(f"State block: can't mix types and values: {value}")
            return {"enum": words + [None] if nullable else words}
    if nullable:
        schema["type"] = [schema["type"], "null"]
    return schema


def object_schema(fields, record):
    """An object schema; a record has every field, each possibly null."""
    schema = {"type": "object",
              "properties": {name: to_schema(kind, record) for name, kind in fields}}
    if record:
        schema["required"] = [name for name, _ in fields]
    return schema


def def_name(name):
    """`Loop` stays `Loop`; `cycle create` becomes `CycleCreate`."""
    return "".join(word[:1].upper() + word[1:] for word in name.split())


def generate(text):
    """The schema, as a dict, for the requirements text."""
    defs = {}
    for name, ids, fields in Parser(tokens(state_block(text))).entries():
        record = " " not in name
        schema = object_schema(fields, record)
        label = "Record" if record else "Input of `msm " + name + "`"
        schema = {"description": f"{label} ({', '.join(ids)})." if ids else f"{label}.",
                  **schema}
        defs[def_name(name)] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "loopstate.schema.json",
        "title": "10km loop state",
        "description": "Generated from the State block of REQUIREMENTS.md by "
                       "`python3 -m tenkm.schema`; don't edit by hand.",
        "$defs": defs,
    }


def render(text):
    """The schema file's contents for the requirements text."""
    return json.dumps(generate(text), indent=2) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in ([], ["--check"]):
        print("usage: python3 -m tenkm.schema [--check]", file=sys.stderr)
        return 2
    with open(REQUIREMENTS, encoding="utf-8") as f:
        wanted = render(f.read())
    if argv == ["--check"]:
        try:
            with open(SCHEMA, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            current = None
        if current != wanted:
            print("loopstate.schema.json is out of date: run python3 -m tenkm.schema",
                  file=sys.stderr)
            return 1
        return 0
    with open(SCHEMA, "w", encoding="utf-8") as f:
        f.write(wanted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
