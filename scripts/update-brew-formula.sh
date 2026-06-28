#!/usr/bin/env bash
# Fill the sha256 checksums + version in the Homebrew formula after a release.
#
#   usage: scripts/update-brew-formula.sh <version> <path-to-netdoctor.rb>
#   e.g.   scripts/update-brew-formula.sh 0.1.0 ../homebrew-tap/Formula/netdoctor.rb
set -euo pipefail

VERSION="${1:?usage: update-brew-formula.sh <version> <formula.rb>}"
FORMULA="${2:?usage: update-brew-formula.sh <version> <formula.rb>}"
REPO="Sahilll15/netdoctor"
BASE="https://github.com/${REPO}/releases/download/v${VERSION}"

# placeholder-key -> release asset name
assets=(
  "macos_arm64:netdoctor-macos-arm64"
  "macos_x86_64:netdoctor-macos-x86_64"
  "linux_x86_64:netdoctor-linux-x86_64"
)

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for pair in "${assets[@]}"; do
  key="${pair%%:*}"; asset="${pair#*:}"
  echo "→ ${asset}"
  curl -fsSL "${BASE}/${asset}" -o "${tmp}/${asset}"
  sum="$(sha256 "${tmp}/${asset}")"
  sed -i.bak "s|REPLACE_WITH_${key}_SHA|${sum}|g" "$FORMULA"
done

sed -i.bak "s|version \"[^\"]*\"|version \"${VERSION}\"|g" "$FORMULA"
rm -f "${FORMULA}.bak"
echo "✓ updated ${FORMULA} for v${VERSION}"
