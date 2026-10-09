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
Unit tests for cmdb.database.updater.versions.updater_20261010

The migration pulls every entry that names no stored CmdbType from every category's ``types``. Its run against real
collections is its own integration test; this module owns the frozen literals, the built filter and update, the read
and the write, and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261010 as module
from cmdb.database.updater.versions.updater_20261010 import Update20261010, build_category_cleanup
from cmdb.errors.updater import UpdaterException
from cmdb.models.category_model import CategoryKey, CmdbCategory
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261010
DATABASE_NAME: str = 'cmdb-unit'
TYPE_IDS: list[int] = [4, 9]


def _build_stubbed_updater(type_ids: list[int]) -> Any:
    """The updater with a stubbed database manager, bypassing the base class's wiring"""
    updater = Update20261010.__new__(Update20261010)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter([{'public_id': type_id} for type_id in type_ids])
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('frozen, live', [
    (module.CATEGORY_COLLECTION, CmdbCategory.COLLECTION),
    (module.TYPE_COLLECTION, CmdbType.COLLECTION),
    (module.TYPES_FIELD, CategoryKey.TYPES.value),
    (module.PUBLIC_ID_FIELD, CategoryKey.PUBLIC_ID.value),
], ids=['categories', 'types', 'types-field', 'public-id'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


def test_the_cleanup_selects_and_pulls_everything_outside_the_type_ids() -> None:
    """The same condition on both sides, so a second run selects nothing"""
    filter_query, update = build_category_cleanup(TYPE_IDS)

    assert filter_query == {'types': {'$elemMatch': {'$nin': TYPE_IDS}}}
    assert update == {'$pull': {'types': {'$nin': TYPE_IDS}}}


def test_reads_type_ids_only_and_pulls_the_rest_then_bumps_the_version() -> None:
    """One projected read over the types, one update over the categories"""
    updater = _build_stubbed_updater(TYPE_IDS)

    updater.start_update()

    find_kwargs: dict[str, Any] = updater.dbm.find.call_args.kwargs
    assert find_kwargs['collection'] == CmdbType.COLLECTION
    assert find_kwargs['projection'] == {'public_id': 1, '_id': 0}
    update_kwargs: dict[str, Any] = updater.dbm.update_many_raw.call_args.kwargs
    assert update_kwargs['collection'] == CmdbCategory.COLLECTION
    assert update_kwargs['update'] == {'$pull': {'types': {'$nin': TYPE_IDS}}}
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


@pytest.mark.parametrize('failing', ['find', 'update_many_raw'])
def test_a_failed_step_is_wrapped_with_the_error_itself_and_leaves_the_version(failing: str) -> None:
    """The next start runs the whole migration again"""
    updater = _build_stubbed_updater(TYPE_IDS)
    error = RuntimeError('down')
    getattr(updater.dbm, failing).side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_names_the_categories() -> None:
    """The line the updater log prints"""
    assert 'categor' in Update20261010.__new__(Update20261010).description()
