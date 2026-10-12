import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "app" / "server.py"
SPEC = importlib.util.spec_from_file_location("image_web_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class HelperTests(unittest.TestCase):
    def test_safe_generation_size(self):
        self.assertEqual(SERVER.safe_generation_size("1920x1080"), (768, 432))
        self.assertEqual(SERVER.safe_generation_size("512x512"), (512, 512))

    def test_history_path_rejects_traversal(self):
        with self.assertRaises(ValueError):
            SERVER.valid_history_name("../model.png")

    def test_history_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image = root / "20261012_120000_abcd1234.png"
            image.write_bytes(b"png")
            image.with_suffix(".json").write_text(json.dumps({"prompt": "测试", "width": 512, "height": 512}), encoding="utf-8")
            items = SERVER.list_history(root)
            self.assertEqual(items[0]["name"], image.name)
            self.assertEqual(items[0]["prompt"], "测试")
            self.assertEqual(items[0]["width"], 512)


if __name__ == "__main__":
    unittest.main()
