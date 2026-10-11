import unittest

from assistant import LinkFlattener, flatten_markdown_links


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


if __name__ == "__main__":
    unittest.main()
