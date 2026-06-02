#!/bin/sh
set -eu

export REDINK_TEXT_PROVIDERS_PATH="${REDINK_TEXT_PROVIDERS_PATH:-/app/config/text_providers.yaml}"
export REDINK_IMAGE_PROVIDERS_PATH="${REDINK_IMAGE_PROVIDERS_PATH:-/app/config/image_providers.yaml}"

seed_config() {
  src="$1"
  dest="$2"
  if [ -n "$dest" ] && [ ! -e "$dest" ]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
  fi
}

seed_config /app/default-config/text_providers.yaml "$REDINK_TEXT_PROVIDERS_PATH"
seed_config /app/default-config/image_providers.yaml "$REDINK_IMAGE_PROVIDERS_PATH"

exec "$@"
