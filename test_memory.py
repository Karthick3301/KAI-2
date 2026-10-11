"""Memory should not collect near-identical copies of the same fact."""
import tempfile, unittest
from pathlib import Path
from memory import LongTermMemory


class DuplicateTests(unittest.TestCase):
    def make(self):
        return LongTermMemory(str(Path(tempfile.mkdtemp()) / "m.json"))

    def test_same_fact_different_capitals_is_not_added_twice(self):
        mem = self.make()
        mem.add("Loves a girl named Vino")
        self.assertTrue(mem.add("loves a girl named vino").startswith("Already"))
        self.assertEqual(len(mem.facts), 1)

    def test_extra_spaces_and_trailing_punctuation_ignored(self):
        mem = self.make()
        mem.add("Name is Karthick")
        mem.add("  name   is karthick. ")
        self.assertEqual(len(mem.facts), 1)

    def test_different_facts_are_both_kept(self):
        mem = self.make()
        mem.add("Name is Karthick")
        mem.add("Lives in Tamil Nadu")
        self.assertEqual(len(mem.facts), 2)

    def test_original_wording_is_kept(self):
        mem = self.make()
        mem.add("Name is Karthick")
        mem.add("NAME IS KARTHICK")
        self.assertEqual(mem.facts, ["Name is Karthick"])


if __name__ == "__main__":
    unittest.main()
