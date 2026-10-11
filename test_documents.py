import base64
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import documents as D


def make_docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


class ExtractTests(unittest.TestCase):
    def test_text_and_encodings(self):
        self.assertEqual(D.extract_text("a.txt", "héllo".encode("utf-8")), "héllo")
        self.assertEqual(D.extract_text("a.md", "caf\xe9".encode("cp1252")), "caf\xe9")

    def test_docx(self):
        text = D.extract_text("x.docx", make_docx(["First line", "Second line"]))
        self.assertEqual(text, "First line\nSecond line")

    def test_bad_docx_and_empty_and_unsupported_and_big(self):
        for name, raw in (("x.docx", b"not a zip"), ("e.txt", b"   "), ("x.exe", b"MZ"), ("x.pdf", b"nope")):
            with self.assertRaises(D.DocumentError):
                D.extract_text(name, raw)
        with self.assertRaises(D.DocumentError):
            D.extract_text("big.txt", b"a" * (D.MAX_UPLOAD_BYTES + 1))

    def test_pdf(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        self.assertIn("Hello PDF", D.extract_text("x.pdf", make_pdf("Hello PDF")))

    def test_missing_pypdf_message(self):
        with mock.patch.dict("sys.modules", {"pypdf": None}):
            with self.assertRaises(D.DocumentError) as cm:
                D.extract_text("x.pdf", b"%PDF")
        self.assertIn("pip install pypdf", str(cm.exception))

    def test_safe_name_and_bad_base64(self):
        self.assertEqual(D.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(D.safe_name(""), "document")
        with self.assertRaises(D.DocumentError):
            D.decode_upload("!!!not base64!!!")


class RetrievalTests(unittest.TestCase):
    def doc(self):
        parts = [f"Section {i}. " + ("filler words about nothing " * 40) for i in range(30)]
        parts[17] = "The warranty period is 24 months and covers battery defects. " * 5
        return "\n".join(parts)

    def test_finds_relevant_passage(self):
        picked = D.pick_chunks(self.doc(), "How long is the warranty on the battery?")
        self.assertTrue(any("warranty period is 24 months" in c for c in picked))
        self.assertLessEqual(len(picked), D.TOP_CHUNKS)

    def test_vague_question_samples_whole_document(self):
        text = self.doc()
        picked = D.pick_chunks(text, "summarise this")
        self.assertEqual(len(picked), D.TOP_CHUNKS)
        self.assertIn("Section 0.", picked[0])

    def test_short_document_is_returned_whole(self):
        self.assertEqual(len(D.pick_chunks("small text", "anything")), 1)

    def test_context_labels_untrusted_and_limits_size(self):
        ctx = D.build_context([{"name": "a.txt", "text": self.doc()}], "warranty")
        self.assertIn("untrusted", ctx)
        self.assertIn('Document "a.txt"', ctx)
        self.assertLess(len(ctx), D.TOP_CHUNKS * (D.CHUNK_CHARS + 50) + 800)
        self.assertEqual(D.build_context([], "x"), "")

    def test_chunking_terminates_on_no_breaks(self):
        self.assertGreater(len(D.split_chunks("x" * 10000)), 5)


class StorageTests(unittest.TestCase):
    def test_add_remove_limit_and_persistence(self):
        path = Path(tempfile.mkdtemp()) / "c.docs.json"
        store = D.ChatDocuments(path)
        store.add("a.txt", "hello")
        self.assertEqual(D.ChatDocuments(path).load()[0]["text"], "hello")  # saved to disk
        store.add("a.txt", "newer")  # same name replaces
        self.assertEqual(len(store.load()), 1)
        for i in range(D.MAX_DOCS_PER_CHAT - 1):
            store.add(f"f{i}.txt", "x")
        with self.assertRaises(D.DocumentError):
            store.add("one-too-many.txt", "x")
        for d in list(store.load()):
            store.remove(d["name"])
        self.assertFalse(path.exists())


class AssistantContextTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        os.environ.update(MODEL_PROVIDER="gemini", GEMINI_API_KEY="fake", AUTO_SAVE="false",
                          WORKSPACE_DIR=f"{tmp}/ws", CHAT_HISTORY_FILE=f"{tmp}/h.jsonl",
                          MEMORY_FILE=f"{tmp}/m.json", PERSONA_FILE=f"{tmp}/p.json")
        import assistant as A
        from config import Config
        self.A = A
        self.assistant = A.Assistant(Config())

    def test_context_reaches_model_but_not_history(self):
        seen = []

        def fake_complete(messages, **kw):
            seen.append(messages)
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(self.assistant, "_complete", side_effect=fake_complete):
            self.assistant.chat("what is the warranty?", context="EXCERPT: 24 months")
        last_user = [m for m in seen[0] if m["role"] == "user"][-1]["content"]
        self.assertIn("EXCERPT: 24 months", last_user)
        self.assertIn("what is the warranty?", last_user)
        saved = [m.content for m in self.assistant.chat_history.messages if m.role == "user"]
        self.assertEqual(saved, ["what is the warranty?"])  # the excerpt is not stored

    def test_documents_count_as_untrusted_for_sensitive_tools(self):
        self.assistant._transient_context = "excerpt"
        self.assertTrue(self.assistant._web_content_in_context())
        self.assistant._transient_context = None
        self.assertFalse(self.assistant._web_content_in_context())


if __name__ == "__main__":
    unittest.main()
