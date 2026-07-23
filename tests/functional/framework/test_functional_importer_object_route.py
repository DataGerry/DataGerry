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
Functional coverage for the /import/object routes

Covers the metadata GETs (importers / importer config / parsers / parser config, both trailing-slash
and no-slash variants, and the bad-type -> 404 after the IndexError->KeyError fix), the /parse
endpoint (real CSV round-trip + the missing-file / missing-format / unknown-format guards, all 400),
and the full /import/object POST (no-file -> 400, no-config -> 400, unknown type -> 404, a deactivated
target type -> 403, and a happy-path CSV import into an active type).
"""
import json
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.errors.importer import ImporterLoadError, ImportRuntimeError
from cmdb.errors.security import AccessDeniedError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

# The route module runs an app-context block at import time, so it cannot be imported at collection;
# it is already loaded by the rest_api fixture, so monkeypatch targets it by dotted path at run time.
_OBJECT_ROUTES: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_object_routes'
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/import/object'

ACTIVE_TYPE_ID: int = 47301
INACTIVE_TYPE_ID: int = 47302
ALL_TYPE_IDS: list[int] = [ACTIVE_TYPE_ID, INACTIVE_TYPE_ID]

CSV_BODY: bytes = b'dg-name\nhost-1\n'


@pytest.fixture(autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an active and a deactivated target type, cleaning up types + imported objects after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    active = make_type_doc(ACTIVE_TYPE_ID, 'import-obj-active')
    inactive = make_type_doc(INACTIVE_TYPE_ID, 'import-obj-inactive')
    inactive['active'] = False
    types.insert_many([active, inactive])
    yield
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .delete_many({'type_id': {'$in': ALL_TYPE_IDS}})


def _import_form(type_id: int) -> dict[str, Any]:
    """Builds the multipart import form data targeting the given type."""
    return {
        'file': (BytesIO(CSV_BODY), 'import.csv'),
        'file_format': 'csv',
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({'type_id': type_id}),
    }


class TestImporterMetadata:
    """The importer / parser metadata GET routes return their catalogues (trailing-slash canonical)."""

    def test_get_importers_trailing_slash(self, rest_api) -> None:
        """GET /importer/ lists the registered object importers."""
        response = rest_api.get(f'{BASE_URL}/importer/')

        assert response.status_code == HTTPStatus.OK
        names = [item['name'] for item in response.get_json()]
        assert 'csv' in names

    def test_no_slash_variant_redirects_to_canonical(self, rest_api) -> None:
        """The no-slash form is not a separate route; strict_slashes redirects it (308) to the slash form."""
        response = rest_api.get(f'{BASE_URL}/importer')

        assert response.status_code in (HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.PERMANENT_REDIRECT)

    def test_get_importer_config(self, rest_api) -> None:
        """GET /importer/config/<type>/ returns the manual-mapping flag."""
        response = rest_api.get(f'{BASE_URL}/importer/config/csv/')

        assert response.status_code == HTTPStatus.OK
        assert 'manually_mapping' in response.get_json()

    def test_get_importer_config_unknown_type_returns_404(self, rest_api) -> None:
        """An unknown importer type returns 404 (was 500 before the IndexError->KeyError fix)."""
        assert rest_api.get(f'{BASE_URL}/importer/config/nope/').status_code == HTTPStatus.NOT_FOUND

    def test_parser_list_route_removed(self, rest_api) -> None:
        """The unused GET /parser/ list route was removed -> 404."""
        assert rest_api.get(f'{BASE_URL}/parser/').status_code == HTTPStatus.NOT_FOUND

    def test_get_parser_config(self, rest_api) -> None:
        """GET /parser/default/<type>/ returns the parser's default config."""
        assert rest_api.get(f'{BASE_URL}/parser/default/csv/').status_code == HTTPStatus.OK

    def test_get_parser_config_unknown_type_returns_404(self, rest_api) -> None:
        """An unknown parser type returns 404 (was 500 before the IndexError->KeyError fix)."""
        assert rest_api.get(f'{BASE_URL}/parser/default/nope/').status_code == HTTPStatus.NOT_FOUND


