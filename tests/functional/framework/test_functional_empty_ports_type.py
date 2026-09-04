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
Functional coverage of the "empty" port-bearing CmdbType

A Type that declares ``uses_ports`` and NOTHING else - no fields, no render_meta sections - is a
supported shape, not a broken Type: a patch panel whose whole content is its ports, which the object
form shows through the ``dg-virtual-tpl-ports`` virtual section template. Ports live in their own
collection, so such a Type carries no field to declare.

The backend has no rule demanding a field or a section anywhere, and these tests pin that: the whole
lifecycle - create the Type, create an object of it, give the object a port, render it, export it,
delete it - must keep working, so a future "a Type must have at least one section" guard cannot break
the shape silently. The one deliberate refusal is the object-import TEMPLATE, which has no column to
offer for a fieldless Type

The Type is created through the REST route rather than seeded into the collection: the point is that
the route accepts the shape
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'
OBJECTS_URL: str = '/objects'
PORTS_URL: str = '/ports'
EXPORTER_URL: str = '/exporter'
SECTION_TEMPLATES_URL: str = '/section_templates'

TYPE_ID: int = 9642
TYPE_NAME: str = 'empty-ports-type'
TYPE_LABEL: str = 'Empty Ports Type'
OBJECT_ID: int = 9643

PORT_NAME: str = 'Gi0/1'
VIRTUAL_PORTS_TEMPLATE: str = 'dg-virtual-tpl-ports'

AUTHOR_ID: int = 1
VERSION: str = '1.0.0'


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """
    Licenses IPAM so a Type may declare `uses_ports` and the /ports surface is reachable

    Port Connectivity is gated behind LicenseFeature.IPAM by decision D6; that the gate really blocks
    the surface is asserted in tests/functional/license/.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_payload() -> dict[str, Any]:
    """The empty port-bearing Type: uses_ports, and no field or section of its own."""
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': TYPE_LABEL,
        'author_id': AUTHOR_ID,
        'active': True,
        'version': VERSION,
        'uses_ports': True,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_payload() -> dict[str, Any]:
    """An object of the empty Type - it has no field to carry."""
    return {
        'public_id': OBJECT_ID,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': VERSION,
        'fields': [],
    }


@pytest.fixture(name='empty_type', autouse=True)
def fixture_empty_type(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Creates the empty Type through the route and removes it, its objects and their ports after."""
    response = rest_api.post(f'{TYPES_URL}/', json=_type_payload())
    assert response.status_code == HTTPStatus.CREATED
    yield
    database_manager.get_collection(CmdbPort.COLLECTION, database_name).delete_many({'object_id': OBJECT_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'type_id': TYPE_ID})
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one({'public_id': TYPE_ID})
    # Creating and deleting an object through the routes writes CmdbObjectLogs; the log routes page
    # through the whole collection, so a suite that leaves its logs behind breaks THEIR assertions
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many({'object_id': OBJECT_ID})


