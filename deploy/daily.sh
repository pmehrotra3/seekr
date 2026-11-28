#!/bin/sh
# One day of crawling, then the fresh index goes live (about 10 seconds of downtime).
# Limits: MUSAFIR_NEW_PAGES_PER_DAY and MUSAFIR_RECRAWL_PER_DAY (see src/musafir/config.py).
# Run it from cron, e.g.:  17 3 * * *  /path/to/musafir/deploy/daily.sh > /path/to/musafir/data/daily.log 2>&1
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi  # local settings, e.g. MUSAFIR_ARCHIVE_DB on an external disk
# cron starts with almost no environment: find docker and talk to the daemon that runs the site
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
export MUSAFIR_MAX_PAGES_PER_DOMAIN="${MUSAFIR_MAX_PAGES_PER_DOMAIN:-20000}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"  # lets cron ask about user services
if systemctl --user is-active --quiet musafir-crawler 2>/dev/null; then
  export MUSAFIR_NEW_PAGES_PER_DAY=0  # the crawler service fetches new pages all day; this run indexes them
fi

# Only one refresh at a time: a second copy started meanwhile exits instead of clashing.
exec 9>data/daily.lock
if ! flock -n 9; then
  echo "another daily refresh is already running; exiting" >&2
  exit 0
fi

.venv/bin/musafir daily data/serve-next.db
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
