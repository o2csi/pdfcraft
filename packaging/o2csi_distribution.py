#!/usr/bin/env python3
"""Check O2CSI source/assets and the two canonical distribution ZIPs. No extraction or publication."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib
from urllib.parse import quote
import zipfile

LABEL = "o2csi.1"
REPOSITORY = "o2csi/pdfcraft"
METADATA = "O2CSI-BUILD.json"
GH_API = ("gh", "api", "--hostname", "github.com", "--header", "X-GitHub-Api-Version: 2026-03-10")
BRAND_NAMES = frozenset(
    f"artcraft-{name}.{extension}"
    for name in ("logo", "logo-white", "mark", "mark-black")
    for extension in ("png", "svg")
)
# Original asset hashes at upstream commit 8f3a4f18bdffe6fcf2fce5d6f20bb0d9a6e91842.
# Keeping hashes identifies forbidden payloads without redistributing the marks as fixtures.
BRAND_HASHES = frozenset({
    "8b86aeb06a12a90ba77a60e0d90329272310e244ee5c1f9b161b391280ca79d8",
    "a3e03dc49f9ad4225b8517d5424309c8d1c864d3996d862190d9cc797d5af427",
    "08fc6d9d3717e8f13417bac6f9025b50e11d1e0b32e9e000883d2fe0c4a0c67b",
    "3188971e1affdf4f6be4fa65f715376a7a305e6aa741ec78b0296c8f934eff08",
    "5954cc0306e1b9d7beb47097e2e842157113a39d9aba078b57304902687936a9",
    "570adcb4f7ba8ca0647f97074476bab81d3272988f1cdee52efa21bf026036a4",
    "9d372157a949c147318561e629b11561c28b7cbc14c84b516a3fe6e84d8fbbad",
    "f87af81b6fa411da8820eed2bfdcc54c0ee9cd453b4e868c64f56c69db142d0e",
    "61731a921902e285d40826d401f1ef25624dabb8c8ac1f8f0c09c1292a17ee1a",
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(version, commit, platform):
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), "version must be major.minor.patch")
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "commit must be a full lowercase Git SHA")
    require(platform in ("web", "windows-x64"), "unsupported distribution platform")
    return {"schema": 1, "repository": REPOSITORY, "source_commit": commit,
            "package_version": version, "build_label": LABEL, "platform": platform,
            "version_transform": "cargo xtask version set", "unofficial": True}


def source_check(root):
    require((root / "Cargo.toml").is_file() and (root / "crates/ui-egui/src/widgets.rs").is_file(),
            "distribution source root is incomplete")
    remaining = sorted(str(p.relative_to(root)) for directory in (root / "docs/brand", root / "docs/images")
                       for p in directory.glob("*") if p.is_file() and
                       (p.name in BRAND_NAMES or hashlib.sha256(p.read_bytes()).hexdigest() in BRAND_HASHES))
    require(not remaining, "ArtCraft asset remains in distribution source: " + ", ".join(remaining))
    for path in (root / "crates/ui-egui/src").rglob("*.rs"):
        require(b"bytes://artcraft-" not in path.read_bytes(), f"ArtCraft image URI remains in {path}")


def checkout_check(root, version, commit):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()
    require(git("rev-parse", "HEAD") == commit, "metadata commit differs from checked-out HEAD")
    changes = set(filter(None, git("diff", "HEAD", "--name-only").splitlines()))
    require(changes <= {"Cargo.toml", "Cargo.lock"}, "checkout contains changes beyond the version transform")
    before = tomllib.loads(git("show", "HEAD:Cargo.toml"))
    after = tomllib.loads((root / "Cargo.toml").read_text())
    expected = copy.deepcopy(before)
    old = expected["workspace"]["package"]["version"]
    expected["workspace"]["package"]["version"] = version
    for value in expected["workspace"].get("dependencies", {}).values():
        if isinstance(value, dict) and "path" in value and value.get("version") == old:
            value["version"] = version
    require(after == expected, "manifest differs from the canonical workspace version transform")
    before_lock = tomllib.loads(git("show", "HEAD:Cargo.lock"))
    after_lock = tomllib.loads((root / "Cargo.lock").read_text())
    foreign = lambda lock: [p for p in lock["package"] if "source" in p]
    require(foreign(before_lock) == foreign(after_lock), "version transform changed registry or Git dependencies")
    require(os.environ.get("PDFCRAFT_BUILD_LABEL") == LABEL, "compile-time build label must be o2csi.1")
    require(os.environ.get("GITHUB_REPOSITORY", REPOSITORY) == REPOSITORY, "unexpected build repository")
    source_check(root)


def prefix_for(version, platform):
    return f"pdfcraft-web-{version}" if platform == "web" else f"pdfcraft-{version}-windows-x64-portable"


def archive_check(path, expected, metadata_required=True):
    prefix = prefix_for(expected["package_version"], expected["platform"])
    require(path.name == prefix + ".zip", "archive filename differs from its version/platform")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(names)), "duplicate ZIP entry")
        require(len(names) <= 4096 and sum(e.file_size for e in entries) <= 2 * 1024**3, "archive exceeds inspection limits")
        for entry in entries:
            parts = PurePosixPath(entry.filename).parts
            require(parts and parts[0] == prefix and ".." not in parts and "\\" not in entry.filename,
                    "archive has an unexpected root/path")
            require(entry.file_size <= 512 * 1024**2, "archive member exceeds inspection limit")
            require(PurePosixPath(entry.filename).name not in BRAND_NAMES, "ArtCraft asset in archive")
            if entry.is_dir():
                continue
            data = archive.read(entry)
            require(hashlib.sha256(data).hexdigest() not in BRAND_HASHES, "ArtCraft asset payload in archive")
            require(b"bytes://artcraft-" not in data, "ArtCraft image URI in archive payload")
        for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
            require(f"{prefix}/{name}" in names, f"missing required notice: {name}")
        if expected["platform"] == "web":
            require(f"{prefix}/index.html" in names, "web index missing")
            wasm = [n for n in names if n.endswith(".wasm")]
            require(len(wasm) == 1 and archive.read(wasm[0]).startswith(b"\x00asm\x01\x00\x00\x00"), "invalid/missing WASM module")
            require(any(n.endswith(".js") for n in names), "web JavaScript glue missing")
        else:
            for name in ("pdfcraft.exe", "pdfcraft-cli.exe"):
                require(f"{prefix}/{name}" in names and archive.read(f"{prefix}/{name}").startswith(b"MZ"), f"missing PE executable: {name}")
            require(f"{prefix}/portable.txt" in names, "portable mode marker missing")
        metadata_path = f"{prefix}/{METADATA}"
        if metadata_required:
            require(metadata_path in names, "O2CSI build metadata missing")
            require(json.loads(archive.read(metadata_path)) == expected, "O2CSI build metadata mismatch")
        else:
            require(metadata_path not in names, "archive is already stamped")


def stamp(path, expected):
    archive_check(path, expected, metadata_required=False)
    name = prefix_for(expected["package_version"], expected["platform"]) + "/" + METADATA
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, json.dumps(expected, sort_keys=True, indent=2) + "\n")
    archive_check(path, expected)


def checksums(web, windows, version, commit, output):
    for platform, path in (("web", web), ("windows-x64", windows)):
        archive_check(path, identity(version, commit, platform))
    lines = []
    for path in sorted((web, windows), key=lambda p: p.name):
        with path.open("rb") as source:
            lines.append(f"{hashlib.file_digest(source, 'sha256').hexdigest()}  {path.name}\n")
    with output.open("x", encoding="utf-8", newline="\n") as destination:
        destination.writelines(lines)


def release_number(value):
    require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value), "release ID must be a positive decimal integer")
    return int(value)


def parse_draft(payload, release_id, version, commit, complete=False):
    """Validate the release returned by GitHub before transferring any draft asset."""
    identity(version, commit, "web")
    number = release_number(release_id)
    value = json.loads(payload)
    require(isinstance(value, dict), "release response must be a JSON object")
    require(type(value.get("id")) is int and value["id"] == number, "release ID mismatch")
    require(value.get("draft") is True, "release must remain a draft")
    require(value.get("tag_name") == "v" + version, "draft tag differs from the requested version")
    require(value.get("target_commitish") == commit, "draft target must be the exact source commit SHA")
    allowed = {prefix_for(version, platform) + ".zip" for platform in ("web", "windows-x64")}
    assets = value.get("assets")
    require(isinstance(assets, list), "release assets must be a JSON array")
    result = {}
    for asset in assets:
        require(isinstance(asset, dict), "release asset must be a JSON object")
        name, asset_id = asset.get("name"), asset.get("id")
        require(isinstance(name, str) and name in allowed and name not in result, "unexpected or duplicate draft asset")
        require(type(asset_id) is int and asset_id > 0 and asset_id not in result.values(), "invalid or duplicate draft asset ID")
        require(asset.get("state") == "uploaded" or (not complete and asset.get("state") == "starter"),
                "draft asset has not finished uploading")
        result[name] = asset_id
    require(not complete or set(result) == allowed, "draft must contain exactly both canonical ZIP archives")
    return result


def _fetch_draft(release_id, version, commit, complete=False):
    number = release_number(release_id)
    payload = subprocess.check_output([*GH_API, f"repos/{REPOSITORY}/releases/{number}"], text=True)
    return parse_draft(payload, release_id, version, commit, complete)


def _upload_to_draft(path, release_id, version, commit, complete=False):
    assets = _fetch_draft(release_id, version, commit, complete)
    allowed = {"SHA256SUMS.txt"} if complete else {prefix_for(version, platform) + ".zip" for platform in ("web", "windows-x64")}
    require(path.name in allowed and path.name not in assets, "draft asset already exists or has an unexpected filename")
    endpoint = f"https://uploads.github.com/repos/{REPOSITORY}/releases/{release_number(release_id)}/assets?name={quote(path.name, safe='')}"
    subprocess.run([*GH_API, endpoint, "--method", "POST", "--header", "Content-Type: application/octet-stream",
                    "--header", f"Content-Length: {path.stat().st_size}", "--input", str(path)],
                   check=True, stdout=subprocess.DEVNULL)


def draft_upload(path, release_id, version, commit, platform):
    archive_check(path, identity(version, commit, platform))
    _upload_to_draft(path, release_id, version, commit)


def draft_complete(directory, release_id, version, commit):
    _fetch_draft(release_id, version, commit, complete=True)
    directory.mkdir(parents=True, exist_ok=True)
    require(not any(directory.iterdir()), "draft download directory must be empty")
    paths = {}
    for platform in ("web", "windows-x64"):
        name = prefix_for(version, platform) + ".zip"
        assets = _fetch_draft(release_id, version, commit, complete=True)
        path = directory / name
        with path.open("xb") as destination:
            subprocess.run([*GH_API, f"repos/{REPOSITORY}/releases/assets/{assets[name]}",
                            "--header", "Accept: application/octet-stream"], check=True, stdout=destination)
        archive_check(path, identity(version, commit, platform))
        paths[platform] = path
    output = directory / "SHA256SUMS.txt"
    checksums(paths["web"], paths["windows-x64"], version, commit, output)
    _upload_to_draft(output, release_id, version, commit, complete=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("source", "identity", "stamp", "verify", "checksums", "draft-upload", "draft-complete"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version")
    parser.add_argument("--commit")
    parser.add_argument("--platform", choices=("web", "windows-x64"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--web", type=Path)
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--release-id")
    args = parser.parse_args()
    if args.command == "source":
        source_check(args.root)
    elif args.command in ("draft-upload", "draft-complete"):
        release_number(args.release_id)
        identity(args.version or "", args.commit or "", args.platform or "web")
        if args.command == "draft-upload":
            require(args.archive and args.platform, "draft-upload requires --archive and --platform")
            draft_upload(args.archive, args.release_id, args.version, args.commit, args.platform)
        else:
            require(args.output, "draft-complete requires --output directory")
            draft_complete(args.output, args.release_id, args.version, args.commit)
    elif args.command == "identity":
        require(args.platform, "identity requires --platform")
        identity(args.version or "", args.commit or "", args.platform)
        actual = subprocess.check_output(["git", "-C", str(args.root), "rev-parse", "HEAD"], text=True).strip()
        require(actual == args.commit, "requested source commit differs from checked-out HEAD")
    elif args.command == "checksums":
        require(args.web and args.windows and args.output, "checksums requires --web, --windows and --output")
        identity(args.version or "", args.commit or "", "web")
        checksums(args.web, args.windows, args.version, args.commit, args.output)
    else:
        require(args.archive and args.platform, "archive command requires --archive and --platform")
        expected = identity(args.version or "", args.commit or "", args.platform)
        if args.command == "stamp":
            checkout_check(args.root, args.version, args.commit)
            stamp(args.archive, expected)
        else:
            archive_check(args.archive, expected)
    print(f"O2CSI distribution {args.command}: OK")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f"O2CSI distribution: {error}", file=sys.stderr)
        sys.exit(1)
