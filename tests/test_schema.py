"""loopstate.schema.json is generated from the State block of REQUIREMENTS.md."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenkm import schema  # noqa: E402


class TestSchema(unittest.TestCase):
    def test_committed_schema_is_current(self):  # R95-R102
        with open(schema.REQUIREMENTS, encoding="utf-8") as f:
            wanted = schema.render(f.read())
        with open(schema.SCHEMA, encoding="utf-8") as f:
            self.assertEqual(f.read(), wanted,
                             "loopstate.schema.json is out of date: run python3 -m tenkm.schema")
        self.assertEqual(schema.main(["--check"]), 0)

    def test_schema_has_every_state_entry_and_its_types(self):  # R95-R102
        with open(schema.REQUIREMENTS, encoding="utf-8") as f:
            defs = schema.generate(f.read())["$defs"]
        self.assertEqual(list(defs), ["Loop", "Session", "Cycle", "Task", "Issue", "Audit",
                                      "CycleCreate", "CycleCurate"])
        loop = defs["Loop"]["properties"]
        self.assertEqual(loop["phase"]["enum"], ["plan", "execute", "curate", None])
        self.assertEqual(loop["stopped"]["type"], ["boolean", "null"])
        self.assertIn("updated_at", defs["Loop"]["required"])
        task = defs["Task"]["properties"]
        self.assertEqual(task["id"]["format"], "uuid")
        self.assertEqual(task["started_at"]["format"], "date-time")
        period = defs["Audit"]["properties"]["period"]
        self.assertEqual(sorted(period["properties"]), ["from", "to"])
        verdicts = defs["CycleCurate"]["properties"]["tasks"]["items"]["properties"]
        self.assertEqual(verdicts["status"]["enum"], ["accepted", "rejected"])
        self.assertNotIn("required", defs["CycleCreate"])
        self.assertIn("R98", defs["Task"]["description"])

    def test_generator_parses_a_small_block(self):
        text = ("### State\n```\nThing { id: uuid,  # R1\n  kind: a|b,\n  note: string|null,\n"
                "  span: { from: time, to: time } }\n\nthing make  # R2\n"
                "  { items: [{ name, size: number }] }\n```\n")
        defs = schema.generate(text)["$defs"]
        self.assertEqual(defs["Thing"]["description"], "Record (R1).")
        self.assertEqual(defs["Thing"]["properties"]["kind"]["enum"], ["a", "b", None])
        self.assertEqual(defs["Thing"]["properties"]["note"]["type"], ["string", "null"])
        self.assertEqual(defs["Thing"]["properties"]["span"]["type"], ["object", "null"])
        items = defs["ThingMake"]["properties"]["items"]["items"]["properties"]
        self.assertEqual(items, {"name": {}, "size": {"type": "number"}})

    def test_generator_rejects_a_malformed_block(self):
        for text in ("no state here", "### State\n```\nThing { id: uuid\n```\n",
                     "### State\n```\nThing { id: number|a }\n```\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                schema.generate(text)


if __name__ == "__main__":
    unittest.main()
