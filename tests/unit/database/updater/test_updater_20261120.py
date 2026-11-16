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
Unit tests for cmdb.database.updater.versions.updater_20261120

The ten retired names, the one ``$pull`` over the groups holding one, the version written after it, a failure wrapped
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261120 as module
from cmdb.database.updater.versions.updater_20261120 import RETIRED_RIGHTS, Update20261120
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

def _update() -> Update20261120:
    """An update without a database"""
    update = Update20261120.__new__(Update20261120)
    update.dbm = MagicMock()
    update.db_name = 'test'
    update.increase_updater_version = MagicMock()

    return update


def test_the_retired_rights_are_the_two_families_wildcards_and_actions() -> None:
    """Ten names; the wider wildcards are not among them"""
    assert len(RETIRED_RIGHTS) == 10
    assert 'base.user-management.person.*' in RETIRED_RIGHTS
    assert 'base.user-management.personGroup.delete' in RETIRED_RIGHTS
    assert 'base.user-management.*' not in RETIRED_RIGHTS


def test_one_pull_over_the_groups_holding_one_then_the_version() -> None:
    """Filtered so an untouched group is not rewritten"""
    update = _update()

    update.start_update()

    groups = update.dbm.get_collection.return_value
    groups.update_many.assert_called_once_with(
        {module.RIGHTS: {'$in': RETIRED_RIGHTS}}, {'$pull': {module.RIGHTS: {'$in': RETIRED_RIGHTS}}},
    )
    update.increase_updater_version.assert_called_once_with(20261120)


def test_a_failure_is_wrapped_and_no_version_written() -> None:
    """The updater tail"""
    update = _update()
    failure = RuntimeError('down')
    update.dbm.get_collection.return_value.update_many.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        update.start_update()

    assert raised.value.__cause__ is failure
    update.increase_updater_version.assert_not_called()
