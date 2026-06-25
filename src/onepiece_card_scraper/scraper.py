#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from functools import partial
import json
import os
import re
import ssl
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, TextIO
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://onepiece-cardgame.com"
CARDLIST_PATH = "/cardlist/"
USER_AGENT = "tcg-search-onepiece-card-scraper/0.1"
CA_BUNDLE_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
COMMON_CA_BUNDLE_PATHS = (
    "/etc/ssl/cert.pem",
    "/private/etc/ssl/cert.pem",
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/usr/local/etc/openssl@3/cert.pem",
    "/usr/local/etc/openssl/cert.pem",
)
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
CARD_SET_CODE_PATTERN = re.compile(r"\[([A-Z0-9-]+)\]")
PARALLEL_ID_PATTERN = re.compile(r"_p\d+$")
CSV_FIELDS = [
    "printing_id",
    "card_no",
    "name",
    "rarity_code",
    "card_type",
    "cost",
    "life",
    "attribute",
    "power",
    "counter",
    "colors",
    "block_icon",
    "traits",
    "effect_text",
    "trigger_text",
    "card_sets",
    "card_set_codes",
    "image_url",
    "source_url",
    "is_parallel",
]


@dataclass
class OnePieceCardPrinting:
    printing_id: str
    card_no: str
    name: str
    rarity_code: str
    card_type: str
    cost: int | None
    life: int | None
    attribute: str | None
    power: int | None
    counter: int | None
    colors: list[str]
    block_icon: str | None
    traits: list[str]
    effect_text: str | None
    trigger_text: str | None
    card_sets: list[str]
    card_set_codes: list[str]
    image_url: str | None
    source_url: str
    is_parallel: bool

    def to_record(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, object]) -> OnePieceCardPrinting:
        return cls(
            printing_id=str(record["printing_id"]),
            card_no=str(record["card_no"]),
            name=str(record["name"]),
            rarity_code=str(record["rarity_code"]),
            card_type=str(record["card_type"]),
            cost=record["cost"],
            life=record["life"],
            attribute=record["attribute"],
            power=record["power"],
            counter=record["counter"],
            colors=list(record["colors"]),
            block_icon=record["block_icon"],
            traits=list(record["traits"]),
            effect_text=record["effect_text"],
            trigger_text=record["trigger_text"],
            card_sets=list(record["card_sets"]),
            card_set_codes=list(record["card_set_codes"]),
            image_url=record["image_url"],
            source_url=str(record["source_url"]),
            is_parallel=bool(record["is_parallel"]),
        )


@dataclass(frozen=True)
class SeriesOption:
    code: str
    name: str


