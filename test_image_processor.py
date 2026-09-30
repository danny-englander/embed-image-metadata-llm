import unittest

from image_processor import (
    llm_option_args,
    DESCRIPTION_STORY_MAX_LEN,
    IPTC_META_PROMPT,
    TITLE_MAX_LEN,
    TITLE_ONLY_PROMPT,
    description_instruction,
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

    def test_iptc_prompt_embeds_selected_instruction(self):
        prompt = IPTC_META_PROMPT.format(
            alt="An astronaut on a desert planet.",
            title_instruction=title_instruction(creative=True),
            description_instruction=description_instruction(),
            keywords_len=500,
            spelling_notes="",
            context_block="",
        )
        self.assertIn("Wanderer Beneath a Burning Sky", prompt)
        self.assertNotIn("{title_instruction}", prompt)
        self.assertNotIn("{description_instruction}", prompt)

    def test_title_only_prompt_embeds_default_instruction(self):
        prompt = TITLE_ONLY_PROMPT.format(
            hint_clause="",
            title_instruction=title_instruction(),
            spelling_notes="",
            context_block="",
        )
        self.assertIn("marketplace-style", prompt)
        self.assertNotIn("{title_instruction}", prompt)


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

    def test_iptc_prompt_embeds_creative_description(self):
        prompt = IPTC_META_PROMPT.format(
            alt="An astronaut on a desert planet.",
            title_instruction=title_instruction(),
            description_instruction=description_instruction(creative=True),
            keywords_len=500,
            spelling_notes="",
            context_block="",
        )
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


class TestLlmOptionArgs(unittest.TestCase):
    def test_model_without_settings_has_no_options(self):
        self.assertEqual(llm_option_args("claude-sonnet-4-6"), [])

    def test_unknown_model_has_no_options(self):
        self.assertEqual(llm_option_args("no-such-model"), [])


if __name__ == "__main__":
    unittest.main()
