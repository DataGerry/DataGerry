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
Unit tests for cmdb.database.updater.versions.updater_20261113

The migration pulls the rights the catalogue no longer offers from every stored group, in one write. Its run against a
real collection is its own integration test; this module owns the frozen literals, the catalogue they must agree with,
the one write, and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261113 as module
from cmdb.database.updater.versions.updater_20261113 import REMOVED_RIGHTS, Update20261113
from cmdb.errors.database import DocumentUpdateError
from cmdb.errors.updater import UpdaterException
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.right_model.all_rights import ALL_RIGHT_NAMES
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261113
DATABASE_NAME: str = 'cmdb-unit'
REMOVED_RIGHT_COUNT: int = 10
NAME_SEPARATOR: str = '.'
MODIFIED_GROUP_COUNT: int = 3


def _build_stubbed_updater() -> Any:
    """The updater with a stubbed database manager"""
    updater = Update20261113.__new__(Update20261113)
    updater.dbm = MagicMock()
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('frozen, live', [
    (module.GROUPS_COLLECTION, CmdbUserGroup.COLLECTION),
    (module.RIGHTS_FIELD, GroupKey.RIGHTS.value),
], ids=['groups', 'rights'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


def test_the_ten_rights_are_distinct() -> None:
    """One entry per removed right"""
    assert len(set(REMOVED_RIGHTS)) == len(REMOVED_RIGHTS) == REMOVED_RIGHT_COUNT


@pytest.mark.parametrize('right', REMOVED_RIGHTS)
def test_a_removed_right_is_out_of_the_catalogue(right: str) -> None:
    """A stored copy would be refused on the group's next save - which is why it is pulled"""
    assert right not in ALL_RIGHT_NAMES


@pytest.mark.parametrize('right', REMOVED_RIGHTS)
def test_the_family_wildcard_of_a_removed_right_stays(right: str) -> None:
    """A group holding the family's wildcard keeps it and everything the family still offers"""
    family_wildcard: str = f'{right.rsplit(NAME_SEPARATOR, 1)[0]}{NAME_SEPARATOR}{GLOBAL_RIGHT_IDENTIFIER}'

    assert family_wildcard in ALL_RIGHT_NAMES


def test_one_write_pulls_every_removed_right_from_the_groups_holding_one() -> None:
    """Only the groups holding one are matched; the pull names all ten"""
    updater = _build_stubbed_updater()

    updater.start_update()

    removed: dict[str, Any] = {'$in': list(REMOVED_RIGHTS)}
    updater.dbm.update_many_raw.assert_called_once_with(
        CmdbUserGroup.COLLECTION, DATABASE_NAME, {'rights': removed}, {'$pull': {'rights': removed}},
    )
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_the_write_count_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """The log names how many groups changed"""
    updater = _build_stubbed_updater()
    updater.dbm.update_many_raw.return_value.modified_count = MODIFIED_GROUP_COUNT

    with caplog.at_level(logging.INFO, logger=module.LOGGER.name):
        updater.start_update()

    assert f'from {MODIFIED_GROUP_COUNT} group(s)' in caplog.text


def test_a_failed_write_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The next start runs the migration again"""
    updater = _build_stubbed_updater()
    error = DocumentUpdateError('down')
    updater.dbm.update_many_raw.side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_names_the_rights() -> None:
    """The line the updater log prints"""
    assert 'rights' in Update20261113.__new__(Update20261113).description()