class Node:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node | str] = []

    def class_names(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def has_class(self, class_name: str) -> bool:
        return class_name in self.class_names()

    def find_first(self, tag: str | None = None, class_name: str | None = None) -> Node | None:
        for node in self.find_all(tag=tag, class_name=class_name):
            return node
        return None

    def find_all(self, tag: str | None = None, class_name: str | None = None) -> Iterable[Node]:
        if (tag is None or self.tag == tag) and (class_name is None or self.has_class(class_name)):
            yield self

        for child in self.children:
            if isinstance(child, Node):
                yield from child.find_all(tag=tag, class_name=class_name)

    def text_content(self) -> str:
        return normalize_text(_collect_text(self))


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        while len(self.stack) > 1:
            node = self.stack.pop()
            if node.tag == tag:
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def build_cardlist_url(base_url: str = DEFAULT_BASE_URL, series: str | None = None) -> str:
    url = f"{base_url.rstrip('/')}{CARDLIST_PATH}"
    if series:
        return f"{url}?{urlencode({'series': series})}"
    return url


def fetch_html(url: str, timeout_seconds: float = 20.0) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        html = response.read().decode(charset, errors="replace")
        return html, response.geturl()


def discover_series_options(html: str, include_all: bool = False) -> list[SeriesOption]:
    builder = TreeBuilder()
    builder.feed(html)

    series_select = None
    for select in builder.root.find_all(tag="select"):
        if select.attrs.get("id") == "series" or select.attrs.get("name") == "series":
            series_select = select
            break
    if not series_select:
        return []

    series_options = []
    for option in series_select.find_all(tag="option"):
        code = option.attrs.get("value", "").strip()
        if not code:
            continue
        if code == "ALL" and not include_all:
            continue
        series_options.append(SeriesOption(code=code, name=_clean_option_label(option.text_content())))
    return series_options


def crawl_all_series(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 20.0,
    fetcher=fetch_html,
) -> list[OnePieceCardPrinting]:
    index_url = build_cardlist_url(base_url=base_url)
    index_html, _ = fetcher(index_url, timeout_seconds)
    series_options = discover_series_options(index_html)
    cards_by_key: dict[tuple[str, tuple[str, ...], str | None], OnePieceCardPrinting] = {}

    for index, series_option in enumerate(series_options, start=1):
        series_url = build_cardlist_url(base_url=base_url, series=series_option.code)
        print(
            f"Fetching series {index}/{len(series_options)} {series_option.code} {series_option.name}",
            file=sys.stderr,
        )
        html, final_url = fetcher(series_url, timeout_seconds)
        for card in parse_card_list(html, source_url=final_url):
            _apply_series_fallback(card, series_option)
            cards_by_key.setdefault(_card_record_key(card), card)

    return list(cards_by_key.values())


def parse_card_list(html: str, source_url: str) -> list[OnePieceCardPrinting]:
    builder = TreeBuilder()
    builder.feed(html)

    cards = []
    for modal in builder.root.find_all(tag="dl", class_name="modalCol"):
        cards.append(_parse_modal_card(modal, source_url=source_url))
    return cards


def write_jsonl(cards: Iterable[OnePieceCardPrinting], output_path: Path) -> None:
    _ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8") as output:
        write_jsonl_stream(cards, output)


def read_jsonl(input_path: Path) -> list[OnePieceCardPrinting]:
    cards = []
    with input_path.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if line.strip():
                cards.append(OnePieceCardPrinting.from_record(json.loads(line)))
    return cards


def write_jsonl_stream(cards: Iterable[OnePieceCardPrinting], output: TextIO) -> None:
    for card in cards:
        output.write(json.dumps(card.to_record(), ensure_ascii=False, sort_keys=True))
        output.write("\n")


def write_csv(cards: Iterable[OnePieceCardPrinting], output_path: Path) -> None:
    _ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8", newline="") as output:
        write_csv_stream(cards, output)


def write_csv_stream(cards: Iterable[OnePieceCardPrinting], output: TextIO) -> None:
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for card in cards:
        writer.writerow(_to_csv_record(card))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.input_jsonl:
        cards = read_jsonl(Path(args.input_jsonl))
    elif args.all_series:
        cards = crawl_all_series(base_url=args.base_url, timeout_seconds=args.timeout)
    else:
        source_url = args.url or build_cardlist_url(base_url=args.base_url, series=args.series)
        html, final_url = fetch_html(source_url, timeout_seconds=args.timeout)
        cards = parse_card_list(html, source_url=final_url)

    if not cards:
        print("No cards found", file=sys.stderr)
        return 2

    if args.upload_images:
        from .storage import ObjectStorageConfig, S3ObjectStorage, fetch_image, upload_card_images

        storage = S3ObjectStorage(
            ObjectStorageConfig(
                endpoint_url=args.storage_endpoint_url,
                bucket=args.storage_bucket,
                access_key=args.storage_access_key,
                secret_key=args.storage_secret_key,
                region=args.storage_region,
                public_base_url=args.storage_public_base_url,
                timeout_seconds=args.timeout,
            ),
        )
        image_key_prefix = args.image_key_prefix.format(language_code=args.language_code)
        image_stats = upload_card_images(
            cards,
            storage=storage,
            image_fetcher=partial(
                fetch_image,
                max_attempts=args.image_retry_attempts,
                retry_delay_seconds=args.image_retry_delay,
            ),
            key_prefix=image_key_prefix,
            timeout_seconds=args.timeout,
        )
        print(
            f"Uploaded {image_stats.uploaded} images to {args.storage_bucket}; "
            f"skipped {image_stats.skipped}",
            file=sys.stderr,
        )

    if args.output:
        output_path = Path(args.output)
        if args.format == "jsonl":
            write_jsonl(cards, output_path)
        else:
            write_csv(cards, output_path)
        print(f"Wrote {len(cards)} cards to {output_path}", file=sys.stderr)
        if not args.load_db:
            return 0

    if args.load_db:
        from .database import connect_database, load_cards_to_database

        with connect_database(args.database_url) as connection:
            stats = load_cards_to_database(
                connection=connection,
                cards=cards,
                language_code=args.language_code,
                region_code=args.region_code,
            )
        print(
            f"Loaded {stats.cards} cards and {stats.printings} printings into database",
            file=sys.stderr,
        )
        return 0

    if args.format == "jsonl":
        write_jsonl_stream(cards, sys.stdout)
    else:
        write_csv_stream(cards, sys.stdout)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape ONE PIECE CARD GAME official card list pages.",
    )
    parser.add_argument(
        "--url",
        help="Exact card list URL. Overrides --base-url and --series.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Official site base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--series",
        help="Official series id, for example 569116. Omit to use the site's default card list.",
    )
    parser.add_argument(
        "--all-series",
        action="store_true",
        help="Discover every official Recording option and crawl each series page.",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="Output format. Default: jsonl.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path. Omit to write to stdout.",
    )
    parser.add_argument(
        "--input-jsonl",
        help="Read scraped JSONL from this path instead of fetching the official site.",
    )
    parser.add_argument(
        "--load-db",
        action="store_true",
        help="Upsert scraped cards into the local PostgreSQL schema.",
    )
    parser.add_argument(
        "--upload-images",
        action="store_true",
        help="Download card images and upload them to the configured local S3-compatible bucket.",
    )
    parser.add_argument(
        "--storage-endpoint-url",
        default=os.environ.get("TCG_SEARCH_STORAGE_ENDPOINT_URL", "http://localhost:9000"),
        help="S3-compatible object storage endpoint. Default: TCG_SEARCH_STORAGE_ENDPOINT_URL or http://localhost:9000.",
    )
    parser.add_argument(
        "--storage-public-base-url",
        default=os.environ.get("TCG_SEARCH_STORAGE_PUBLIC_BASE_URL"),
        help="Public base URL stored in image_url. Default: storage endpoint URL.",
    )
    parser.add_argument(
        "--storage-bucket",
        default=os.environ.get("MINIO_BUCKET", "tcg-search-local"),
        help="S3 bucket for card images. Default: MINIO_BUCKET or tcg-search-local.",
    )
    parser.add_argument(
        "--storage-access-key",
        default=os.environ.get("MINIO_ROOT_USER", "tcg_search"),
        help="S3 access key. Default: MINIO_ROOT_USER or tcg_search.",
    )
    parser.add_argument(
        "--storage-secret-key",
        default=os.environ.get("MINIO_ROOT_PASSWORD", "tcg_search_minio"),
        help="S3 secret key. Default: MINIO_ROOT_PASSWORD or the local MinIO default.",
    )
    parser.add_argument(
        "--storage-region",
        default=os.environ.get("TCG_SEARCH_STORAGE_REGION", "us-east-1"),
        help="S3 signing region. Default: TCG_SEARCH_STORAGE_REGION or us-east-1.",
    )
    parser.add_argument(
        "--image-key-prefix",
        default=os.environ.get("TCG_SEARCH_IMAGE_KEY_PREFIX", "onepiece/{language_code}/cards"),
        help="Object key prefix for uploaded card images. Default: onepiece/{language_code}/cards.",
    )
    parser.add_argument(
        "--image-retry-attempts",
        type=int,
        default=int(os.environ.get("TCG_SEARCH_IMAGE_RETRY_ATTEMPTS", "6")),
        help="Image download retry attempts for transient upstream failures. Default: 6.",
    )
    parser.add_argument(
        "--image-retry-delay",
        type=float,
        default=float(os.environ.get("TCG_SEARCH_IMAGE_RETRY_DELAY_SECONDS", "2.0")),
        help="Initial image retry delay in seconds; retries use exponential backoff. Default: 2.0.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "TCG_SEARCH_DATABASE_URL",
            "postgresql://tcg_search:tcg_search@localhost:5432/tcg_search",
        ),
        help="PostgreSQL URL for --load-db. Defaults to TCG_SEARCH_DATABASE_URL or local Docker DB.",
    )
    parser.add_argument(
        "--language-code",
        default="en",
        help="card_printings.language_code value for DB loading. Default: en.",
    )
    parser.add_argument(
        "--region-code",
        help="Optional card_printings.region_code value for DB loading.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds. Default: 20.",
    )
    args = parser.parse_args(argv)
    if args.all_series and (args.url or args.series or args.input_jsonl):
        parser.error("--all-series cannot be used with --url, --series, or --input-jsonl")
    return args


