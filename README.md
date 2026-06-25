# ONE PIECE CARD GAME 카드 스크래퍼

TCG Search 배치 작업에서 사용할 독립 Python 스크래퍼입니다.

## 기본 실행

특정 공식 시리즈만 JSONL로 저장합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --output /tmp/onepiece_cards.jsonl
```

공식 사이트의 모든 Recording/시리즈 옵션을 순회해서 JSONL로 저장합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --output /tmp/onepiece_all_cards.jsonl
```

특정 시리즈를 크롤링한 뒤 로컬 PostgreSQL DB에 적재합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --load-db
```

모든 시리즈를 크롤링한 뒤 로컬 DB에 적재합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --load-db
```

모든 시리즈를 크롤링하고, 카드 이미지를 로컬 MinIO 버킷에 업로드한 뒤,
로컬 버킷 이미지 URL로 DB에 적재합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --all-series --upload-images --load-db
```

## 일판/영판/한글판 한 번에 실행

일본어, 영어, 한국어 공식 카드 리스트를 한 번에 순회하고, 누락된 이미지를
업로드한 뒤 DB에 적재합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --all-languages --upload-images --load-db
```

기본 순서는 `jp,en,ko`입니다. 순서를 바꾸거나 일부 언어만 실행하려면
`--languages`를 사용합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --all-languages --languages ko,en --upload-images --load-db
```

언어별 공식 카드 리스트 진입점은 아래와 같습니다.

```text
jp: https://onepiece-cardgame.com/cardlist/
en: https://en.onepiece-cardgame.com/cardlist/
ko: https://onepiece-cardgame.kr/cardlist.do
```

이미지 키 기본 prefix는 `onepiece/{language_code}/cards`입니다. 따라서 같은
`printing_id`가 있어도 언어별로 아래처럼 분리되어 충돌하지 않습니다.

```text
onepiece/jp/cards/...
onepiece/en/cards/...
onepiece/ko/cards/...
```

## 재시도 및 요청 차단 대응 옵션

카드 목록 HTML 요청은 `429`, `500`, `502`, `503`, `504` 같은 일시적
실패에 대해 exponential backoff와 jitter로 재시도합니다.

```bash
.venv/bin/python -m onepiece_card_scraper \
  --all-languages \
  --upload-images \
  --load-db \
  --request-retry-attempts 8 \
  --request-retry-delay 3 \
  --request-retry-jitter 0.25 \
  --language-cooldown-seconds 10
```

| 옵션 | 기본값 | 설명 |
| --- | ---: | --- |
| `--request-retry-attempts` | `6` | 카드 목록 HTML 요청 재시도 횟수 |
| `--request-retry-delay` | `2.0` | 첫 재시도 대기 시간(초). 이후 exponential backoff 적용 |
| `--request-retry-jitter` | `0.25` | 재시도 대기 시간에 더하는 jitter 비율 |
| `--language-cooldown-seconds` | `5.0` | `--all-languages` 실행 시 언어 배치 사이 대기 시간(초) |
| `--image-retry-attempts` | `6` | 이미지 다운로드 재시도 횟수 |
| `--image-retry-delay` | `2.0` | 이미지 다운로드 첫 재시도 대기 시간(초) |

요청 차단이 자주 발생하면 아래처럼 보수적으로 실행합니다.

```bash
.venv/bin/python -m onepiece_card_scraper \
  --all-languages \
  --upload-images \
  --load-db \
  --request-retry-attempts 10 \
  --request-retry-delay 5 \
  --language-cooldown-seconds 20 \
  --image-retry-attempts 10 \
  --image-retry-delay 5
