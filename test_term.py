import os
import unittest
from unittest.mock import patch

from term import BOLD, RED, RESET, enabled, paint


class TestTerm(unittest.TestCase):
    def test_paint_wraps_when_force_color_is_set(self):
        env = {"FORCE_COLOR": "1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(enabled())
            self.assertEqual(paint("hi", RED), f"{RED}hi{RESET}")
            self.assertEqual(paint("hi", BOLD, RED), f"{BOLD}{RED}hi{RESET}")

    def test_paint_skips_codes_when_no_color_is_set(self):
        env = {"NO_COLOR": "1", "FORCE_COLOR": "1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(enabled())
            self.assertEqual(paint("hi", RED), "hi")

    def test_paint_skips_codes_when_force_color_is_zero(self):
        env = {"FORCE_COLOR": "0"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(enabled())
            self.assertEqual(paint("hi", RED), "hi")

    def test_paint_returns_text_when_empty_or_no_codes(self):
        env = {"FORCE_COLOR": "1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(paint("", RED), "")
            self.assertEqual(paint("hi"), "hi")


if __name__ == "__main__":
    unittest.main()
