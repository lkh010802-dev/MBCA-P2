import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import download_popup_json

from tests.test_popup_service import make_popup


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
    def paths(self, directory):
        output = Path(directory)
        return {
            "OUTPUT_DIR": output,
            "POPUP_DATA_PATH": output / "popup_places.json",
            "POPUP_BACKUP_PATH": output / "popup_places_backup.json",
        }

    def content(self, **overrides):
        return json.dumps(
            [make_popup(**overrides)],
            ensure_ascii=False,
        ).encode()

    def test_normal_download_creates_operating_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            download_popup_json,
            **self.paths(directory),
        ), patch(
            "download_popup_json.urlopen",
            return_value=FakeResponse(self.content()),
        ):
            target, count = download_popup_json.download_today("secret")

            self.assertEqual(target, Path(directory) / "popup_places.json")
            self.assertEqual(count, 1)
            self.assertTrue(target.exists())
            self.assertFalse(
                (Path(directory) / "popup_places_backup.json").exists()
            )

    def test_replacement_keeps_previous_valid_file_as_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory)
            paths["POPUP_DATA_PATH"].write_bytes(self.content(name="이전 팝업"))

            with patch.multiple(download_popup_json, **paths), patch(
                "download_popup_json.urlopen",
                return_value=FakeResponse(self.content(name="새 팝업")),
            ):
                download_popup_json.download_today("secret")

            current = json.loads(paths["POPUP_DATA_PATH"].read_text("utf-8"))
            backup = json.loads(paths["POPUP_BACKUP_PATH"].read_text("utf-8"))

        self.assertEqual(current[0]["name"], "새 팝업")
        self.assertEqual(backup[0]["name"], "이전 팝업")

    def test_download_failure_preserves_operating_and_backup_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.paths(directory)
            paths["POPUP_DATA_PATH"].write_bytes(self.content(name="운영 팝업"))
            paths["POPUP_BACKUP_PATH"].write_bytes(self.content(name="백업 팝업"))
            before_current = paths["POPUP_DATA_PATH"].read_bytes()
            before_backup = paths["POPUP_BACKUP_PATH"].read_bytes()

            with patch.multiple(download_popup_json, **paths), patch(
                "download_popup_json.urlopen",
                side_effect=URLError("offline"),
            ), self.assertRaises(URLError):
                download_popup_json.download_today("secret")

            self.assertEqual(paths["POPUP_DATA_PATH"].read_bytes(), before_current)
            self.assertEqual(paths["POPUP_BACKUP_PATH"].read_bytes(), before_backup)

    def test_invalid_downloads_preserve_existing_files(self):
        invalid_contents = (
            b"{broken",
            b"[]",
            json.dumps([{"name": "invalid"}]).encode(),
        )

        for content in invalid_contents:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                paths = self.paths(directory)
                paths["POPUP_DATA_PATH"].write_bytes(self.content(name="운영 팝업"))
                paths["POPUP_BACKUP_PATH"].write_bytes(self.content(name="백업 팝업"))
                before_current = paths["POPUP_DATA_PATH"].read_bytes()
                before_backup = paths["POPUP_BACKUP_PATH"].read_bytes()

                with patch.multiple(download_popup_json, **paths), patch(
                    "download_popup_json.urlopen",
                    return_value=FakeResponse(content),
                ), self.assertRaises((ValueError, json.JSONDecodeError)):
                    download_popup_json.download_today("secret")

                self.assertEqual(
                    paths["POPUP_DATA_PATH"].read_bytes(),
                    before_current,
                )
                self.assertEqual(
                    paths["POPUP_BACKUP_PATH"].read_bytes(),
                    before_backup,
                )

    def test_invalid_rows_are_skipped_when_one_record_is_normalizable(self):
        content = json.dumps(
            [{"name": "invalid"}, make_popup(name="정상 팝업")],
            ensure_ascii=False,
        ).encode()

        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            download_popup_json,
            **self.paths(directory),
        ), patch(
            "download_popup_json.urlopen",
            return_value=FakeResponse(content),
        ):
            target, count = download_popup_json.download_today("secret")
            self.assertTrue(target.exists())

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
