import unittest

from assistant import LinkFlattener, PlainTextFilter, flatten_markdown_links


def run(pieces):
    out = []
    f = LinkFlattener(out.append)
    for p in pieces:
        f.feed(p)
    f.flush()
    return "".join(out)


class LinkTests(unittest.TestCase):
    def test_flatten(self):
        self.assertEqual(flatten_markdown_links("see [JK](https://a.com/x) now"), "see JK: https://a.com/x now")
        self.assertEqual(flatten_markdown_links("[https://a.com](https://a.com)"), "https://a.com")
        self.assertEqual(flatten_markdown_links("no links [here]"), "no links [here]")

    def test_stream_matches_flatten_for_any_split(self):
        text = "Hi [JK Tamil](https://www.youtube.com/channel/UC_x-1) and [a] b [c](not a url) [d](https://d.io)!\nend [open"
        expected = flatten_markdown_links(text)
        for size in (1, 2, 3, 5, 7, 1000):
            pieces = [text[i:i + size] for i in range(0, len(text), size)]
            self.assertEqual(run(pieces), expected, size)

    def test_plain_text_untouched(self):
        t = "Just a normal answer (with brackets) and a list [1, 2, 3]."
        self.assertEqual(run([t[:10], t[10:]]), t)

    def test_unfinished_bracket_is_flushed(self):
        self.assertEqual(run(["wait [what"]), "wait [what")

    def test_long_bracket_does_not_hang(self):
        t = "[" + "a" * 1000
        self.assertEqual(run([t]), t)


def run_plain(pieces):
    out = []
    f = PlainTextFilter(out.append)
    for p in pieces:
        f.feed(p)
    f.flush()
    return "".join(out)


class PlainTextTests(unittest.TestCase):
    def test_bold_markers_are_removed(self):
        self.assertEqual(run_plain(["**Main Method** sorts it"]), "Main Method sorts it")
        self.assertEqual(run_plain(["__also bold__ here"]), "also bold here")

    def test_headings_lose_their_marks(self):
        self.assertEqual(run_plain(["### Program Overview\nBody"]), "Program Overview\nBody")

    def test_backticks_are_removed(self):
        self.assertEqual(run_plain(["call `bubbleSort(a)` now"]), "call bubbleSort(a) now")
        self.assertEqual(run_plain(["```java\nint x = 1;\n```\n"]), "java\nint x = 1;\n\n")

    def test_maths_and_names_keep_single_marks(self):
        self.assertEqual(run_plain(["2 * 3 = 6 and snake_case_name"]), "2 * 3 = 6 and snake_case_name")
        self.assertEqual(run_plain(["2 ** 10 = 1024"]), "2 ** 10 = 1024")
        self.assertEqual(run_plain(["C# and #1 pick"]), "C# and #1 pick")

    def test_any_stream_split_gives_the_same_text(self):
        text = "## Steps\n1. **Read** the `array`\n2. **Swap** 2 * 3 times\n"
        expected = "Steps\n1. Read the array\n2. Swap 2 * 3 times\n"
        for size in (1, 2, 3, 4, 7, 1000):
            pieces = [text[i:i + size] for i in range(0, len(text), size)]
            self.assertEqual(run_plain(pieces), expected, size)

    def test_link_flattening_still_works_through_both_filters(self):
        out = []
        plain = PlainTextFilter(out.append)
        flattener = LinkFlattener(plain.feed)
        for piece in ["**See** [JK](https://a.com/x) for `more`"]:
            flattener.feed(piece)
        flattener.flush()
        plain.flush()
        self.assertEqual("".join(out), "See JK: https://a.com/x for more")


if __name__ == "__main__":
    unittest.main()
