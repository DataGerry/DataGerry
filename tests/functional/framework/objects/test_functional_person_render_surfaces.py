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
Functional tests: every render surface outside the own selector fields shows only the persons the reader may see

Seeds a visible person type (Ada) and one only the admin group may READ (Eve), an asset type whose person field
``owner`` is in its summary, in an external link and its CI Explorer label, two assets (owned by Ada / by Ada + Eve),
and a ticket type referencing an asset with a nested summary line and pulling the asset's section in. An editor whose
group holds the object and CI Explorer view rights reads them. Pinned, for the editor and for the admin:

  - the own summaries and summary line show the visible labels
  - an external link filled with a hidden person is left out
  - a reference's summaries and line show the visible labels
  - a person field pulled into a reference section keeps the visible ids and carries ``persons``
  - the MDS reference route shows the visible labels
  - the CI Explorer title and the node's person field show the visible labels
  - no render marker is answered anywhere
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_selector.person_selector_constants import PersonRenderMarker
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerRight
from tests.utils.type_access_seed import SeededAccess, remove_type_access, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
CI_EXPLORER_URL: str = '/ci_explorer/items'

PERSON_TYPE: int = 48501
HIDDEN_TYPE: int = 48502
ASSET_TYPE: int = 48503
TICKET_TYPE: int = 48504
TYPE_IDS: list[int] = [PERSON_TYPE, HIDDEN_TYPE, ASSET_TYPE, TICKET_TYPE]

ADA: int = 48511
EVE: int = 48512
SHARED_ASSET: int = 48521
ADA_ASSET: int = 48522
TICKET: int = 48531
OBJECT_IDS: list[int] = [ADA, EVE, SHARED_ASSET, ADA_ASSET, TICKET]

EDITOR_GROUP: int = 48541
EDITOR: int = 48542

NAME: str = 'name'
OWNER: str = 'owner'
ASSET_FIELD: str = 'asset'
REF_SECTION: str = 'pulled'
REF_SECTION_FIELD: str = f'{REF_SECTION}-field'
LINK_NAME: str = 'profile'
LINE_TEMPLATE: str = 'Owned by {}'
SHARED_ASSET_NAME: str = 'srv-shared'
ADMIN_PERMISSIONS: list[str] = ['CREATE', 'READ', 'UPDATE', 'DELETE']


def _type(public_id: int, name: str, fields: list[dict[str, Any]], sections: list[dict[str, Any]],
          marker: str = '', admin_only: bool = False, **extra: Any) -> dict[str, Any]:
    """A type document"""
    meta: dict[str, Any] = {'icon': 'fa-cube', 'summary': {'fields': extra.pop('summary', [])},
                            'sections': sections, 'externals': extra.pop('externals', [])}

    return {
        'public_id': public_id, 'name': name, 'label': name.title(), 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker, 'fields': fields,
        'render_meta': meta,
        'acl': {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ADMIN_PERMISSIONS}}}
        if admin_only else {'activated': False, 'groups': {'includes': None}},
        **extra,
    }


def _section(name: str, fields: list[str]) -> dict[str, Any]:
    """A plain section"""
    return {'type': 'section', 'name': name, 'label': name.title(), 'fields': fields}


def _person_type(public_id: int, name: str, admin_only: bool = False) -> dict[str, Any]:
    """A PERSON type labelled by display_name"""
    return _type(public_id, name, [{'type': 'text', 'name': 'display_name', 'label': 'Name'}],
                 [_section('main', ['display_name'])], marker='PERSON', admin_only=admin_only)