def _ssl_context() -> ssl.SSLContext:
    ca_file = _resolve_ca_file()
    if ca_file:
        return ssl.create_default_context(cafile=str(ca_file))
    return ssl.create_default_context()


def _resolve_ca_file(common_paths: tuple[str, ...] = COMMON_CA_BUNDLE_PATHS) -> Path | None:
    for env_var in CA_BUNDLE_ENV_VARS:
        env_path = os.environ.get(env_var)
        if env_path:
            path = Path(env_path)
            if path.is_file():
                return path

    for candidate in common_paths:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _parse_modal_card(modal: Node, source_url: str) -> OnePieceCardPrinting:
    printing_id = modal.attrs.get("id", "").strip()
    info = modal.find_first(class_name="infoCol")
    info_values = [span.text_content() for span in info.find_all(tag="span")] if info else []
    if len(info_values) < 3:
        raise ValueError(f"Could not parse card info for modal id {printing_id!r}")

    card_no, rarity_code, card_type = info_values[:3]
    name_node = modal.find_first(class_name="cardName")
    image_node = modal.find_first(tag="img")
    cost_node = modal.find_first(class_name="cost")

    cost = None
    life = None
    if cost_node:
        cost_or_life = _parse_int(_field_value(cost_node))
        label = _field_label(cost_node).lower()
        if "life" in label:
            life = cost_or_life
        else:
            cost = cost_or_life

    return OnePieceCardPrinting(
        printing_id=printing_id,
        card_no=card_no,
        name=name_node.text_content() if name_node else "",
        rarity_code=_normalize_rarity(rarity_code),
        card_type=card_type.upper(),
        cost=cost,
        life=life,
        attribute=_normalize_missing(_field_value(modal.find_first(class_name="attribute"))),
        power=_parse_int(_field_value(modal.find_first(class_name="power"))),
        counter=_parse_int(_field_value(modal.find_first(class_name="counter"))),
        colors=_split_slash(_field_value(modal.find_first(class_name="color"))),
        block_icon=_normalize_missing(_field_value(modal.find_first(class_name="block"))),
        traits=_split_slash(_field_value(modal.find_first(class_name="feature"))),
        effect_text=_normalize_missing(_field_value(modal.find_first(class_name="text"))),
        trigger_text=_normalize_missing(_field_value(modal.find_first(class_name="trigger"))),
        card_sets=_split_card_sets(_field_value(modal.find_first(class_name="getInfo"))),
        card_set_codes=_extract_card_set_codes(_field_value(modal.find_first(class_name="getInfo"))),
        image_url=_image_url(image_node, source_url),
        source_url=source_url,
        is_parallel=bool(PARALLEL_ID_PATTERN.search(printing_id)),
    )


