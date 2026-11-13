# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.database.updater.versions.updater_20261118

The migration gives every object its type's marker. Its run against real collections is its own integration test;
this module owns the frozen literals, the grouping of the types, the statements, the orchestration and the failure
tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261118 as module
from cmdb.database.updater.versions.updater_20261118 import (
    Update20261118,
    build_marker_criteria,
    read_type_markers,
)
from cmdb.errors.updater import UpdaterException
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261118
DATABASE_NAME: str = 'cmdb-unit'
TYPES: list[dict[str, Any]] = [
    {'public_id': 1, 'special_type': 'SUPERNET'}, {'public_id': 2, 'special_type': 'SUPERNET'},
    {'public_id': 3, 'special_type': 'RACK'}, {'public_id': 4, 'special_type': None}, {'public_id': 5,
                                                                                         'special_type': ''},
    {'public_id': 6},
]


def _build_stubbed_updater(types: list[dict[str, Any]], modified: int = 0) -> Any:
    """The updater with a stubbed database manager answering the given types"""
    updater = Update20261118.__new__(Update20261118)
    updater.dbm = MagicMock()
    updater.dbm.find_all.return_value = types
    updater.dbm.update_many.return_value = MagicMock(modified_count=modified)
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def test_the_frozen_literals() -> None:
    """The two collections"""
    assert (module.TYPES_COLLECTION, module.OBJECTS_COLLECTION) == (CmdbType.COLLECTION, CmdbObject.COLLECTION)


def test_the_types_are_grouped_by_marker() -> None:
    """An empty or missing marker counts as none"""
    dbm = MagicMock()
    dbm.find_all.return_value = TYPES

    assert read_type_markers(dbm, DATABASE_NAME) == ({'SUPERNET': [1, 2], 'RACK': [3]}, [4, 5, 6])


def test_the_criteria_select_only_the_objects_holding_another_marker() -> None:
    """What makes a re-run a no-op"""
    assert build_marker_criteria([1, 2], 'SUPERNET') == {'type_id': {'$in': [1, 2]},
                                                         'special_type': {'$ne': 'SUPERNET'}}


def test_one_statement_per_marker_and_one_for_the_unmarked() -> None:
    """Then the version"""
    updater = _build_stubbed_updater(TYPES, modified=1)

    updater.start_update()

    assert [call.args[2:] for call in updater.dbm.update_many.call_args_list] == [
        (build_marker_criteria([1, 2], 'SUPERNET'), {'special_type': 'SUPERNET'}),
        (build_marker_criteria([3], 'RACK'), {'special_type': 'RACK'}),
        (build_marker_criteria([4, 5, 6], None), {'special_type': None}),
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_no_type_no_statement() -> None:
    """An empty database"""
    updater = _build_stubbed_updater([])

    updater.start_update()

    updater.dbm.update_many.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failure_is_wrapped_and_keeps_the_version() -> None:
    """The exception itself is carried"""
    updater = _build_stubbed_updater(TYPES)
    failure = RuntimeError('boom')
    updater.dbm.update_many.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()


def test_the_metadata() -> None:
    """The date in its name and a description"""
    updater = Update20261118.__new__(Update20261118)

    assert updater.creation_date() == CREATION_DATE
    assert updater.description().strip()
