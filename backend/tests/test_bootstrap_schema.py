"""The schema the bootstrap script creates must be one Appwrite accepts.

Appwrite rejects an index whose string columns add up to more than 767
characters, and it only says so halfway through a bootstrap run.
"""

import pytest

from tests.test_function_entrypoints import SCRIPTS, load

APPWRITE_MAX_INDEX_LENGTH = 767

schema = load(SCRIPTS / "bootstrap_db.py", "vulnagent_script_bootstrap_schema")

INDEXES = [(table, index) for table in schema.TABLES for index in table.indexes]


@pytest.mark.parametrize(
    ("table", "index"), INDEXES, ids=[f"{table.id}.{index.key}" for table, index in INDEXES]
)
def test_every_index_fits_within_appwrites_length_limit(table, index):
    sizes = {column.key: column.size for column in table.columns if column.kind == "string"}

    length = sum(sizes.get(key, 0) for key in index.columns)

    assert length <= APPWRITE_MAX_INDEX_LENGTH
