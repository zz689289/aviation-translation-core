"""Checkpoint an ordered PDF translation inventory in atomic, idempotent batches.

This ledger verifies coverage and bound inputs. A committed translation is not a
semantic, visual, or release approval. Run with --help for command arguments.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing, contextmanager
from pathlib import Path

from common import sha256_file


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def read_inventory(path, page_count):
    rows = []
    pages = set()
    ids = set()
    previous = 0
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if not all(nonempty(row.get(k)) for k in ('id', 'source', 'role')):
                raise ValueError('Inventory entry requires id, source and role, including non-text objects')
            page, key = row['page'], row['id']
            if type(page) != int or not 1 <= page <= page_count or page < previous or key in ids:
                raise ValueError(f'Invalid order, page or duplicate id: {key}')
            rows.append(row)
            previous = page
            ids.add(key)
            pages.add(page)
    if pages != set(range(1, page_count + 1)):
        raise ValueError('Missing source page; record an actual blank or graphical page explicitly')
    return rows


def source_bindings(args):
    return {k: {'path': str(getattr(args, k).resolve(strict=True)), 'sha256': sha256_file(getattr(args, k))}
            for k in ('pdf', 'inventory', 'settings')}


def initialize(db, args):
    import pymupdf
    if args.pages_per_batch < 1:
        raise ValueError('pages-per-batch must be positive')
    bindings = source_bindings(args)
    if not isinstance(json.loads(args.settings.read_text(encoding='utf-8-sig')), dict):
        raise ValueError('Settings must be a JSON object')
    with pymupdf.open(args.pdf) as doc:
        if not doc.is_pdf or not len(doc):
            raise ValueError('Expected a readable nonempty PDF')
        count = len(doc)
    rows = read_inventory(args.inventory, count)
    descriptor = {'schema': 1, 'inputs': bindings, 'pages': count, 'pages_per_batch': args.pages_per_batch}
    key = hashlib.sha256(encode(descriptor).encode()).hexdigest()
    with transaction(db):
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if names and 'job' not in names:
            raise ValueError('Destination contains an unrelated database')
        db.execute('CREATE TABLE IF NOT EXISTS job (singleton INTEGER PRIMARY KEY CHECK(singleton=1), data TEXT, key TEXT)')
        existing = db.execute('SELECT key FROM job').fetchone()
        if existing:
            if existing[0] != key:
                raise ValueError('Job exists with different inputs or batch settings')
            return
        db.execute('CREATE TABLE units (seq INTEGER PRIMARY KEY, batch INTEGER, id TEXT UNIQUE, source TEXT)')
        db.execute('CREATE INDEX units_by_batch ON units(batch,seq)')
        db.execute('CREATE TABLE receipts (batch INTEGER PRIMARY KEY, data TEXT NOT NULL)')
        db.executemany('INSERT INTO units(seq,batch,id,source) VALUES(?,?,?,?)',
                       ((i, (row['page']-1)//args.pages_per_batch+1, row['id'], encode(row)) for i,row in enumerate(rows)))
        if source_bindings(args) != bindings:
            raise ValueError('Inputs changed while importing')
        db.execute('INSERT INTO job VALUES(1,?,?)', (encode(descriptor),key))


def check_bindings(db):
    job, key = db.execute('SELECT data,key FROM job WHERE singleton=1').fetchone()
    config = json.loads(job)
    for name, item in config['inputs'].items():
        if sha256_file(Path(item['path'])) != item['sha256']:
            raise ValueError(f'{name} has changed since initialization; restore inputs or initialize a new job')
    return config,key


def pending(db):
    return db.execute('SELECT min(batch) FROM units WHERE batch NOT IN (SELECT batch FROM receipts)').fetchone()[0]


def state(db):
    total, batches = db.execute('SELECT count(*),count(DISTINCT batch) FROM units').fetchone()
    done, = db.execute('SELECT count(*) FROM receipts').fetchone()
    return {'status': 'CONTENT_ASSEMBLED' if done == batches else 'IN_PROGRESS', 'units': total,
            'batches': batches, 'committed': done, 'next_batch': pending(db), 'release_qa': 'SEPARATE'}


def next_batch(db, key):
    batch = pending(db)
    if batch is None:
        return state(db)
    entries = db.execute('SELECT seq,source FROM units WHERE batch=? ORDER BY seq',(batch,)).fetchall()
    def neighbor(seq):
        other = db.execute('SELECT source FROM units WHERE seq=?',(seq,)).fetchone()
        return json.loads(other[0]) if other else None
    return {'job':key, 'batch':batch, 'units':[json.loads(r[1]) for r in entries],
            'preceding':neighbor(entries[0][0]-1), 'following':neighbor(entries[-1][0]+1)}


def commit(db, key, receipt):
    batch = receipt.get('batch')
    if receipt.get('job') != key or type(batch) != int:
        raise ValueError('Wrong job or batch')
    with transaction(db):
        ordered = [r[0] for r in db.execute('SELECT id FROM units WHERE batch=? ORDER BY seq',(batch,))]
        results = receipt['results']
        if not ordered or not isinstance(results,list) or [r.get('id') for r in results] != ordered:
            raise ValueError('Missing, reordered, foreign or duplicate result')
        for r in results:
            if r.get('action') not in ('translated','preserved') or not nonempty(r.get('target')):
                raise ValueError('Each result needs an action and target text or object locator')
            if r['action']=='preserved' and not nonempty(r.get('basis')):
                raise ValueError('Preserved object needs a source-based justification')
        raw = encode(receipt)
        old = db.execute('SELECT data FROM receipts WHERE batch=?',(batch,)).fetchone()
        if old:
            if raw != old[0]:
                raise ValueError('Conflicting retry; use a new revision for changed translations')
            return
        if batch != pending(db):
            raise ValueError('Commit the next open batch in sequence')
        db.execute('INSERT INTO receipts VALUES(?,?)',(batch,raw))


def write_new(path, text):
    # Publish only complete output. Hard-link creation also refuses concurrent overwrite.
    import os
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=path.parent,delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.link(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def run(args):
    paths = [p.resolve() for p in vars(args).values() if isinstance(p,Path)]
    if len(paths)!=len(set(paths)):
        raise ValueError('Input and output paths must be distinct')
    create = args.command=='init'
    if create:
        args.db.parent.mkdir(exist_ok=True,parents=True)
    elif not args.db.is_file():
        raise ValueError('Missing job database')
    dbfile = args.db.resolve()
    uri = dbfile.as_uri() + ('?mode=rwc' if create else '?mode=rw')
    with closing(sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)) as db:
        if create:
            initialize(db,args)
        config,key = check_bindings(db)
        if args.command=='commit':
            commit(db,key,json.loads(args.input.read_text(encoding='utf-8-sig')))
        if args.command=='export':
            if pending(db) is not None:
                raise ValueError('Incomplete content; resume the next open batch')
            def exported():
                for (raw,) in db.execute('SELECT data FROM receipts ORDER BY batch'):
                    for row in json.loads(raw)['results']:
                        yield encode(row) + '\n'
            write_new(args.output,''.join(exported()))
        elif args.command=='next':
            write_new(args.output, json.dumps(next_batch(db,key),ensure_ascii=False,indent=2)+'\n')
        return {'job':key,'pages':config['pages'],**state(db)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest='command',required=True)
    for name in ('init','next','commit','status','export'):
        child=cmd.add_parser(name)
        child.add_argument('--db',type=Path,required=True)
        if name=='init':
            for flag in ('pdf','inventory','settings'):
                child.add_argument('--'+flag,type=Path,required=True)
            child.add_argument('--pages-per-batch',type=int,default=8)
        if name in ('next','export'):
            child.add_argument('--output',type=Path,required=True)
        if name=='commit':
            child.add_argument('--input',type=Path,required=True)
    try:
        print(encode(run(parser.parse_args())))
    except (KeyError,ValueError,TypeError,OSError,sqlite3.Error) as exc:
        sys.exit(f'Invalid translation job: {exc}')


if __name__=='__main__':
    main()
