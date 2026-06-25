from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .scraper import OnePieceCardPrinting


DEFAULT_DATABASE_URL = "postgresql://tcg_search:tcg_search@localhost:5432/tcg_search"
DEFAULT_LANGUAGE_CODE = "jp"
RARITY_NAMES = {
    "L": "Leader",
    "C": "Common",
    "UC": "Uncommon",
    "R": "Rare",
    "SR": "Super Rare",
    "SEC": "Secret Rare",
    "P": "Promotion",
    "TR": "Treasure Rare",
    "SP_CARD": "Special Card",
}
PRODUCT_TYPE_PREFIXES = {
    "OP": "BOOSTER",
    "ST": "STARTER",
    "EB": "EXTRA_BOOSTER",
    "PRB": "PREMIUM_BOOSTER",
}


@dataclass(frozen=True)
class LoadStats:
    cards: int = 0
    printings: int = 0


def connect_database(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for database loading. "
            "Install project dependencies in the venv first.",
        ) from exc

    return psycopg.connect(database_url)


def load_cards_to_database(
    connection,
    cards: Iterable[OnePieceCardPrinting],
    language_code: str = DEFAULT_LANGUAGE_CODE,
    region_code: str | None = None,
) -> LoadStats:
    card_count = 0
    printing_count = 0
    for card in cards:
        card_count += 1
        attribute_id = _upsert_attribute(connection, card.attribute)
        identity_id = _upsert_card_identity(connection, card, attribute_id)
        _upsert_card_identity_translation(connection, identity_id, card, language_code)
        _replace_colors(connection, identity_id, card.colors)
        _replace_traits(connection, identity_id, card.traits)

        rarity_id = _upsert_rarity(connection, card.rarity_code)
        card_sets = _card_sets_for(card)
        for card_set_code, card_set_name in card_sets:
            card_set_id = _upsert_card_set(connection, card_set_code, card_set_name)
            _upsert_card_set_translation(connection, card_set_id, language_code, card_set_name)
            _upsert_card_printing(
                connection=connection,
                card=card,
                identity_id=identity_id,
                card_set_id=card_set_id,
                rarity_id=rarity_id,
                language_code=language_code,
                region_code=region_code,
            )
            printing_count += 1

    return LoadStats(cards=card_count, printings=printing_count)


def _upsert_attribute(connection, name: str | None):
    if not name:
        return None
    return _fetch_id(
        connection,
        """
        insert into attributes (name)
        values (%s)
        on conflict (name) do update
        set name = excluded.name
        returning id
        """,
        (name,),
    )


def _upsert_color(connection, name: str):
    code = name.lower()
    return _fetch_id(
        connection,
        """
        insert into colors (code, name)
        values (%s, %s)
        on conflict (code) do update
        set name = excluded.name
        returning id
        """,
        (code, name),
    )


def _upsert_trait(connection, name: str):
    return _fetch_id(
        connection,
        """
        insert into traits (name)
        values (%s)
        on conflict (name) do update
        set name = excluded.name
        returning id
        """,
        (name,),
    )


def _upsert_rarity(connection, code: str):
    return _fetch_id(
        connection,
        """
        insert into rarities (code, name)
        values (%s, %s)
        on conflict (code) do update
        set name = excluded.name
        returning id
        """,
        (code, _rarity_name(code)),
    )


def _upsert_card_set(connection, code: str, name: str):
    return _fetch_id(
        connection,
        """
        insert into card_sets (code, name, product_type)
        values (%s, %s, %s)
        on conflict (code) do update
        set
            product_type = excluded.product_type,
            updated_at = now()
        returning id
        """,
        (code, code, _product_type_for_set_code(code)),
    )


def _upsert_card_identity(connection, card: OnePieceCardPrinting, attribute_id):
    return _fetch_id(
        connection,
        """
        insert into card_identities (
            card_no,
            name,
            card_type,
            cost,
            life,
            power,
            counter,
            attribute_id,
            effect_text,
            trigger_text,
            block_no
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (card_no) do update
        set
            card_type = excluded.card_type,
            cost = excluded.cost,
            life = excluded.life,
            power = excluded.power,
            counter = excluded.counter,
            attribute_id = excluded.attribute_id,
            block_no = excluded.block_no,
            updated_at = now()
        returning id
        """,
        (
            card.card_no,
            card.card_no,
            card.card_type,
            card.cost,
            card.life,
            card.power,
            card.counter,
            attribute_id,
            None,
            None,
            _block_no(card.block_icon),
        ),
    )


