#!/usr/bin/env python3
"""Build and verify Blender-installable GTANAVMESH Edit ZIP archives.

Blender's add-on installer is most reliable when the archive includes an
explicit directory entry for the top-level Python package.  Some generic ZIP
commands only emit file entries, even when their file names contain a slash.
This script writes that directory entry deliberately and rejects archives
that do not contain it.

Examples:

    py .\\tools\\package_blender_addon.py --version 0.11.1
    py .\\tools\\package_blender_addon.py --check `
        .\\dist\\GTANAVMESH-Edit-v0.11.1.zip
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ADDON_PACKAGE = "ynv_blender_addon"
ADDON_SOURCE = REPOSITORY_ROOT / ADDON_PACKAGE
PACKAGE_ROOT_ENTRY = f"{ADDON_PACKAGE}/"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
IGNORED_PARTS = {"__pycache__", ".git", ".svn", ".hg"}
IGNORED_FILENAMES = {".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class PackageValidationError(RuntimeError):
    """Raised when an archive cannot safely be installed as this add-on."""


def _zip_timestamp() -> tuple[int, int, int, int, int, int]:
    """Return a reproducible ZIP timestamp, optionally from SOURCE_DATE_EPOCH."""

    epoch_text = os.environ.get("SOURCE_DATE_EPOCH")
    if not epoch_text:
        return (1980, 1, 1, 0, 0, 0)

    try:
        instant = datetime.fromtimestamp(int(epoch_text), tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise PackageValidationError(
            "SOURCE_DATE_EPOCH must be a valid Unix timestamp."
        ) from exc

    if instant.year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    # The ZIP timestamp format has two-second precision.
    return (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second - (instant.second % 2),
    )


def _is_payload_path(path: Path) -> bool:
    """Return whether a path belongs in the distributable Python package."""

    relative_parts = path.relative_to(ADDON_SOURCE).parts
    if any(part in IGNORED_PARTS for part in relative_parts):
        return False
    if path.name in IGNORED_FILENAMES or path.suffix.lower() in IGNORED_SUFFIXES:
        return False
    return True


def _payload_directories() -> Iterable[Path]:
    """Yield package directories in deterministic parent-before-child order."""

    directories = [ADDON_SOURCE]
    directories.extend(
        path
        for path in ADDON_SOURCE.rglob("*")
        if path.is_dir() and _is_payload_path(path)
    )
    return sorted(
        set(directories),
        key=lambda path: (len(path.relative_to(ADDON_SOURCE).parts), path.as_posix()),
    )


def _payload_files() -> Iterable[Path]:
    """Yield package files in a stable archive order."""

    return sorted(
        (
            path
            for path in ADDON_SOURCE.rglob("*")
            if path.is_file() and _is_payload_path(path)
        ),
        key=lambda path: path.relative_to(ADDON_SOURCE).as_posix(),
    )


def _archive_name(path: Path) -> str:
    """Map an add-on source path to a POSIX ZIP entry name."""

    relative = path.relative_to(ADDON_SOURCE).as_posix()
    return PACKAGE_ROOT_ENTRY if relative == "." else f"{PACKAGE_ROOT_ENTRY}{relative}"


def _directory_info(name: str, timestamp: tuple[int, int, int, int, int, int]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=timestamp)
    info.compress_type = zipfile.ZIP_STORED
    # Mark the item as a conventional 0755 Unix directory for ZIP consumers.
    info.create_system = 3
    info.external_attr = (0o40755 << 16) | 0x10
    return info


def _file_info(name: str, timestamp: tuple[int, int, int, int, int, int]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=timestamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _compile_python_source(path_label: str, payload: bytes) -> None:
    """Fail early if a Python source file cannot compile from the release ZIP."""

    if path_label.endswith(".py"):
        compile(payload, path_label, "exec")


def verify_archive(archive_path: Path) -> list[str]:
    """Validate archive layout and return its payload file names.

    The checks deliberately enforce a physical `ynv_blender_addon/` directory
    record.  Merely having file names such as `ynv_blender_addon/__init__.py`
    is not enough for this release workflow.
    """

    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise PackageValidationError(f"Archive does not exist: {archive_path}")

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise PackageValidationError(
                    f"Archive CRC check failed for member: {bad_member}"
                )

            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not infos:
                raise PackageValidationError("Archive is empty.")
            if len(names) != len(set(names)):
                raise PackageValidationError("Archive contains duplicate member names.")
            if names[0] != PACKAGE_ROOT_ENTRY:
                raise PackageValidationError(
                    f"First archive member must be the explicit directory entry "
                    f"{PACKAGE_ROOT_ENTRY!r}; got {names[0]!r}."
                )

            try:
                package_root = archive.getinfo(PACKAGE_ROOT_ENTRY)
            except KeyError as exc:
                raise PackageValidationError(
                    f"Archive is missing explicit directory entry {PACKAGE_ROOT_ENTRY!r}."
                ) from exc
            if not package_root.is_dir():
                raise PackageValidationError(
                    f"Archive member {PACKAGE_ROOT_ENTRY!r} must be a directory entry."
                )

            for info in infos:
                name = info.filename
                member = PurePosixPath(name)
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or "\\" in name
                    or not name.startswith(PACKAGE_ROOT_ENTRY)
                ):
                    raise PackageValidationError(
                        f"Archive contains an unsafe or out-of-package member: {name!r}."
                    )

            init_name = f"{PACKAGE_ROOT_ENTRY}__init__.py"
            try:
                init_info = archive.getinfo(init_name)
            except KeyError as exc:
                raise PackageValidationError(
                    f"Archive is missing required add-on module {init_name!r}."
                ) from exc
            if init_info.is_dir():
                raise PackageValidationError(
                    f"Required add-on module {init_name!r} is a directory."
                )

            payload_files = []
            for info in infos:
                if info.is_dir():
                    continue
                payload = archive.read(info)
                _compile_python_source(info.filename, payload)
                payload_files.append(info.filename)
            return payload_files
    except zipfile.BadZipFile as exc:
        raise PackageValidationError(f"Invalid ZIP archive: {archive_path}") from exc


def build_archive(output_path: Path) -> list[str]:
    """Create a deterministic Blender add-on archive and validate it."""

    if not ADDON_SOURCE.is_dir():
        raise PackageValidationError(f"Add-on source directory is missing: {ADDON_SOURCE}")

    output_path = output_path.resolve()
    if ADDON_SOURCE == output_path.parent or ADDON_SOURCE in output_path.parents:
        raise PackageValidationError("Release ZIP cannot be written inside the add-on source folder.")

    timestamp = _zip_timestamp()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".zip", prefix=".gtnavmesh-package-", dir=output_path.parent, delete=False
        ) as temporary:
            temp_name = temporary.name

        with zipfile.ZipFile(
            temp_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            # This is intentionally a separate archive record.  Blender's
            # installer must not have to infer the add-on package directory.
            for directory in _payload_directories():
                archive.writestr(_directory_info(_archive_name(directory), timestamp), b"")
            for source_file in _payload_files():
                payload = source_file.read_bytes()
                _compile_python_source(str(source_file), payload)
                archive.writestr(_file_info(_archive_name(source_file), timestamp), payload)

        os.replace(temp_name, output_path)
        temp_name = None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)

    return verify_archive(output_path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as archive:
        for block in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check",
        type=Path,
        metavar="ARCHIVE",
        help="validate an existing ZIP without changing it",
    )
    action.add_argument(
        "--version",
        metavar="X.Y.Z",
        help="build dist/GTANAVMESH-Edit-vX.Y.Z.zip",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="ARCHIVE",
        help="explicit output path for a --version build",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacement of an existing --output archive",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.check:
        if args.output or args.force:
            raise SystemExit("--output and --force are only valid with --version.")
        files = verify_archive(args.check)
        print(f"PASS: {args.check.resolve()} ({len(files)} payload files)")
        print(f"SHA256: {_sha256(args.check.resolve())}")
        return 0

    assert args.version is not None
    if not VERSION_PATTERN.fullmatch(args.version):
        raise SystemExit("--version must be numeric semantic version X.Y.Z (for example 0.11.1).")

    output = args.output or (
        REPOSITORY_ROOT / "dist" / f"GTANAVMESH-Edit-v{args.version}.zip"
    )
    output = output.resolve()
    if output.exists() and not args.force:
        raise SystemExit(
            f"Refusing to replace existing archive: {output}. Use --force only after review."
        )
    files = build_archive(output)
    print(f"BUILT: {output} ({len(files)} payload files)")
    print(f"SHA256: {_sha256(output)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PackageValidationError, SyntaxError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
