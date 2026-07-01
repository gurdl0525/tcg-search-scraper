import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from io import BytesIO

from onepiece_card_scraper.scraper import (
    DEFAULT_BASE_URL,
    _resolve_ca_file,
    build_cardlist_url,
    crawl_all_series,
    discover_series_options,
    fetch_html,
    main,
    parse_card_list,
    read_jsonl,
    write_jsonl,
)
from onepiece_card_scraper.storage import ImageUploadStats


SOURCE_URL = "https://en.onepiece-cardgame.com/cardlist/?series=569116"


SERIES_INDEX_HTML = """
<select name="series" class="selectModal" id="series">
  <option value>Recording</option>
  <option value>ALL</option>
  <option value="569101">BOOSTER PACK &lt;br class=&quot;spInline&quot;&gt;-ROMANCE DAWN- [OP-01]</option>
  <option value="569102">BOOSTER PACK &lt;br class=&quot;spInline&quot;&gt;-PARAMOUNT WAR- [OP-02]</option>
  <option value="569026">STARTER DECK &lt;br class=&quot;spInline&quot;&gt;-PURPLE/BLACK Monkey.D.Luffy- [ST-26]</option>
</select>
"""


SAMPLE_HTML = """
<div class="resultCol">
  <dl class="modalCol" id="OP16-001_p1">
    <dt>
      <div class="infoCol">
        <span>OP16-001</span> | <span>L</span> | <span>LEADER</span>
      </div>
      <div class="cardName">Portgas.D.Ace</div>
    </dt>
    <dd>
      <div class="frontCol">
        <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/OP16-001_p1.png?260616" alt="Portgas.D.Ace">
      </div>
      <div class="backCol">
        <div class="col2">
          <div class="cost"><h3>Life</h3>5</div>
          <div class="attribute"><h3>Attribute</h3><img alt="Special"><i>Special</i></div>
        </div>
        <div class="col2">
          <div class="power"><h3>Power</h3>5000</div>
          <div class="counter"><h3>Counter</h3>-</div>
        </div>
        <div class="col2">
          <div class="color"><h3>Color</h3>Red/Yellow</div>
          <div class="block"><h3>Block<br class="spInline"> icon</h3>5</div>
        </div>
        <div class="feature"><h3>Type</h3>Whitebeard Pirates/Straw Hat Crew</div>
        <div class="text"><h3>Effect</h3>[Activate: Main] Example.<br>[On Play] Next line.</div>
        <div class="getInfo"><h3>Card Set(s)</h3>-THE TIME OF BATTLE- [OP-16]</div>
      </div>
    </dd>
  </dl>
  <dl class="modalCol" id="EB04-054_p1">
    <dt>
      <div class="infoCol">
        <span>EB04-054</span> | <span>SP CARD</span> | <span>CHARACTER</span>
      </div>
      <div class="cardName">Bartholomew Kuma</div>
    </dt>
    <dd>
      <div class="frontCol">
        <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/EB04-054_p1.png?260616" alt="Bartholomew Kuma">
      </div>
      <div class="backCol">
        <div class="col2">
          <div class="cost"><h3>Cost</h3>7</div>
          <div class="attribute"><h3>Attribute</h3><i>Strike</i></div>
        </div>
        <div class="col2">
          <div class="power"><h3>Power</h3>9000</div>
          <div class="counter"><h3>Counter</h3>1000</div>
        </div>
        <div class="col2">
          <div class="color"><h3>Color</h3>Black</div>
          <div class="block"><h3>Block<br class="spInline"> icon</h3>X</div>
        </div>
        <div class="feature"><h3>Type</h3>The Seven Warlords of the Sea</div>
        <div class="text"><h3>Effect</h3>-</div>
        <div class="trigger"><h3>Trigger</h3>[Trigger] Play this card.</div>
        <div class="getInfo"><h3>Card Set(s)</h3>-THE TIME OF BATTLE- [OP-16]; -MEMORIAL COLLECTION- [EB-01]</div>
      </div>
    </dd>
  </dl>
</div>
"""


