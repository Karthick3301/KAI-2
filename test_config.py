"""Settings: friendly errors for bad numbers, sensible defaults, old persona files upgraded."""
import os, unittest
from unittest import mock

import config as C


def make(**env):
    base = {"MODEL_PROVIDER": "ollama", "WORKSPACE_DIR": os.path.join(os.environ.get("TMPDIR", "/tmp"), "kai_cfg_ws"),
            "PERSONA_FILE": os.path.join(os.environ.get("TMPDIR", "/tmp"), "kai_cfg_none.json")}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=False):
        return C.Config()


class ConfigTests(unittest.TestCase):
    def test_bad_number_gives_friendly_message(self):
        with self.assertRaises(ValueError) as cm:
            make(MAX_TOKENS="abc")
        self.assertIn("MAX_TOKENS", str(cm.exception))
        self.assertIn("whole number", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            make(TEMPERATURE="hot")
        self.assertIn("TEMPERATURE", str(cm.exception))

    def test_ollama_default_model_matches_readme(self):
        self.assertEqual(make(MODEL_NAME="").model_config.name, "qwen2.5:7b")
        self.assertEqual(make(MODEL_NAME="llama3.2").model_config.name, "llama3.2")

    def test_default_persona_mentions_web_search(self):
        self.assertIn("web search", C.Persona().build_system_prompt())

    def test_old_saved_capabilities_are_upgraded(self):
        old = {"name": "KAI", "capabilities": C.OLD_DEFAULT_CAPABILITIES}
        self.assertEqual(C.Persona.from_dict(old).capabilities, C.Persona().capabilities)
        custom = {"capabilities": ["do my own thing"]}
        self.assertEqual(C.Persona.from_dict(custom).capabilities, ["do my own thing"])


if __name__ == "__main__":
    unittest.main()