def _field_label(node: Node | None) -> str:
    if not node:
        return ""
    heading = node.find_first(tag="h3")
    return heading.text_content() if heading else ""


def _field_value(node: Node | None) -> str:
    if not node:
        return ""
    parts: list[str] = []

    def walk(current: Node) -> None:
        for child in current.children:
            if isinstance(child, str):
                parts.append(child)
                continue
            if child.tag == "h3":
                continue
            if child.tag == "br":
                parts.append("\n")
                continue
            walk(child)

    walk(node)
    return normalize_text("".join(parts))


def _collect_text(node: Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        else:
            parts.append(_collect_text(child))
    return "".join(parts)


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip()


def _clean_option_label(value: str) -> str:
    value = re.sub(r"<br[^>]*>", " ", value)
    return normalize_text(value)


def _normalize_missing(value: str) -> str | None:
    value = normalize_text(value)
    if not value or value == "-":
        return None
    return value


def _normalize_rarity(value: str) -> str:
    return normalize_text(value).upper().replace(" ", "_")


def _parse_int(value: str) -> int | None:
    value = normalize_text(value).replace(",", "")
    if not value or value == "-":
        return None
    if not value.isdigit():
        return None
    return int(value)


def _split_slash(value: str) -> list[str]:
    value = normalize_text(value)
    if not value or value == "-":
        return []
    return [part.strip() for part in value.split("/") if part.strip()]


def _split_card_sets(value: str) -> list[str]:
    value = normalize_text(value)
    if not value or value == "-":
        return []

    matches = re.findall(r"[^;\n]*?\[[^\]]+\]", value)
    if matches:
        return [normalize_text(match.lstrip("; ")) for match in matches]
    return [value]


def _extract_card_set_codes(value: str) -> list[str]:
    return CARD_SET_CODE_PATTERN.findall(value)


def _apply_series_fallback(card: OnePieceCardPrinting, series_option: SeriesOption) -> None:
    if card.card_sets:
        return

    card.card_sets = [series_option.name]
    card.card_set_codes = _extract_card_set_codes(series_option.name)


def _image_url(node: Node | None, source_url: str) -> str | None:
    if not node:
        return None
    raw_url = node.attrs.get("data-src") or node.attrs.get("src")
    if not raw_url:
        return None
    return urljoin(source_url, raw_url)


def _card_record_key(card: OnePieceCardPrinting) -> tuple[str, tuple[str, ...], str | None]:
    return (card.printing_id, tuple(card.card_set_codes or card.card_sets), card.image_url)


def _to_csv_record(card: OnePieceCardPrinting) -> dict[str, object]:
    record = card.to_record()
    for key, value in list(record.items()):
        if isinstance(value, list):
            record[key] = "|".join(value)
        elif isinstance(value, bool):
            record[key] = "true" if value else "false"
        elif value is None:
            record[key] = ""
    return record


def _ensure_parent(output_path: Path) -> None:
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
