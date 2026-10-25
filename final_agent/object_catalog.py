"""Shared visual defaults. Only committed imports or an explicit sync register new types."""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile


CATALOG_PATH = Path(__file__).with_name("object_catalog.json")


def normalize_object_type(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("Object type must be a non-empty string of at most 120 characters.")
    return "_".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


def positive_height(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def read_catalog(path: Path = CATALOG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def estimate_object_height(asset: dict, catalog: dict) -> tuple[float, str]:
    """Transparent estimates for unfamiliar types; never infer height from XY size."""
    if positive_height(asset.get("height_m")):
        return float(asset["height_m"]), "Initial object supplies an explicit height; used as the new type's visual default."
    tokens = set(normalize_object_type(asset["type"]).split("_"))
    for rule in catalog["estimation_rules"]:
        if tokens.intersection(rule["tokens"]):
            return rule["height_m"], rule["reason"]
    category = asset.get("category", "")
    height = catalog["defaults"]["category_heights_m"].get(category, catalog["defaults"]["height_m"])
    return height, f"No known shape keyword; conservative {category or 'object'} category estimate. Review when dimensions are known."


def object_height(asset: dict, catalog: dict | None = None) -> float:
    """Explicit per-instance height wins; reads never mutate the shared table."""
    catalog = catalog if catalog is not None else read_catalog()
    if positive_height(asset.get("height_m")):
        return float(asset["height_m"])
    entry = catalog["objects"].get(normalize_object_type(asset["type"]))
    return entry["height_m"] if entry else estimate_object_height(asset, catalog)[0]


def _lock_fd(fd: int) -> None:
    # fcntl is Unix-only. Windows locks a byte range, so the lock file needs one byte.
    if os.name == "nt":
        import msvcrt
        if os.lseek(fd, 0, os.SEEK_END) == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _catalog_lock(path: Path):
    # A stable lock outside the source tree survives os.replace and serializes processes.
    key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
    fd = os.open(Path(tempfile.gettempdir()) / f"building-object-catalog-{key}.lock", os.O_CREAT | os.O_RDWR)
    try:
        _lock_fd(fd)
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def register_asset_types(assets: list[dict], path: Path = CATALOG_PATH) -> list[str]:
    """Atomically extend the one JSON table; existing curated defaults are preserved."""
    path = Path(path)
    with _catalog_lock(path):
        catalog = read_catalog(path)
        added = []
        for asset in assets:
            object_type = normalize_object_type(asset.get("type", ""))
            if object_type in catalog["objects"]:
                continue
            height, reason = estimate_object_height(asset, catalog)
            category = asset.get("category")
            catalog["objects"][object_type] = {
                "height_m": height, "height_reason": reason, "height_status": "estimated",
                "categories": [category] if isinstance(category, str) and category else [],
                "model_path": catalog["defaults"]["model_path"],
                "model_source": "project_procedural", "model_kind": "placeholder",
            }
            added.append(object_type)
        if not added:
            return []
        catalog["objects"] = dict(sorted(catalog["objects"].items()))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(catalog, output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return added


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Register new building asset types with estimated heights and grey blocks.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("data")], help="building.json files or directories")
    args = parser.parse_args()
    assets = []
    for path in args.paths:
        paths = sorted(path.rglob("building.json")) if path.is_dir() else [path]
        for building_path in paths:
            assets.extend(json.loads(building_path.read_text(encoding="utf-8")).get("assets", []))
    added = register_asset_types(assets)
    print(f"Registered {len(added)} new object types" + (": " + ", ".join(added) if added else "."))


if __name__ == "__main__":
    main()
