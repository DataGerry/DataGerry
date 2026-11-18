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
Unit tests for cmdb.database.updater.versions.updater_20261121

One pipeline update over the users still carrying ``group_id``, the version written after it, a failure wrapped
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261121 as module
from cmdb.database.updater.versions.updater_20261121 import CONVERT_PIPELINE, LEGACY_USERS, Update20261121
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

def _update() -> Update20261121:
    """An update without a database"""
    update = Update20261121.__new__(Update20261121)
    update.dbm = MagicMock()
    update.db_name = 'test'
    update.increase_updater_version = MagicMock()

    return update


def test_only_users_without_a_converted_list_are_selected() -> None:
    """The single group, or no group key at all - a converted user is never touched again"""
    assert LEGACY_USERS == {'$or': [{module.GROUP_ID: {'$exists': True}}, {module.GROUP_IDS: {'$exists': False}}]}


def test_the_pipeline_sets_the_list_then_removes_the_single_group() -> None:
    """Two stages: $set of group_ids, $unset of group_id"""
    assert [next(iter(stage)) for stage in CONVERT_PIPELINE] == ['$set', '$unset']
    assert CONVERT_PIPELINE[1] == {'$unset': module.GROUP_ID}


def test_one_update_over_the_legacy_users_then_the_version() -> None:
    """One write on the users collection"""
    update = _update()

    update.start_update()

    update.dbm.get_collection.assert_called_once_with(module.USERS, 'test')
    update.dbm.get_collection.return_value.update_many.assert_called_once_with(LEGACY_USERS, CONVERT_PIPELINE)
    update.increase_updater_version.assert_called_once_with(20261121)


def test_a_failure_is_wrapped_and_no_version_written() -> None:
    """The updater tail"""
    update = _update()
    failure = RuntimeError('down')
    update.dbm.get_collection.return_value.update_many.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        update.start_update()

    assert raised.value.__cause__ is failure
    update.increase_updater_version.assert_not_called()