def _types() -> list[dict[str, Any]]:
    """The two person types, the asset type and the ticket type"""
    asset_fields: list[dict[str, Any]] = [
        {'type': 'text', 'name': NAME, 'label': 'Name'},
        {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON'], 'multiple': True},
    ]
    ticket_fields: list[dict[str, Any]] = [
        {'type': 'ref', 'name': ASSET_FIELD, 'label': 'Asset', 'ref_types': [ASSET_TYPE],
         'summaries': [{'type_id': ASSET_TYPE, 'line': LINE_TEMPLATE, 'fields': [OWNER]}]},
        {'type': 'ref-section-field', 'name': REF_SECTION_FIELD, 'label': 'Pulled'},
    ]
    ticket_sections: list[dict[str, Any]] = [
        _section('main', [ASSET_FIELD]),
        {'type': 'ref-section', 'name': REF_SECTION, 'label': 'Pulled', 'fields': [],
         'reference': {'type_id': ASSET_TYPE, 'section_name': 'main', 'selected_fields': [OWNER]}},
    ]

    return [
        _person_type(PERSON_TYPE, 'fn-surface-person'),
        _person_type(HIDDEN_TYPE, 'fn-surface-hidden', admin_only=True),
        _type(ASSET_TYPE, 'fn-surface-asset', asset_fields, [_section('main', [NAME, OWNER])],
              summary=[NAME, OWNER], ci_explorer_label=OWNER,
              externals=[{'name': LINK_NAME, 'href': 'https://example.org/{}', 'label': 'Profile', 'icon': 'fa-link',
                          'fields': [OWNER]}]),
        _type(TICKET_TYPE, 'fn-surface-ticket', ticket_fields, ticket_sections),
    ]


def _object(public_id: int, type_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    """An object document"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
            'fields': [{'name': name, 'value': value} for name, value in fields.items()]}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The types (with the access rules their ACLs translate to), the objects and the editor; purged before and after"""
    collections = {kind: database_manager.get_collection(kind.COLLECTION, database_name)
                   for kind in (CmdbType, CmdbObject, CmdbUserGroup, CmdbUser)}

    def _purge() -> None:
        collections[CmdbType].delete_many({'public_id': {'$in': TYPE_IDS}})
        collections[CmdbObject].delete_many({'public_id': {'$in': OBJECT_IDS}})
        collections[CmdbUserGroup].delete_many({'public_id': EDITOR_GROUP})
        collections[CmdbUser].delete_many({'public_id': EDITOR})

    _purge()
    collections[CmdbType].insert_many(_types())
    collections[CmdbObject].insert_many([
        _object(ADA, PERSON_TYPE, {'display_name': 'Ada'}),
        _object(EVE, HIDDEN_TYPE, {'display_name': 'Eve'}),
        _object(SHARED_ASSET, ASSET_TYPE, {NAME: SHARED_ASSET_NAME, OWNER: [ADA, EVE]}),
        _object(ADA_ASSET, ASSET_TYPE, {NAME: 'srv-ada', OWNER: [ADA]}),
        _object(TICKET, TICKET_TYPE, {ASSET_FIELD: SHARED_ASSET, REF_SECTION_FIELD: SHARED_ASSET}),
    ])
    collections[CmdbUserGroup].insert_one({
        'public_id': EDITOR_GROUP, 'name': 'fn-surface-editors', 'label': 'Editors',
        'rights': [right.value for right in ObjectRightName] + [CiExplorerRight.VIEW.value],
    })
    collections[CmdbUser].insert_one({'public_id': EDITOR, 'user_name': 'fn-surface-editor', 'active': True,
                                      'group_ids': [EDITOR_GROUP], 'registration_time': datetime.now(timezone.utc)})
    access: SeededAccess = store_type_access(database_manager.connector.client[database_name], TYPE_IDS)
    yield
    remove_type_access(database_manager.connector.client[database_name], access)
    _purge()


def _as(reader: str) -> dict[str, Any]:
    """The request kwargs: the editor, or nothing for the admin the test client sends by default"""
    if reader == 'admin':
        return {}

    return {'user': CmdbUser(public_id=EDITOR, user_name='fn-surface-editor', active=True, group_ids=[EDITOR_GROUP])}


# What each reader sees of the shared asset's owners
LABELS: dict[str, str] = {'editor': 'Ada', 'admin': 'Ada, Eve'}
VISIBLE_IDS: dict[str, list[int]] = {'editor': [ADA], 'admin': [ADA, EVE]}
READERS: list[str] = ['editor', 'admin']


def _get(rest_api, url: str, reader: str) -> dict[str, Any]:
    """The answer of a GET, asserted 200, with no render marker anywhere in it"""
    response = rest_api.get(url, **_as(reader))

    assert response.status_code == HTTPStatus.OK
    body: str = response.get_data(as_text=True)
    assert all(marker.value not in body for marker in PersonRenderMarker)

    return json.loads(body)


@pytest.mark.usefixtures('seeded')
@pytest.mark.parametrize('reader', READERS)
class TestTheObjectsOwnSurfaces:
    """GET /objects/<asset>"""

    def test_the_summaries_and_the_line_show_the_visible_labels(self, rest_api, reader: str) -> None:
        """The person summary value is text"""
        rendered: dict[str, Any] = _get(rest_api, f'{OBJECTS_URL}/{SHARED_ASSET}', reader)

        assert [entry['value'] for entry in rendered['summaries']] == [SHARED_ASSET_NAME, LABELS[reader]]
        assert rendered['summary_line'] == f'{SHARED_ASSET_NAME} | {LABELS[reader]}'

    def test_a_link_filled_with_a_hidden_person_is_left_out(self, rest_api, reader: str) -> None:
        """The editor may not see Eve, the admin may"""
        shared: dict[str, Any] = _get(rest_api, f'{OBJECTS_URL}/{SHARED_ASSET}', reader)
        own: dict[str, Any] = _get(rest_api, f'{OBJECTS_URL}/{ADA_ASSET}', reader)

        assert [link['name'] for link in shared['externals']] == ([] if reader == 'editor' else [LINK_NAME])
        assert [link['name'] for link in own['externals']] == [LINK_NAME]


@pytest.mark.usefixtures('seeded')
@pytest.mark.parametrize('reader', READERS)
class TestTheReferencingObject:
    """GET /objects/<ticket>"""

    def test_the_reference_summaries_and_line_show_the_visible_labels(self, rest_api, reader: str) -> None:
        """The nested summary names the owner field"""
        fields: dict[str, Any] = {field['name']: field
                                  for field in _get(rest_api, f'{OBJECTS_URL}/{TICKET}', reader)['fields']}
        reference: dict[str, Any] = fields[ASSET_FIELD]['reference']

        assert [entry['value'] for entry in reference['summaries']] == [LABELS[reader]]
        assert reference['line'] == LINE_TEMPLATE.format(LABELS[reader])

    def test_a_pulled_person_field_keeps_the_visible_ids_with_persons(self, rest_api, reader: str) -> None:
        """The reference section's owner field"""
        fields: dict[str, Any] = {field['name']: field
                                  for field in _get(rest_api, f'{OBJECTS_URL}/{TICKET}', reader)['fields']}
        pulled: dict[str, Any] = fields[REF_SECTION_FIELD]['references']['fields'][0]

        assert pulled['value'] == VISIBLE_IDS[reader]
        assert [person['object_id'] for person in pulled['persons']] == VISIBLE_IDS[reader]


@pytest.mark.usefixtures('seeded')
@pytest.mark.parametrize('reader', READERS)
class TestTheOtherReaders:
    """The MDS reference route and the CI Explorer"""

    def test_the_mds_reference_shows_the_visible_labels(self, rest_api, reader: str) -> None:
        """The asset's own summary fields"""
        reference: dict[str, Any] = _get(rest_api, f'{OBJECTS_URL}/{SHARED_ASSET}/mds_reference', reader)

        assert [entry['value'] for entry in reference['summaries']] == [SHARED_ASSET_NAME, LABELS[reader]]

    def test_the_ci_explorer_title_and_field_show_the_visible_labels(self, rest_api, reader: str) -> None:
        """The asset's label field is its person field"""
        graph: dict[str, Any] = _get(rest_api, f'{CI_EXPLORER_URL}?target_id={SHARED_ASSET}&with_root=true', reader)
        root: dict[str, Any] = graph['root_node']
        owner: Any = next(field['value'] for field in root['linked_object']['fields'] if field['name'] == OWNER)

        assert root['title'] == LABELS[reader]
        assert owner == LABELS[reader]
