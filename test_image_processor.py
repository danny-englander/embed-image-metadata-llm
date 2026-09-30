import unittest
from pathlib import Path
from unittest.mock import patch

from image_processor import (
    llm_option_args,
    parse_iptc_json,
    DESCRIPTION_CAPTION_MAX_LEN,
    DESCRIPTION_STORY_MAX_LEN,
    DESCRIPTION_STYLES,
    TITLE_MAX_LEN,
    TITLE_STYLES,
    build_metadata_prompt,
    description_instruction,
    description_max_len,
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
        text = title_instruction("creative")
        self.assertIn("evocative", text)
        self.assertIn("Astronaut in Red Spacesuit Under Radiant Desert Sky", text)
        self.assertIn("Wanderer Beneath a Burning Sky", text)
        self.assertIn(str(TITLE_MAX_LEN), text)
        self.assertNotIn("{title_len}", text)

    def test_prompt_embeds_creative_title_instruction(self):
        prompt = build_metadata_prompt(["title"], title_style="creative")
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
        text = description_instruction("creative")
        self.assertIn("short-story", text)
        self.assertIn(str(DESCRIPTION_STORY_MAX_LEN), text)
        self.assertNotIn("{desc_len}", text)
        self.assertIn("do not default to them", text)
        self.assertIn("do not open every story", text)
        self.assertIn("If gender is unclear", text)

    def test_prompt_embeds_creative_description(self):
        prompt = build_metadata_prompt(["description"], description_style="creative")
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


class TestStyles(unittest.TestCase):
    def test_every_style_has_a_formatted_instruction(self):
        for style in TITLE_STYLES:
            text = title_instruction(style)
            self.assertTrue(text)
            self.assertNotIn("{", text)
        for style in DESCRIPTION_STYLES:
            text = description_instruction(style)
            self.assertTrue(text)
            self.assertNotIn("{", text)

    def test_title_styles_are_distinct(self):
        self.assertEqual(len({title_instruction(s) for s in TITLE_STYLES}), len(TITLE_STYLES))

    def test_editorial_title_is_subject_place_and_never_guesses(self):
        text = title_instruction("editorial")
        self.assertIn("Subject, Place", text)
        self.assertIn("never guess a place", text)

    def test_poetic_title_asks_for_verse_like_imagery(self):
        self.assertIn("Amber Light Folding into Still Water", title_instruction("poetic"))

    def test_literal_title_is_short_and_plain(self):
        text = title_instruction("literal")
        self.assertIn("2-5", text)
        self.assertIn("no mood, metaphor, or decoration", text)

    def test_caption_description_is_one_capped_sentence(self):
        text = description_instruction("caption")
        self.assertIn("single factual", text)
        self.assertIn(str(DESCRIPTION_CAPTION_MAX_LEN), text)

    def test_photographic_description_does_not_invent_camera_data(self):
        text = description_instruction("photographic")
        self.assertIn("light", text)
        self.assertIn("do not invent camera", text)

    def test_description_caps_depend_on_style(self):
        self.assertEqual(description_max_len("creative"), DESCRIPTION_STORY_MAX_LEN)
        self.assertEqual(description_max_len("caption"), DESCRIPTION_CAPTION_MAX_LEN)
        self.assertIsNone(description_max_len("standard"))
        self.assertIsNone(description_max_len("photographic"))

    def test_unknown_styles_are_rejected(self):
        with self.assertRaises(ValueError):
            title_instruction("shouty")
        with self.assertRaises(ValueError):
            description_instruction("shouty")
        with self.assertRaises(ValueError):
            description_max_len("shouty")

    def test_prompt_uses_each_fields_own_style(self):
        prompt = build_metadata_prompt(
            ["title", "description"], title_style="poetic", description_style="caption"
        )
        self.assertIn("lyrical, poetic title", prompt)
        self.assertIn("photo-caption sentence", prompt)
        self.assertNotIn("marketplace-style", prompt)


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

    def test_styles_reach_generation_and_the_description_cap(self):
        image = FakeImage()
        with patch("image_processor.read_exif_field", side_effect=image.read), \
             patch("image_processor.generate_iptc_fields",
                   return_value={"title": "T", "description": "D"}) as gen_iptc, \
             patch("image_processor.write_iptc_fields", return_value=True) as write_iptc:
            process_single_image(
                self.path, "m", None, ["title", "description"], (),
                title_style="editorial", description_style="caption",
            )
        self.assertEqual(gen_iptc.call_args.args[5:7], ("editorial", "caption"))
        self.assertEqual(write_iptc.call_args.kwargs["description_max_len"], DESCRIPTION_CAPTION_MAX_LEN)

    def test_unknown_style_is_rejected_before_any_work(self):
        with self.assertRaises(ValueError):
            process_single_image(self.path, "m", None, ["title"], (), title_style="shouty")
        with self.assertRaises(ValueError):
            process_single_image(self.path, "m", None, ["description"], (), description_style="shouty")

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


class TestParseIptcJson(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_iptc_json('{"title": "A"}'), {"title": "A"})

    def test_markdown_fenced_object(self):
        self.assertEqual(parse_iptc_json('```json\n{"title": "A"}\n```'), {"title": "A"})

    def test_prose_around_the_object_is_ignored(self):
        self.assertEqual(parse_iptc_json('Here you go: {"title": "A"} Hope that helps!'), {"title": "A"})

    def test_last_object_wins_when_the_model_corrects_itself(self):
        raw = (
            '{"title": "A", "description": "D", "keywords": null}\n\n'
            'Correction: the response must contain only the two requested keys. Final JSON:\n\n'
            '{"title": "A", "description": "D"}'
        )
        self.assertEqual(parse_iptc_json(raw), {"title": "A", "description": "D"})

    def test_nested_objects_are_kept_whole(self):
        self.assertEqual(parse_iptc_json('{"a": {"b": 1}}'), {"a": {"b": 1}})

    def test_braces_inside_strings_do_not_confuse_it(self):
        self.assertEqual(parse_iptc_json('{"title": "Curly {braces} here"}'), {"title": "Curly {braces} here"})

    def test_invalid_or_missing_json_returns_none(self):
        self.assertIsNone(parse_iptc_json("no json here"))
        self.assertIsNone(parse_iptc_json('{"title": '))
        self.assertIsNone(parse_iptc_json("[1, 2, 3]"))


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
