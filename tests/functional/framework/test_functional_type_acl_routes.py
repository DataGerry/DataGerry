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
Functional tests: a Type the caller's group may not READ under its ACL is hidden on every route, not just the listing

The editor's group holds every type, export, import and category right, so only the Type's own ACL stands between it
and the hidden Type. Pinned, through the real decorator chain:

  - every route that addresses one Type by id answers 403 for the hidden Type - the read, the four pre-checks, the
    update, the delete and the CI Explorer label-field write - and the update cannot rewrite the ACL that keeps
    the editor out
  - the whole-catalogue export leaves the hidden Type out; a selected export naming it is refused
  - the import update reports the hidden Type as a failed entry and writes nothing
  - the category tree leaves the hidden Type out of its category
  - the reference-section pre-check counts a hidden dependent without naming it
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerRight
from cmdb.interface.rest_api.routes.exporter_routes.exporter_constants import ExporterRight
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import CategoryRight
from cmdb.interface.rest_api.routes.importer_routes.importer_constants import ImporterRight
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError
from tests.utils.ipam_doc_builders import make_type_doc
from tests.functional.framework.test_functional_importer_type_route import _errors, _upload_form
# -------------------------------------------------------------------------------------------------------------------- #

HIDDEN_TYPE_ID: int = 89811
OPEN_TYPE_ID: int = 89812
HIDDEN_DEPENDENT_ID: int = 89813
TYPE_IDS: list[int] = [HIDDEN_TYPE_ID, OPEN_TYPE_ID, HIDDEN_DEPENDENT_ID]

EDITOR_GROUP_ID: int = 89801
EDITOR_ID: int = 89802
EDITOR_NAME: str = 'type-acl-editor'
CATEGORY_ID: int = 89821

REFERENCED_SECTION: str = 'information'
ACL_KEY: str = TypeSchemaKey.ACL.value

EDITOR_RIGHTS: list[str] = [
    TypeRight.VIEW.value, TypeRight.EDIT.value, TypeRight.DELETE.value,
    ExporterRight.TYPE.value, ImporterRight.TYPE.value, CategoryRight.VIEW.value, CiExplorerRight.EDIT.value,
]

# The admin group alone may read the hidden types; the open type grants the editor's group as well
ADMIN_ONLY_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
OPEN_ACL: dict[str, Any] = {
    'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ'], str(EDITOR_GROUP_ID): ['READ']}},
}
# What an editor kept out would like the hidden type's ACL to say
SELF_GRANTING_ACL: dict[str, Any] = {
    'activated': True,
    'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ'], str(EDITOR_GROUP_ID): ['READ', 'UPDATE', 'DELETE']}},
}

TYPES_URL: str = '/types'
SINGLE_TYPE_READS: list[str] = [
    f'{TYPES_URL}/{HIDDEN_TYPE_ID}',
    f'{TYPES_URL}/count_objects/{HIDDEN_TYPE_ID}',
    f'{TYPES_URL}/location_field_usage/{HIDDEN_TYPE_ID}',
    f'{TYPES_URL}/referenced_section_usage/{HIDDEN_TYPE_ID}',
    f'{TYPES_URL}/uses_ports_usage/{HIDDEN_TYPE_ID}',
]
EXPORT_URL: str = '/export/type'
IMPORT_UPDATE_URL: str = '/import/type/update/'
TREE_URL: str = '/categories/?view=tree'
LABEL_FIELD_URL: str = '/ci_explorer/label_field'
LABEL_KEY: str = TypeSchemaKey.CI_EXPLORER_LABEL.value
NAME_FIELD: str = 'dg-name'


