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
Functional coverage of ``PUT /ci_explorer/label_field/<public_id>`` and the rule behind it

``CmdbType.ci_explorer_label`` holds the NAME of one of the Type's own fields; the CI Explorer reads
that field off every object of the Type and draws its value on the node. This suite pins the whole
loop the frontend will use: nominate a field, see it on the rendered nodes, clear it, and be refused
when the nomination names something the Type does not offer.

The two write paths are covered together on purpose - ``PUT /types/<id>`` (what the type builder
sends today) and this route (what the CI Explorer will send) have to agree on the same rule, or a
nomination refused in one place could be smuggled in through the other.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

LABEL_FIELD_URL: str = '/ci_explorer/label_field'
TYPES_URL: str = '/types'
OBJECTS_URL: str = '/objects'

TYPE_ID: int = 9660
OBJECT_ID: int = 9661
MISSING_TYPE_ID: int = 987654

TYPE_NAME: str = 'label-field-type'
PLAIN_FIELD: str = 'hostname'
SECOND_FIELD: str = 'serial'
MDS_FIELD: str = 'port-name'

HOSTNAME_VALUE: str = 'db-01'
SERIAL_VALUE: str = 'SN-4711'

AUTHOR_ID: int = 1
VERSION: str = '1.0.0'


def _type_payload(**overrides: Any) -> dict[str, Any]:
    """A Type with two ordinary fields and one multi-data-section field."""
    payload: dict[str, Any] = {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Label Field Type',
        'author_id': AUTHOR_ID,
        'active': True,
        'version': VERSION,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [
            {'type': 'text', 'name': PLAIN_FIELD, 'label': 'Hostname'},
            {'type': 'text', 'name': SECOND_FIELD, 'label': 'Serial'},
            {'type': 'text', 'name': MDS_FIELD, 'label': 'Port'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [
                {'type': 'section', 'name': 'information', 'label': 'Information',
                 'fields': [PLAIN_FIELD, SECOND_FIELD]},
                {'type': 'multi-data-section', 'name': 'ports', 'label': 'Ports',
                 'fields': [MDS_FIELD]},
            ],
            'summary': {'fields': [PLAIN_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }
    payload.update(overrides)

    return payload


@pytest.fixture(name='label_field_type', autouse=True)
def fixture_label_field_type(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Creates the Type through the route and removes it (and its objects) afterwards."""
    def _purge() -> None:
        database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .delete_many({'type_id': TYPE_ID})
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .delete_many({'public_id': TYPE_ID})

    _purge()
    assert rest_api.post(f'{TYPES_URL}/', json=_type_payload()).status_code == HTTPStatus.CREATED

    yield

    _purge()


def _nominate(rest_api, field_name: Any):
    """Sends the nomination through the CI Explorer route"""
    return rest_api.put(f'{LABEL_FIELD_URL}/{TYPE_ID}', json={'ci_explorer_label': field_name})


def _stored_nomination(rest_api) -> Any:
    """Reads the Type back through the route and returns its nomination"""
    response = rest_api.get(f'{TYPES_URL}/{TYPE_ID}')

    assert response.status_code == HTTPStatus.OK

    return response.get_json()['result']['ci_explorer_label']


# -------------------------------------------------------------------------------------------------------------------- #
#                                            PUT /ci_explorer/label_field                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheCiExplorerRoute:
    """What the frontend will call when it lets a user pick the field from the graph."""

    def test_a_field_of_the_type_is_nominated(self, rest_api) -> None:
        """The stored value is the FIELD NAME, and the answer repeats it"""
        response = _nominate(rest_api, PLAIN_FIELD)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['ci_explorer_label'] == PLAIN_FIELD
        assert _stored_nomination(rest_api) == PLAIN_FIELD

    def test_the_answer_lists_what_the_type_offers(self, rest_api) -> None:
        """
        So a client can refresh its picker from the same answer

        The multi-data-section field is not in the list: its values live per row and a node can only
        show one.
        """
        selectable = _nominate(rest_api, PLAIN_FIELD).get_json()['selectable_fields']

        assert selectable == [PLAIN_FIELD, SECOND_FIELD]

    @pytest.mark.parametrize('sent', [None, ''], ids=['null', 'empty'])
    def test_the_nomination_can_be_cleared(self, rest_api, sent: Any) -> None:
        """Both spellings of "no field chosen" store None, and the nodes go back to unlabelled"""
        assert _nominate(rest_api, PLAIN_FIELD).status_code == HTTPStatus.OK

        response = _nominate(rest_api, sent)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['ci_explorer_label'] is None
        assert _stored_nomination(rest_api) is None

    def test_a_name_the_type_does_not_have_is_refused(self, rest_api) -> None:
        """
        The defect this rule exists for: a display string sent where a field name belongs

        Stored, it would render every node of the Type as "Label not selected" with nothing anywhere
        saying why.
        """
        response = _nominate(rest_api, 'Switch')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'Switch' in response.get_json()['message']
        assert _stored_nomination(rest_api) is None

    def test_a_multi_data_section_field_is_refused(self, rest_api) -> None:
        """It would resolve - to a flat entry carrying none of the section's rows"""
        response = _nominate(rest_api, MDS_FIELD)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'multi-data-section' in response.get_json()['message']

    def test_an_unknown_type_is_404(self, rest_api) -> None:
        """The lookup answers before the rule does"""
        response = rest_api.put(
            f'{LABEL_FIELD_URL}/{MISSING_TYPE_ID}', json={'ci_explorer_label': PLAIN_FIELD},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_the_write_is_targeted(self, rest_api) -> None:
        """Only the one key is written - the Type's fields, sections and version are untouched"""
        before = rest_api.get(f'{TYPES_URL}/{TYPE_ID}').get_json()['result']

        assert _nominate(rest_api, SECOND_FIELD).status_code == HTTPStatus.OK

        after = rest_api.get(f'{TYPES_URL}/{TYPE_ID}').get_json()['result']

        assert after['fields'] == before['fields']
        assert after['render_meta'] == before['render_meta']
        assert after['version'] == before['version']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PUT/POST /types/                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheTypeRoutes:
    """The type builder's path has to enforce the same rule, or the refusal is one route wide."""

    def test_a_create_with_an_unknown_field_is_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Nothing is stored - the Type is refused as a whole"""
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .delete_many({'public_id': TYPE_ID})

        response = rest_api.post(f'{TYPES_URL}/', json=_type_payload(ci_explorer_label='Switch'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_update_choosing_an_unknown_field_is_refused(self, rest_api) -> None:
        """Choosing a bad nomination on an update is as much a client bug as on a create"""
        response = rest_api.put(f'{TYPES_URL}/{TYPE_ID}', json=_type_payload(ci_explorer_label='Switch'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_removing_the_nominated_field_clears_the_nomination(self, rest_api) -> None:
        """
        The update is NOT refused over a cosmetic key

        Dropping a field is a legitimate edit; the nomination is unchanged, it only stopped
        resolving, so it is cleared instead of blocking the whole write.
        """
        assert _nominate(rest_api, PLAIN_FIELD).status_code == HTTPStatus.OK

        without_the_field = _type_payload(
            ci_explorer_label=PLAIN_FIELD,
            fields=[{'type': 'text', 'name': SECOND_FIELD, 'label': 'Serial'}],
        )
        without_the_field['render_meta']['sections'] = [
            {'type': 'section', 'name': 'information', 'label': 'Information', 'fields': [SECOND_FIELD]},
        ]
        without_the_field['render_meta']['summary'] = {'fields': [SECOND_FIELD]}

        response = rest_api.put(f'{TYPES_URL}/{TYPE_ID}', json=without_the_field)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_nomination(rest_api) is None

    def test_a_create_without_a_nomination_stores_the_key(self, rest_api) -> None:
        """One stored spelling of "no field chosen", whichever route wrote the Type"""
        assert _stored_nomination(rest_api) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  WHAT THE GRAPH SHOWS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRenderedNode:
    """The nomination is only worth enforcing because of what it does to the graph."""

    @pytest.fixture(name='one_object', autouse=True)
    def fixture_one_object(self, rest_api):
        """One object of the Type, carrying a value in both ordinary fields"""
        response = rest_api.post(f'{OBJECTS_URL}/', json={
            'public_id': OBJECT_ID,
            'type_id': TYPE_ID,
            'active': True,
            'author_id': AUTHOR_ID,
            'version': VERSION,
            'fields': [
                {'name': PLAIN_FIELD, 'value': HOSTNAME_VALUE},
                {'name': SECOND_FIELD, 'value': SERIAL_VALUE},
            ],
        })

        assert response.status_code == HTTPStatus.OK

    def test_the_node_title_is_the_objects_own_value(self, rest_api) -> None:
        """
        The whole point: ONE nomination, a different title per object

        A static label would put the same string on every node of the Type.
        """
        assert _nominate(rest_api, PLAIN_FIELD).status_code == HTTPStatus.OK

        response = rest_api.get(f'/ci_explorer/items?target_id={OBJECT_ID}&with_root=true')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['root_node']['title'] == HOSTNAME_VALUE

    def test_nominating_another_field_changes_the_title(self, rest_api) -> None:
        """The graph follows the nomination without the objects being touched"""
        assert _nominate(rest_api, SECOND_FIELD).status_code == HTTPStatus.OK

        response = rest_api.get(f'/ci_explorer/items?target_id={OBJECT_ID}&with_root=true')

        assert response.get_json()['root_node']['title'] == SERIAL_VALUE

    def test_without_a_nomination_the_node_has_no_title(self, rest_api) -> None:
        """Which the frontend draws as "Label not selected" - the state a bad nomination produced"""
        response = rest_api.get(f'/ci_explorer/items?target_id={OBJECT_ID}&with_root=true')

        assert response.get_json()['root_node']['title'] is None
