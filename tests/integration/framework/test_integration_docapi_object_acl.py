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
Integration tests for the object ACL inside a DocAPI document, against a real MongoDB

A document is built from more than its root object: the objects it references, the objects the
template names by id, the partners of the relations it follows and the rows of the report tables it
embeds. Each of those is read here through the real managers for two users - the admin group, which
may read the hidden type, and the default user group, which may not - and only the first may see the
hidden object's values
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.models.docapi_model.default_template_data import DefaultTemplateData
from cmdb.models.docapi_model.docapi_cache_helper import cache_objects_and_types
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

VISIBLE_TYPE_ID: int = 89001
HIDDEN_TYPE_ID: int = 89002
VISIBLE_ID: int = 89011
HIDDEN_ID: int = 89012

NAME_FIELD: str = 'dg-name'
UPLINK_FIELD: str = 'uplink'
HIDDEN_VALUE: str = 'hidden-acl-value'
VISIBLE_VALUE: str = 'visible-acl-value'
REFERENCE_DEPTH: int = 2


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """Pushes the REST API app context so ManagerProvider (current_app.database_manager) resolves."""
    with rest_api.application.app_context():
        yield


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """A visible type whose object references an object of a type only the admin group may read."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [VISIBLE_TYPE_ID, HIDDEN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': [VISIBLE_ID, HIDDEN_ID]}})

    _purge()
    fields: list[dict[str, Any]] = [
        {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
        {'type': 'ref', 'name': UPLINK_FIELD, 'label': 'Uplink', 'ref_types': [HIDDEN_TYPE_ID]},
    ]
    sections: list[dict[str, Any]] = [
        {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD, UPLINK_FIELD]},
    ]
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_TYPE_ID, 'docapi-acl-hidden', fields=fields, sections=sections)
    hidden_type['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    types.insert_many([
        make_type_doc(VISIBLE_TYPE_ID, 'docapi-acl-visible', fields=fields, sections=sections), hidden_type,
    ])
    now: datetime = datetime.now(timezone.utc)
    objects.insert_many([
        {'public_id': HIDDEN_ID, 'type_id': HIDDEN_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': now, 'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': HIDDEN_VALUE}]},
        {'public_id': VISIBLE_ID, 'type_id': VISIBLE_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': now, 'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': VISIBLE_VALUE},
                                          {'type': 'ref', 'name': UPLINK_FIELD, 'value': HIDDEN_ID}]},
    ])
    yield
    _purge()


def _user(group_id: int) -> CmdbUser:
    """A request user of the given group."""
    return CmdbUser(public_id=1, user_name='docapi-acl', active=True, group_id=group_id)


ADMIN: CmdbUser = _user(ADMIN_GROUP_ID)
DEFAULT_USER: CmdbUser = _user(USER_GROUP_ID)


def _objects_manager(user: CmdbUser) -> ObjectsManager:
    """The objects manager a document is built with."""
    return ManagerProvider.get_manager(ManagerType.OBJECTS, user)


def _object_template_data(user: CmdbUser) -> ObjectTemplateData:
    """
    The template data of the visible object, built for `user`

    Rendered WITH reference resolution, so the reference field keeps the id the extraction resolves -
    a render without it clears a plain reference field's value, and then nothing is left to resolve
    """
    objects_manager: ObjectsManager = _objects_manager(user)
    visible: CmdbObject = objects_manager.get_object(VISIBLE_ID, as_dict=False)
    render = CmdbMultiRender([visible], user, True).result(single_object=True)

    return ObjectTemplateData(render, objects_manager, user, DocapiTemplateType.OBJECT)


class TestAReferencedObject:
    """The object a reference field points at."""

    def test_the_admin_resolves_it(self) -> None:
        """The control: a reader of the hidden type gets its values"""
        resolved: dict[str, Any] | None = _object_template_data(ADMIN)._resolve_reference(HIDDEN_ID, REFERENCE_DEPTH)

        assert resolved is not None
        assert resolved['fields'][NAME_FIELD] == HIDDEN_VALUE

    def test_the_default_user_does_not(self) -> None:
        """Denied reads like missing - no value of the hidden object is in the data"""
        assert _object_template_data(DEFAULT_USER)._resolve_reference(HIDDEN_ID, REFERENCE_DEPTH) is None

    def test_the_default_users_template_data_carries_no_hidden_value(self) -> None:
        """
        Across the whole extraction of the visible object, the hidden value appears nowhere

        The hidden type configures no summary on purpose: a summary is what the RENDERER's reference
        expansion carries, and that expansion reads the referenced object without the ACL - a
        separate problem from the document's own reads, which is what this pins
        """
        assert HIDDEN_VALUE not in repr(_object_template_data(DEFAULT_USER).get_template_data())


class TestTheSharedBulkLoad:
    """What a template names by id, and what a relation reaches, goes through one loader."""

    @pytest.mark.parametrize('user, expected', [(ADMIN, {VISIBLE_ID, HIDDEN_ID}), (DEFAULT_USER, {VISIBLE_ID})],
                             ids=['admin', 'default-user'])
    def test_only_readable_objects_are_cached(self, user: CmdbUser, expected: set[int]) -> None:
        """A denied object never enters the cache, so no accessor can hand it to the template"""
        object_cache: dict[int, dict] = {}
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, user)

        cache_objects_and_types([VISIBLE_ID, HIDDEN_ID], object_cache, {}, _objects_manager(user), types_manager, user)

        assert set(object_cache) == expected


class TestAReportTable:
    """The rows of a `{{ report(<id>) }}` table."""

    @pytest.mark.parametrize('user, expected', [(ADMIN, {VISIBLE_ID, HIDDEN_ID}), (DEFAULT_USER, {VISIBLE_ID})],
                             ids=['admin', 'default-user'])
    def test_only_readable_rows_are_listed(self, user: CmdbUser, expected: set[int]) -> None:
        """A report table in a document lists the rows its reader could list"""
        template_data: DefaultTemplateData = DefaultTemplateData.__new__(DefaultTemplateData)
        template_data.request_user = user
        template_data.objects_manager = _objects_manager(user)
        report: dict[str, Any] = {'report_query': {'data': repr({'public_id': {'$in': [VISIBLE_ID, HIDDEN_ID]}})}}

        rows = template_data._run_report_query(report)

        assert {row.public_id for row in rows} == expected