@pytest.fixture(name='empty_object')
def fixture_empty_object(rest_api):
    """Creates one object of the empty Type."""
    response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload())
    assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        THE TYPE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEmptyTypeItself:
    """The Type routes accept and return a Type carrying no field and no section."""

    def test_the_type_is_created_by_the_route(self, rest_api) -> None:
        """POST /types/ accepts the empty shape - the fixture's assertion, restated as its own test."""
        response = rest_api.get(f'{TYPES_URL}/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        result = response.get_json()['result']
        assert result['fields'] == []
        assert result['render_meta']['sections'] == []
        assert result['uses_ports'] is True

    def test_the_type_lists_and_appears_in_the_overview(self, rest_api) -> None:
        """A Type with no content must not drop out of the list or the overview."""
        listed = rest_api.get(f'{TYPES_URL}/')
        overview = rest_api.get(f'{TYPES_URL}/overview')

        assert listed.status_code == HTTPStatus.OK
        assert overview.status_code == HTTPStatus.OK
        assert TYPE_ID in [item['public_id'] for item in listed.get_json()['results']]
        assert TYPE_ID in [item['type_data']['public_id'] for item in overview.get_json()['results']]

    def test_the_ports_virtual_template_is_served_independently(self, rest_api) -> None:
        """The object form's ports section comes from the virtual template, not from the Type."""
        response = rest_api.get(f'{SECTION_TEMPLATES_URL}/virtual/')

        assert response.status_code == HTTPStatus.OK
        assert VIRTUAL_PORTS_TEMPLATE in [template['name'] for template in response.get_json()]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ITS OBJECTS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestObjectsOfTheEmptyType:
    """An object of the empty Type is created, rendered and updated like any other."""

    def test_an_object_without_fields_is_created(self, rest_api, empty_object) -> None:
        """POST /objects/ with an empty field list is accepted - there is no required field to miss."""
        response = rest_api.get(f'{OBJECTS_URL}/native/{OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['fields'] == []

    def test_the_render_falls_back_to_the_default_summary_line(self, rest_api, empty_object) -> None:
        """
        With no summary field the renderer answers '<type label> #<public_id>'

        That fallback is what the frontend shows wherever an object needs a name, so a Type with
        nothing to summarise still reads as something in every list.
        """
        response = rest_api.get(f'{OBJECTS_URL}/{OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        rendered = response.get_json()
        assert rendered['summary_line'] == f'{TYPE_LABEL} #{OBJECT_ID}'
        assert rendered['fields'] == []
        assert rendered['sections'] == []

    def test_the_object_can_be_updated(self, rest_api, empty_object) -> None:
        """A full update of a fieldless object is a normal update, not an empty-payload rejection."""
        response = rest_api.put(f'{OBJECTS_URL}/{OBJECT_ID}', json=_object_payload())

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_the_object_is_deletable(self, rest_api, empty_object) -> None:
        """Deleting it runs the same cascade as any other object."""
        assert rest_api.delete(f'{OBJECTS_URL}/{OBJECT_ID}').status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ITS PORTS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPortsOfTheEmptyType:
    """The point of the shape: the object's whole content is its ports."""

    def test_a_port_can_be_created_and_listed(self, rest_api, empty_object) -> None:
        """The owner object carrying no field is still a valid port owner."""
        created = rest_api.post(f'{PORTS_URL}/', json={'object_id': OBJECT_ID, 'name': PORT_NAME})

        assert created.status_code == HTTPStatus.CREATED

        listed = rest_api.get(f'{PORTS_URL}/object/{OBJECT_ID}')

        assert listed.status_code == HTTPStatus.OK
        assert [port['name'] for port in listed.get_json()] == [PORT_NAME]

    def test_the_type_reports_its_port_usage(self, rest_api, empty_object) -> None:
        """The uses_ports usage route counts the ports of a Type that declares nothing else."""
        assert rest_api.post(f'{PORTS_URL}/', json={'object_id': OBJECT_ID, 'name': PORT_NAME}).status_code \
            == HTTPStatus.CREATED

        response = rest_api.get(f'{TYPES_URL}/uses_ports_usage/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['port_count'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   EXPORT / IMPORT                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestExportOfTheEmptyType:
    """The export surface handles a fieldless Type; only the import template has nothing to offer."""

    @pytest.mark.parametrize('export_format', [
        'JsonExportFormat',
        'CsvExportFormat',
        'XmlExportFormat',
        'XlsxExportFormat',
    ])
    def test_objects_export_in_every_format(self, rest_api, empty_object, export_format: str) -> None:
        """Every tabular and document format copes with an object that has no column to write."""
        response = rest_api.get(
            f'{EXPORTER_URL}/?filter={{"type_id":{TYPE_ID}}}&classname={export_format}&zip=false'
        )

        assert response.status_code == HTTPStatus.OK

    def test_the_type_itself_exports(self, rest_api) -> None:
        """The Type export carries the empty Type, so it can be moved to another installation."""
        response = rest_api.post(f'/export/type/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[0]['name'] == TYPE_NAME

    def test_the_import_template_is_refused(self, rest_api) -> None:
        """
        The one deliberate refusal: a Type declaring no field has no column to put in a template

        The identity columns alone are not a document anyone can fill in, so the route says so
        instead of answering with them.
        """
        response = rest_api.get(f'{EXPORTER_URL}/template/{TYPE_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'declares no fields' in response.get_json()['message']
