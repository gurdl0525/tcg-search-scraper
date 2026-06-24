from datetime import datetime, timezone
from io import BytesIO
import unittest
from urllib.error import HTTPError

from onepiece_card_scraper.scraper import parse_card_list
from onepiece_card_scraper.storage import (
    DownloadedImage,
    ImageDownloadError,
    ObjectStorageConfig,
    S3ObjectStorage,
    fetch_image,
    upload_card_images,
)
from tests.test_scraper import SAMPLE_HTML, SOURCE_URL


class FakeStorage:
    def __init__(self):
        self.uploads = []

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        self.uploads.append((key, body, content_type))

    def public_url(self, key: str) -> str:
        return f"http://localhost:9000/tcg-search-local/{key}"


class FakeResponse:
    headers = None

    def __init__(self, body: bytes = b"", content_type: str = "image/png"):
        self._body = body
        self.headers = FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class FakeHeaders:
    def __init__(self, content_type: str):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class StorageTests(unittest.TestCase):
    def test_fetch_image_retries_transient_http_errors(self):
        calls = []

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
            return FakeResponse(body=b"image-bytes", content_type="image/png")

        image = fetch_image(
            "https://example.com/card.png",
            timeout_seconds=3.0,
            opener=fake_opener,
            sleep=lambda seconds: None,
        )

        self.assertEqual(image.body, b"image-bytes")
        self.assertEqual(image.content_type, "image/png")
        self.assertEqual(calls, ["https://example.com/card.png", "https://example.com/card.png"])

    def test_fetch_image_reports_url_after_retry_exhaustion(self):
        calls = []
        sleeps = []

        def fake_opener(request, timeout, context):
            calls.append(request.full_url)
            raise HTTPError(
                request.full_url,
                502,
                "Bad Gateway",
                hdrs=None,
                fp=BytesIO(b"bad gateway"),
            )

        with self.assertRaisesRegex(
            ImageDownloadError,
            "https://example.com/card.png.*after 6 attempts.*HTTP Error 502",
        ):
            fetch_image(
                "https://example.com/card.png",
                opener=fake_opener,
                sleep=sleeps.append,
            )

        self.assertEqual(len(calls), 6)
        self.assertEqual(sleeps, [2.0, 4.0, 8.0, 16.0, 32.0])

    def test_upload_card_images_uploads_original_image_and_rewrites_card_url(self):
        card = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)[0]
        storage = FakeStorage()

        def fake_fetcher(url, timeout_seconds):
            self.assertEqual(url, "https://en.onepiece-cardgame.com/images/cardlist/card/OP16-001_p1.png?260616")
            self.assertEqual(timeout_seconds, 7.0)
            return DownloadedImage(body=b"image-bytes", content_type="image/png")

        stats = upload_card_images(
            [card],
            storage=storage,
            image_fetcher=fake_fetcher,
            timeout_seconds=7.0,
        )

        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.uploaded, 1)
        self.assertEqual(stats.skipped, 0)
        self.assertEqual(
            storage.uploads,
            [("onepiece/cards/OP16-001_p1.png", b"image-bytes", "image/png")],
        )
        self.assertEqual(
            card.image_url,
            "http://localhost:9000/tcg-search-local/onepiece/cards/OP16-001_p1.png",
        )

    def test_upload_card_images_skips_cards_without_image_url(self):
        card = parse_card_list(SAMPLE_HTML, source_url=SOURCE_URL)[0]
        card.image_url = None
        storage = FakeStorage()

        stats = upload_card_images([card], storage=storage)

        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.uploaded, 0)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(storage.uploads, [])

    def test_s3_object_storage_put_object_signs_path_style_put_request(self):
        requests = []
        config = ObjectStorageConfig(
            endpoint_url="http://localhost:9000",
            bucket="tcg-search-local",
            access_key="tcg_search",
            secret_key="tcg_search_minio",
            region="us-east-1",
        )

        def fake_opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        storage = S3ObjectStorage(
            config,
            opener=fake_opener,
            clock=lambda: datetime(2026, 6, 23, 1, 2, 3, tzinfo=timezone.utc),
        )

        storage.put_object("onepiece/cards/OP16-001_p1.png", b"abc", "image/png")

        request, timeout = requests[0]
        headers = dict(request.header_items())
        self.assertEqual(request.full_url, "http://localhost:9000/tcg-search-local/onepiece/cards/OP16-001_p1.png")
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.data, b"abc")
        self.assertEqual(timeout, 20.0)
        self.assertEqual(headers["Content-type"], "image/png")
        self.assertEqual(headers["X-amz-date"], "20260623T010203Z")
        self.assertEqual(
            headers["X-amz-content-sha256"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertIn("AWS4-HMAC-SHA256 Credential=tcg_search/20260623/us-east-1/s3/aws4_request", headers["Authorization"])

    def test_s3_object_storage_uses_endpoint_for_put_and_public_base_for_saved_url(self):
        requests = []
        config = ObjectStorageConfig(
            endpoint_url="http://minio:9000",
            public_base_url="http://localhost:9000",
            bucket="tcg-search-local",
            access_key="tcg_search",
            secret_key="tcg_search_minio",
        )

        def fake_opener(request, timeout):
            requests.append(request)
            return FakeResponse()

        storage = S3ObjectStorage(config, opener=fake_opener)

        storage.put_object("onepiece/cards/OP16-001_p1.png", b"abc", "image/png")

        self.assertEqual(requests[0].full_url, "http://minio:9000/tcg-search-local/onepiece/cards/OP16-001_p1.png")
        self.assertEqual(
            storage.public_url("onepiece/cards/OP16-001_p1.png"),
            "http://localhost:9000/tcg-search-local/onepiece/cards/OP16-001_p1.png",
        )


if __name__ == "__main__":
    unittest.main()