def _type(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A stored type carrying that ACL."""
    doc = make_type_doc(public_id, f'type-acl-{public_id}')
    doc[ACL_KEY] = acl

    return doc


def _hidden_dependent() -> dict[str, Any]:
    """A hidden type pulling the open type's section through a reference section."""
    doc = _type(HIDDEN_DEPENDENT_ID, ADMIN_ONLY_ACL)
    doc['render_meta']['sections'].append({
        'type': SectionType.REF_SECTION.value, 'name': 'the-ref', 'label': 'The ref', 'fields': [],
        'reference': {'type_id': OPEN_TYPE_ID, 'section_name': REFERENCED_SECTION, 'selected_fields': []},
    })

    return doc


def _editor() -> CmdbUser:
    """A member of the group holding every right involved - the hidden types' ACL grants it nothing."""
    return CmdbUser(public_id=EDITOR_ID, user_name=EDITOR_NAME, active=True, group_id=EDITOR_GROUP_ID)


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the three types, the editor and its group, and a category holding the hidden and the open type."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        groups.delete_many({'public_id': EDITOR_GROUP_ID})
        users.delete_many({'public_id': EDITOR_ID})
        categories.delete_many({'public_id': CATEGORY_ID})

    _purge()
    types.insert_many([_type(HIDDEN_TYPE_ID, ADMIN_ONLY_ACL), _type(OPEN_TYPE_ID, OPEN_ACL), _hidden_dependent()])
    groups.insert_one({'public_id': EDITOR_GROUP_ID, 'name': EDITOR_NAME, 'label': EDITOR_NAME,
                       'rights': EDITOR_RIGHTS})
    users.insert_one({'public_id': EDITOR_ID, 'user_name': EDITOR_NAME, 'active': True, 'group_id': EDITOR_GROUP_ID,
                      'registration_time': datetime.now(timezone.utc)})
    categories.insert_one({'public_id': CATEGORY_ID, 'name': 'type-acl-category', 'label': 'Type ACL',
                           'parent': None, 'types': [HIDDEN_TYPE_ID, OPEN_TYPE_ID],
                           'meta': {'icon': '', 'order': None}})
    yield types
    _purge()


def _stored(types: Any, public_id: int) -> dict[str, Any]:
    """The stored type, without its Mongo _id."""
    return types.find_one({'public_id': public_id}, {'_id': 0})


class TestEveryRouteOnAHiddenTypeIsRefused:
    """403 naming the type, by id, whatever the route."""

    @pytest.mark.parametrize('url', SINGLE_TYPE_READS)
    def test_a_read_is_refused(self, rest_api, types, url: str) -> None:
        """The read and each pre-check"""
        del types
        response = rest_api.get(url, user=_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert str(HIDDEN_TYPE_ID) in response.get_json()['message']

    @pytest.mark.parametrize('url', SINGLE_TYPE_READS)
    def test_the_admin_group_the_acl_grants_reads_it(self, rest_api, types, url: str) -> None:
        """The control: the same routes answer the group the ACL lets in"""
        del types

        assert rest_api.get(url).status_code == HTTPStatus.OK

    def test_the_open_type_is_readable_by_the_editor(self, rest_api, types) -> None:
        """The control: the editor's rights are enough wherever the ACL grants its group"""
        del types

        assert rest_api.get(f'{TYPES_URL}/{OPEN_TYPE_ID}', user=_editor()).status_code == HTTPStatus.OK

    def test_the_update_cannot_rewrite_the_acl_that_keeps_the_editor_out(self, rest_api, types) -> None:
        """Judged on the stored ACL: refused, and the stored type keeps its ACL"""
        body = _stored(types, HIDDEN_TYPE_ID)
        body[ACL_KEY] = SELF_GRANTING_ACL
        # server-owned: the identity is the URL's, the creation time is never the payload's
        body.pop(TypeSchemaKey.PUBLIC_ID.value)
        body.pop(TypeSchemaKey.CREATION_TIME.value)

        response = rest_api.put(f'{TYPES_URL}/{HIDDEN_TYPE_ID}', json=body, user=_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(types, HIDDEN_TYPE_ID)[ACL_KEY] == ADMIN_ONLY_ACL

    def test_the_ci_explorer_label_write_is_refused_and_nothing_is_written(self, rest_api, types) -> None:
        """The presentation write names the type's fields in its answer - refused like the rest"""
        response = rest_api.put(f'{LABEL_FIELD_URL}/{HIDDEN_TYPE_ID}', json={LABEL_KEY: NAME_FIELD}, user=_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(types, HIDDEN_TYPE_ID).get(LABEL_KEY) != NAME_FIELD

    def test_the_ci_explorer_label_write_on_the_open_type_is_applied(self, rest_api, types) -> None:
        """The control"""
        response = rest_api.put(f'{LABEL_FIELD_URL}/{OPEN_TYPE_ID}', json={LABEL_KEY: NAME_FIELD}, user=_editor())

        assert response.status_code == HTTPStatus.OK
        assert _stored(types, OPEN_TYPE_ID)[LABEL_KEY] == NAME_FIELD

    def test_the_delete_is_refused_and_the_type_stays(self, rest_api, types) -> None:
        """An empty, unreferenced type the delete guard would let go"""
        response = rest_api.delete(f'{TYPES_URL}/{HIDDEN_TYPE_ID}', user=_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(types, HIDDEN_TYPE_ID) is not None


class TestTheExportLeavesAHiddenTypeOut:
    """The catalogue is what the group may read; a selection naming a hidden type is refused."""

    def test_the_catalogue_export_leaves_it_out(self, rest_api, types) -> None:
        """The open type is in it, the hidden ones are not"""
        del types
        response = rest_api.post(f'{EXPORT_URL}/', user=_editor())

        assert response.status_code == HTTPStatus.OK
        exported: set[int] = {entry['public_id'] for entry in response.get_json()}
        assert OPEN_TYPE_ID in exported
        assert not exported & {HIDDEN_TYPE_ID, HIDDEN_DEPENDENT_ID}

    def test_a_selection_naming_it_is_refused(self, rest_api, types) -> None:
        """403 naming the hidden id - and only that one"""
        del types
        response = rest_api.post(f'{EXPORT_URL}/{OPEN_TYPE_ID},{HIDDEN_TYPE_ID}', user=_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        message: str = response.get_json()['message']
        assert str(HIDDEN_TYPE_ID) in message
        assert str(OPEN_TYPE_ID) not in message

    def test_a_selection_of_readable_types_is_exported(self, rest_api, types) -> None:
        """The control"""
        del types
        response = rest_api.post(f'{EXPORT_URL}/{OPEN_TYPE_ID}', user=_editor())

        assert response.status_code == HTTPStatus.OK
        assert [entry['public_id'] for entry in response.get_json()] == [OPEN_TYPE_ID]


class TestTheImportUpdateRefusesAHiddenType:
    """One failed entry; the stored type, its ACL included, is untouched."""

    def test_an_upload_rewriting_the_acl_is_reported_and_not_written(self, rest_api, types) -> None:
        """The uploaded ACL would let the editor in - the stored one decides"""
        upload = _stored(types, HIDDEN_TYPE_ID)
        upload[ACL_KEY] = SELF_GRANTING_ACL
        upload['label'] = 'rewritten'

        response = rest_api.post(IMPORT_UPDATE_URL, data=_upload_form([upload]),
                                 content_type='multipart/form-data', user=_editor())

        assert response.status_code == HTTPStatus.OK
        assert _errors(response) == [TypeImportError.TYPE_ACCESS_DENIED.format(public_id=HIDDEN_TYPE_ID)]
        stored = _stored(types, HIDDEN_TYPE_ID)
        assert stored[ACL_KEY] == ADMIN_ONLY_ACL
        assert stored['label'] != 'rewritten'


class TestTheCategoryTreeLeavesAHiddenTypeOut:
    """The category stays; the hidden type is not among its types."""

    @staticmethod
    def _type_ids(response: Any) -> list[int]:
        node = next(node for node in response.get_json()['results'] if node['category']['public_id'] == CATEGORY_ID)

        return [a_type['public_id'] for a_type in node['types']]

    def test_the_editor_sees_the_open_type_only(self, rest_api, types) -> None:
        """The hidden type is assigned to the category and not shown in it"""
        del types

        assert self._type_ids(rest_api.get(TREE_URL, user=_editor())) == [OPEN_TYPE_ID]

    def test_the_admin_group_sees_both(self, rest_api, types) -> None:
        """The control"""
        del types

        assert sorted(self._type_ids(rest_api.get(TREE_URL))) == [HIDDEN_TYPE_ID, OPEN_TYPE_ID]


class TestTheReferencePreCheckCountsAHiddenDependentWithoutNamingIt:
    """The guard refuses on it, so it counts; the editor may not read it, so it is not named."""

    def test_the_open_type_reports_one_unnamed_dependent(self, rest_api, types) -> None:
        """count 1, no id, the section present and empty"""
        del types
        response = rest_api.get(f'{TYPES_URL}/referenced_section_usage/{OPEN_TYPE_ID}', user=_editor())

        assert response.status_code == HTTPStatus.OK
        payload: dict[str, Any] = response.get_json()
        assert payload['in_use'] is True
        assert payload['count'] == 1
        assert payload['referencing_type_ids'] == []
        assert payload['sections'] == {REFERENCED_SECTION: []}

    def test_the_admin_group_sees_it_named(self, rest_api, types) -> None:
        """The control"""
        del types
        payload: dict[str, Any] = rest_api.get(f'{TYPES_URL}/referenced_section_usage/{OPEN_TYPE_ID}').get_json()

        assert payload['referencing_type_ids'] == [HIDDEN_DEPENDENT_ID]
