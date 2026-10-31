#!/usr/bin/env python3
"""Copy the server settings from .env onto the hydra function (docs/deployment.md).

    uv run python scripts/push_env.py

Only the variables `Settings` reads are sent, so the dashboard's public
`VITE_` values and anything unrelated stay local. Values are never printed.
Re-run it after rotating a key: existing variables are updated in place.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Final

from appwrite.client import Client
from appwrite.services.functions import Functions
from dotenv import dotenv_values

from vulnagent.config.settings import Settings, load_settings
from vulnagent.db.responses import plain
from vulnagent.entrypoints.tasks import DEFAULT_FUNCTION_ID

LOCKFILE_FUNCTION_ID: Final = "npm_lockfile"
SETTINGS: Final = [field.upper() for field in Settings.model_fields]


def variables_for(env: Mapping[str, str | None]) -> dict[str, str]:
    chosen = {key: value for key in SETTINGS if (value := env.get(key))}
    return {"NPM_LOCKFILE_FUNCTION_ID": LOCKFILE_FUNCTION_ID, **chosen}


def main() -> int:
    settings = load_settings(dotenv=".env")
    functions = Functions(
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )

    listed = plain(functions.list_variables(DEFAULT_FUNCTION_ID))
    existing = {row["key"]: row["$id"] for row in listed.get("variables", [])}

    for key, value in sorted(variables_for(dotenv_values(".env")).items()):
        if key in existing:
            functions.update_variable(
                DEFAULT_FUNCTION_ID, existing[key], key=key, value=value, secret=True
            )
            print(f"updated {key}")
        else:
            functions.create_variable(
                DEFAULT_FUNCTION_ID, "unique()", key=key, value=value, secret=True
            )
            print(f"created {key}")

    print(f"\n{DEFAULT_FUNCTION_ID} picks these up on its next execution")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"pushing the environment failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
