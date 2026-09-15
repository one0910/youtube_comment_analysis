"""Back up local Compose PostgreSQL; optionally restore into a NEW verification DB."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def normalize_columns(rows):
    """Ignore dropped-column number gaps, but preserve live column order."""
    positions = {}
    normalized = []
    for row in rows:
        table = row[0]
        positions[table] = positions.get(table, 0) + 1
        normalized.append((*row[:6], positions[table], *row[7:]))
    return normalized


def fingerprint(conn):
    """Compare every public table row, column, constraint, index and sequence."""
    result = {}
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
        for (table,) in tables:
            # Hash each canonical JSON row; retain duplicates; independent of row order.
            hashes = []
            with conn.cursor(name='backup_rows') as cursor:
                cursor.execute(sql.SQL('SELECT row_to_json(t) FROM {} AS t').format(sql.Identifier('public', table)))
                for (row,) in cursor:
                    value = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                    hashes.append(hashlib.sha256(value.encode('utf-8')).hexdigest())
            result[table] = {'count': len(hashes), 'sha256': hashlib.sha256(''.join(sorted(hashes)).encode()).hexdigest()}
        # DROP COLUMN leaves ordinal gaps in the source; pg_dump/restore removes
        # those gaps. Compare logical positions instead of historical slot IDs.
        result['_columns'] = normalize_columns(conn.execute("SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,ordinal_position,is_identity,identity_generation FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position").fetchall())
        result['_constraints'] = conn.execute("SELECT c.relname,k.conname,pg_get_constraintdef(k.oid),k.convalidated FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,k.conname").fetchall()
        result['_indexes'] = conn.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname").fetchall()
        result['_sequences'] = []
        for (name,) in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall():
            value = conn.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier('public', name))).fetchone()
            result['_sequences'].append((name, *value))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Restore to a unique NEW database and compare; leave it available for inspection.')
    args = parser.parse_args()
    config = {**dotenv_values(ROOT / '.env.postgres'), **os.environ}
    user = config.get('POSTGRES_USER', 'admin')
    database = config.get('POSTGRES_DB', 'tubesense')
    # This tool intentionally targets this project's local Compose service only.
    host = config.get('POSTGRES_HOST', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('This tool only supports the local Compose PostgreSQL host.')
    options = dict(host=host, port=config.get('POSTGRES_PORT', '5432'), user=user,
                   password=config['POSTGRES_PASSWORD'], connect_timeout=10, autocommit=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
    folder = ROOT / 'backups' / 'postgres' / stamp
    folder.mkdir(parents=True, exist_ok=False)
    archive = folder / 'tubesense.dump'
    docker = ['docker', 'compose', 'exec', '-T', 'postgres']
    with psycopg.connect(dbname=database, **options) as source:
        before = fingerprint(source)
        # Binary output goes directly to disk, never through PowerShell text redirection.
        with archive.open('xb') as output:
            subprocess.run(docker + ['pg_dump', '-U', user, '-d', database, '-Fc'],
                           cwd=ROOT, stdout=output, check=True)
        after = fingerprint(source)
        if before != after:
            raise RuntimeError('Source changed during backup; pause writers and retry. Archive retained but NOT verified.')
        with archive.open('rb') as archive_file:
            archive_hash = hashlib.file_digest(archive_file, 'sha256').hexdigest()
        manifest = {'source_database': database, 'created_utc': stamp,
                    'archive_sha256': archive_hash,
                    'source_version': source.execute('SHOW server_version').fetchone()[0],
                    'fingerprint': before, 'verified': False}
        manifest_path = folder / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Backup:', archive, flush=True)
        if args.verify:
            target = 'tubesense_restore_check_' + stamp.lower()
            # CREATE DATABASE fails on a collision; never reuse or overwrite an existing DB.
            source.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
            manifest['verification_database'] = target
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Restoring into NEW database:', target, flush=True)
            with archive.open('rb') as input_file:
                subprocess.run(docker + ['pg_restore', '-U', user, '-d', target, '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges'],
                               cwd=ROOT, stdin=input_file, check=True)
            with psycopg.connect(dbname=target, **options) as restored:
                actual = fingerprint(restored)
            if actual != before:
                raise RuntimeError('Restore differs from source: ' + repr([key for key in before if before[key] != actual.get(key)]))
            if fingerprint(source) != before:
                raise RuntimeError('Source changed during verification; retry with writers paused.')
            manifest['verified'] = True
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            print('PASS: all rows, columns, constraints, indexes and sequence values match.')
            print('Verification database retained; original database untouched.')
        print('Table counts:', json.dumps({key: value['count'] for key, value in before.items() if not key.startswith('_')}))
        print('Manifest:', manifest_path)


if __name__ == '__main__':
    main()
