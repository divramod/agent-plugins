"""The DBML subset and the ERD diff (hal2 plan 0364, D5): green added, yellow changed, red removed."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dbml  # noqa: E402
import erd  # noqa: E402

CURRENT = """
// the schema today
Project shop { database_type: 'PostgreSQL' }
Table users as U {
  id integer [pk, increment]
  email varchar(255) [not null, unique, note: 'login, lowercased']
  name varchar
  Note: 'people'
  indexes {
    (email) [unique]
  }
}
Table "orders" {
  id integer [pk]
  user_id integer [ref: > users.id]
  total decimal(10, 2)
}
Table legacy { id integer }
/* a block
   comment with Table fake { x int } */
Ref: orders.user_id > users.id
Enum status { active  closed }
"""

NEW = """
Table users {
  id integer [pk, increment]
  email varchar(320) [not null, unique, note: 'login, lowercased']
  display_name varchar
}
Table orders {
  id integer [pk]
  user_id integer
  total decimal(10, 2)
}
Table sessions {
  id uuid [pk]
  user_id integer
}
Ref fk_session {
  sessions.user_id > users.id
}
Ref: orders.user_id > users.id
"""


class ParseTest(unittest.TestCase):
    def test_tables_columns_and_settings(self):
        model = dbml.parse(CURRENT)
        self.assertEqual(list(model["tables"]), ["users", "orders", "legacy"])
        users = model["tables"]["users"]["columns"]
        self.assertEqual([c["name"] for c in users], ["id", "email", "name"])
        self.assertEqual(users[1]["type"], "varchar(255)")
        self.assertEqual(users[1]["settings"], ["not null", "unique", "note: 'login, lowercased'"])
        self.assertEqual(model["tables"]["orders"]["columns"][2]["type"], "decimal(10, 2)")

    def test_refs_inline_short_and_long(self):
        self.assertEqual(dbml.parse(CURRENT)["refs"], [
            {"from": "orders.user_id", "op": ">", "to": "users.id"},
            {"from": "orders.user_id", "op": ">", "to": "users.id"}])
        refs = dbml.parse(NEW)["refs"]
        self.assertIn({"from": "sessions.user_id", "op": ">", "to": "users.id"}, refs)

    def test_comments_are_dropped(self):
        self.assertNotIn("fake", dbml.parse(CURRENT)["tables"])

    def test_settings_split_respects_quotes(self):
        self.assertEqual(dbml.split_settings("pk, note: 'a, b', default: \"x,y\""),
                         ["pk", "note: 'a, b'", 'default: "x,y"'])


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.diff = dbml.diff(dbml.parse(CURRENT), dbml.parse(NEW))
        self.tables = {t["name"]: t for t in self.diff["tables"]}

    def test_table_status(self):
        # orders: the inline ref became a separate Ref, the same relation: unchanged
        status = {n: t["status"] for n, t in self.tables.items()}
        self.assertEqual(status, {"users": "changed", "orders": "same", "sessions": "added", "legacy": "removed"})
        self.assertEqual([t["name"] for t in self.diff["tables"]][-1], "legacy")

    def test_column_status(self):
        users = {c["name"]: c for c in self.tables["users"]["columns"]}
        self.assertEqual(users["id"]["status"], "same")
        self.assertEqual(users["email"]["status"], "changed")
        self.assertEqual(users["email"]["old_type"], "varchar(255)")
        self.assertEqual(users["display_name"]["status"], "added")
        self.assertEqual(users["name"]["status"], "removed")

    def test_ref_status(self):
        status = {(r["from"], r["status"]) for r in self.diff["refs"]}
        self.assertIn(("sessions.user_id", "added"), status)
        self.assertIn(("orders.user_id", "same"), status)

    def test_same_schema_is_all_same(self):
        same = dbml.plain(dbml.parse(NEW))
        self.assertTrue(all(t["status"] == "same" for t in same["tables"]))
        self.assertTrue(all(c["status"] == "same" for t in same["tables"] for c in t["columns"]))

    def test_a_ref_change_alone_changes_its_table(self):
        old = dbml.parse("Table a { id int }\nTable b { a_id int }\n")
        new = dbml.parse("Table a { id int }\nTable b { a_id int }\nRef: b.a_id > a.id\n")
        status = {t["name"]: t["status"] for t in dbml.diff(old, new)["tables"]}
        self.assertEqual(status, {"a": "same", "b": "changed"})


class CardsTest(unittest.TestCase):
    def test_diff_cards_carry_the_colour_classes_and_legend(self):
        html = erd.diff_html(CURRENT, NEW)
        self.assertIn('class="erd-legend"', html)
        self.assertIn('<div class="erd-card st-added" data-table="sessions">', html)
        self.assertIn('<div class="erd-card st-removed" data-table="legacy">', html)
        self.assertIn('<div class="erd-card st-changed" data-table="users">', html)
        self.assertIn('<tr class="st-removed"><td class="erd-col">name</td>', html)
        self.assertIn("<s>varchar(255)</s> &rarr; varchar(320)", html)

    def test_plain_cards_have_no_legend_and_escape(self):
        html = erd.plain_html('Table "a<b" { id int [note: \'<x>\'] }')
        self.assertNotIn("erd-legend", html)
        self.assertIn("a&lt;b", html)
        self.assertNotIn("<x>", html)


if __name__ == "__main__":
    unittest.main()
