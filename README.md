# ONE PIECE CARD GAME card scraper

Standalone Python scraper for TCG Search batch jobs.

## PyCharm

Use this interpreter:

```text
/Users/kanghyeok/Projects/tcg-search/onepiece-card-scraper/.venv/bin/python
```

The local `.venv` is configured to include `src`, so PyCharm can import
`onepiece_card_scraper` without setting `PYTHONPATH` manually.

Official English card list page:

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --output /tmp/onepiece_cards.jsonl
```

All official Recording/series options:

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --output /tmp/onepiece_all_cards.jsonl
```

Scrape and load into the local TCG Search PostgreSQL database:

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --load-db
```

Scrape every official series and load into the local database:

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --load-db
```

Scrape every official series, upload card images to the local MinIO bucket, and
load DB rows with local bucket image URLs:

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --upload-images --load-db
```

Load an already scraped JSONL file into the local database:

```bash
.venv/bin/python -m onepiece_card_scraper --input-jsonl /tmp/onepiece_cards.jsonl --load-db
```

The default database URL is:

```text
postgresql://tcg_search:tcg_search@localhost:5432/tcg_search
```

Override it with `--database-url` or `TCG_SEARCH_DATABASE_URL`.

The default local object storage settings match `tcg-search-be/docker-compose.local.yml`:

```text
endpoint: http://localhost:9000
bucket: tcg-search-local
access key: tcg_search
secret key: tcg_search_minio
image key prefix: onepiece/cards
```

Override them with `--storage-endpoint-url`, `--storage-public-base-url`,
`--storage-bucket`, `--storage-access-key`, `--storage-secret-key`,
`--storage-region`, or `--image-key-prefix`.

Image downloads retry transient upstream failures by default. Tune them with
`--image-retry-attempts` and `--image-retry-delay` when the official image
server resets connections during large batches.

CSV output:

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --format csv --output /tmp/onepiece_cards.csv
```

Use an exact official card list URL when a regional site or custom filter is needed:

```bash
.venv/bin/python -m onepiece_card_scraper \
  --url 'https://en.onepiece-cardgame.com/cardlist/?series=569116' \
  --output /tmp/onepiece_cards.jsonl
```

After installing the project, the same scraper is available as:

```bash
onepiece-card-scraper --series 569116 --output /tmp/onepiece_cards.jsonl
```

The scraper outputs one record per printing. `card_no` is the game identity key,
while `printing_id`, `rarity_code`, `image_url`, and `is_parallel` describe the
printing.

Run tests:

```bash
.venv/bin/python -m unittest discover -s tests
```
