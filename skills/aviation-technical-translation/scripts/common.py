"""Shared, dependency-light helpers for the aviation translation Skill."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parent.parent


def canonical_path(path: Path) -> str:
    """Return a case-normalized absolute path key for collision checks."""

    return os.path.normcase(str(path.resolve()))


def ensure_distinct_paths(named_paths: dict[str, Path]) -> None:
    """Reject two logical inputs/outputs that resolve to the same filesystem path."""

    seen: dict[str, str] = {}
    for label, path in named_paths.items():
        key = canonical_path(path)
        if key in seen:
            raise ValueError(f"{label} must differ from {seen[key]}: {path.resolve()}")
        seen[key] = label


def require_suffix(path: Path, suffix: str, label: str) -> None:
    if path.suffix.lower() != suffix.lower():
        raise ValueError(f"{label} must use the {suffix} extension: {path.resolve()}")


def require_package(import_name: str, install_name: str | None = None) -> Any:
    try:
        return importlib.import_module(import_name)
    except ImportError as exc:
        package = install_name or import_name
        raise RuntimeError(
            f"Missing Python dependency '{package}'. Install it in the active Python environment "
            f"before running this command."
        ) from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required JSON file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def _schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def _schema_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"The dependency-light schema validator supports internal references only: {reference}")
    node: Any = root
    for part in reference[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(node, dict):
        raise ValueError(f"Schema reference does not resolve to an object: {reference}")
    return node


def _mini_schema_errors(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "<root>") -> list[str]:
    if "$ref" in schema:
        return _mini_schema_errors(value, _schema_ref(root, schema["$ref"]), root, path)
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_schema_type_matches(value, item) for item in types):
            return [f"{path}: expected type {types}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in {schema['enum']!r}")
    if "anyOf" in schema:
        alternatives = [_mini_schema_errors(value, item, root, path) for item in schema["anyOf"]]
        if not any(not alternative for alternative in alternatives):
            errors.append(f"{path}: value does not match any allowed schema")
    if "oneOf" in schema:
        matches = sum(not _mini_schema_errors(value, item, root, path) for item in schema["oneOf"])
        if matches != 1:
            errors.append(f"{path}: value must match exactly one allowed schema; matched {matches}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than {schema['minLength']}")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errors.append(f"{path}: string does not match pattern {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: value must be greater than {schema['exclusiveMinimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array has more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            normalized = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(normalized) != len(set(normalized)):
                errors.append(f"{path}: array items are not unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(_mini_schema_errors(item, schema["items"], root, f"{path}/{index}"))
    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: object has fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path}: object has more than {schema['maxProperties']} properties")
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}/{key}"
            if key in properties:
                errors.extend(_mini_schema_errors(item, properties[key], root, child_path))
            elif additional is False:
                errors.append(f"{child_path}: additional property is not allowed")
            elif isinstance(additional, dict):
                errors.extend(_mini_schema_errors(item, additional, root, child_path))
    if "not" in schema and not _mini_schema_errors(value, schema["not"], root, path):
        errors.append(f"{path}: value matches a forbidden schema")
    for sub_schema in schema.get("allOf", []):
        if "if" in sub_schema:
            if not _mini_schema_errors(value, sub_schema["if"], root, path):
                errors.extend(_mini_schema_errors(value, sub_schema.get("then", {}), root, path))
        else:
            errors.extend(_mini_schema_errors(value, sub_schema, root, path))
    return errors


def schema_validation_errors(value: Any, schema_path: Path) -> list[str]:
    """Validate with jsonschema when present, otherwise a strict bundled subset."""

    schema = load_json(schema_path)
    try:
        jsonschema = importlib.import_module("jsonschema")
    except ImportError:
        return _mini_schema_errors(value, schema, schema)
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    ]


def load_layout_profile(profile_id: str) -> dict[str, Any]:
    """Load a bundled layout profile without importing project-specific geometry."""

    if profile_id not in {"source_faithful", "zh_formal_print", "personal_zh_review", "personal_paper_review"}:
        raise ValueError(f"Unknown layout profile: {profile_id}")
    profile_path = SKILL_ROOT / "profiles" / f"{profile_id}.json"
    profile = load_json(profile_path)
    if profile.get("profile_id") != profile_id:
        raise ValueError(f"Layout profile identity mismatch in {profile_path}")
    return profile


def resolve_layout_profile(layout: dict[str, Any]) -> dict[str, Any]:
    """Apply optional typography defaults while preserving project overrides."""

    resolved = deepcopy(layout)
    profile_id = str(resolved.get("profile_id") or "source_faithful")
    profile = load_layout_profile(profile_id)
    roles = dict(profile.get("default_style_names", {}))
    roles.update(resolved.get("style_roles", {}))
    styles = deepcopy(resolved.get("styles", {}))
    for role, defaults in profile.get("style_defaults", {}).items():
        style_name = roles.get(role)
        if not style_name:
            continue
        merged = dict(defaults)
        merged.update(styles.get(style_name, {}))
        styles[style_name] = merged
    resolved["profile_id"] = profile_id
    resolved["style_roles"] = roles
    resolved["styles"] = styles
    resolved["math_font"] = str(resolved.get("math_font") or profile["math_font"])
    return resolved


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required JSONL file is missing: {path}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object in {path}:{line_number}")
        records.append(value)
    return records


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_relative(base: Path, value: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"Path must be relative to the project file: {value}")
    base_resolved = base.resolve()
    resolved = (base_resolved / candidate).resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes the project directory: {value}") from exc
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Required project path does not exist: {resolved}")
    return resolved


def relative_posix(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def find_executable(explicit: str | None, names: Iterable[str]) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Executable does not exist: {path}")
        return path
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


def microsoft_word_registered() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        for root in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
            key_path = r"Word.Application\CLSID" if root == winreg.HKEY_CLASSES_ROOT else r"Software\Classes\Word.Application\CLSID"
            try:
                with winreg.OpenKey(root, key_path):
                    return True
            except OSError:
                continue
    except (ImportError, OSError):
        return False
    return False


def count_han_and_latin(text: str) -> tuple[int, int]:
    han = sum("\u3400" <= char <= "\u9fff" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    return han, latin
