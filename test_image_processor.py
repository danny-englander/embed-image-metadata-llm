import unittest
from pathlib import Path
from unittest.mock import patch

from image_processor import (
    llm_option_args,
    DESCRIPTION_STORY_MAX_LEN,
    TITLE_MAX_LEN,
    build_metadata_prompt,
    description_instruction,
    process_single_image,
    title_instruction,
    truncate_description,
)


class TestTitleInstruction(unittest.TestCase):
    def test_default_is_marketplace_style(self):
        text = title_instruction()
        self.assertIn("marketplace-style", text)
        self.assertIn(str(TITLE_MAX_LEN), text)
        self.assertNotIn("{title_len}", text)

    def test_creative_asks_for_mood_not_catalog(self):
        text = title_instruction(creative=True)
        self.assertIn("evocative", text)
        self.assertIn("Astronaut in Red Spacesuit Under Radiant Desert Sky", text)
        self.assertIn("Wanderer Beneath a Burning Sky", text)
        self.assertIn(str(TITLE_MAX_LEN), text)
        self.assertNotIn("{title_len}", text)

    def test_prompt_embeds_creative_title_instruction(self):
        prompt = build_metadata_prompt(["title"], creative_title=True)
        self.assertIn("Wanderer Beneath a Burning Sky", prompt)
        self.assertNotIn("{title_instruction}", prompt)

    def test_prompt_embeds_default_title_instruction(self):
        prompt = build_metadata_prompt(["title"])
        self.assertIn("marketplace-style", prompt)


class TestDescriptionInstruction(unittest.TestCase):
    def test_default_is_literal_prose(self):
        text = description_instruction()
        self.assertIn("3-4 complete sentences", text)
        self.assertNotIn("{desc_len}", text)

    def test_creative_is_short_story_with_limit(self):
        text = description_instruction(creative=True)
        self.assertIn("short-story", text)
        self.assertIn(str(DESCRIPTION_STORY_MAX_LEN), text)
        self.assertNotIn("{desc_len}", text)
        self.assertIn("do not default to them", text)
        self.assertIn("do not open every story", text)
        self.assertIn("If gender is unclear", text)

    def test_prompt_embeds_creative_description(self):
        prompt = build_metadata_prompt(["description"], creative_description=True)
        self.assertIn("short-story", prompt)
        self.assertIn(str(DESCRIPTION_STORY_MAX_LEN), prompt)
        self.assertNotIn("{description_instruction}", prompt)

    def test_truncate_description_prefers_sentence_boundary(self):
        first = "The red figure paused on the dune and listened to the wind."
        extra = " Then the sun went out behind a wall of glass." * 12
        text = first + extra
        self.assertGreater(len(text), DESCRIPTION_STORY_MAX_LEN)
        truncated = truncate_description(text, DESCRIPTION_STORY_MAX_LEN)
        self.assertLessEqual(len(truncated), DESCRIPTION_STORY_MAX_LEN)
        self.assertTrue(truncated.endswith("."))
        self.assertIn("listened to the wind.", truncated)

    def test_truncate_description_without_max_len_is_unchanged_aside_from_whitespace(self):
        text = "A long default description can exceed three hundred seventy five characters easily when it is several sentences."
        self.assertEqual(truncate_description(text), text)


class TestBuildMetadataPrompt(unittest.TestCase):
    def test_only_requested_keys_are_asked_for(self):
        prompt = build_metadata_prompt(["keywords"])
        self.assertIn('"keywords"', prompt)
        self.assertNotIn('"title"', prompt)
        self.assertNotIn('"description"', prompt)
        self.assertIn("exactly this key", prompt)

    def test_multiple_keys_in_canonical_order(self):
        prompt = build_metadata_prompt(["keywords", "title"])
        self.assertLess(prompt.index('"title"'), prompt.index('"keywords"'))
        self.assertIn("exactly these keys", prompt)

    def test_hints_and_context_are_included(self):
        prompt = build_metadata_prompt(
            ["title"], hints=["alt text: A red door."], context="Trip to Japan"
        )
        self.assertIn("(alt text: A red door.)", prompt)
        self.assertIn("Additional context: Trip to Japan", prompt)


class FakeImage:
    """Stand-in for exiftool state: maps exif tag -> existing value."""

    def __init__(self, **existing):
        self.existing = existing

    def read(self, _path, tag):
        return self.existing.get(tag)


