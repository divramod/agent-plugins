"""Hal2 plan 0611 step 6 (design.md §4, D6): `tollman.py state` lists the train, its cars, the hitched wagons, the open
fix orders, every open record with what closes it and the standing orders, as `--json` that validates against
schemas/state.schema.json and as text; `act` prints it before the handoff's DO FIRST. Whole commands on test_orders.Red
(a red train of the cars 07 and 09)."""

import json
import re
import unittest
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import handoff
import records_kinds
import role_records
import roles
import standing
import tollman
from test_orders import RUN, Red

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schemas/state.schema.json").read_text())
WORDS = "the user, 2026-11-05: no train until CI is rebuilt"
TYPES = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list, "null": type(None)}


def problems(value, schema, where="$") -> list[str]:
    """The subset of JSON Schema the state schema uses (no jsonschema library on the machine)."""
    out, want = [], schema.get("type")
    if want and not any(isinstance(value, TYPES[t]) and not (t == "integer" and isinstance(value, bool))
                        for t in ([want] if isinstance(want, str) else want)):
        return [f"{where}: {type(value).__name__} is not {want}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool):
        out += [f"{where}: {value} out of range" for k, ok in (("minimum", value >= schema.get("minimum", value)),
                                                              ("maximum", value <= schema.get("maximum", value)))
                if k in schema and not ok]
    if isinstance(value, dict):
        out += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            out += [f"{where}: unexpected {k}" for k in value if k not in props]
        for k, v in value.items():
            out += problems(v, props[k], f"{where}.{k}") if k in props else []
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            out += problems(v, schema["items"], f"{where}[{i}]")
    return out


class State(Red):
    def of(self):
        code, text = self.call("state", "--json")
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def test_the_json_validates_and_lists_the_train_cars_orders_records_and_standing_orders(self):
        self.assertEqual(self.call("order", "07", "--why", "its test fails", "--run", RUN)[0], 0)
        rec = standing.add(str(self.main), "minimum", 2, WORDS)
        d = self.of()
        self.assertEqual(problems(d, SCHEMA), [])
        self.assertEqual((d["schema"], bool(d["train"]["train"]), d["train"]["state"]), (1, True, "fixing"))
        self.assertEqual([c["field"] for c in d["cars"]], ["07", "09"])
        self.assertEqual([(o["id"], o["field"], o["record"]) for o in d["orders"]], [("07-fix-1", "07", "R1")])
        self.assertEqual([(r["id"], r["type"], r["slot"], r["waits_for"]) for r in d["records"]],
                         [("R1", "fix-order", "07", "fix_order")])
        self.assertEqual([(s["id"], s["rule"], s["value"], s["words"]) for s in d["standing"]],
                         [(rec["id"], "minimum", "2", WORDS)])
        self.assertIsNone(d["held"])

    def test_every_open_record_is_listed_and_a_closed_one_is_not(self):
        main = str(self.main)
        a = records_kinds.add(main, "hand-merge", "12", "hand merge of 12")
        b = records_kinds.add(main, "restart", "09", "restart 09", of="session")
        role_records.close(main, records_kinds.ROLE, b["id"], "user", "the user: not needed", "user")
        d = self.of()
        self.assertEqual([r["id"] for r in d["records"]], [a["id"]])
        open_ids = [r["id"] for r in role_records.open_(main, records_kinds.ROLE)]
        self.assertEqual([r["id"] for r in d["records"]], open_ids)
        self.assertEqual(problems(d, SCHEMA), [])

    def test_a_hold_is_shown_with_its_record_and_the_text_names_everything(self):
        self.assertEqual(self.call("hold", "--by", "user", "--words", WORDS, "--why", "CI rebuild")[0], 0)
        d = self.of()
        self.assertEqual((d["held"]["why"], d["held"]["words"], d["held"]["record"]), ("CI rebuild", WORDS, "R1"))
        self.assertEqual(problems(d, SCHEMA), [])
        code, text = self.call("state")
        self.assertEqual(code, 0)
        for part in ("train ", "cars: 07, 09", "HELD R1: CI rebuild", "standing R1 hold CI rebuild", WORDS):
            self.assertIn(part, text)

    def test_a_red_train_without_records_validates_and_a_wrong_document_does_not(self):
        d = self.of()
        self.assertEqual(problems(d, SCHEMA), [])
        self.assertTrue(problems({**d, "schema": 2}, SCHEMA) and problems({**d, "extra": 1}, SCHEMA))
        self.assertTrue(problems({k: v for k, v in d.items() if k != "records"}, SCHEMA))

    def test_act_prints_the_state_before_the_handoff_and_the_template_trusts_it(self):
        self.assertIs(tollman.WIRING.state, tollman.state_text)
        self.assertIsNone(roles.FARMER.state)
        self.call("hold", "--by", "user", "--words", WORDS, "--why", "CI rebuild")
        hf = handoff.path(str(self.main), tollman.WIRING)
        hf.parent.mkdir(parents=True, exist_ok=True)
        hf.write_text("# tollman handoff\n\n## DO FIRST\n\nlook at 07\n")
        code, text = self.call("act")
        self.assertEqual(code, 0, text)
        self.assertLess(text.index("tollman state:"), text.index("DO FIRST (from"))
        self.assertIn("HELD R1", text)
        self.assertIn("`tollman state` was printed above", handoff.show("/nonexistent", tollman.WIRING))
        self.assertNotIn("state` was printed above", handoff.show("/nonexistent", roles.FARMER))


if __name__ == "__main__":
    unittest.main()
