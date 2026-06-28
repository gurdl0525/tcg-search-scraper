from __future__ import annotations

from dataclasses import dataclass
import re


SEARCH_TOKEN_SEPARATOR_RE = re.compile(
    r"[^\w\u3130-\u318f\uac00-\ud7a3\u3040-\u309f\u30a0-\u30fa\u30fc-\u30ff\u3400-\u9fff]+",
    re.UNICODE,
)
SEARCH_TOKEN_STRIP_RE = SEARCH_TOKEN_SEPARATOR_RE
HANGUL_CHOSEONG = (
    "ㄱ",
    "ㄲ",
    "ㄴ",
    "ㄷ",
    "ㄸ",
    "ㄹ",
    "ㅁ",
    "ㅂ",
    "ㅃ",
    "ㅅ",
    "ㅆ",
    "ㅇ",
    "ㅈ",
    "ㅉ",
    "ㅊ",
    "ㅋ",
    "ㅌ",
    "ㅍ",
    "ㅎ",
)
HANGUL_SYLLABLE_START = 0xAC00
HANGUL_SYLLABLE_END = 0xD7A3
HANGUL_JUNGSEONG_JONGSEONG_COUNT = 21 * 28
HANGUL_COMPATIBILITY_JAMO_START = 0x3130
HANGUL_COMPATIBILITY_JAMO_END = 0x318F


@dataclass(frozen=True)
class SearchToken:
    source_field: str
    token_type: str
    token: str
    weight: int


def search_tokens_for_fields(
    name: str,
    effect_text: str | None,
    trigger_text: str | None,
) -> set[SearchToken]:
    tokens: set[SearchToken] = set()
    tokens.update(search_tokens_for_text(name, source_field="name"))
    if effect_text:
        tokens.update(search_tokens_for_text(effect_text, source_field="effect_text"))
    if trigger_text:
        tokens.update(search_tokens_for_text(trigger_text, source_field="trigger_text"))
    return tokens


def search_tokens_for_text(value: str, source_field: str) -> set[SearchToken]:
    tokens: set[SearchToken] = set()
    normalized = normalize_search_token(value)
    if normalized:
        tokens.add(SearchToken(source_field, "normalized", normalized, 100))
        for token in ngrams(normalized, size=2):
            tokens.add(SearchToken(source_field, "ngram", token, 20))

    for word in token_words(value):
        tokens.add(SearchToken(source_field, "word", word, 90))
        for token in prefixes(word):
            tokens.add(SearchToken(source_field, "prefix", token, 50))

        word_choseong = hangul_choseong(word)
        if word_choseong:
            tokens.add(SearchToken(source_field, "choseong", word_choseong, 70))
            for token in prefixes(word_choseong):
                tokens.add(SearchToken(source_field, "choseong_prefix", token, 60))

    full_choseong = hangul_choseong(value)
    if full_choseong:
        tokens.add(SearchToken(source_field, "choseong", full_choseong, 70))
        for token in prefixes(full_choseong):
            tokens.add(SearchToken(source_field, "choseong_prefix", token, 60))

    return tokens


def normalize_search_token(value: str) -> str:
    return SEARCH_TOKEN_STRIP_RE.sub("", value.lower())


def token_words(value: str) -> list[str]:
    return [
        normalize_search_token(part)
        for part in SEARCH_TOKEN_SEPARATOR_RE.split(value)
        if normalize_search_token(part)
    ]


def prefixes(value: str) -> list[str]:
    return [value[:index] for index in range(1, len(value) + 1)]


def ngrams(value: str, size: int) -> list[str]:
    if len(value) < size:
        return []
    return [value[index:index + size] for index in range(0, len(value) - size + 1)]


def hangul_choseong(value: str) -> str:
    chars = []
    for char in value:
        code = ord(char)
        if HANGUL_SYLLABLE_START <= code <= HANGUL_SYLLABLE_END:
            chars.append(HANGUL_CHOSEONG[(code - HANGUL_SYLLABLE_START) // HANGUL_JUNGSEONG_JONGSEONG_COUNT])
        elif HANGUL_COMPATIBILITY_JAMO_START <= code <= HANGUL_COMPATIBILITY_JAMO_END:
            chars.append(char)
    return "".join(chars)
