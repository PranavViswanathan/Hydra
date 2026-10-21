"""Shared test helpers: fixture loading."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def npm_files(name: str) -> dict[str, str]:
    """Load a fixture directory as the FileMap an adapter receives."""
    directory = FIXTURES / "npm" / name
    files = {path.name: path.read_text() for path in directory.iterdir() if path.is_file()}
    if "package.json" not in files:
        # Most fixtures only care about the lockfile; synthesise the manifest
        # from the lockfile's root entry so detect() still has both files.
        lock = json.loads(files["package-lock.json"])
        root = lock.get("packages", {}).get("", {})
        files["package.json"] = json.dumps(
            {
                "name": lock.get("name", "fixture"),
                "version": lock.get("version", "1.0.0"),
                **{
                    key: root[key]
                    for key in ("dependencies", "devDependencies", "optionalDependencies")
                    if key in root
                },
            },
            indent=2,
        )
    return files