class TestParseObjects:
    """POST /parse parses an uploaded file and guards the missing inputs."""

    def test_parse_csv_returns_output(self, rest_api) -> None:
        """A CSV upload with a parser config and file format is parsed and returned."""
        form = {
            'file': (BytesIO(CSV_BODY), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK

    def test_parse_missing_file_returns_400(self, rest_api) -> None:
        """A parse request with no file is a client error -> 400 (was wrongly 500)."""
        form = {'file_format': 'csv', 'parser_config': json.dumps({})}

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_parse_missing_file_format_returns_400(self, rest_api) -> None:
        """A parse request with no file_format is a client error -> 400 (was wrongly 500)."""
        form = {'file': (BytesIO(CSV_BODY), 'import.csv'), 'parser_config': json.dumps({})}

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_parse_unknown_format_returns_400(self, rest_api) -> None:
        """A parse request whose format has no parser is a client error -> 400 (was wrongly 500)."""
        form = {
            'file': (BytesIO(CSV_BODY), 'import.csv'),
            'file_format': 'bogus',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestImportObjects:
    """POST /import/object/ imports parsed objects and guards its inputs."""

    def test_no_file_returns_400(self, rest_api) -> None:
        """An import with no file is rejected with 400."""
        response = rest_api.post(f'{BASE_URL}/', data={}, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_no_importer_config_returns_400(self, rest_api) -> None:
        """An import with a file but no importer_config is rejected with 400."""
        form = {
            'file': (BytesIO(CSV_BODY), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_import_unknown_type_returns_404(self, rest_api) -> None:
        """Importing into a non-existent type is rejected with 404 (guards a missing type_id)."""
        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(987654), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_import_into_deactivated_type_returns_403(self, rest_api) -> None:
        """Importing into a deactivated type is rejected with 403."""
        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(INACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_import_into_active_type_succeeds(self, rest_api) -> None:
        """A CSV import into an active type completes successfully."""
        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK

    def test_unexpected_type_resolution_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An unexpected error while resolving the target type is a client error -> 400."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('unexpected')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.CmdbType.from_data', _boom)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_file_format_returns_500(self, rest_api) -> None:
        """An import whose file_format has no parser fails to load the parser -> 500."""
        form = _import_form(ACTIVE_TYPE_ID)
        form['file_format'] = 'bogus'

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_importer_config_load_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure loading the importer config class surfaces as 500."""
        def _boom(*_args, **_kwargs):
            raise ImporterLoadError('boom')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.load_importer_config_class', _boom)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_importer_class_load_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure loading the importer class surfaces as 500."""
        def _boom(*_args, **_kwargs):
            raise ImporterLoadError('boom')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.load_importer_class', _boom)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_import_runtime_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An ImportRuntimeError raised by the importer surfaces as 500."""
        class _FailingImporter:
            """Importer stub whose start_import raises an ImportRuntimeError."""
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def start_import(self):
                """Always fails with a runtime error."""
                raise ImportRuntimeError('boom')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.load_importer_class', lambda *_a, **_k: _FailingImporter)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_import_unexpected_start_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error raised by the importer surfaces as 500."""
        class _CrashingImporter:
            """Importer stub whose start_import raises an unexpected error."""
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def start_import(self):
                """Always fails with an unexpected error."""
                raise RuntimeError('boom')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.load_importer_class', lambda *_a, **_k: _CrashingImporter)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_import_succeeds_even_if_logging_fails(self, rest_api, monkeypatch) -> None:
        """A failure while logging an imported object is best-effort and must not fail the import."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('render exploded')

        # Rendering runs only inside the post-import logging loop
        monkeypatch.setattr(f'{_OBJECT_ROUTES}.CmdbMultiRender', _boom)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK

    def test_import_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError raised by the importer surfaces as 403."""
        class _DenyingImporter:
            """Importer stub whose start_import raises an AccessDeniedError."""
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def start_import(self):
                """Always fails with an access-denied error."""
                raise AccessDeniedError('nope')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.load_importer_class', lambda *_a, **_k: _DenyingImporter)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
