import importlib.util
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "update_images", Path(__file__).parent / "update-images.py"
)
update_images = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_images)


def parse(*argv):
    return update_images.parse_args(["folder", *argv])


def parse_error(*argv):
    with redirect_stderr(StringIO()) as err, unittest.TestCase().assertRaises(SystemExit):
        parse(*argv)
    return err.getvalue()


class TestParseArgs(unittest.TestCase):
    def test_fields_are_independent(self):
        self.assertEqual(parse("--alt").fields, ("alt",))
        self.assertEqual(parse("--keywords", "--title").fields, ("title", "keywords"))
        self.assertEqual(
            parse("--alt", "--title", "--description", "--keywords").fields,
            ("alt", "title", "description", "keywords"),
        )

    def test_no_field_selected_is_an_error(self):
        self.assertIn("select at least one field", parse_error())

    def test_overwrite_flags_are_per_field(self):
        args = parse("--alt", "--title", "--overwrite-title")
        self.assertEqual(args.overwrite, ("title",))

    def test_overwrite_requires_its_field(self):
        self.assertIn("--overwrite-keywords requires --keywords", parse_error("--alt", "--overwrite-keywords"))

    def test_creative_flags_require_their_field(self):
        self.assertIn("--creative-title requires --title", parse_error("--alt", "--creative-title"))
        self.assertIn(
            "--creative-description requires --description",
            parse_error("--title", "--creative-description"),
        )

    def test_context_option_is_not_discarded(self):
        self.assertEqual(parse("--alt", "--context", "Koi pond").context, "Koi pond")
        self.assertEqual(parse("--alt", "-c", "Koi pond").context, "Koi pond")

    def test_context_positional_still_works(self):
        self.assertEqual(parse("--alt", "Koi pond").context, "Koi pond")

    def test_context_is_none_when_not_given(self):
        self.assertIsNone(parse("--alt").context)

    def test_removed_flags_are_rejected(self):
        for flag in ("--iptc", "--title-only", "--force"):
            parse_error("--alt", flag)


if __name__ == "__main__":
    unittest.main()
