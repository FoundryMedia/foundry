#!/bin/sh
# Foundry CLI installer for macOS (Apple Silicon).
#
#   curl -fsSL https://raw.githubusercontent.com/FoundryMedia/foundry/release/cli/package/install.sh | sh
#
# Installs the latest GitHub release to ~/.foundry/cli/<version> and links
# ~/.foundry/bin/foundry. Re-run any time to update (the CLI's update banner
# will tell you when a new version ships).
#
# Env overrides:
#   FOUNDRY_INSTALL_DIR   install root (default ~/.foundry)
#   FOUNDRY_VERSION       install a specific version tag (e.g. v0.10.0)
set -eu

REPO="FoundryMedia/foundry"
INSTALL_ROOT="${FOUNDRY_INSTALL_DIR:-$HOME/.foundry}"
BIN_DIR="$INSTALL_ROOT/bin"

fail() { printf 'install.sh: %s\n' "$1" >&2; exit 1; }

# ── Platform check ──────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
[ "$OS" = "Darwin" ] || fail "this installer is for macOS (got $OS). On Windows use the .exe installer from https://github.com/$REPO/releases/latest"
[ "$ARCH" = "arm64" ] || fail "only Apple Silicon (arm64) builds are published (got $ARCH). Open an issue if you need an Intel build."

command -v curl >/dev/null 2>&1 || fail "curl is required"

# ── Resolve release ─────────────────────────────────────────────
if [ -n "${FOUNDRY_VERSION:-}" ]; then
  TAG="$FOUNDRY_VERSION"
else
  TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/^ *"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
  [ -n "$TAG" ] || fail "could not resolve the latest release tag"
fi
VERSION="${TAG#v}"

ASSET="foundrycli-$VERSION-macos-arm64.tar.gz"
URL="https://github.com/$REPO/releases/download/$TAG/$ASSET"

printf 'Installing Foundry CLI %s ...\n' "$VERSION"

# ── Download + verify ───────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fSL --progress-bar -o "$TMP/$ASSET" "$URL" \
  || fail "download failed: $URL (release $TAG may predate macOS builds)"

if curl -fsSL -o "$TMP/$ASSET.sha256" "$URL.sha256" 2>/dev/null; then
  EXPECTED="$(awk '{print $1}' "$TMP/$ASSET.sha256")"
  ACTUAL="$(shasum -a 256 "$TMP/$ASSET" | awk '{print $1}')"
  [ "$EXPECTED" = "$ACTUAL" ] || fail "checksum mismatch for $ASSET"
else
  printf 'warning: no checksum file published for %s — skipping verification\n' "$ASSET" >&2
fi

# ── Install ─────────────────────────────────────────────────────
DEST="$INSTALL_ROOT/cli/$VERSION"
rm -rf "$DEST"
mkdir -p "$DEST" "$BIN_DIR"
tar -xzf "$TMP/$ASSET" -C "$DEST"

# The archive holds the PyInstaller onedir contents (foundry + _internal/).
[ -x "$DEST/foundry" ] || fail "extracted archive is missing the foundry binary"
ln -sf "$DEST/foundry" "$BIN_DIR/foundry"

printf 'Installed to %s\n' "$DEST"

# ── PATH hint ───────────────────────────────────────────────────
case ":$PATH:" in
  *":$BIN_DIR:"*)
    printf 'Done. Run: foundry --help\n'
    ;;
  *)
    printf '\nAdd Foundry to your PATH (then restart your shell):\n'
    printf '  echo '\''export PATH="$HOME/.foundry/bin:$PATH"'\'' >> ~/.zshrc\n'
    printf '\nThen run: foundry --help\n'
    ;;
esac
