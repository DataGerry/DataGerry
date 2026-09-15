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
Functional smoke for the ``/section_templates`` REST routes

Covers the route-layer concerns the SectionTemplatesManager suite cannot: HTTP status codes, the
query-string parameter parsing on create/update, the predefined-create rejection (400), the 404 on
a missing id, the GET-list envelope, the PUT round-trip and the DELETE + follow-up 404. The CRUD /
propagation behavior itself is asserted at the manager layer; these tests verify the route wraps it
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.section_templates.virtual_section_templates import (
    PORTS_VIRTUAL_TEMPLATE_NAME,
    VIRTUAL_TEMPLATE_NAME_PREFIX,
)
from cmdb.models.type_model import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates'

TEMPLATE_ID_FOR_CREATE: int = 9801
TEMPLATE_ID_FOR_GET: int = 9802
TEMPLATE_ID_FOR_UPDATE: int = 9803
TEMPLATE_ID_FOR_DELETE: int = 9804
MISSING_TEMPLATE_ID: int = 9899

ALL_TEMPLATE_IDS: list[int] = [
    TEMPLATE_ID_FOR_CREATE,
    TEMPLATE_ID_FOR_GET,
    TEMPLATE_ID_FOR_UPDATE,
    TEMPLATE_ID_FOR_DELETE,
]

CREATE_NAME: str = 'func-sectpl-create'
ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _create_params(name: str, predefined: str = 'false') -> dict[str, str]:
    """Builds the query-string parameters POST /section_templates/ parses (fields is a JSON string)."""
    return {
        'name': name,
        'label': ORIGINAL_LABEL,
        'type': SectionType.SECTION.value,
        'is_global': 'false',
        'predefined': predefined,
        'fields': '[]',
    }


