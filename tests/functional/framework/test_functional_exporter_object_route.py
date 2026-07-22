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
Functional coverage for the /exporter object-export routes

Covers the supported-extensions catalogue, the object export in its default (JSON), csv and zip
formats, the unsupported-format -> 400 guard (the whitelist fix), and the manager-error mappings
(ObjectsManagerIterationError -> 400, AccessDeniedError -> 403). A single type + object is seeded and
every export is scoped to that type so the format writers have deterministic data to render.
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.framework.exporter.writer.supported_exporter_extension import SupportedExporterExtension
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

EXTENSIONS_URL: str = '/exporter/extensions'
EXPORT_URL: str = '/exporter/'

TYPE_ID: int = 47501
OBJECT_ID: int = 47511
NAME_FIELD: str = 'dg-name'

TYPE_FILTER: str = json.dumps({'type_id': TYPE_ID})


def _type_doc() -> dict[str, Any]:
    """Builds an active CmdbType with a single text field and a matching section."""
    return {
        'public_id': TYPE_ID,
        'name': 'export-obj-type',
        'label': 'Export Obj Type',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _object_doc() -> dict[str, Any]:
    """Builds a CmdbObject of the seeded type for direct DB insertion."""
    return {
        'public_id': OBJECT_ID,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': 'host-1'}],
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the export target type + object, cleaning both up after each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': OBJECT_ID})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_one(_object_doc())
    yield
    _purge()


def _export_url(**params: str) -> str:
    """Builds the export URL scoped to the seeded type plus any extra query params."""
    query = {'filter': TYPE_FILTER, **params}
    return EXPORT_URL + '?' + '&'.join(f'{key}={value}' for key, value in query.items())


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestExtensions:
    """GET /exporter/extensions lists the supported export formats."""

    def test_lists_supported_formats(self, rest_api) -> None:
        """The catalogue includes the built-in JSON export format."""
        response = rest_api.get(EXTENSIONS_URL)

        assert response.status_code == HTTPStatus.OK
        assert 'JsonExportFormat' in [item['extension'] for item in response.get_json()]

    def test_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error building the catalogue surfaces as 500."""
        monkeypatch.setattr(SupportedExporterExtension, 'convert_to', _raiser(RuntimeError('boom')))

        assert rest_api.get(EXTENSIONS_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestExportObjects:
    """GET /exporter/ exports objects in the requested format."""

    def test_default_json_export(self, rest_api) -> None:
        """A default export (no classname) succeeds."""
        assert rest_api.get(_export_url()).status_code == HTTPStatus.OK

    def test_csv_export(self, rest_api) -> None:
        """An explicit csv export format succeeds."""
        assert rest_api.get(_export_url(classname='CsvExportFormat')).status_code == HTTPStatus.OK

    def test_zip_export(self, rest_api) -> None:
        """A zip export (packing the JSON format) succeeds."""
        assert rest_api.get(_export_url(zip='true', classname='JsonExportFormat')).status_code == HTTPStatus.OK

    def test_unsupported_format_returns_400(self, rest_api) -> None:
        """An unknown export format is rejected with 400 (whitelist guard)."""
        assert rest_api.get(_export_url(classname='Bogus')).status_code == HTTPStatus.BAD_REQUEST

    def test_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError while fetching objects surfaces as 400."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(_export_url()).status_code == HTTPStatus.BAD_REQUEST

    def test_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError while fetching objects surfaces as 403."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(_export_url()).status_code == HTTPStatus.FORBIDDEN

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while exporting surfaces as 500."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(_export_url()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_missing_format_module_returns_500(self, rest_api, monkeypatch) -> None:
        """A ModuleNotFoundError loading the (whitelisted) format class surfaces as 500."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.exporter_routes.exporter_object_routes.load_class',
            _raiser(ModuleNotFoundError('boom')),
        )

        assert rest_api.get(_export_url()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