def _upsert_card_identity_translation(
    connection,
    identity_id,
    card: OnePieceCardPrinting,
    language_code: str,
) -> None:
    _execute(
        connection,
        """
        insert into card_identity_translations (
            card_identity_id,
            language_code,
            name,
            effect_text,
            trigger_text
        )
        values (%s, %s, %s, %s, %s)
        on conflict (card_identity_id, language_code) do update
        set
            name = excluded.name,
            effect_text = excluded.effect_text,
            trigger_text = excluded.trigger_text,
            updated_at = now()
        """,
        (
            identity_id,
            language_code,
            card.name,
            card.effect_text,
            card.trigger_text,
        ),
    )


def _upsert_card_set_translation(connection, card_set_id, language_code: str, name: str) -> None:
    _execute(
        connection,
        """
        insert into card_set_translations (card_set_id, language_code, name)
        values (%s, %s, %s)
        on conflict (card_set_id, language_code) do update
        set
            name = excluded.name,
            updated_at = now()
        """,
        (card_set_id, language_code, name),
    )


def _replace_colors(connection, identity_id, colors: list[str]) -> None:
    _execute(
        connection,
        "delete from card_identity_colors where card_identity_id = %s",
        (identity_id,),
    )
    for color in colors:
        color_id = _upsert_color(connection, color)
        _execute(
            connection,
            """
            insert into card_identity_colors (card_identity_id, color_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (identity_id, color_id),
        )


def _replace_traits(connection, identity_id, traits: list[str]) -> None:
    _execute(
        connection,
        "delete from card_identity_traits where card_identity_id = %s",
        (identity_id,),
    )
    for trait in traits:
        trait_id = _upsert_trait(connection, trait)
        _execute(
            connection,
            """
            insert into card_identity_traits (card_identity_id, trait_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (identity_id, trait_id),
        )


def _upsert_card_printing(
    connection,
    card: OnePieceCardPrinting,
    identity_id,
    card_set_id,
    rarity_id,
    language_code: str,
    region_code: str | None,
) -> None:
    _execute(
        connection,
        """
        insert into card_printings (
            card_identity_id,
            card_set_id,
            rarity_id,
            language_code,
            region_code,
            variant_name,
            is_parallel,
            foil_treatment,
            illustration_type,
            image_url,
            source_url
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (
            card_identity_id,
            card_set_id,
            rarity_id,
            language_code,
            region_code,
            variant_name,
            is_parallel,
            foil_treatment
        )
        do update
        set
            illustration_type = excluded.illustration_type,
            image_url = excluded.image_url,
            source_url = excluded.source_url,
            updated_at = now()
        """,
        (
            identity_id,
            card_set_id,
            rarity_id,
            language_code,
            region_code,
            _variant_name(card),
            card.is_parallel,
            None,
            None,
            card.image_url,
            card.source_url,
        ),
    )


def _fetch_id(connection, sql: str, params: tuple):
    row = connection.execute(sql, params).fetchone()
    return row[0]


def _execute(connection, sql: str, params: tuple) -> None:
    connection.execute(sql, params)


def _card_sets_for(card: OnePieceCardPrinting) -> list[tuple[str, str]]:
    if not card.card_set_codes and not card.card_sets:
        raise ValueError(f"{card.printing_id} has no card set code")

    if not card.card_set_codes:
        return [(name, name) for name in card.card_sets]

    names_by_code = {
        code: name for code, name in zip(card.card_set_codes, card.card_sets, strict=False)
    }
    return [(code, names_by_code.get(code, code)) for code in card.card_set_codes]


def _variant_name(card: OnePieceCardPrinting) -> str | None:
    if card.printing_id == card.card_no:
        return None
    return card.printing_id


def _block_no(block_icon: str | None) -> int | None:
    if block_icon and block_icon.isdigit():
        return int(block_icon)
    return None


def _rarity_name(code: str) -> str:
    if code in RARITY_NAMES:
        return RARITY_NAMES[code]
    return code.replace("_", " ").title()


def _product_type_for_set_code(code: str) -> str:
    prefix = code.split("-", maxsplit=1)[0]
    return PRODUCT_TYPE_PREFIXES.get(prefix, "OTHER")
