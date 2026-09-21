import json
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import download_popup_json

from tests.test_popup_service import make_popup


KST = timezone(timedelta(hours=9))


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.content


class DownloadPopupJsonTests(unittest.TestCase):
    def content(self, **overrides):
        return json.dumps(
            [make_popup(**overrides)],
            ensure_ascii=False,
        ).encode()

    def test_normal_download_creates_dated_file(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "download_popup_json.OUTPUT_DIR",
            Path(directory),
        ), patch(
            "download_popup_json.datetime"
        ) as mock_datetime, patch(
            "download_popup_json.urlopen",
            return_value=FakeResponse(self.content()),
        ):
            mock_datetime.now.return_value = datetime(
                2026,
                9,
                21,
                9,
                0,
                tzinfo=KST,
            )

            target, count = download_popup_json.download_today("secret")

            self.assertEqual(
                target,
                Path(directory) / "20260921_popup_places.json",
            )
            self.assertEqual(count, 1)
            self.assertTrue(target.exists())

    def test_existing_same_day_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            target = output_dir / "20260921_popup_places.json"
            target.write_bytes(self.content(name="이전 팝업"))

            with patch(
                "download_popup_json.OUTPUT_DIR",
                output_dir,
            ), patch(
                "download_popup_json.datetime"
            ) as mock_datetime, patch(
                "download_popup_json.urlopen",
                return_value=FakeResponse(self.content(name="새 팝업")),
            ):
                mock_datetime.now.return_value = datetime(
                    2026,
                    9,
                    21,
                    9,
                    0,
                    tzinfo=KST,
                )

                returned_target, count = (
                    download_popup_json.download_today("secret")
                )

            data = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(returned_target, target)
        self.assertEqual(count, 1)
        self.assertEqual(data[0]["name"], "새 팝업")

    def test_download_failure_preserves_existing_dated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            target = output_dir / "20260921_popup_places.json"
            target.write_bytes(self.content(name="기존 팝업"))
            before = target.read_bytes()

            with patch(
                "download_popup_json.OUTPUT_DIR",
                output_dir,
            ), patch(
                "download_popup_json.datetime"
            ) as mock_datetime, patch(
                "download_popup_json.urlopen",
                side_effect=URLError("offline"),
            ), self.assertRaises(URLError):
                mock_datetime.now.return_value = datetime(
                    2026,
                    9,
                    21,
                    9,
                    0,
                    tzinfo=KST,
                )

                download_popup_json.download_today("secret")

            self.assertEqual(target.read_bytes(), before)

    def test_invalid_downloads_preserve_existing_dated_file(self):
        invalid_contents = (
            b"{broken",
            b"[]",
            json.dumps([{"name": "invalid"}]).encode(),
        )

        for content in invalid_contents:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                output_dir = Path(directory)
                target = output_dir / "20260921_popup_places.json"
                target.write_bytes(self.content(name="기존 팝업"))
                before = target.read_bytes()

                with patch(
                    "download_popup_json.OUTPUT_DIR",
                    output_dir,
                ), patch(
                    "download_popup_json.datetime"
                ) as mock_datetime, patch(
                    "download_popup_json.urlopen",
                    return_value=FakeResponse(content),
                ), self.assertRaises((ValueError, json.JSONDecodeError)):
                    mock_datetime.now.return_value = datetime(
                        2026,
                        9,
                        21,
                        9,
                        0,
                        tzinfo=KST,
                    )

                    download_popup_json.download_today("secret")

                self.assertEqual(target.read_bytes(), before)

    def test_invalid_rows_are_allowed_when_one_record_is_normalizable(self):
        content = json.dumps(
            [
                {"name": "invalid"},
                make_popup(name="정상 팝업"),
            ],
            ensure_ascii=False,
        ).encode()

        with tempfile.TemporaryDirectory() as directory, patch(
            "download_popup_json.OUTPUT_DIR",
            Path(directory),
        ), patch(
            "download_popup_json.datetime"
        ) as mock_datetime, patch(
            "download_popup_json.urlopen",
            return_value=FakeResponse(content),
        ):
            mock_datetime.now.return_value = datetime(
                2026,
                9,
                21,
                9,
                0,
                tzinfo=KST,
            )

            target, count = download_popup_json.download_today("secret")

            self.assertTrue(target.exists())

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()