def _template_doc(public_id: int, name: str, label: str = ORIGINAL_LABEL) -> dict[str, Any]:
    """Builds a non-global CmdbSectionTemplate doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'name': name,
        'label': label,
        'type': SectionType.SECTION.value,
        'fields': [],
        'is_global': False,
        'predefined': False,
    }


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the section-template collection bound to the test database."""
    return database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test section templates after the module's tests have run."""
    yield
    _collection(database_manager, database_name).delete_many(
        {'$or': [{'public_id': {'$in': ALL_TEMPLATE_IDS}}, {'name': CREATE_NAME}]},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostSectionTemplate:
    """POST /section_templates/ creates a template from query params and rejects predefined ones."""

    def test_creates_new_template(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST with valid params succeeds and the template is then present in the collection."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(CREATE_NAME))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            assert _collection(database_manager, database_name).find_one({'name': CREATE_NAME}) is not None
        finally:
            _collection(database_manager, database_name).delete_many({'name': CREATE_NAME})

    def test_predefined_create_returns_400(self, rest_api) -> None:
        """A POST asking for a predefined template is rejected with 400 (not creatable via API)."""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(CREATE_NAME, predefined='true'))

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetSectionTemplate:
    """GET /section_templates/<id> and GET /section_templates/ return the expected responses."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one template directly via the DB before each test and removes it after."""
        _collection(database_manager, database_name).insert_one(
            _template_doc(TEMPLATE_ID_FOR_GET, 'func-sectpl-get'),
        )
        yield
        _collection(database_manager, database_name).delete_one({'public_id': TEMPLATE_ID_FOR_GET})

    def test_get_single_returns_template(self, rest_api) -> None:
        """A GET for a seeded template returns 200."""
        response = rest_api.get(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_TEMPLATE_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET list returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])

    def test_list_authenticates_before_parsing_params(self, rest_api) -> None:
        """Auth runs before collection-param parsing (decorator order).

        An unauthorized request whose collection params would fail to parse (``filter`` is not JSON)
        is rejected with 401 by ``@insert_request_user`` - not the 400 the parse decorator raised
        when it sat outside the auth decorators.
        """
        response = rest_api.get(f'{ROUTE_URL}/?filter=notjson', unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutSectionTemplate:
    """PUT /section_templates/ updates a template addressed by its public_id query param."""

    def test_update_persists_new_label(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After PUT, the stored template carries the updated label."""
        collection = _collection(database_manager, database_name)
        collection.insert_one(_template_doc(TEMPLATE_ID_FOR_UPDATE, 'func-sectpl-update'))
        try:
            params = {
                'public_id': str(TEMPLATE_ID_FOR_UPDATE),
                'name': 'func-sectpl-update',
                'label': UPDATED_LABEL,
                'type': SectionType.SECTION.value,
                'is_global': 'false',
                'predefined': 'false',
                'fields': '[]',
            }

            response = rest_api.put(f'{ROUTE_URL}/', query_string=params)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            stored = collection.find_one({'public_id': TEMPLATE_ID_FOR_UPDATE})
            assert stored['label'] == UPDATED_LABEL
        finally:
            collection.delete_one({'public_id': TEMPLATE_ID_FOR_UPDATE})

    def test_predefined_template_not_editable_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A predefined template cannot be edited via PUT (400) and is left unchanged."""
        collection = _collection(database_manager, database_name)
        predefined_doc = _template_doc(TEMPLATE_ID_FOR_UPDATE, 'func-sectpl-predef')
        predefined_doc['predefined'] = True
        collection.insert_one(predefined_doc)
        try:
            params = {
                'public_id': str(TEMPLATE_ID_FOR_UPDATE),
                'name': 'func-sectpl-predef',
                'label': UPDATED_LABEL,
                'type': SectionType.SECTION.value,
                'is_global': 'false',
                'predefined': 'true',
                'fields': '[]',
            }

            response = rest_api.put(f'{ROUTE_URL}/', query_string=params)

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # the predefined template is left untouched
            stored = collection.find_one({'public_id': TEMPLATE_ID_FOR_UPDATE})
            assert stored['label'] == ORIGINAL_LABEL
        finally:
            collection.delete_one({'public_id': TEMPLATE_ID_FOR_UPDATE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteSectionTemplate:
    """DELETE /section_templates/<id>/ removes the template; a follow-up GET reports 404."""

    def test_delete_removes_template(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE succeeds and a subsequent GET for the same id returns 404."""
        collection = _collection(database_manager, database_name)
        collection.insert_one(_template_doc(TEMPLATE_ID_FOR_DELETE, 'func-sectpl-delete'))
        try:
            # Registered without the trailing slash now - the form the frontend calls
            response = rest_api.delete(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            collection.delete_one({'public_id': TEMPLATE_ID_FOR_DELETE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                            THE VIRTUAL TEMPLATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
VIRTUAL_URL: str = f'{ROUTE_URL}/virtual/'


@pytest.fixture(name='ipam_licensed')
def fixture_ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM, which the virtual-template route is gated behind."""
    monkeypatch.setattr(LicenseService, 'has_feature',
                        lambda _self, feature: feature == LicenseFeature.IPAM)


class TestVirtualSectionTemplates:
    # Most cases take the 'ipam_licensed' fixture purely for its side effect - it unlocks the gate the
    # route sits behind - and never touch what it yields
    # pylint: disable=unused-argument
    """
    GET /section_templates/virtual/ serves definitions that are not in the database

    The isolation cases below are the point of the whole design: DataGerry has no partial update, so
    anything a stored-template route hands out can come back in a write. A virtual template leaking
    into those routes would eventually be inlined into a CmdbType for real.
    """

    def test_the_route_serves_the_ports_template(self, rest_api, ipam_licensed) -> None:
        """The one virtual template there is today."""
        response = rest_api.get(VIRTUAL_URL)

        assert response.status_code == HTTPStatus.OK
        names = [template['name'] for template in response.get_json()]
        assert names == [PORTS_VIRTUAL_TEMPLATE_NAME]

    def test_the_served_template_has_no_public_id(self, rest_api, ipam_licensed) -> None:
        """It is not a resource, so nothing can be fetched or updated by id."""
        template = rest_api.get(VIRTUAL_URL).get_json()[0]

        assert 'public_id' not in template

    def test_the_served_template_is_flagged_predefined(self, rest_api, ipam_licensed) -> None:
        """
        System-owned, so the frontend keeps the dropped section locked

        Unlike public_id, this flag is safe to serve: it reaches no stored-template route, and the
        predefined-select guard reads names out of the collection rather than a served payload.
        """
        template = rest_api.get(VIRTUAL_URL).get_json()[0]

        assert template['predefined'] is True

    def test_the_served_template_carries_its_option_types(self, rest_api, ipam_licensed) -> None:
        """
        What lets the frontend fill the three selects from framework.extendableOptions

        Without them the selects would render empty, since a virtual template carries no inline
        options list.
        """
        template = rest_api.get(VIRTUAL_URL).get_json()[0]
        option_types = {field['name']: field.get('option_type') for field in template['fields']}

        assert option_types['status'] == 'PORT_STATUS'
        assert option_types['port_type'] == 'PORT_TYPE'
        assert option_types['speed'] == 'PORT_SPEED'

    def test_the_route_is_403_without_the_license(self, rest_api) -> None:
        """Port Connectivity is gated behind IPAM, so its template is too."""
        assert rest_api.get(VIRTUAL_URL).status_code == HTTPStatus.FORBIDDEN

    def test_it_is_not_in_the_ordinary_list(self, rest_api, ipam_licensed) -> None:
        """
        The list route reads framework.sectionTemplates, which the virtual one is not in

        A frontend that discovered it here would treat it as a stored global template.
        """
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        names = [item['name'] for item in response.get_json()['results']]
        assert PORTS_VIRTUAL_TEMPLATE_NAME not in names

    def test_it_is_not_reachable_by_id(self, database_manager, database_name) -> None:
        """No public_id means no single-get, and nothing in the collection carries its name."""
        assert _collection(database_manager, database_name)\
            .find_one({'name': PORTS_VIRTUAL_TEMPLATE_NAME}) is None

    def test_an_unexpected_failure_is_a_500(self, rest_api, ipam_licensed, monkeypatch) -> None:
        """
        The route builds a static definition, so a failure here is a programming error

        Reported as a 500 rather than masked as an empty 200, which a frontend would render as "no
        virtual templates" and silently lose the ports panel.
        """
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates'
            '.section_template_routes.get_virtual_section_templates',
            lambda: (_ for _ in ()).throw(RuntimeError('boom')),
        )

        assert rest_api.get(VIRTUAL_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_reserved_prefix_is_refused_on_create(self, rest_api, database_manager,
                                                     database_name) -> None:
        """
        A stored template with a virtual name would shadow the virtual one

        Every frontend resolves a virtual template by name, so the name space has to be closed.
        """
        reserved_name = f'{VIRTUAL_TEMPLATE_NAME_PREFIX}something'

        response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(reserved_name))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'reserved' in response.get_json()['message']
        assert _collection(database_manager, database_name).find_one({'name': reserved_name}) is None

    def test_the_ports_name_itself_is_refused_on_create(self, rest_api) -> None:
        """The name in use today is refused by the same prefix rule, not by a special case."""
        response = rest_api.post(f'{ROUTE_URL}/',
                                 query_string=_create_params(PORTS_VIRTUAL_TEMPLATE_NAME))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_ordinary_name_is_still_accepted(self, rest_api, database_manager, database_name) -> None:
        """The guard is a prefix check and must not block normal template creation."""
        ordinary = 'func-sectpl-not-virtual'

        try:
            response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(ordinary))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        finally:
            _collection(database_manager, database_name).delete_many({'name': ordinary})
