#!/bin/sh
# Use a PostgreSQL backup role via PGHOST/PGUSER/PGDATABASE and .pgpass.
# No credentials are accepted as command-line arguments or printed.
set -eu
umask 077
backup_dir=${1:?Usage: backup_product_master.sh /absolute/backup/directory}
case "$backup_dir" in /*) ;; *) echo 'Backup directory must be absolute' >&2; exit 1;; esac
mkdir -p "$backup_dir"
backup_file="$backup_dir/product-master-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --file="$backup_file" --table='public.pm_*'
pg_restore --list "$backup_file" >/dev/null
printf '%s\n' "$backup_file"
