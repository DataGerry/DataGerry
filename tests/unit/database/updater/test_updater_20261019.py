# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.database.updater.versions.updater_20261019

The migration takes the ids of deleted CmdbTypes out of the CmdbCategories that still list them. Its run against a
real database is its own integration test; this module owns the frozen literals, the id reading, the update, the
batching, which ids count as deleted, the order and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261019 as module
from cmdb.database.updater.versions.updater_20261019 import (
    Update20261019,
    batches,
    listed_type_ids,
    pull_update,
)
from cmdb.models.category_model import CategoryKey, CmdbCategory
from cmdb.models.type_model import CmdbType
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261019
DATABASE_NAME: str = 'cmdb-unit'
LISTED_IDS: list[int] = [12, 5, 9]
EXISTING_IDS: list[int] = [9]
DELETED_IDS: list[int] = [5, 12]
MODIFIED: int = 3


def _updater(listed: list[int] | None = None,
             existing: list[int] | None = None) -> tuple[Update20261019, MagicMock]:
    """The migration over a mocked database manager: one category listing `listed`, `existing` types stored"""
    dbm = MagicMock()

    def _find(collection: str, *_args: Any, **_kwargs: Any) -> Any:
        if collection == module.CATEGORIES_COLLECTION:
            return iter([{module.TYPES_FIELD: listed}] if listed is not None else [])

        return iter([{module.PUBLIC_ID_FIELD: type_id} for type_id in existing or []])

    dbm.find.side_effect = _find
    dbm.update_many_raw.return_value = MagicMock(modified_count=MODIFIED)
    updater = Update20261019.__new__(Update20261019)
    updater.dbm = dbm
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.CATEGORIES_COLLECTION, CmdbCategory.COLLECTION),
    (module.TYPES_COLLECTION, CmdbType.COLLECTION),
    (module.TYPES_FIELD, CategoryKey.TYPES.value),
    (module.PUBLIC_ID_FIELD, CategoryKey.PUBLIC_ID.value),
], ids=['categories', 'types', 'types-field', 'public-id'])
def test_the_frozen_literals_still_match_the_model(frozen: Any, live: Any) -> None:
    """Frozen on purpose; a drift would mean the migration no longer touches what the application stores"""
    assert frozen == live


@pytest.mark.parametrize('categories, expected', [
    ([], []),
    ([{'types': [3, 1]}, {'types': [1, 2]}], [1, 2, 3]),
    ([{'types': None}, {}, {'types': 'x'}], []),
    ([{'types': [4, 'x', {'a': 1}, True, 2.5, 7]}], [4, 7]),
], ids=['none', 'union-sorted', 'no-list', 'integers-only'])
def test_listed_type_ids(categories: list[dict[str, Any]], expected: list[int]) -> None:
    """Every integer entry once, ascending; a bool is no type id and anything else is left alone"""
    assert listed_type_ids(categories) == expected


def test_the_pull_update() -> None:
    """One $pull of every id of the batch"""
    assert pull_update(DELETED_IDS) == {'$pull': {'types': {'$in': DELETED_IDS}}}


@pytest.mark.parametrize('ids, size, expected', [
    ([], 2, []), ([1], 2, [[1]]), ([1, 2], 2, [[1, 2]]), ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]]),
], ids=['none', 'one', 'exact', 'remainder'])
def test_batches(ids: list[int], size: int, expected: list[list[int]]) -> None:
    """Consecutive, in order, none larger than the size"""
    assert batches(ids, size) == expected


class TestFindDeletedTypeIds:
    """A listed id whose type no longer exists"""

    def test_answers_the_listed_ids_without_a_type_ascending(self) -> None:
        """One projected read of the categories, one existence read of the types"""
        updater, dbm = _updater(LISTED_IDS, EXISTING_IDS)

        assert updater.find_deleted_type_ids() == DELETED_IDS
        assert dbm.find.call_args_list == [
            call(module.CATEGORIES_COLLECTION, DATABASE_NAME, {'types': {'$exists': True, '$ne': []}},
                 projection={'types': 1, '_id': 0}),
            call(module.TYPES_COLLECTION, DATABASE_NAME, {'public_id': {'$in': sorted(LISTED_IDS)}},
                 projection={'public_id': 1, '_id': 0}),
        ]

    def test_nothing_listed_reads_no_type(self) -> None:
        """No category lists a type"""
        updater, dbm = _updater(None)

        assert not updater.find_deleted_type_ids()
        assert dbm.find.call_count == 1

    def test_the_existence_read_is_batched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One read per batch, after the category read"""
        monkeypatch.setattr(module, 'ID_BATCH_SIZE', 2)
        updater, dbm = _updater(LISTED_IDS, [])

        assert updater.find_deleted_type_ids() == sorted(LISTED_IDS)
        assert dbm.find.call_count == 3


class TestRemove:
    """One update per batch of ids"""

    def test_each_batch_is_one_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The counts summed"""
        monkeypatch.setattr(module, 'ID_BATCH_SIZE', 1)
        updater, dbm = _updater()

        assert updater.remove(DELETED_IDS) == MODIFIED * len(DELETED_IDS)
        assert dbm.update_many_raw.call_args_list == [call(
            module.CATEGORIES_COLLECTION, DATABASE_NAME, {'types': {'$in': [type_id]}}, pull_update([type_id]),
        ) for type_id in DELETED_IDS]

    def test_no_ids_update_nothing(self) -> None:
        """Nothing to take out"""
        updater, dbm = _updater()

        assert updater.remove([]) == 0
        dbm.update_many_raw.assert_not_called()


class TestStartUpdate:
    """Find, remove, then bump the version"""

    def test_the_version_is_bumped_after_the_removal(self) -> None:
        """Only once everything went through"""
        updater, dbm = _updater(LISTED_IDS, EXISTING_IDS)

        updater.start_update()

        dbm.update_many_raw.assert_called_once()
        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_a_failure_is_raised_carrying_the_error_and_the_version_stays(self) -> None:
        """The exception itself, not its text"""
        updater, dbm = _updater(LISTED_IDS, EXISTING_IDS)
        failure = RuntimeError('db')
        dbm.update_many_raw.side_effect = failure

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        assert caught.value.args[0] is failure
        updater.increase_updater_version.assert_not_called()

    def test_creation_date_and_description(self) -> None:
        """The registered version"""
        updater, _ = _updater()

        assert updater.creation_date() == CREATION_DATE
        assert updater.description()
