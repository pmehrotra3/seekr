#!/bin/sh
# One day of crawling, then the fresh index goes live (about 10 seconds of downtime).
# Limits: SEEKR_NEW_PAGES_PER_DAY and SEEKR_RECRAWL_PER_DAY (see src/seekr/config.py).
# Run it from cron, e.g.:  17 3 * * *  /path/to/seekr/deploy/daily.sh > /path/to/seekr/data/daily.log 2>&1
set -eu
cd "$(dirname "$0")/.."
export SEEKR_MAX_PAGES_PER_DOMAIN="${SEEKR_MAX_PAGES_PER_DOMAIN:-20000}"

.venv/bin/seekr daily data/serve-next.db
if [ -s data/serve-next.db-wal ]; then  # the export did not close cleanly: keep serving the old index
  echo "data/serve-next.db is incomplete; not swapping" >&2
  exit 1
fi

docker compose stop
for suffix in "" .ids.npy .vectors.npy; do
  mv "data/serve-next.db$suffix" "data/serve.db$suffix"
done
rm -f data/serve.db-wal data/serve.db-shm  # belonged to the old index; the server closed it cleanly
docker compose up -d
echo "daily refresh done: $(date)"
