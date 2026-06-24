from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import mimetypes
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .scraper import OnePieceCardPrinting, USER_AGENT, _ssl_context


DEFAULT_STORAGE_ENDPOINT_URL = "http://localhost:9000"
DEFAULT_STORAGE_BUCKET = "tcg-search-local"
DEFAULT_STORAGE_ACCESS_KEY = "tcg_search"
DEFAULT_STORAGE_SECRET_KEY = "tcg_search_minio"
DEFAULT_STORAGE_REGION = "us-east-1"
DEFAULT_IMAGE_KEY_PREFIX = "onepiece/cards"
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


class ImageDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedImage:
    body: bytes
    content_type: str


@dataclass(frozen=True)
class ImageUploadStats:
    total: int = 0
    uploaded: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ObjectStorageConfig:
    endpoint_url: str = DEFAULT_STORAGE_ENDPOINT_URL
    bucket: str = DEFAULT_STORAGE_BUCKET
    access_key: str = DEFAULT_STORAGE_ACCESS_KEY
    secret_key: str = DEFAULT_STORAGE_SECRET_KEY
    region: str = DEFAULT_STORAGE_REGION
    public_base_url: str | None = None
    timeout_seconds: float = 20.0


class S3ObjectStorage:
    def __init__(self, config: ObjectStorageConfig, opener=urlopen, clock=None) -> None:
        self._config = config
        self._opener = opener
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        url = self._object_url(self._config.endpoint_url, key)
        now = self._clock()
        headers = self._signed_headers(
            method="PUT",
            url=url,
            body=body,
            content_type=content_type,
            now=now,
        )
        request = Request(url, data=body, headers=headers, method="PUT")
        with self._opener(request, timeout=self._config.timeout_seconds) as response:
            response.read()

    def public_url(self, key: str) -> str:
        return self._object_url(self._config.public_base_url or self._config.endpoint_url, key)

    def _object_url(self, base_url: str, key: str) -> str:
        base_url = base_url.rstrip("/")
        return f"{base_url}/{_quote_path_part(self._config.bucket)}/{_quote_key(key)}"

    def _signed_headers(
        self,
        method: str,
        url: str,
        body: bytes,
        content_type: str,
        now: datetime,
    ) -> dict[str, str]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        parsed_url = urlparse(url)
        payload_hash = hashlib.sha256(body).hexdigest()
        headers_to_sign = {
            "content-type": content_type,
            "host": parsed_url.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_header_names = sorted(headers_to_sign)
        canonical_headers = "".join(
            f"{name}:{_normalize_header_value(headers_to_sign[name])}\n"
            for name in signed_header_names
        )
        signed_headers = ";".join(signed_header_names)
        canonical_request = "\n".join(
            [
                method,
                parsed_url.path or "/",
                parsed_url.query,
                canonical_headers,
                signed_headers,
                payload_hash,
            ],
        )
        credential_scope = f"{date_stamp}/{self._config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ],
        )
        signature = hmac.new(
            _signing_key(
                secret_key=self._config.secret_key,
                date_stamp=date_stamp,
                region=self._config.region,
            ),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self._config.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": parsed_url.netloc,
            "X-Amz-Content-SHA256": payload_hash,
            "X-Amz-Date": amz_date,
        }


def fetch_image(
    url: str,
    timeout_seconds: float = 20.0,
    max_attempts: int = 6,
    retry_delay_seconds: float = 2.0,
    opener=urlopen,
    sleep=time.sleep,
) -> DownloadedImage:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout_seconds, context=_ssl_context()) as response:
                body = response.read()
                content_type = response.headers.get_content_type()
            if content_type == "text/plain":
                content_type = _guess_content_type(url)
            return DownloadedImage(body=body, content_type=content_type)
        except HTTPError as exc:
            if exc.code not in TRANSIENT_HTTP_STATUS_CODES or attempt == attempts:
                raise ImageDownloadError(
                    f"Failed to download image {url} after {attempt} attempts: {exc}",
                ) from exc
        except URLError as exc:
            if attempt == attempts:
                raise ImageDownloadError(
                    f"Failed to download image {url} after {attempt} attempts: {exc}",
                ) from exc

        sleep(retry_delay_seconds * (2 ** (attempt - 1)))

    raise AssertionError("unreachable")


def upload_card_images(
    cards: list[OnePieceCardPrinting],
    storage,
    image_fetcher=fetch_image,
    key_prefix: str = DEFAULT_IMAGE_KEY_PREFIX,
    timeout_seconds: float = 20.0,
) -> ImageUploadStats:
    uploaded = 0
    skipped = 0
    for card in cards:
        if not card.image_url:
            skipped += 1
            continue

        source_image_url = card.image_url
        image = image_fetcher(source_image_url, timeout_seconds)
        key = _object_key_for_card(card, source_image_url=source_image_url, key_prefix=key_prefix)
        storage.put_object(key, image.body, image.content_type)
        card.image_url = storage.public_url(key)
        uploaded += 1

    return ImageUploadStats(total=uploaded + skipped, uploaded=uploaded, skipped=skipped)


def _object_key_for_card(card: OnePieceCardPrinting, source_image_url: str, key_prefix: str) -> str:
    prefix = key_prefix.strip("/")
    suffix = _image_suffix(source_image_url)
    return f"{prefix}/{card.printing_id}{suffix}"


def _image_suffix(url: str) -> str:
    path = urlparse(url).path
    suffix = mimetypes.guess_extension(_guess_content_type(url)) or ""
    for candidate in (".png", ".jpg", ".jpeg", ".webp"):
        if path.lower().endswith(candidate):
            return candidate
    return suffix or ".png"


def _guess_content_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    return guessed or "application/octet-stream"


def _quote_key(key: str) -> str:
    return "/".join(_quote_path_part(part) for part in key.split("/"))


def _quote_path_part(value: str) -> str:
    return quote(value, safe="-_.~")


def _normalize_header_value(value: str) -> str:
    return " ".join(value.strip().split())


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    date_key = _hmac_sha256(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    date_region_key = _hmac_sha256(date_key, region)
    date_region_service_key = _hmac_sha256(date_region_key, "s3")
    return _hmac_sha256(date_region_service_key, "aws4_request")


def _hmac_sha256(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