SINGLE_CARD_HTML = """
<div class="resultCol">
  <dl class="modalCol" id="OP02-001">
    <dt>
      <div class="infoCol">
        <span>OP02-001</span> | <span>L</span> | <span>LEADER</span>
      </div>
      <div class="cardName">Edward.Newgate</div>
    </dt>
    <dd>
      <div class="frontCol">
        <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/OP02-001.png?260616" alt="Edward.Newgate">
      </div>
      <div class="backCol">
        <div class="col2">
          <div class="cost"><h3>Life</h3>6</div>
          <div class="attribute"><h3>Attribute</h3><i>Special</i></div>
        </div>
        <div class="col2">
          <div class="power"><h3>Power</h3>6000</div>
          <div class="counter"><h3>Counter</h3>-</div>
        </div>
        <div class="col2">
          <div class="color"><h3>Color</h3>Red</div>
          <div class="block"><h3>Block<br class="spInline"> icon</h3>1</div>
        </div>
        <div class="feature"><h3>Type</h3>Whitebeard Pirates</div>
        <div class="text"><h3>Effect</h3>Example.</div>
        <div class="getInfo"><h3>Card Set(s)</h3>-PARAMOUNT WAR- [OP-02]</div>
      </div>
    </dd>
  </dl>
</div>
"""


NO_SET_CARD_HTML = """
<div class="resultCol">
  <dl class="modalCol" id="ST14-010_r1">
    <dt>
      <div class="infoCol">
        <span>ST14-010</span> | <span>C</span> | <span>CHARACTER</span>
      </div>
      <div class="cardName">Brook</div>
    </dt>
    <dd>
      <div class="frontCol">
        <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/ST14-010_r1.png?260616" alt="Brook">
      </div>
      <div class="backCol">
        <div class="col2">
          <div class="cost"><h3>Cost</h3>5</div>
          <div class="attribute"><h3>Attribute</h3><i>Slash</i></div>
        </div>
        <div class="col2">
          <div class="power"><h3>Power</h3>7000</div>
          <div class="counter"><h3>Counter</h3>1000</div>
        </div>
        <div class="col2">
          <div class="color"><h3>Color</h3>Black</div>
          <div class="block"><h3>Block<br class="spInline"> icon</h3>2</div>
        </div>
        <div class="feature"><h3>Type</h3>Straw Hat Crew</div>
        <div class="text"><h3>Effect</h3>-</div>
      </div>
    </dd>
  </dl>
</div>
"""


KOREAN_SERIES_INDEX_HTML = """
<div class="sub_p_search_box">
  <select>
    <option value="all">전체</option>
    <option value="[OPK-13] 부스터 팩 계승되는 의지" selected="selected">[OPK-13] 부스터 팩 계승되는 의지</option>
    <option value="[STK-01] 스타트 덱 밀짚모자 일당">[STK-01] 스타트 덱 밀짚모자 일당</option>
    <option value="【프로모션】">프로모션</option>
  </select>
</div>
"""


KOREAN_CARD_LIST_HTML = """
<div class="card_sch_list">
  <button class="item">
    <img class="image" src="/fileDownload?downname=op13-001" alt="image">
    <p class="cardGet">[OPK-13] 부스터 팩 계승되는 의지
    <p class="cardType">리더
    <p class="cardColor">적색,녹색
    <p class="life">4
    <p class="cardPoint">초신성/밀짚모자 일당
    <p class="cardCounter">-
    <p class="animationType">오리지널
    <p class="cardTrigger">
    <p class="cardAttr">타격
    <p class="power">5000
    <p class="cardNumber">OP13-001
    <p class="rarity">L
    <p class="cardText">【두웅!!×1】효과 텍스트
    <p class="blockNumber">4
    <p class="cardName">몽키 D. 루피
  </button>
  <button class="item">
    <img class="image" src="/fileDownload?downname=op13-001-p1" alt="image">
    <p class="cardGet">[OPK-13] 부스터 팩 계승되는 의지
    <p class="cardType">캐릭터
    <p class="cardColor">적색
    <p class="life">1
    <p class="cardPoint">후샤 마을
    <p class="cardCounter">+2000
    <p class="animationType">원작
    <p class="cardTrigger">【트리거】파워 +3000.
    <p class="cardAttr">지혜
    <p class="power">0
    <p class="cardNumber">OP13-001_P1
    <p class="rarity">C
    <p class="cardText">등장 시 효과
    <p class="blockNumber">4
    <p class="cardName">마키노
  </button>
</div>
<div class="pagination">
  <a href="/cardlist.do?page=0&amp;size=20&amp;series=%5BOPK-13%5D" class="num active">1</a>
  <a href="/cardlist.do?page=1&amp;size=20&amp;series=%5BOPK-13%5D" class="num">2</a>
  <a href="/cardlist.do?page=1&amp;size=20&amp;series=%5BOPK-13%5D" class="pagi_next">Next</a>
</div>
"""


