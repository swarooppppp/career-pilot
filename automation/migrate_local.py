#!/usr/bin/env python3
"""Private, checksum-verified SQLite + artifact migration. Never includes .env."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from local_career_portals.runtime_support import FileLock

DB_MEMBER = 'data/career_pilot.db'


@contextmanager
def connect(path):
    # sqlite3's transaction context alone does not close Windows file handles.
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection


def database_path(root):
    config = dotenv_values(root / '.env')
    url = make_url(os.getenv('DATABASE_URL') or config.get('DATABASE_URL') or 'sqlite:///data/career_pilot.db')
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        raise ValueError('Migration supports a local SQLite database only.')
    path = Path(url.database).expanduser()
    return path if path.is_absolute() else root / path


def require_stopped(root):
    config = dotenv_values(root / '.env')
    port = int(os.getenv('PORT') or config.get('PORT') or 8000)
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(('127.0.0.1', port)) == 0:
            raise ValueError('Stop the local app before backup/restore; its port is still open.')
    for name in ['data/portal_schedule.lock', 'data/windows-service.lock']:
        lock = FileLock(root / name)
        if not lock.acquire():
            raise ValueError('A local collection or server is still running.')
        lock.close()


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def database_summary(path):
    with connect(path) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {table: connection.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
        states = dict(connection.execute('SELECT user_status, COUNT(*) FROM jobs GROUP BY user_status'))
        return {'tables': counts, 'job_states': states}


def allowed_name(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name
            and name.startswith(('data/', 'generated/', 'local_career_portals/data/'))
            and not any(part.startswith('.') for part in path.parts)
            and not name.endswith(('.lock', '.tmp', '-wal', '-shm'))
            and not name.startswith(('data/backups/', 'data/logs/', 'data/windows-service.')))


def backup(root, output):
    require_stopped(root)
    db = database_path(root)
    if not db.is_file():
        raise ValueError('No database found. Check DATABASE_URL in .env.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('Backup output already exists; choose a new filename.')
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / 'snapshot.db'
        with connect(db) as source, connect(snapshot) as destination:
            source.backup(destination)
        manifest = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'summary': database_summary(snapshot), 'files': {}}
        partial = output.with_suffix(output.suffix + '.tmp')
        try:
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for folder in ['data', 'generated', 'local_career_portals/data']:
                    for path in sorted((root / folder).rglob('*')):
                        name = path.relative_to(root).as_posix()
                        if not path.is_file() or path.is_symlink() or path.resolve() == db.resolve() or not allowed_name(name):
                            continue
                        # Database files only come from SQLite's consistent backup API.
                        if path.suffix in {'.db', '.sqlite', '.sqlite3'}:
                            continue
                        archive.write(path, name)
                        manifest['files'][name] = digest(path)
                archive.write(snapshot, DB_MEMBER)
                manifest['files'][DB_MEMBER] = digest(snapshot)
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
            partial.replace(output)
            if os.name != 'nt':
                output.chmod(0o600)
        finally:
            partial.unlink(missing_ok=True)
    return manifest['summary']


def normalize_resume_paths(db):
    with connect(db) as connection:
        for ident, filename in connection.execute('SELECT id, resume_filename FROM jobs WHERE resume_filename IS NOT NULL').fetchall():
            normalized = filename.replace('\\', '/')
            marker = f'/generated/resumes/{ident}/'
            if marker in normalized:
                normalized = normalized.split(marker, 1)[1]
            if PurePosixPath(normalized).is_absolute() or ':' in normalized or '..' in PurePosixPath(normalized).parts:
                raise ValueError(f'Unsafe stored resume path for job {ident}')
            connection.execute('UPDATE jobs SET resume_filename=? WHERE id=?', (normalized, ident))


def restore(root, archive_path, replace=False):
    require_stopped(root)
    target_db = database_path(root)
    if target_db.exists() and not replace:
        raise ValueError('Database already exists. Use --replace only after making a backup.')
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len({name.casefold() for name in names}):
                raise ValueError('Duplicate archive members')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('version') != 1 or DB_MEMBER not in manifest.get('files', {}):
                raise ValueError('Unsupported or incomplete migration archive')
            if set(names) != set(manifest['files']) | {'manifest.json'}:
                raise ValueError('Archive contents do not match the manifest')
            for name, expected in manifest['files'].items():
                if not allowed_name(name):
                    raise ValueError('Unsafe archive member: ' + name)
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
                if digest(destination) != expected:
                    raise ValueError('Checksum mismatch: ' + name)
        db = stage / DB_MEMBER
        summary = database_summary(db)
        if summary != manifest['summary']:
            raise ValueError('Database counts do not match the manifest')
        normalize_resume_paths(db)
        # Validate all destination paths before touching the destination tree.
        for name in manifest['files']:
            target = target_db if name == DB_MEMBER else root / name
            if name != DB_MEMBER and not target.resolve().is_relative_to(root.resolve()):
                raise ValueError('Destination escapes repository')
            if target.exists() and name != DB_MEMBER and not replace and digest(target) != manifest['files'][name]:
                raise ValueError('Existing file differs: ' + name + '; restore into a fresh clone or use --replace.')
        # Install DB last: a failed artifact copy cannot expose a partially restored app DB.
        for name in manifest['files']:
            if name == DB_MEMBER:
                continue
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / name, target)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        if replace:
            for suffix in ['-wal', '-shm']:
                Path(str(target_db) + suffix).unlink(missing_ok=True)
        shutil.copy2(db, target_db.with_suffix('.restore.tmp'))
        target_db.with_suffix('.restore.tmp').replace(target_db)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('archive', type=Path)
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    try:
        result = backup(ROOT, args.archive.resolve()) if args.action == 'backup' else restore(ROOT, args.archive.resolve(), args.replace)
        print(json.dumps(result, indent=2))
        print('Done. .env is deliberately separate; transfer it privately.')
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
