# PdfCraft O2CSI

This repository prepares independent O2CSI builds based on [PdfCraft](https://github.com/storytold/pdfcraft) by the ArtCraft team and contributors. O2CSI maintains these modified builds; they are not official ArtCraft releases.

The application keeps PdfCraft's local PDF workflow. Our distribution removes the ArtCraft logos and wordmark, retains the original copyrights and third-party notices, and identifies itself as an O2CSI build in Home and About.

## Build web and Windows x64

The manual **O2CSI web and Windows builds** workflow creates:

- `pdfcraft-web-<version>.zip` on `ubuntu-latest`;
- `pdfcraft-<version>-windows-x64-portable.zip` on `windows-latest`;
- `SHA256SUMS.txt` only after both archives pass their checks.

Both builds check out the same full commit, apply the canonical `cargo xtask version set <version>` transformation, and compile with `PDFCRAFT_BUILD_LABEL=o2csi.1`. Each archive contains `O2CSI-BUILD.json` recording that source commit, requested package version, transformation, label and platform. Registry and Git dependency entries in the lockfile must remain unchanged.

The workflow uses standard public GitHub runners. It does not run macOS, larger runners, Linux desktop, x86, ARM or FreeBSD builds. It stores build outputs as assets of an existing draft release, without Actions artifacts. Rust caches use GitHub's default repository allowance. The workflow does not create or publish a release, create a tag, push a commit or deploy to Cloudflare.

Before dispatch, manually create a new draft release in `o2csi/pdfcraft` with tag `v<version>` and `target_commitish` set to the exact 40-character source commit SHA. Supply its numeric release ID as `draft_release_id` and run the workflow on that same commit. The shared packaging tool verifies the ID, unpublished status, tag and SHA from GitHub's API before every transfer. Each build uploads only its own canonical ZIP. The final job requires exactly both ZIPs, downloads them by asset ID, verifies their contents and metadata, and adds `SHA256SUMS.txt`.

Transfers use the runner's GitHub CLI and ephemeral `GITHUB_TOKEN`, supplied only as `GH_TOKEN` to the transfer steps. No additional token or service is needed. Existing assets are never overwritten. After an interrupted or failed upload, leave the incomplete draft unpublished and create a fresh draft for a rerun; the workflow does not delete or replace its assets. A failed build changes no active version. Publish the complete draft separately after checking the workflow, both builds and their checksums.

Use a new numeric version for each published O2CSI build. Never move an existing tag or replace its archives. Verify both archives and their checksums before a separate manual publication. A source synchronization does not publish or deploy anything.

## Local reproduction

Use the Rust version and pinned tools declared in the workflow. Web builds need `wasm32-unknown-unknown`, Trunk and Binaryen. The workflow checks out the same pinned `storytold/craft-fonts` revision for both platforms; preserve that input and its licence notices when reproducing a release.

Build in a clean disposable checkout so the version transformation does not alter a contribution branch:

```sh
cargo xtask version set 0.15.1
export PDFCRAFT_VERSION=0.15.1 PDFCRAFT_BUILD_LABEL=o2csi.1
packaging/web/package.sh
python3 packaging/o2csi_distribution.py stamp --platform web \
  --version 0.15.1 --commit "$(git rev-parse HEAD)" \
  --archive dist/release/pdfcraft-web-0.15.1.zip
```

On Windows, after the same version transformation and with `PDFCRAFT_BUILD_LABEL=o2csi.1` set:

```powershell
./packaging/windows/package.ps1 -Arch x64 -PortableOnly
python packaging/o2csi_distribution.py stamp --platform windows-x64 `
  --version 0.15.1 --commit (git rev-parse HEAD) `
  --archive dist/release/pdfcraft-0.15.1-windows-x64-portable.zip
```

The portable archive includes the application, CLI, OCR models, font notices and `portable.txt`. It does not install an MSI or reuse the official installer's registration/upgrade identity. Unless a separate O2CSI signing configuration is supplied, these Windows binaries are unsigned. The default packaging script invocation still builds the upstream MSI and portable ZIP; the O2CSI workflow deliberately uses `-PortableOnly`.

**Help ▸ Check for updates…** opens O2CSI's GitHub releases in the browser on desktop and web. Download and replace the Windows portable build manually. PdfCraft does not check for releases at startup or download, install or restart itself for updates. Unsaved documents stay open when the release page opens.

## Verification and hosting

Run `python3 -m unittest discover -s packaging -p test_o2csi_distribution.py` and `python3 packaging/o2csi_distribution.py source`. The packaging checks reject the known original mark assets and their image URIs, while allowing required copyrights and plain-text attribution. They inspect ZIP structure and metadata; real browser editing/export and native Windows execution still require their platform checks.

For web MIME, HTTPS and cache requirements, see [the hosting guide](packaging/web/README.md). Use the existing private Craft publisher for deployment; this public repository does not contain Cloudflare credentials.

## Upstream and licences

Contributions to PdfCraft's engine remain separate from O2CSI packaging and branding. See the [upstream contribution instructions](https://github.com/storytold/pdfcraft/blob/main/CLAUDE.md), [licences](LICENSE-MIT), [Apache licence](LICENSE-APACHE), and [required notices](NOTICE). ArtCraft's [trademark terms](docs/brand/LICENSE-brand.txt) remain available as legal text; their logos are not included in this distribution.
