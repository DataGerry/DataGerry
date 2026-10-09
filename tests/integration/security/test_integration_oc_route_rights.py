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
Integration tests for the OpenCelium rights the Automation routes ask for, against real groups in MongoDB

``user_has_right`` - the check behind each ``.protect`` - reads the caller's group from the database and resolves
wildcard rights through the right tree. Pinned for the rights the 23 Automation routes now ask for:

  - a group holding exactly one ``OcRight`` passes that right and no other OpenCelium right
  - ``base.openCelium.connection.*`` passes every connection right and no connector right, and the reverse
  - ``base.openCelium.*`` passes all eight, the master right too
"""
from datetime import datetime, timezone

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcRight
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTION_RIGHTS: set[OcRight] = {right for right in OcRight if '.connection.' in right.value}
CONNECTOR_RIGHTS: set[OcRight] = set(OcRight) - CONNECTION_RIGHTS

SINGLE_GROUP_IDS: dict[OcRight, int] = {right: 89701 + index for index, right in enumerate(OcRight)}
CONNECTION_WILDCARD_GROUP_ID: int = 89721
CONNECTOR_WILDCARD_GROUP_ID: int = 89722
OC_WILDCARD_GROUP_ID: int = 89723

GROUPS: dict[int, list[str]] = {
    **{group_id: [right.value] for right, group_id in SINGLE_GROUP_IDS.items()},
    CONNECTION_WILDCARD_GROUP_ID: ['base.openCelium.connection.*'],
    CONNECTOR_WILDCARD_GROUP_ID: ['base.openCelium.connector.*'],
    OC_WILDCARD_GROUP_ID: ['base.openCelium.*'],
}


@pytest.fixture(autouse=True)
def _groups(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The groups, inside the request context ManagerProvider resolves through"""
    collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': list(GROUPS)}})
    collection.insert_many([{'public_id': group_id, 'name': f'oc-right-{group_id}', 'label': f'OC {group_id}',
                             'rights': rights} for group_id, rights in GROUPS.items()])

    with rest_api.application.test_request_context():
        yield

    collection.delete_many({'public_id': {'$in': list(GROUPS)}})


def _member(group_id: int) -> CmdbUser:
    """A member of ``group_id`` - the check reads the group, not the user"""
    return CmdbUser(public_id=group_id, user_name=f'oc-right-{group_id}', active=True, group_id=group_id,
                    registration_time=datetime.now(timezone.utc))


def _passed(group_id: int) -> set[OcRight]:
    """The OpenCelium rights a member of the group holds"""
    return {right for right in OcRight if user_has_right(right.value, _member(group_id))}


@pytest.mark.parametrize('right', list(OcRight), ids=[right.name for right in OcRight])
def test_one_right_passes_that_right_alone(right: OcRight) -> None:
    """view does not imply add, a connection right no connector right"""
    assert _passed(SINGLE_GROUP_IDS[right]) == {right}


@pytest.mark.parametrize('group_id, expected', [
    (CONNECTION_WILDCARD_GROUP_ID, CONNECTION_RIGHTS),
    (CONNECTOR_WILDCARD_GROUP_ID, CONNECTOR_RIGHTS),
    (OC_WILDCARD_GROUP_ID, set(OcRight)),
    (ADMIN_GROUP_ID, set(OcRight)),
], ids=['connection-wildcard', 'connector-wildcard', 'open-celium-wildcard', 'admin'])
def test_a_wildcard_passes_its_family(group_id: int, expected: set[OcRight]) -> None:
    """Resolved through the right tree"""
    assert _passed(group_id) == expected
