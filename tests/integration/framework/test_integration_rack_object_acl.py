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
Integration tests for the rack read surfaces under the caller's READ ACL, against a real MongoDB

The real `resolve_denied_type_ids`, `ObjectsManager.iterate_query` and `resolve_mounted_object_meta`, for a group
the member type's ACL leaves out: the picker's page and its total both exclude the unreadable candidate, the
overview metadata keeps the member's type id and blanks the rest, and the same reads for a group that may read
everything change nothing
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import resolve_mounted_object_meta

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

HIDDEN_TYPE_ID: int = 89901
SHOWN_TYPE_ID: int = 89902
HIDDEN_OBJECT_ID: int = 89911
SHOWN_OBJECT_ID: int = 89912
GROUP_ID: int = 89921
NAME_FIELD: str = 'dg-name'


def _object(public_id: int, type_id: int, name: str) -> dict[str, Any]:
    """A CmdbObject with a name field"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': [{'type': 'text', 'name': NAME_FIELD,
                                                                     'value': name}]}


@pytest.fixture(name='seeded')
def fixture_seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A type only the administrators may read, an open one, one object each; a group of neither"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    fields = [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}]
    sections = [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [HIDDEN_TYPE_ID, SHOWN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': [HIDDEN_OBJECT_ID, SHOWN_OBJECT_ID]}})
        groups.delete_many({'public_id': GROUP_ID})

    _purge()
    hidden = make_type_doc(HIDDEN_TYPE_ID, 'rack-acl-int-hidden', fields=fields, sections=sections)
    hidden['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    types.insert_many([hidden, make_type_doc(SHOWN_TYPE_ID, 'rack-acl-int-shown', fields=fields, sections=sections)])
    objects.insert_many([
        _object(HIDDEN_OBJECT_ID, HIDDEN_TYPE_ID, 'secret'), _object(SHOWN_OBJECT_ID, SHOWN_TYPE_ID, 'public'),
    ])
    groups.insert_one({'public_id': GROUP_ID, 'name': 'rack-acl-int', 'label': 'Rack ACL', 'rights': []})

    with rest_api.application.test_request_context():
        yield ObjectsManager(database_manager), TypesManager(database_manager)

    _purge()


def _member_of(group_id: int) -> CmdbUser:
    """A member of the group - the ACL reads the group"""
    return CmdbUser(public_id=group_id, user_name=f'rack-acl-{group_id}', active=True, group_id=group_id)


CANDIDATES: dict[str, Any] = {'public_id': {'$in': [HIDDEN_OBJECT_ID, SHOWN_OBJECT_ID]}}


def test_the_picker_page_and_total_exclude_the_unreadable_candidate(seeded) -> None:
    """Both aggregations carry the ACL"""
    objects_manager, _ = seeded

    docs, total = objects_manager.iterate_query(
        BuilderParameters(criteria=CANDIDATES), _member_of(GROUP_ID), AccessControlPermission.READ,
    )

    assert [doc['public_id'] for doc in docs] == [SHOWN_OBJECT_ID]
    assert total == 1


def test_the_administrator_reads_both(seeded) -> None:
    """The same query for a group the ACL names"""
    objects_manager, _ = seeded

    docs, total = objects_manager.iterate_query(
        BuilderParameters(criteria=CANDIDATES), _member_of(ADMIN_GROUP_ID), AccessControlPermission.READ,
    )

    assert sorted(doc['public_id'] for doc in docs) == [HIDDEN_OBJECT_ID, SHOWN_OBJECT_ID]
    assert total == 2


def test_the_overview_meta_blanks_the_unreadable_member(seeded) -> None:
    """Real denied types, real summary lines: the hidden member keeps its type id and loses its names"""
    objects_manager, types_manager = seeded
    mounts = [{'public_id': 1, 'object_id': HIDDEN_OBJECT_ID}, {'public_id': 2, 'object_id': SHOWN_OBJECT_ID}]

    denied: list[int] = resolve_denied_type_ids(_member_of(GROUP_ID), AccessControlPermission.READ)

    summary_lines, type_meta, object_types = resolve_mounted_object_meta(objects_manager, types_manager, mounts, denied)

    assert HIDDEN_OBJECT_ID not in summary_lines and 'public' in summary_lines[SHOWN_OBJECT_ID]
    assert type_meta[HIDDEN_TYPE_ID] == {} and type_meta[SHOWN_TYPE_ID]
    assert object_types == {HIDDEN_OBJECT_ID: HIDDEN_TYPE_ID, SHOWN_OBJECT_ID: SHOWN_TYPE_ID}
