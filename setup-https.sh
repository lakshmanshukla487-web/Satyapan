#!/usr/bin/env bash
# setup-https.sh – Generate a locally trusted TLS certificate for LAN HTTPS development.
#
# Requirements: mkcert (https://github.com/FiloSottile/mkcert)
#   macOS (Homebrew): brew install mkcert
#   Or download the binary: https://github.com/FiloSottile/mkcert/releases
#
# Run once per machine. Re-run after changing your LAN IP.
set -e
cd "$(dirname "$0")"

LAN_IP="192.168.18.117"

# ── 1. Locate mkcert ──────────────────────────────────────────────────────────
MKCERT=$(command -v mkcert 2>/dev/null || echo "")
if [ -z "$MKCERT" ] && [ -x /tmp/mkcert ]; then
  MKCERT=/tmp/mkcert
fi
if [ -z "$MKCERT" ]; then
  echo ""
  echo "mkcert not found. Install it first:"
  echo "  macOS (Homebrew): brew install mkcert"
  echo "  or download from: https://github.com/FiloSottile/mkcert/releases"
  echo "  and place the binary at /usr/local/bin/mkcert"
  exit 1
fi

# ── 2. Install the local CA into macOS Keychain (requires sudo / password) ───
echo ""
echo "Installing the local CA into your system trust store."
echo "You may be prompted for your system password."
"$MKCERT" -install

# ── 3. Generate the certificate ───────────────────────────────────────────────
CERT_DIR="frontend/certs"
mkdir -p "$CERT_DIR"
"$MKCERT" -cert-file "$CERT_DIR/lan.crt" -key-file "$CERT_DIR/lan.key" \
  "$LAN_IP" localhost 127.0.0.1

# Copy the root CA certificate so it can be transferred to test devices
CAROOT=$("$MKCERT" -CAROOT)
cp "$CAROOT/rootCA.pem" "$CERT_DIR/rootCA.pem"

echo ""
echo "✅  Certificate written to $CERT_DIR/lan.crt"
echo "    Private key at $CERT_DIR/lan.key  (never commit this file)"
echo "    CA cert at $CERT_DIR/rootCA.pem   (install this on test devices)"
echo ""
echo "Next: restart the app with ./start.sh"
echo "Then open: https://${LAN_IP}:5173 on this machine and other LAN devices."
echo ""
echo "To trust the certificate on test devices, see README.md § HTTPS / LAN setup."
