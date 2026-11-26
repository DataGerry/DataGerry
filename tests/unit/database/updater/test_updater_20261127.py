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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.database.updater.versions.updater_20261127

The migration gives the user groups that could set a type ACL ``base.access.view``. Pinned here: which stored rights
qualify a group (the selection), the frozen literals against the code's own, and the failure tail. Its run against a
real database - the writes, the report, a double run, a fresh database - is the integration test's
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261127 as module
from cmdb.database.updater.versions.updater_20261127 import Update20261127, qualifies, qualifying_group_ids
from cmdb.models.access_model import (
    ACCESS_RIGHTS_MIGRATION_REPORT_ID,
    MIGRATION_REPORT_COLLECTION,
    RightsMigrationReportKey,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_EDIT: str = 'base.framework.type.edit'
ACCESS_VIEW: str = 'base.access.view'


@pytest.mark.parametrize('rights', [
    [TYPE_EDIT], ['base.framework.type.*'], ['base.framework.*'], ['base.framework.object.view', TYPE_EDIT],
], ids=['type-edit', 'type-wildcard', 'framework-wildcard', 'among-others'])
def test_a_former_type_acl_editor_qualifies(rights: list[str]) -> None:
    """Each right that let a group set a type ACL"""
    assert qualifies(rights) is True


@pytest.mark.parametrize('rights', [
    [TYPE_EDIT, 'base.*'], [TYPE_EDIT, 'base.access.*'], [TYPE_EDIT, ACCESS_VIEW],
], ids=['master', 'access-wildcard', 'view-held'])
def test_a_group_viewing_the_access_rules_already_does_not(rights: list[str]) -> None:
    """Nothing to give - and a second run finds the group given the right"""
    assert qualifies(rights) is False


@pytest.mark.parametrize('rights', [
    ['base.framework.type.view'], ['base.framework.type.add'], ['base.framework.type.delete'], [], None, 'x',
    [None, 7], {TYPE_EDIT: True},
], ids=['type-view', 'type-add', 'type-delete', 'empty', 'none', 'not-a-list', 'junk-entries', 'a-mapping'])
def test_anything_else_does_not(rights: Any) -> None:
    """Only the edit right or a wildcard covering it; a malformed rights value is passed over"""
    assert qualifies(rights) is False


def test_the_qualifying_ids_ascending() -> None:
    """Out of order in, ascending out; non-qualifying groups left out"""
    groups: list[dict[str, Any]] = [{'public_id': 9, 'rights': [TYPE_EDIT]}, {'public_id': 1, 'rights': ['base.*']},
                                    {'public_id': 4, 'rights': ['base.framework.*']}, {'public_id': 2, 'rights': []}]

    assert qualifying_group_ids(groups) == [4, 9]


@pytest.mark.parametrize('frozen, live', [
    (module.GROUPS, CmdbUserGroup.COLLECTION),
    (module.REPORTS, MIGRATION_REPORT_COLLECTION),
    (module.REPORT_ID, ACCESS_RIGHTS_MIGRATION_REPORT_ID),
    (module.REPORT_GROUPS, RightsMigrationReportKey.GROUPS.value),
    (module.REPORT_STARTED_AT, RightsMigrationReportKey.STARTED_AT.value),
    (module.REPORT_COMPLETED_AT, RightsMigrationReportKey.COMPLETED_AT.value),
], ids=['groups', 'reports', 'report-id', 'groups-key', 'started-key', 'completed-key'])
def test_the_frozen_literals_still_match_the_code(frozen: object, live: object) -> None:
    """The literals were frozen from the code's own"""
    assert frozen == live


def test_a_failure_is_the_updater_exception_carrying_it() -> None:
    """The error itself, not its text"""
    dbm = MagicMock()
    cause = RuntimeError('groups gone')
    dbm.get_collection.side_effect = cause

    with pytest.raises(UpdaterException) as raised:
        Update20261127(dbm, 'cmdb-unit').start_update()

    assert raised.value.args[0] is cause


def test_the_creation_date() -> None:
    """The registered version"""
    assert Update20261127(MagicMock(), 'cmdb-unit').creation_date() == 20261127
