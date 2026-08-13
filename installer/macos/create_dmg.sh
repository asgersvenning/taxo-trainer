#!/usr/bin/env bash
# macOS DMG Packaging Script for Taxo-Trainer
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
APP_DIR="${DIST_DIR}/taxo-trainer"
DMG_NAME="TaxoTrainer-macOS.dmg"
OUTPUT_DMG="${DIST_DIR}/${DMG_NAME}"
TMP_DMG_DIR="${DIST_DIR}/dmg_tmp"

echo "🍏 Packaging Taxo-Trainer for macOS distribution..."

if [ ! -d "${APP_DIR}" ]; then
    echo "❌ Error: Compiled directory bundle at ${APP_DIR} does not exist!"
    exit 1
fi

rm -rf "${TMP_DMG_DIR}" "${OUTPUT_DMG}"
mkdir -p "${TMP_DMG_DIR}"

echo "Copying application bundle..."
cp -R "${APP_DIR}" "${TMP_DMG_DIR}/Taxo-Trainer"
ln -s /Applications "${TMP_DMG_DIR}/Applications"

if command -v create-dmg &> /dev/null; then
    echo "Creating DMG using create-dmg utility..."
    create-dmg \
        --volname "Taxo-Trainer Installation" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --app-drop-link 450 180 \
        "${OUTPUT_DMG}" \
        "${TMP_DMG_DIR}"
else
    echo "Creating standard DMG image using hdiutil..."
    hdiutil create -volname "Taxo-Trainer" -srcfolder "${TMP_DMG_DIR}" -ov -format UDZO "${OUTPUT_DMG}"
fi

rm -rf "${TMP_DMG_DIR}"
echo "✅ macOS disk image created at ${OUTPUT_DMG}"
