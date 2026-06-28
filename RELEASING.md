# Releasing netdoctor

Cutting a release is a single tag push. The [`Release` workflow](.github/workflows/release.yml)
then publishes to **PyPI**, builds **standalone binaries** for every OS, and pushes a
**Docker image** to GHCR — all automatically.

## One-time setup: PyPI Trusted Publishing (no tokens)

This is the only manual step, and you only do it once.

1. Create a free account at <https://pypi.org>.
2. Open <https://pypi.org/manage/account/publishing/> and add a **pending publisher**:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `netdoctor` |
   | Owner | `Sahilll15` |
   | Repository name | `netdoctor` |
   | Workflow name | `release.yml` |
   | Environment | *(leave blank)* |

That's it — no API token ever lives in the repo. GitHub proves the workflow's identity to PyPI via OIDC.

## Cut a release

1. Bump the version in **`pyproject.toml`** and **`src/netdoctor/__init__.py`**.
2. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

The workflow then:

- 📦 builds + publishes the package to **PyPI** → `pipx install netdoctor`
- 💾 builds **single-file binaries** (macOS arm64/x86_64, Linux, Windows) and attaches them to the GitHub Release
- 🐳 builds + pushes the image to **`ghcr.io/sahilll15/netdoctor`**

## Finalize the Homebrew formula (after the release)

The brew formula references the binary checksums, which only exist once the release
artifacts are built. After the release finishes:

```bash
# from the netdoctor repo, with the tap checked out next to it
bash scripts/update-brew-formula.sh 0.1.0 ../homebrew-tap/Formula/netdoctor.rb
cd ../homebrew-tap && git commit -am "netdoctor 0.1.0" && git push
```

Then anyone can:

```bash
brew install Sahilll15/tap/netdoctor
```
