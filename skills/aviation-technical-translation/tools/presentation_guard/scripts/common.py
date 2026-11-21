"""Shared helpers for Aviation Translation Core. No environment discovery or reduced validator fallback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

class Invalid(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()

def no_links(path):
    p = Path(os.path.abspath(path))
    for part in [*reversed(p.parents), p]:
        if part.exists() or part.is_symlink():
            s = part.lstat()
            if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 1024:
                raise Invalid('LINK_REJECTED')
    return p

class Store:
    def __init__(self, root):
        self.root = no_links(root)
        if not self.root.is_dir(): raise Invalid('ROOT_REQUIRED')
        self.inputs = set()
        self.observed = {}

    def path(self, value):
        if not isinstance(value, str) or not value or '\\' in value or ':' in value:
            raise Invalid('PATH_INVALID')
        rel = Path(value)
        if rel.is_absolute() or '..' in rel.parts or value.startswith('/'):
            raise Invalid('PATH_ESCAPE')
        p = no_links(self.root / rel)
        if not p.is_relative_to(self.root): raise Invalid('PATH_ESCAPE')
        return p

    def read(self, value, expected=None):
        p = self.path(value)
        if not p.is_file() or p.stat().st_size > 16 * 1024 * 1024:
            raise Invalid('INPUT_MISSING_OR_TOO_LARGE')
        data = p.read_bytes()
        h = digest(data)
        if expected is not None and expected != h: raise Invalid('HASH_DRIFT')
        self.inputs.add(p)
        self.observed[p] = h
        return data

    def json(self, value, expected=None):
        try: return json.loads(self.read(value, expected).decode('utf-8-sig'))
        except (UnicodeError, json.JSONDecodeError): raise Invalid('JSON_INVALID') from None

    def recheck(self):
        for p, h in self.observed.items():
            no_links(p)
            if not p.is_file() or digest(p.read_bytes()) != h: raise Invalid('INPUT_CHANGED_DURING_CHECK')

    def write(self, value, data):
        p = self.path(value)
        if p in self.inputs: raise Invalid('INPUT_OUTPUT_COLLISION')
        if p.exists(): raise Invalid('OUTPUT_EXISTS')
        # An existing real directory is required; no path creation through links.
        if not p.parent.is_dir(): raise Invalid('OUTPUT_PARENT_REQUIRED')
        self.recheck()
        raw = (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode()
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError: raise Invalid('OUTPUT_EXISTS') from None
        with os.fdopen(fd, 'wb') as f: f.write(raw)

def validate(value, name):
    try:
        from jsonschema import Draft202012Validator
    except ImportError: raise Invalid('DEPENDENCY_JSONSCHEMA_MISSING') from None
    p = no_links(Path(__file__).resolve().parents[1] / 'schemas' / name)
    schema = json.loads(p.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    if any(Draft202012Validator(schema).iter_errors(value)):
        raise Invalid('SCHEMA_INVALID')

def summary(kind, failures=(), **counts):
    return dict(check=kind, mechanical_status='FAIL' if failures else 'PASS',
                errors=sorted(set(failures)), counts=counts,
                semantic_qa='NOT_PERFORMED', host_qa='INDEPENDENT_QA_UNAVAILABLE',
                human_approved=False, released=False, completion='BLOCKED_PENDING_REAL_QA')

class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"status":"INVALID","code":"ARGUMENTS_INVALID"}\n')

def cli(operation, workflow=False):
    p=SafeParser(description='Local mechanical evidence checker; no semantic approval.')
    if workflow: p.add_argument('command', choices=['snapshot','verify-snapshot','route','cache','coverage','scope'])
    p.add_argument('--root', required=True)
    p.add_argument('--spec', required=True)
    p.add_argument('--output', required=True)
    a=p.parse_args()
    try:
        store=Store(a.root)
        spec=store.json(a.spec)
        value=operation(store,spec,a.command) if workflow else operation(store,spec)
        store.write(a.output,value)
        print(json.dumps({'mechanical_status':value['mechanical_status'], 'completion':value['completion']}))
        return 0 if value['mechanical_status']=='PASS' else 1
    except Invalid as e:
        print(json.dumps({'status':'INVALID','code':e.code}),file=sys.stderr); return 2
    except Exception:
        # No exception message, path, input content or library traceback is shareable.
        print('{"status":"INVALID","code":"INTERNAL_OR_INPUT_ERROR"}',file=sys.stderr); return 2