KOREAN_CARD_PAGE_2_HTML = """
<div class="card_sch_list">
  <button class="item">
    <img class="image" src="/fileDownload?downname=op13-002" alt="image">
    <p class="cardGet">[OPK-13] 부스터 팩 계승되는 의지
    <p class="cardType">이벤트
    <p class="cardColor">청색
    <p class="life">2
    <p class="cardPoint">밀짚모자 일당
    <p class="cardCounter">-
    <p class="animationType">원작
    <p class="cardTrigger">【트리거】카드를 1장 뽑는다.
    <p class="cardAttr">-
    <p class="power">-
    <p class="cardNumber">OP13-002
    <p class="rarity">R
    <p class="cardText">메인 효과
    <p class="blockNumber">4
    <p class="cardName">고무고무
  </button>
</div>
<div class="pagination">
  <a href="/cardlist.do?page=1&amp;size=20&amp;series=%5BOPK-13%5D" class="num active">2</a>
  <a href="/cardlist.do?page=2&amp;size=20&amp;series=%5BOPK-13%5D" class="num">3</a>
</div>
"""


KOREAN_CARD_PAGE_3_HTML = """
<div class="card_sch_list">
  <button class="item">
    <img class="image" src="/fileDownload?downname=op13-003" alt="image">
    <p class="cardGet">[OPK-13] 부스터 팩 계승되는 의지
    <p class="cardType">스테이지
    <p class="cardColor">녹색
    <p class="life">1
    <p class="cardPoint">이스트 블루
    <p class="cardCounter">-
    <p class="animationType">원작
    <p class="cardTrigger">
    <p class="cardAttr">-
    <p class="power">-
    <p class="cardNumber">OP13-003
    <p class="rarity">C
    <p class="cardText">스테이지 효과
    <p class="blockNumber">4
    <p class="cardName">후샤 마을
  </button>
</div>
"""


class FakeHtmlResponse:
    def __init__(self, body: bytes, final_url: str, charset: str = "utf-8") -> None:
        self._body = body
        self._final_url = final_url
        self.headers = mock.Mock()
        self.headers.get_content_charset.return_value = charset

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body

    def geturl(self):
        return self._final_url


