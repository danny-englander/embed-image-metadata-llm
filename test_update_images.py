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

    def test_overwrite_all_covers_every_selected_field_only(self):
        args = parse("--alt", "--keywords", "--overwrite-all")
        self.assertEqual(args.overwrite, ("alt", "keywords"))

    def test_overwrite_all_still_requires_a_field(self):
        self.assertIn("select at least one field", parse_error("--overwrite-all"))

    def test_overwrite_all_combines_with_per_field_flags(self):
        args = parse("--alt", "--title", "--overwrite-title", "--overwrite-all")
        self.assertEqual(args.overwrite, ("alt", "title"))

    def test_overwrite_requires_its_field(self):
        self.assertIn("--overwrite-keywords requires --keywords", parse_error("--alt", "--overwrite-keywords"))

    def test_creative_flags_require_their_field(self):
        self.assertIn("--creative-title requires --title", parse_error("--alt", "--creative-title"))
        self.assertIn(
            "--creative-description requires --description",
            parse_error("--title", "--creative-description"),
        )

    def test_styles_default_to_standard(self):
        args = parse("--title", "--description")
        self.assertEqual((args.title_style, args.description_style), ("standard", "standard"))

    def test_style_flags_select_each_fields_style(self):
        args = parse(
            "--title", "--description",
            "--title-style", "editorial", "--description-style", "photographic",
        )
        self.assertEqual((args.title_style, args.description_style), ("editorial", "photographic"))

    def test_creative_flags_are_shortcuts_for_the_creative_style(self):
        args = parse("--title", "--description", "--creative-title", "--creative-description")
        self.assertEqual((args.title_style, args.description_style), ("creative", "creative"))

    def test_creative_shortcut_may_repeat_the_same_style(self):
        self.assertEqual(parse("--title", "--creative-title", "--title-style", "creative").title_style, "creative")

    def test_creative_shortcut_conflicts_with_a_different_style(self):
        self.assertIn(
            "--creative-title conflicts with --title-style literal",
            parse_error("--title", "--creative-title", "--title-style", "literal"),
        )

    def test_style_requires_its_field(self):
        self.assertIn("--title-style requires --title", parse_error("--alt", "--title-style", "poetic"))
        self.assertIn(
            "--description-style requires --description",
            parse_error("--title", "--description-style", "caption"),
        )

    def test_styles_only_accept_their_own_choices(self):
        parse_error("--title", "--title-style", "caption")
        parse_error("--description", "--description-style", "poetic")

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
