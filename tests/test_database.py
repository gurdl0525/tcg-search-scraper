import unittest

from onepiece_card_scraper.database import (
    _block_no,
    _card_sets_for,
    _product_type_for_set_code,
    _rarity_name,
    load_cards_to_database,
)
from onepiece_card_scraper.scraper import parse_card_list
from tests.test_scraper import SAMPLE_HTML, SOURCE_URL


class RecordingResult:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


class RecordingConnection:
    def __init__(self):
        self.statements = []
        self.next_id = 1

    def execute(self, sql, params=None):
        normalized_sql = " ".join(sql.split())
        self.statements.append((normalized_sql, params or ()))
        if "returning id" in normalized_sql.lower():
            value = f"id-{self.next_id}"
            self.next_id += 1
            return RecordingResult(value)
        return RecordingResult(None)


class DatabaseLoaderTests(unittest.TestCase):
    def test_reference_value_mappers_match_current_schema(self):
        self.assertEqual(_block_no("5"), 5)
        self.assertIsNone(_block_no("X"))
        self.assertEqual(_product_type_for_set_code("OP-16"), "BOOSTER")
        self.assertEqual(_product_type_for_set_code("ST-15"), "STARTER")
        self.assertEqual(_rarity_name("SP_CARD"), "Special Card")
        self.assertEqual(_rarity_name("TR"), "Treasure Rare")

    def test_load_cards_to_database_upserts_identity_printing_and_references(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)
        connection = RecordingConnection()

        stats = load_cards_to_database(connection, cards)

        self.assertEqual(stats.cards, 2)
        self.assertEqual(stats.printings, 3)
        self.assertTrue(any("insert into card_identities" in sql.lower() for sql, _ in connection.statements))
        self.assertTrue(any("insert into card_printings" in sql.lower() for sql, _ in connection.statements))
        self.assertTrue(any("insert into rarities" in sql.lower() and params[0] == "SP_CARD" for sql, params in connection.statements))
        self.assertTrue(any("insert into card_sets" in sql.lower() and params[0] == "OP-16" for sql, params in connection.statements))

        identity_params = [
            params
            for sql, params in connection.statements
            if "insert into card_identities" in sql.lower() and params[0] == "EB04-054"
        ]
        self.assertEqual(identity_params[0][10], None)

    def test_card_sets_for_uses_name_when_official_set_has_no_code(self):
        card = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)[0]
        card.card_sets = ["Offline Regional Participation Pack 2025 Vol.2"]
        card.card_set_codes = []

        self.assertEqual(
            _card_sets_for(card),
            [
                (
                    "Offline Regional Participation Pack 2025 Vol.2",
                    "Offline Regional Participation Pack 2025 Vol.2",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
