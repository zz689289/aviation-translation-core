"""Compare scoped presentation evidence, not PDF semantics or native clipboard behavior.

Profiles are supplied by an independent source measurement and an output measurement.
The checker binds their artifacts and evidence bytes; it does not authenticate who
measured them. P6 RGB crops and raw UTF-8 probes are compared without normalization.
"""
import math
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Invalid, cli, summary, validate


def read_ref(store, ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise Invalid('PRESENTATION_REFERENCE_INVALID')
    if not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256']):
        raise Invalid('PRESENTATION_HASH_INVALID')
    return store.read(ref['path'], ref['sha256'])


def rgb_crop(data):
    """Read an 8-bit binary PPM (P6). Do not discard whitespace-valued pixels."""
    pos = 0
    tokens = []
    for _ in range(4):
        match = re.match(rb'(?:\s+|\#[^\r\n]*(?:\r?\n|$))*([^\s#]+)', data[pos:])
        if match is None:
            raise Invalid('RGB_CROP_INVALID')
        tokens.append(match[1])
        pos += match.end()
    try:
        width, height, maximum = map(int, tokens[1:])
    except ValueError:
        raise Invalid('RGB_CROP_INVALID') from None
    if tokens[0] != b'P6' or maximum != 255 or not (0 < width <= 100000 and 0 < height <= 100000):
        raise Invalid('RGB_CROP_INVALID')
    if data[pos:pos+2] == b'\r\n':
        pos += 2
    elif data[pos:pos+1] in (b' ', b'\t', b'\n', b'\r'):
        pos += 1
    else:
        raise Invalid('RGB_CROP_INVALID')
    pixels = data[pos:]
    if len(pixels) != width * height * 3:
        raise Invalid('RGB_CROP_INVALID')
    return width, height, pixels


def load_profile(store, ref, artifact, basis):
    data = read_ref(store, ref)
    import json
    try:
        profile = json.loads(data.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise Invalid('PRESENTATION_PROFILE_INVALID') from None
    validate(profile, 'presentation-profile.schema.json')
    if profile['basis'] != basis or profile['artifact_sha256'] != artifact['sha256']:
        raise Invalid('PRESENTATION_PROFILE_BINDING')
    result = {}
    for unit in profile['units']:
        if unit['id'] in result:
            raise Invalid('PRESENTATION_DUPLICATE_ID')
        if basis == 'SOURCE_EVIDENCE' and unit.get('authority') not in ('source_measurement', 'scoped_decision'):
            raise Invalid('PRESENTATION_SOURCE_AUTHORITY')
        for evidence in unit['evidence']:
            read_ref(store, evidence)
        result[unit['id']] = unit
    return result


def value(store, unit):
    kind = unit['kind']
    v = unit['value']
    if kind == 'metric':
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise Invalid('PRESENTATION_METRIC_INVALID')
        if not isinstance(unit.get('unit'), str) or not unit['unit'].strip():
            raise Invalid('PRESENTATION_METRIC_UNIT_REQUIRED')
        return v
    if kind == 'role':
        if not isinstance(v, str) or not v.strip():
            raise Invalid('PRESENTATION_ROLE_INVALID')
        return v
    if kind == 'text':
        try:
            text = read_ref(store, v).decode('utf-8')
        except UnicodeError:
            raise Invalid('PRESENTATION_TEXT_INVALID') from None
        if not text.strip():
            raise Invalid('PRESENTATION_TEXT_EMPTY')
        return text
    if kind == 'pixels':
        return rgb_crop(read_ref(store, v))
    raise Invalid('PRESENTATION_KIND_INVALID')


def run(store, spec):
    validate(spec, 'presentation.schema.json')
    read_ref(store, spec['source_artifact'])
    source = load_profile(store, spec['source_profile'], spec['source_artifact'], 'SOURCE_EVIDENCE')
    read_ref(store, spec['target_artifact'])
    target = load_profile(store, spec['target_profile'], spec['target_artifact'], 'OUTPUT_MEASURED')
    scope = spec['scope_ids']
    if set(source) != set(scope):
        raise Invalid('PRESENTATION_SOURCE_SCOPE')
    errors = []
    if set(target) - set(scope):
        errors.append('PRESENTATION_EXTRA_TARGET_UNIT')
    counts = {k: 0 for k in ('metric', 'role', 'text', 'pixels')}
    failed_ids = []
    for uid in scope:
        a = source[uid]
        if uid not in target:
            errors.append('PRESENTATION_MISSING_TARGET_UNIT'); failed_ids.append(uid); continue
        b = target[uid]
        if a['kind'] != b['kind']:
            errors.append('PRESENTATION_KIND_MISMATCH'); failed_ids.append(uid); continue
        kind = a['kind']; counts[kind] += 1
        if kind == 'pixels':
            if 'pixel_context' not in a or 'pixel_context' not in b:
                raise Invalid('PRESENTATION_PIXEL_CONTEXT_REQUIRED')
            if a['pixel_context'] != b['pixel_context']:
                raise Invalid('PRESENTATION_PIXEL_CONTEXT_MISMATCH')
        av, bv = value(store, a), value(store, b)
        if kind == 'metric':
            tolerance = a.get('abs_tolerance', 0)
            if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
                raise Invalid('PRESENTATION_TOLERANCE_INVALID')
            if a.get('unit') != b.get('unit'):
                errors.append('PRESENTATION_UNIT_MISMATCH'); failed_ids.append(uid); continue
            equal = abs(av - bv) <= tolerance
        else:
            if 'abs_tolerance' in a or 'abs_tolerance' in b:
                raise Invalid('PRESENTATION_TOLERANCE_NOT_APPLICABLE')
            equal = av == bv
        if not equal:
            errors.append('PRESENTATION_' + kind.upper() + '_MISMATCH'); failed_ids.append(uid)
    result = summary('scoped_presentation', errors, **counts)
    result.update(scope_ids=scope, failed_ids=failed_ids,
                  source_artifact_sha256=spec['source_artifact']['sha256'],
                  target_artifact_sha256=spec['target_artifact']['sha256'],
                  visual_qa='NOT_PERFORMED', native_clipboard='NOT_TESTED',
                  evidence_scope='Provided artifact/profile/crop bytes only; measurement authorship is not authenticated.')
    return result


if __name__ == '__main__':
    raise SystemExit(cli(run))