```

## 이미 크롤링한 항목 스킵 방식

DB 적재는 upsert 방식이라 같은 카드를 다시 실행해도 중복 insert 대신 기존
row를 갱신합니다.

이미지는 업로드 전에 대상 object가 버킷에 이미 있는지 확인합니다.

- 버킷 object가 이미 있으면 이미지 다운로드와 PUT 업로드를 스킵합니다.
- 이 경우에도 카드의 `image_url`은 로컬 버킷 URL로 다시 세팅됩니다.
- DB에는 row가 있지만 버킷 object가 없는 경우에는 이미지를 다시 다운로드하고 업로드합니다.
- 따라서 이전 실행에서 DB insert만 되고 이미지 업로드가 실패한 항목도 다음 실행에서 보정됩니다.
- 특정 이미지가 재시도 횟수를 모두 소진해도 전체 배치는 중단하지 않습니다.
- 실패한 이미지는 `failed` 개수로 출력되고, 해당 카드는 기존 공식 이미지 URL을 유지합니다.
- 다음 실행에서 같은 카드 이미지를 다시 다운로드하고 버킷 업로드를 재시도합니다.

## DB 옵션

기본 DB URL은 아래 값입니다.

```text
postgresql://tcg_search:tcg_search@localhost:5432/tcg_search
```

다른 DB를 쓰려면 `--database-url` 또는 `TCG_SEARCH_DATABASE_URL`을 사용합니다.

```bash
.venv/bin/python -m onepiece_card_scraper \
  --all-languages \
  --upload-images \
  --load-db \
  --database-url postgresql://tcg_search:tcg_search@localhost:5432/tcg_search
```

이미 크롤링해 둔 JSONL 파일을 DB에 적재할 수도 있습니다.

```bash
.venv/bin/python -m onepiece_card_scraper --input-jsonl /tmp/onepiece_cards.jsonl --load-db
```

## 로컬 버킷 옵션

기본 로컬 object storage 설정은 `tcg-search-be/docker-compose.local.yml`과
맞춥니다.

```text
endpoint: http://localhost:9000
bucket: tcg-search-local
access key: tcg_search
secret key: tcg_search_minio
image key prefix: onepiece/{language_code}/cards
```

필요하면 아래 옵션으로 바꿀 수 있습니다.

| 옵션 | 설명 |
| --- | --- |
| `--storage-endpoint-url` | S3 호환 object storage endpoint |
| `--storage-public-base-url` | DB에 저장할 public base URL. 생략하면 endpoint URL 사용 |
| `--storage-bucket` | 이미지 저장 버킷 |
| `--storage-access-key` | S3 access key |
| `--storage-secret-key` | S3 secret key |
| `--storage-region` | S3 signing region |
| `--image-key-prefix` | 이미지 object key prefix |

예시:

```bash
.venv/bin/python -m onepiece_card_scraper \
  --all-languages \
  --upload-images \
  --load-db \
  --storage-endpoint-url http://localhost:9000 \
  --storage-public-base-url http://localhost:9000 \
  --storage-bucket tcg-search-local \
  --image-key-prefix 'onepiece/{language_code}/cards'
```

## 출력 옵션

CSV로 저장합니다.

```bash
.venv/bin/python -m onepiece_card_scraper --series 569116 --format csv --output /tmp/onepiece_cards.csv
```

지역 사이트나 직접 필터링한 공식 URL을 그대로 사용할 수 있습니다.

```bash
.venv/bin/python -m onepiece_card_scraper \
  --url 'https://en.onepiece-cardgame.com/cardlist/?series=569116' \
  --output /tmp/onepiece_cards.jsonl
```

프로젝트를 설치한 뒤에는 console script로도 실행할 수 있습니다.

```bash
onepiece-card-scraper --series 569116 --output /tmp/onepiece_cards.jsonl
```

스크래퍼는 printing 단위로 한 줄씩 출력합니다. `card_no`는 게임 카드
identity 키이고, `printing_id`, `rarity_code`, `image_url`, `is_parallel`은
printing 정보를 나타냅니다.

## 테스트

```bash
.venv/bin/python -m unittest discover -s tests
```
