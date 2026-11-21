"""Create the public, reproducible rc7 skill archive from tracked distribution inputs."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "aviation-technical-translation"
MANIFEST = ROOT / "downloads" / "package-files.txt"
VERSION = "1.2.2-rc7"


def package(destination):
    paths = MANIFEST.read_text(encoding="utf8").splitlines()
    if not paths or paths != sorted(set(paths)):
        raise ValueError("Package manifest must be nonempty, sorted and unique")
    if f'version: "{VERSION}"' not in (SKILL / "SKILL.md").read_text(encoding="utf8"):
        raise ValueError("Package version disagrees with SKILL.md")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{SKILL.name}-{VERSION}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as output:
        for name in paths:
            path = SKILL / name
            if not path.resolve().is_relative_to(SKILL.resolve()) or path.is_symlink() or not path.is_file():
                raise ValueError(f"Invalid package member: {name}")
            element = ZipInfo(f"{SKILL.name}/{name}", (2026, 11, 21, 0, 0, 0))
            element.create_system = 3
            element.external_attr = 0o100644 << 16
            output.writestr(element, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_bytes(f"{digest}  {archive.name}\n".encode("ascii"))
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "downloads")
    print(package(parser.parse_args().output))