class TestProcessSingleImage(unittest.TestCase):
    path = Path("photo.jpg")

    def run_fields(self, fields, overwrite=(), existing=None, iptc_values=None, alt="A red door."):
        image = FakeImage(**(existing or {}))
        with patch("image_processor.read_exif_field", side_effect=image.read), \
             patch("image_processor.get_existing_alt_text",
                   side_effect=lambda p: image.existing.get("AltTextAccessibility")), \
             patch("image_processor.generate_alt_text", return_value=alt) as gen_alt, \
             patch("image_processor.write_alt_text", return_value=True) as write_alt, \
             patch("image_processor.generate_iptc_fields", return_value=iptc_values) as gen_iptc, \
             patch("image_processor.write_iptc_fields", return_value=True) as write_iptc:
            result = process_single_image(self.path, "m", None, fields, overwrite)
        return result, gen_alt, write_alt, gen_iptc, write_iptc

    def test_requires_at_least_one_field(self):
        with self.assertRaises(ValueError):
            process_single_image(self.path, "m", None, (), ())

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(ValueError):
            process_single_image(self.path, "m", None, ("alt", "nope"), ())

    def test_alt_only_makes_no_iptc_call(self):
        result, gen_alt, write_alt, gen_iptc, write_iptc = self.run_fields(["alt"])
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["written"], ["alt"])
        gen_alt.assert_called_once()
        gen_iptc.assert_not_called()
        write_iptc.assert_not_called()

    def test_title_only_makes_no_alt_call_and_one_llm_call(self):
        result, gen_alt, write_alt, gen_iptc, write_iptc = self.run_fields(
            ["title"], iptc_values={"title": "Red Door"}
        )
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["title"], "Red Door")
        gen_alt.assert_not_called()
        write_alt.assert_not_called()
        self.assertEqual(gen_iptc.call_args.args[2], ["title"])
        self.assertEqual(write_iptc.call_args.kwargs["title"], "Red Door")
        self.assertNotIn("description", write_iptc.call_args.kwargs)

    def test_title_description_keywords_share_one_call(self):
        values = {"title": "T", "description": "D", "keywords": "k1, k2"}
        result, _, _, gen_iptc, _ = self.run_fields(
            ["title", "description", "keywords"], iptc_values=values
        )
        gen_iptc.assert_called_once()
        self.assertEqual(result["written"], ["title", "description", "keywords"])

    def test_filled_field_without_overwrite_is_skipped(self):
        result, gen_alt, *_ = self.run_fields(
            ["alt"], existing={"AltTextAccessibility": "Existing alt"}
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["skipped"], ["alt"])
        gen_alt.assert_not_called()

    def test_overwrite_replaces_filled_field(self):
        result, gen_alt, *_ = self.run_fields(
            ["alt"], overwrite=["alt"], existing={"AltTextAccessibility": "Existing alt"}
        )
        self.assertEqual(result["status"], "written")
        gen_alt.assert_called_once()

    def test_skipped_field_does_not_block_others(self):
        result, _, _, gen_iptc, write_iptc = self.run_fields(
            ["title", "keywords"],
            existing={"Title": "Existing title"},
            iptc_values={"keywords": "a, b"},
        )
        self.assertEqual(result["status"], "written")
        self.assertEqual(result["skipped"], ["title"])
        self.assertEqual(result["written"], ["keywords"])
        self.assertEqual(gen_iptc.call_args.args[2], ["keywords"])
        self.assertEqual(write_iptc.call_args.kwargs, {"keywords": "a, b", "description_max_len": None})

    def test_overwrite_only_applies_to_the_named_field(self):
        result, *_ = self.run_fields(
            ["title", "keywords"],
            overwrite=["title"],
            existing={"Title": "Old", "Keywords": "old"},
            iptc_values={"title": "New"},
        )
        self.assertEqual(result["written"], ["title"])
        self.assertEqual(result["skipped"], ["keywords"])

    def test_generated_alt_is_used_as_hint_for_iptc(self):
        _, _, _, gen_iptc, _ = self.run_fields(
            ["alt", "title"], iptc_values={"title": "T"}, alt="A red door."
        )
        self.assertEqual(gen_iptc.call_args.args[3], "A red door.")

    def test_existing_alt_is_used_as_hint_when_alt_not_selected(self):
        _, _, _, gen_iptc, _ = self.run_fields(
            ["title"], existing={"AltTextAccessibility": "Existing alt"}, iptc_values={"title": "T"}
        )
        self.assertEqual(gen_iptc.call_args.args[3], "Existing alt")

    def test_iptc_failure_reports_error_but_keeps_written_alt(self):
        result, *_ = self.run_fields(["alt", "title"], iptc_values=None)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["written"], ["alt"])
        self.assertIn("title", result["message"])
        self.assertIn("Written: alt text", result["message"])
        self.assertEqual(result["failed"], {"title": "none generated"})

    def test_skipped_field_records_its_existing_value(self):
        result, *_ = self.run_fields(["title"], existing={"Title": "Existing title"})
        self.assertEqual(result["existing"], {"title": "Existing title"})


class TestLlmOptionArgs(unittest.TestCase):
    def test_sonnet_5_5_uses_medium_thinking_effort(self):
        self.assertEqual(
            llm_option_args("claude-sonnet-5-5"), ["-o", "thinking_effort", "medium"]
        )

    def test_model_without_settings_has_no_options(self):
        self.assertEqual(llm_option_args("claude-sonnet-4-6"), [])

    def test_unknown_model_has_no_options(self):
        self.assertEqual(llm_option_args("no-such-model"), [])


if __name__ == "__main__":
    unittest.main()
