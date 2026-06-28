import unittest

from onepiece_card_scraper.search_tokens import search_tokens_for_fields, search_tokens_for_text


class SearchTokenTests(unittest.TestCase):
    def test_english_name_generates_normalized_word_prefix_and_ngram_tokens(self):
        tokens = search_tokens_for_text("Monkey.D.Luffy", source_field="name")
        token_pairs = {(token.token, token.token_type) for token in tokens}

        self.assertIn(("monkeydluffy", "normalized"), token_pairs)
        self.assertIn(("monkey", "word"), token_pairs)
        self.assertIn(("luffy", "word"), token_pairs)
        self.assertIn(("luf", "prefix"), token_pairs)
        self.assertIn(("lu", "ngram"), token_pairs)

    def test_japanese_name_generates_prefix_and_ngram_tokens(self):
        tokens = search_tokens_for_text("モンキー・D・ルフィ", source_field="name")
        token_pairs = {(token.token, token.token_type) for token in tokens}

        self.assertIn(("モンキーdルフィ".lower(), "normalized"), token_pairs)
        self.assertIn(("ルフィ", "word"), token_pairs)
        self.assertIn(("ル", "prefix"), token_pairs)
        self.assertIn(("ルフ", "ngram"), token_pairs)

    def test_korean_name_generates_choseong_prefix_tokens(self):
        tokens = search_tokens_for_text("몽키 D. 루피", source_field="name")
        token_pairs = {(token.token, token.token_type) for token in tokens}

        self.assertIn(("몽키d루피", "normalized"), token_pairs)
        self.assertIn(("루피", "word"), token_pairs)
        self.assertIn(("루", "prefix"), token_pairs)
        self.assertIn(("ㄹㅍ", "choseong"), token_pairs)
        self.assertIn(("ㄹ", "choseong_prefix"), token_pairs)

    def test_search_tokens_for_fields_keeps_source_field(self):
        tokens = search_tokens_for_fields(
            name="몽키 D. 루피",
            effect_text="한국어 효과",
            trigger_text=None,
        )

        self.assertTrue(any(token.source_field == "name" and token.token == "ㄹ" for token in tokens))
        self.assertTrue(any(token.source_field == "effect_text" and token.token == "효과" for token in tokens))
        self.assertFalse(any(token.source_field == "trigger_text" for token in tokens))


if __name__ == "__main__":
    unittest.main()
