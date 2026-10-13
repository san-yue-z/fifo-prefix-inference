"""Check the documented recorder hash convention without changing a transcript."""

import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_fifo_complete_clean_archive_v3_1 import canonical_record_line


class RecordEncodingControls(unittest.TestCase):
    def test_lf_is_unchanged(self):
        self.assertEqual(canonical_record_line(b'{"theta":"1/2"}\n'), b'{"theta":"1/2"}\n')

    def test_windows_translation_matches_generated_line(self):
        logical = b'{"theta":"1/2"}\n'
        physical = b'{"theta":"1/2"}\r\n'
        self.assertEqual(hashlib.sha256(canonical_record_line(physical)).digest(), hashlib.sha256(logical).digest())
        self.assertNotEqual(hashlib.sha256(physical).digest(), hashlib.sha256(logical).digest())

    def test_content_is_not_reserialized(self):
        original = b'{"theta": "1/2"}\r\n'
        self.assertEqual(canonical_record_line(original), b'{"theta": "1/2"}\n')
        self.assertNotEqual(canonical_record_line(original), b'{"theta":"1/2"}\n')

    def test_unterminated_record_rejected(self):
        with self.assertRaises(ValueError):
            canonical_record_line(b'{"theta":"1/2"}')


if __name__ == "__main__":
    unittest.main()
