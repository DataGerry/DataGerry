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
Functional coverage of ``CmdbType.port_section_index`` on the Type routes

A port-bearing Type's ports are not one of its sections - they live in framework.ports and the object
form renders them from the ``dg-virtual-tpl-ports`` virtual template - so the position the user drops
that section into has nowhere to live on the Type itself. ``port_section_index`` is that position: 0
draws the ports section above every declared section, 1 after the first, and so on.

What is pinned here is the contract the frontend sees end to end: the value survives a create, an
update and the read back; an unusable one is refused rather than stored; and a Type that does not use
ports always reads 0, whatever the payload asked for - the index is only meaningful while the flag is
on, and a stale position would resurface if the flag were ever set again.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'

TYPE_NAME: str = 'port-section-index-type'
TYPE_LABEL: str = 'Port Section Index Type'

AUTHOR_ID: int = 1
VERSION: str = '1.0.0'

PLACED_INDEX: int = 2
MOVED_INDEX: int = 5


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so a Type may declare `uses_ports` at all (decision D6)."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_payload(**overrides: Any) -> dict[str, Any]:
    """A port-bearing Type with two ordinary sections, so a position between them means something."""
    payload: dict[str, Any] = {
        'name': TYPE_NAME,
        'label': TYPE_LABEL,
        'author_id': AUTHOR_ID,
        'active': True,
        'version': VERSION,
        'uses_ports': True,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [
            {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
            {'type': 'text', 'name': 'dg-note', 'label': 'Note'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [
                {'type': 'section', 'name': 'information', 'label': 'Information', 'fields': ['dg-name']},
                {'type': 'section', 'name': 'notes', 'label': 'Notes', 'fields': ['dg-note']},
            ],
            'summary': {'fields': ['dg-name']},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }
    payload.update(overrides)

    return payload


@pytest.fixture(name='cleanup_type', autouse=True)
def fixture_cleanup_type(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the Type after each test - every test creates it itself, with its own payload."""
    def _purge() -> None:
        # Keyed on the NAME: `public_id` is server-owned, so the payload cannot choose the id and the
        # test does not know it until the route answers
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .delete_many({'name': TYPE_NAME})

    _purge()
    yield
    _purge()


def _create(rest_api, **overrides: Any):
    """POSTs the Type payload with the given overrides"""
    return rest_api.post(f'{TYPES_URL}/', json=_type_payload(**overrides))


def _stored_type(rest_api) -> dict[str, Any]:
    """
    Reads the Type back through the list route, found by its NAME

    The id is assigned by the server (`public_id` is not part of a request body), and the name is
    unique - so the name is what a test can look the Type up by.
    """
    response = rest_api.get(f'{TYPES_URL}/?filter={{"name":"{TYPE_NAME}"}}')

    assert response.status_code == HTTPStatus.OK
    results: list[dict[str, Any]] = response.get_json()['results']

    assert len(results) == 1

    return results[0]


def _stored_id(rest_api) -> int:
    """The public_id the route assigned to the Type this module creates"""
    return _stored_type(rest_api)['public_id']


def _stored_index(rest_api) -> int:
    """Reads the Type back through the route and returns its stored position"""
    return _stored_type(rest_api)['port_section_index']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        CREATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreate:
    """POST /types/ stores the position, or refuses it."""

    def test_a_position_is_stored_and_read_back(self, rest_api) -> None:
        """The value the type builder sent is what the next GET returns"""
        assert _create(rest_api, port_section_index=PLACED_INDEX).status_code == HTTPStatus.CREATED
        assert _stored_index(rest_api) == PLACED_INDEX

    def test_an_omitted_position_is_stored_as_the_default(self, rest_api) -> None:
        """
        The created Type carries the key even though the payload did not

        POST /types/ stores the payload as given, so without the normalisation a created Type would
        not carry the key at all and only its first edit would add it - two stored shapes for one
        meaning, decided by whether anyone had edited the Type.
        """
        payload = _type_payload()
        payload.pop('port_section_index', None)

        assert rest_api.post(f'{TYPES_URL}/', json=payload).status_code == HTTPStatus.CREATED
        assert _stored_index(rest_api) == 0

    @pytest.mark.parametrize('sent', [-1, 1.5, 'left', True], ids=str)
    def test_an_unusable_position_is_refused(self, rest_api, sent: Any) -> None:
        """
        A value that cannot mean a position is reported instead of silently corrected

        True is in the list because bool is an int subclass in Python: unguarded, a client sending it
        would be read as position 1.
        """
        response = _create(rest_api, port_section_index=sent)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_type_without_ports_stores_the_default(self, rest_api) -> None:
        """The index is only read while `uses_ports` is on, so it is reset rather than kept"""
        response = _create(rest_api, uses_ports=False, port_section_index=PLACED_INDEX)

        assert response.status_code == HTTPStatus.CREATED
        assert _stored_index(rest_api) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        UPDATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdate:
    """PUT /types/<id> moves the ports section, and resets it with the flag."""

    @pytest.fixture(autouse=True)
    def _created(self, rest_api):
        """Every update test starts from a placed ports section"""
        assert _create(rest_api, port_section_index=PLACED_INDEX).status_code == HTTPStatus.CREATED

    def test_the_position_can_be_moved(self, rest_api) -> None:
        """Dragging the section elsewhere in the type builder is an ordinary full-document update"""
        response = rest_api.put(
            f'{TYPES_URL}/{_stored_id(rest_api)}', json=_type_payload(port_section_index=MOVED_INDEX),
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_index(rest_api) == MOVED_INDEX

    def test_turning_ports_off_resets_the_position(self, rest_api) -> None:
        """
        A Type that stops using ports must not keep the placement

        Nothing reads the index while the flag is off, so keeping it would resurface a placement the
        user may never make again the moment the flag came back.
        """
        response = rest_api.put(
            f'{TYPES_URL}/{_stored_id(rest_api)}',
            json=_type_payload(uses_ports=False, port_section_index=PLACED_INDEX),
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_index(rest_api) == 0

    def test_an_unusable_position_is_refused(self, rest_api) -> None:
        """The refusal is the same on the update path, and the stored position is left alone"""
        response = rest_api.put(f'{TYPES_URL}/{_stored_id(rest_api)}', json=_type_payload(port_section_index=-2))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_index(rest_api) == PLACED_INDEX

    def test_an_omitted_position_falls_back_to_the_default(self, rest_api) -> None:
        """
        There is no partial update: a payload without the key asks for the default, not for "unchanged"

        The whole document is always sent, so an absent key is the frontend saying the ports section
        sits first - which is what the type builder sends for a Type it has just enabled ports on.
        """
        payload = _type_payload()
        payload.pop('port_section_index', None)

        response = rest_api.put(f'{TYPES_URL}/{_stored_id(rest_api)}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_index(rest_api) == 0