class OnePieceCardScraperTests(unittest.TestCase):
    def test_discover_series_options_skips_placeholder_and_all(self):
        series_options = discover_series_options(SERIES_INDEX_HTML)

        self.assertEqual([option.code for option in series_options], ["569101", "569102", "569026"])
        self.assertEqual(series_options[0].name, "BOOSTER PACK -ROMANCE DAWN- [OP-01]")

    def test_discover_series_options_supports_korean_series_select(self):
        series_options = discover_series_options(KOREAN_SERIES_INDEX_HTML)

        self.assertEqual(
            [option.code for option in series_options],
            [
                "[OPK-13] 부스터 팩 계승되는 의지",
                "[STK-01] 스타트 덱 밀짚모자 일당",
                "【프로모션】",
            ],
        )
        self.assertEqual(series_options[0].name, "[OPK-13] 부스터 팩 계승되는 의지")

    def test_crawl_all_series_fetches_each_series(self):
        fetched_urls = []

        def fake_fetcher(url, timeout_seconds):
            fetched_urls.append(url)
            if "series=569101" in url:
                return SAMPLE_HTML, url
            if "series=569102" in url:
                return SINGLE_CARD_HTML, url
            if "series=569026" in url:
                return NO_SET_CARD_HTML, url
            return SERIES_INDEX_HTML, url

        cards = crawl_all_series(fetcher=fake_fetcher)

        self.assertEqual(
            [card.printing_id for card in cards],
            ["OP16-001_p1", "EB04-054_p1", "OP02-001", "ST14-010_r1"],
        )
        self.assertEqual(cards[-1].card_set_codes, ["ST-26"])
        self.assertEqual(cards[-1].card_sets, ["STARTER DECK -PURPLE/BLACK Monkey.D.Luffy- [ST-26]"])
        self.assertEqual(
            fetched_urls,
            [
                build_cardlist_url(base_url=DEFAULT_BASE_URL),
                build_cardlist_url(base_url=DEFAULT_BASE_URL, series="569101"),
                build_cardlist_url(base_url=DEFAULT_BASE_URL, series="569102"),
                build_cardlist_url(base_url=DEFAULT_BASE_URL, series="569026"),
            ],
        )

    def test_crawl_all_series_follows_korean_pagination(self):
        fetched_urls = []

        def fake_fetcher(url, timeout_seconds):
            fetched_urls.append(url)
            if "page=2" in url:
                return KOREAN_CARD_PAGE_3_HTML, url
            if "page=1" in url:
                return KOREAN_CARD_PAGE_2_HTML, url
            if "series=%5BOPK-13%5D" in url:
                return KOREAN_CARD_LIST_HTML, url
            return KOREAN_SERIES_INDEX_HTML, url

        cards = crawl_all_series(base_url="https://onepiece-cardgame.kr/cardlist.do", fetcher=fake_fetcher)

        self.assertEqual([card.printing_id for card in cards], ["OP13-001", "OP13-001_P1", "OP13-002", "OP13-003"])
        self.assertEqual(fetched_urls[0], "https://onepiece-cardgame.kr/cardlist.do")
        self.assertIn("series=%5BOPK-13%5D", fetched_urls[1])
        self.assertIn("page=1", fetched_urls[2])
        self.assertIn("page=2", fetched_urls[3])

    def test_fetch_html_retries_transient_http_errors(self):
        calls = []
        sleeps = []

        def fake_opener(request, timeout, context):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(
                    request.full_url,
                    502,
                    "Bad Gateway",
                    hdrs=None,
                    fp=BytesIO(b"bad gateway"),
                )
            return FakeHtmlResponse(b"<html>ok</html>", "https://example.com/cardlist/")

        html, final_url = fetch_html(
            "https://example.com/cardlist/",
            opener=fake_opener,
            sleep=sleeps.append,
            retry_jitter_ratio=0.0,
        )

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(final_url, "https://example.com/cardlist/")
        self.assertEqual(calls, ["https://example.com/cardlist/", "https://example.com/cardlist/"])
        self.assertEqual(sleeps, [2.0])

    def test_build_cardlist_url_accepts_exact_cardlist_do_base_url(self):
        self.assertEqual(
            build_cardlist_url("https://onepiece-cardgame.kr/cardlist.do"),
            "https://onepiece-cardgame.kr/cardlist.do",
        )
        self.assertEqual(
            build_cardlist_url("https://onepiece-cardgame.kr/cardlist.do", series="569101"),
            "https://onepiece-cardgame.kr/cardlist.do?series=569101",
        )

    def test_parse_card_list_normalizes_modal_cards(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)

        self.assertEqual(len(cards), 2)

        ace = cards[0]
        self.assertEqual(ace.printing_id, "OP16-001_p1")
        self.assertEqual(ace.card_no, "OP16-001")
        self.assertEqual(ace.name, "Portgas.D.Ace")
        self.assertEqual(ace.rarity_code, "L")
        self.assertEqual(ace.card_type, "LEADER")
        self.assertIsNone(ace.cost)
        self.assertEqual(ace.life, 5)
        self.assertEqual(ace.attribute, "Special")
        self.assertEqual(ace.power, 5000)
        self.assertIsNone(ace.counter)
        self.assertEqual(ace.colors, ["Red", "Yellow"])
        self.assertEqual(ace.block_icon, "5")
        self.assertEqual(ace.traits, ["Whitebeard Pirates", "Straw Hat Crew"])
        self.assertEqual(ace.effect_text, "[Activate: Main] Example.\n[On Play] Next line.")
        self.assertIsNone(ace.trigger_text)
        self.assertEqual(ace.card_set_codes, ["OP-16"])
        self.assertTrue(ace.is_parallel)
        self.assertEqual(ace.detail_tags, ["PARALLEL"])
        self.assertEqual(ace.illustrators, [])
        self.assertEqual(
            ace.image_url,
            "https://en.onepiece-cardgame.com/images/cardlist/card/OP16-001_p1.png?260616",
        )

        kuma = cards[1]
        self.assertEqual(kuma.rarity_code, "SP_CARD")
        self.assertEqual(kuma.card_type, "CHARACTER")
        self.assertEqual(kuma.cost, 7)
        self.assertEqual(kuma.block_icon, "X")
        self.assertIsNone(kuma.effect_text)
        self.assertEqual(kuma.trigger_text, "[Trigger] Play this card.")
        self.assertEqual(kuma.card_set_codes, ["OP-16", "EB-01"])
        self.assertEqual(kuma.detail_tags, ["PARALLEL", "SP"])
        self.assertEqual(kuma.illustrators, [])

    def test_parse_card_list_supports_korean_card_items(self):
        cards = parse_card_list(
            KOREAN_CARD_LIST_HTML,
            source_url="https://onepiece-cardgame.kr/cardlist.do?series=%5BOPK-13%5D",
        )

        self.assertEqual(len(cards), 2)

        leader = cards[0]
        self.assertEqual(leader.printing_id, "OP13-001")
        self.assertEqual(leader.card_no, "OP13-001")
        self.assertEqual(leader.name, "몽키 D. 루피")
        self.assertEqual(leader.card_type, "LEADER")
        self.assertIsNone(leader.cost)
        self.assertEqual(leader.life, 4)
        self.assertEqual(leader.colors, ["적색", "녹색"])
        self.assertEqual(leader.traits, ["초신성", "밀짚모자 일당"])
        self.assertEqual(leader.attribute, "타격")
        self.assertEqual(leader.power, 5000)
        self.assertIsNone(leader.counter)
        self.assertEqual(leader.effect_text, "【두웅!!×1】효과 텍스트")
        self.assertIsNone(leader.trigger_text)
        self.assertEqual(leader.card_set_codes, ["OPK-13"])
        self.assertEqual(leader.card_sets, ["[OPK-13] 부스터 팩 계승되는 의지"])
        self.assertFalse(leader.is_parallel)
        self.assertEqual(leader.detail_tags, [])
        self.assertEqual(leader.illustrators, [])
        self.assertEqual(
            leader.image_url,
            "https://onepiece-cardgame.kr/fileDownload?downname=op13-001",
        )

        parallel = cards[1]
        self.assertEqual(parallel.printing_id, "OP13-001_P1")
        self.assertEqual(parallel.card_no, "OP13-001")
        self.assertEqual(parallel.card_type, "CHARACTER")
        self.assertEqual(parallel.cost, 1)
        self.assertIsNone(parallel.life)
        self.assertEqual(parallel.counter, 2000)
        self.assertEqual(parallel.trigger_text, "【트리거】파워 +3000.")
        self.assertTrue(parallel.is_parallel)
        self.assertEqual(parallel.detail_tags, ["PARALLEL"])
        self.assertEqual(parallel.illustrators, [])

    def test_write_jsonl_outputs_one_record_per_line(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "cards.jsonl"
            write_jsonl(cards, output_path)

            lines = output_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        first_record = json.loads(lines[0])
        self.assertEqual(first_record["card_no"], "OP16-001")
        self.assertEqual(first_record["source_url"], SOURCE_URL)

    def test_read_jsonl_restores_card_records(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "cards.jsonl"
            write_jsonl(cards, output_path)
            loaded_cards = read_jsonl(output_path)

        self.assertEqual(len(loaded_cards), 2)
        self.assertEqual(loaded_cards[0].printing_id, "OP16-001_p1")
        self.assertEqual(loaded_cards[1].rarity_code, "SP_CARD")

    def test_main_with_output_file_does_not_also_write_records_to_stdout(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.jsonl"
            output_path = Path(temp_dir) / "output.jsonl"
            write_jsonl(cards, input_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main(["--input-jsonl", str(input_path), "--output", str(output_path)])

            output_lines = output_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(output_lines), 2)
        self.assertEqual(stdout.getvalue(), "")

    def test_main_uploads_images_before_writing_output_file(self):
        cards = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.jsonl"
            output_path = Path(temp_dir) / "output.jsonl"
            write_jsonl(cards, input_path)

            def fake_upload(cards, storage, image_fetcher, key_prefix, timeout_seconds):
                self.assertEqual(key_prefix, "onepiece/jp/cards")
                self.assertEqual(timeout_seconds, 4.0)
                self.assertEqual(image_fetcher.keywords["max_attempts"], 9)
                self.assertEqual(image_fetcher.keywords["retry_delay_seconds"], 3.0)
                cards[0].image_url = "http://localhost:9000/tcg-search-local/onepiece/jp/cards/OP16-001_p1.png"
                return ImageUploadStats(total=2, uploaded=1, skipped=1)

            with mock.patch("onepiece_card_scraper.storage.upload_card_images", side_effect=fake_upload):
                exit_code = main(
                    [
                        "--input-jsonl",
                        str(input_path),
                        "--upload-images",
                        "--language-code",
                        "jp",
                        "--image-key-prefix",
                        "onepiece/{language_code}/cards",
                        "--timeout",
                        "4",
                        "--image-retry-attempts",
                        "9",
                        "--image-retry-delay",
                        "3",
                        "--output",
                        str(output_path),
                    ],
                )

            records = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            records[0]["image_url"],
            "http://localhost:9000/tcg-search-local/onepiece/jp/cards/OP16-001_p1.png",
        )

    def test_main_all_languages_runs_each_config_with_language_scoped_images_and_db_load(self):
        crawl_calls = []
        upload_prefixes = []
        db_loads = []
        cards_by_language = {
            "jp": parse_card_list(SINGLE_CARD_HTML, source_url="https://onepiece-cardgame.com/cardlist/"),
            "en": parse_card_list(SINGLE_CARD_HTML, source_url="https://en.onepiece-cardgame.com/cardlist/"),
            "ko": parse_card_list(SINGLE_CARD_HTML, source_url="https://onepiece-cardgame.kr/cardlist.do"),
        }

        def fake_crawl_all_series(base_url, timeout_seconds, fetcher):
            language_code = {
                "https://onepiece-cardgame.com": "jp",
                "https://en.onepiece-cardgame.com": "en",
                "https://onepiece-cardgame.kr/cardlist.do": "ko",
            }[base_url]
            crawl_calls.append((language_code, base_url, timeout_seconds))
            return cards_by_language[language_code]

        def fake_upload(cards, storage, image_fetcher, key_prefix, timeout_seconds):
            upload_prefixes.append(key_prefix)
            cards[0].image_url = f"http://localhost:9000/tcg-search-local/{key_prefix}/{cards[0].printing_id}.png"
            return ImageUploadStats(total=1, uploaded=1, skipped=0)

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        def fake_load(connection, cards, language_code, region_code):
            db_loads.append((language_code, region_code, cards[0].image_url))
            return mock.Mock(cards=1, printings=1)

        with (
            mock.patch("onepiece_card_scraper.scraper.crawl_all_series", side_effect=fake_crawl_all_series),
            mock.patch("onepiece_card_scraper.storage.upload_card_images", side_effect=fake_upload),
            mock.patch("onepiece_card_scraper.database.connect_database", return_value=FakeConnection()),
            mock.patch("onepiece_card_scraper.database.load_cards_to_database", side_effect=fake_load),
        ):
            exit_code = main(
                [
                    "--all-languages",
                    "--upload-images",
                    "--load-db",
                    "--timeout",
                    "4",
                    "--language-cooldown-seconds",
                    "0",
                ],
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            crawl_calls,
            [
                ("jp", "https://onepiece-cardgame.com", 4.0),
                ("en", "https://en.onepiece-cardgame.com", 4.0),
                ("ko", "https://onepiece-cardgame.kr/cardlist.do", 4.0),
            ],
        )
        self.assertEqual(upload_prefixes, ["onepiece/jp/cards", "onepiece/en/cards", "onepiece/ko/cards"])
        self.assertEqual(
            db_loads,
            [
                ("jp", None, "http://localhost:9000/tcg-search-local/onepiece/jp/cards/OP02-001.png"),
                ("en", None, "http://localhost:9000/tcg-search-local/onepiece/en/cards/OP02-001.png"),
                ("ko", None, "http://localhost:9000/tcg-search-local/onepiece/ko/cards/OP02-001.png"),
            ],
        )

    def test_resolve_ca_file_prefers_environment_path(self):
        with tempfile.NamedTemporaryFile() as ca_file:
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": ca_file.name}, clear=False):
                resolved = _resolve_ca_file(common_paths=())

        self.assertEqual(resolved, Path(ca_file.name))

    def test_main_file_runs_when_executed_directly(self):
        project_root = Path(__file__).resolve().parents[1]
        main_file = project_root / "src" / "onepiece_card_scraper" / "__main__.py"

        result = subprocess.run(
            [sys.executable, str(main_file), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Scrape ONE PIECE CARD GAME official card list pages.", result.stdout)


if __name__ == "__main__":
    unittest.main()
