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
Integration tests for `ObjectsManager.guard_writable_type` against real stored CmdbTypes

The guard the object delete routes run for every target before their first side effect. What only a
real database shows: the ACL and the ``active`` flag are read from the stored type document, so a type
whose ACL grants READ but not DELETE, a deactivated type, and a missing type are each refused the
way the routes rely on - and a type granting DELETE passes and comes back resolved
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import ObjectWriteVerb
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

READ_ONLY_TYPE_ID: int = 96910
DELETABLE_TYPE_ID: int = 96911
DEACTIVATED_TYPE_ID: int = 96912
MISSING_TYPE_ID: int = 96919
TYPE_IDS: list[int] = [READ_ONLY_TYPE_ID, DELETABLE_TYPE_ID, DEACTIVATED_TYPE_ID]


def _type_document(public_id: int, permissions: list[str] | None, active: bool = True) -> dict[str, Any]:
    """A stored CmdbType; `permissions` None means no ACL at all."""
    acl: dict[str, Any] = (
        {'activated': False, 'groups': {'includes': None}} if permissions is None
        else {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): permissions}}}
    )

    return {
        'public_id': public_id, 'name': f'write-guard-{public_id}', 'label': f'Write Guard {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': active, 'fields': [],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}}, 'acl': acl, 'version': '1.0.0',
    }


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the three types and yields an ObjectsManager over the test database."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    types.insert_many([
        _type_document(READ_ONLY_TYPE_ID, [AccessControlPermission.READ.value]),
        _type_document(DELETABLE_TYPE_ID, [AccessControlPermission.READ.value, AccessControlPermission.DELETE.value]),
        _type_document(DEACTIVATED_TYPE_ID, None, active=False),
    ])
    yield ObjectsManager(database_manager)
    types.delete_many({'public_id': {'$in': TYPE_IDS}})


def _admin() -> CmdbUser:
    """A member of the admin group - the group each ACL above names."""
    return CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)


def _guard(objects_manager: ObjectsManager, type_id: int) -> CmdbType:
    """Asks the guard exactly what the delete routes ask it."""
    return objects_manager.guard_writable_type(
        type_id, _admin(), AccessControlPermission.DELETE, ObjectsManagerDeleteError, ObjectWriteVerb.REMOVED.value,
    )


class TestGuardWritableType:
    """The type's stored ACL and active flag decide, before anything is written"""

    def test_a_type_granting_delete_passes_and_is_resolved(self, objects_manager: ObjectsManager) -> None:
        """The resolved type comes back, so a caller does not read it a second time"""
        assert _guard(objects_manager, DELETABLE_TYPE_ID).public_id == DELETABLE_TYPE_ID

    def test_an_acl_without_delete_is_refused(self, objects_manager: ObjectsManager) -> None:
        """READ alone does not allow a delete"""
        with pytest.raises(AccessDeniedError):
            _guard(objects_manager, READ_ONLY_TYPE_ID)

    def test_a_deactivated_type_is_refused_with_the_verb(self, objects_manager: ObjectsManager) -> None:
        """The message names the operation the caller attempted"""
        with pytest.raises(AccessDeniedError) as refused:
            _guard(objects_manager, DEACTIVATED_TYPE_ID)

        assert f'cannot be {ObjectWriteVerb.REMOVED.value}' in str(refused.value)

    def test_a_missing_type_raises_the_callers_error(self, objects_manager: ObjectsManager) -> None:
        """Each caller names its own failure for a type that is gone"""
        with pytest.raises(ObjectsManagerDeleteError):
            _guard(objects_manager, MISSING_TYPE_ID)
