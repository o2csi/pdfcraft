"""Synthetic ZIP/metadata checks; real binaries and browser behavior are verified separately."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import o2csi_distribution as distribution

VERSION = "0.15.1"
COMMIT = "b" * 40


def fixture(directory, platform, extra=None):
    prefix = distribution.prefix_for(VERSION, platform)
    path = directory / (prefix + ".zip")
    entries = {"LICENSE-MIT": b"MIT", "LICENSE-APACHE": b"Apache", "NOTICE": b"Copyright ArtCraft Team and PdfCraft contributors."}
    if platform == "web":
        entries.update({"index.html": b"<title>PdfCraft O2CSI</title>", "app.js": b"", "app.wasm": b"\x00asm\x01\x00\x00\x00"})
    else:
        entries.update({"pdfcraft.exe": b"MZ", "pdfcraft-cli.exe": b"MZ", "portable.txt": b""})
    entries[distribution.METADATA] = json.dumps(distribution.identity(VERSION, COMMIT, platform)).encode()
    entries.update(extra or {})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(prefix + "/" + name, data)
    return path


class DistributionChecks(unittest.TestCase):
    def draft(self, assets=None, **changes):
        value = {"id": 123, "draft": True, "tag_name": "v" + VERSION,
                 "target_commitish": COMMIT, "assets": assets if assets is not None else []}
        value.update(changes)
        return json.dumps(value)

    def test_draft_metadata_accepts_only_the_requested_unpublished_commit(self):
        self.assertEqual(distribution.parse_draft(self.draft(), "123", VERSION, COMMIT), {})

    def test_partial_draft_allows_the_other_parallel_upload_to_be_in_progress(self):
        name = distribution.prefix_for(VERSION, "windows-x64") + ".zip"
        payload = self.draft([{"id": 10, "name": name, "state": "starter"}])
        self.assertEqual(distribution.parse_draft(payload, "123", VERSION, COMMIT), {name: 10})

    def test_draft_metadata_refuses_published_wrong_sha_tag_id_and_malformed_json(self):
        for payload in [self.draft(draft=False), self.draft(target_commitish="main"),
                        self.draft(target_commitish="c" * 40), self.draft(tag_name="v0.15.0"),
                        self.draft(id=124), self.draft(id=True), "[]", "{bad json"]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                distribution.parse_draft(payload, "123", VERSION, COMMIT)

    def test_complete_draft_requires_exactly_two_uploaded_canonical_archives(self):
        names = [distribution.prefix_for(VERSION, platform) + ".zip" for platform in ("web", "windows-x64")]
        assets = [{"id": index + 10, "name": name, "state": "uploaded"} for index, name in enumerate(names)]
        self.assertEqual(distribution.parse_draft(self.draft(assets), "123", VERSION, COMMIT, complete=True),
                         {asset["name"]: asset["id"] for asset in assets})
        for bad in [assets[:1], assets + [{"id": 12, "name": "SHA256SUMS.txt", "state": "uploaded"}],
                    [dict(assets[0], state="starter"), assets[1]], [assets[0], assets[0]]]:
            with self.subTest(assets=bad), self.assertRaises(ValueError):
                distribution.parse_draft(self.draft(bad), "123", VERSION, COMMIT, complete=True)

    def test_release_workflow_uses_draft_transport_and_canonical_builds(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text()
        self.assertNotIn("actions/upload-artifact@", workflow)
        self.assertNotIn("actions/download-artifact@", workflow)
        for literal in ("draft_release_id:", "draft-upload", "draft-complete", "needs: [web, windows]",
                        "packaging/web/package.sh", "./packaging/windows/package.ps1 -Arch x64 -PortableOnly"):
            self.assertIn(literal, workflow)

    def test_an_empty_directory_does_not_count_as_a_clean_distribution_source(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "source root is incomplete"):
                distribution.source_check(Path(temp))

    def test_distribution_source_has_no_original_mark_assets(self):
        distribution.source_check(Path(__file__).resolve().parents[1])

    def test_nonoriginal_pdfcraft_tools_payload_is_allowed_in_distribution_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "crates/ui-egui/src").mkdir(parents=True)
            (root / "docs/images").mkdir(parents=True)
            (root / "Cargo.toml").write_text("")
            (root / "crates/ui-egui/src/widgets.rs").write_text("")
            (root / "docs/images/pdfcraft-tools.png").write_bytes(b"O2CSI generated screenshot control")
            distribution.source_check(root)

    def test_nonoriginal_pdfcraft_tools_payload_is_allowed_in_a_valid_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            path = fixture(Path(temp), "web", {"pdfcraft-tools.png": b"O2CSI generated screenshot control"})
            distribution.archive_check(path, distribution.identity(VERSION, COMMIT, "web"))

    def test_two_validated_platforms_produce_exactly_two_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            web = fixture(directory, "web")
            windows = fixture(directory, "windows-x64")
            output = directory / "SHA256SUMS.txt"
            distribution.checksums(web, windows, VERSION, COMMIT, output)
            self.assertEqual(output.read_text().splitlines(), [
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in sorted((web, windows), key=lambda p: p.name)
            ])
            with self.assertRaises(FileExistsError):
                distribution.checksums(web, windows, VERSION, COMMIT, output)

    def test_mark_uri_is_refused_after_valid_metadata_and_binary_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = fixture(Path(temp), "web", {"app.wasm": b"\x00asm\x01\x00\x00\x00bytes://artcraft-mark.svg"})
            with self.assertRaisesRegex(ValueError, "ArtCraft image URI"):
                distribution.archive_check(path, distribution.identity(VERSION, COMMIT, "web"))

    def test_known_mark_filename_is_refused_even_with_valid_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = fixture(Path(temp), "windows-x64", {"artcraft-logo.svg": b"not a copied logo"})
            with self.assertRaisesRegex(ValueError, "ArtCraft asset"):
                distribution.archive_check(path, distribution.identity(VERSION, COMMIT, "windows-x64"))

    def test_wrong_platform_commit_prevents_checksum_file_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            web = fixture(directory, "web")
            metadata = distribution.identity(VERSION, "c" * 40, "windows-x64")
            windows = fixture(directory, "windows-x64", {distribution.METADATA: json.dumps(metadata).encode()})
            output = directory / "SHA256SUMS.txt"
            with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                distribution.checksums(web, windows, VERSION, COMMIT, output)
            self.assertFalse(output.exists())

    def test_missing_windows_archive_prevents_checksum_file_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            web = fixture(directory, "web")
            output = directory / "SHA256SUMS.txt"
            with self.assertRaises(FileNotFoundError):
                missing = directory / (distribution.prefix_for(VERSION, "windows-x64") + ".zip")
                distribution.checksums(web, missing, VERSION, COMMIT, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
