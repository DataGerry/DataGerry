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
target type -> 403, a happy-path CSV import into an active type, and the overwrite path: a CSV row
carrying a public_id replaces the stored object, is rejected per object when that id belongs to an
incompatible type, and creates the object when the id is unused).
"""
import json
from datetime import datetime
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.errors.importer import ImporterLoadError, ImportRuntimeError
from cmdb.errors.security import AccessDeniedError
from tests.utils.ipam_doc_builders import make_type_doc, make_object_doc, make_field
# -------------------------------------------------------------------------------------------------------------------- #

# The route module runs an app-context block at import time, so it cannot be imported at collection;
# it is already loaded by the rest_api fixture, so monkeypatch targets it by dotted path at run time.
_OBJECT_ROUTES: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_object_routes'
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/import/object'

ACTIVE_TYPE_ID: int = 47301
INACTIVE_TYPE_ID: int = 47302
OTHER_TYPE_ID: int = 47303  # a second type, used to overwrite an object the target type cannot hold
ALL_TYPE_IDS: list[int] = [ACTIVE_TYPE_ID, INACTIVE_TYPE_ID, OTHER_TYPE_ID]

EXISTING_OBJECT_ID: int = 47350  # the public_id an overwrite import carries

CSV_BODY: bytes = b'dg-name\nhost-1\n'
# A boolean column written the way a spreadsheet exports it - the spelling that used to stay a string
UPPERCASE_BOOL_CSV_BODY: bytes = b'dg-name,dg-active\nhost-1,TRUE\n'
# A header-only file: what a freshly downloaded import template looks like before it is filled in
HEADER_ONLY_CSV_BODY: bytes = b'dg-name\n'
# The JSON counterpart of an empty file - answered the same way since the two formats were aligned
EMPTY_JSON_BODY: bytes = b'[]'

ADMIN_PUBLIC_ID: int = 1  # the user the rest_api fixture authenticates as


@pytest.fixture(autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an active and a deactivated target type, cleaning up types + imported objects after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    active = make_type_doc(ACTIVE_TYPE_ID, 'import-obj-active')
    inactive = make_type_doc(INACTIVE_TYPE_ID, 'import-obj-inactive')
    inactive['active'] = False
    types.insert_many([active, inactive])
    yield

    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    imported_ids = [doc['public_id'] for doc in objects.find({'type_id': {'$in': ALL_TYPE_IDS}})]

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    objects.delete_many({'type_id': {'$in': ALL_TYPE_IDS}})
    # A successful import writes a CREATE log per object; left behind they pile up in the log
    # collection every other log test then pages through
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': imported_ids}})


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

    def test_parse_casts_an_uppercase_boolean_column(self, rest_api) -> None:
        """
        The parse preview shows the caller what their file will import as.

        A spreadsheet writes TRUE, which used to come back as the string 'TRUE' while a
        lowercase 'true' came back as a real boolean - so the preview showed two types for one
        logical column.
        """
        form = {
            'file': (BytesIO(UPPERCASE_BOOL_CSV_BODY), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['entries'] == [{'0': 'host-1', '1': True}]

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

    def test_parse_header_only_file_names_the_real_reason(self, rest_api) -> None:
        """An empty file is a 400 that says it has no data rows - NOT 'check your parser config'.

        A freshly downloaded import template is exactly this file, so the message must point at the
        file's content instead of at settings that are not at fault.
        """
        form = {
            'file': (BytesIO(HEADER_ONLY_CSV_BODY), 'template.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        message = response.get_json()['message']
        assert 'no data rows' in message
        assert 'configuration' not in message

    def test_parse_empty_json_list_names_the_real_reason(self, rest_api) -> None:
        """An empty JSON list is answered exactly like a header-only CSV (the formats are aligned)."""
        form = {
            'file': (BytesIO(EMPTY_JSON_BODY), 'empty.json'),
            'file_format': 'json',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'no data rows' in response.get_json()['message']

    def test_parse_unknown_format_returns_400(self, rest_api) -> None:
        """
        A parse request whose format has no parser is a client error -> 400 (was wrongly 500)

        The message has to name the format and the supported set: /parse/ resolves the format the
        same way /import/ does, so the caller is no longer told to check a parser configuration that
        was never the problem.
        """
        form = {
            'file': (BytesIO(CSV_BODY), 'import.csv'),
            'file_format': 'bogus',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{BASE_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'bogus' in response.get_json()['message']
        assert 'csv' in response.get_json()['message']


class TestImportObjects:
    """POST /import/object/ imports parsed objects and guards its inputs."""

    def test_no_file_returns_400(self, rest_api) -> None:
        """An import with no file is rejected with 400."""
        response = rest_api.post(f'{BASE_URL}/', data={}, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_imported_object_is_authored_by_the_importer(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload that carries no author_id imports fine and is attributed to the importing user."""
        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'type_id': ACTIVE_TYPE_ID})
        assert stored is not None
        assert stored['author_id'] == ADMIN_PUBLIC_ID
        assert stored['editor_id'] is None
        assert stored['last_edit_time'] is None

    def test_an_uppercase_boolean_is_stored_as_a_boolean(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        End to end: the spelling a spreadsheet writes reaches MongoDB as a bool, not as text.

        The caster used to accept only 'True' / 'true', so a file exported from Excel stored the
        string 'TRUE' in `active` - truthy in Python, but not the boolean the field is declared as,
        and not equal to the `true` a file written by hand produced for the same column.
        """
        form = {
            'file': (BytesIO(UPPERCASE_BOOL_CSV_BODY), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': ACTIVE_TYPE_ID}),
        }

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'type_id': ACTIVE_TYPE_ID})
        assert stored is not None
        assert stored['active'] is True

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

    def test_import_of_a_header_only_file_returns_400_not_500(self, rest_api) -> None:
        """An empty file is the caller's doing, so it must not surface as a server error.

        Before this was named separately, the parser's no-content error was wrapped into an
        ImportRuntimeError and answered with 500 'Failed to import Objects!'.
        """
        form = {
            'file': (BytesIO(HEADER_ONLY_CSV_BODY), 'template.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': ACTIVE_TYPE_ID}),
        }

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'no data rows' in response.get_json()['message']

    def test_import_of_an_empty_json_list_returns_400_not_500(self, rest_api) -> None:
        """JSON no longer imports nothing quietly: an empty file is refused like an empty CSV."""
        form = {
            'file': (BytesIO(EMPTY_JSON_BODY), 'empty.json'),
            'file_format': 'json',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': ACTIVE_TYPE_ID}),
        }

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'no data rows' in response.get_json()['message']

    def test_unexpected_type_resolution_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An unexpected error while resolving the target type is a client error -> 400."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('unexpected')

        monkeypatch.setattr(f'{_OBJECT_ROUTES}.CmdbType.from_data', _boom)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_file_format_returns_400(self, rest_api) -> None:
        """An unsupported file_format is the caller's mistake, like on the /parse/ route."""
        form = _import_form(ACTIVE_TYPE_ID)
        form['file_format'] = 'bogus'

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_missing_file_format_returns_400(self, rest_api) -> None:
        """An import without a file_format is rejected the same way the /parse/ route rejects it."""
        form = _import_form(ACTIVE_TYPE_ID)
        form.pop('file_format')

        response = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.BAD_REQUEST

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


class TestOverwriteExistingObject:
    """A CSV carrying a public_id with overwrite enabled replaces the stored object of that id."""

    OVERWRITE_CSV: bytes = b'public_id,dg-name\n' + str(EXISTING_OBJECT_ID).encode() + b',host-new\n'

    @staticmethod
    def _overwrite_form(type_id: int) -> dict[str, Any]:
        """The multipart form of a CSV whose first column is the public_id, with overwrite enabled."""
        return {
            'file': (BytesIO(TestOverwriteExistingObject.OVERWRITE_CSV), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({
                'type_id': type_id,
                'overwrite_public': True,
                'mapping': [
                    {'name': 'public_id', 'value': 0, 'type': 'property'},
                    {'name': 'dg-name', 'value': 1, 'type': 'field'},
                ],
            }),
        }

    def _seed_object(self, database_manager: MongoDatabaseManager, database_name: str, type_id: int) -> None:
        """Seeds the object the import overwrites."""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            make_object_doc(EXISTING_OBJECT_ID, type_id, [make_field('dg-name', 'host-old')])
        )

    def test_existing_object_of_the_same_type_is_overwritten(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The stored object is replaced, not duplicated, and no failure is reported."""
        self._seed_object(database_manager, database_name, ACTIVE_TYPE_ID)

        response = rest_api.post(
            f'{BASE_URL}/', data=self._overwrite_form(ACTIVE_TYPE_ID), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK

        body = response.get_json()

        assert body['failed_imports'] == []
        assert body['success_imports'] == 1

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        assert objects.count_documents({'public_id': EXISTING_OBJECT_ID}) == 1

        stored = objects.find_one({'public_id': EXISTING_OBJECT_ID})
        stored_names = {field['name']: field['value'] for field in stored['fields']}

        assert stored_names['dg-name'] == 'host-new'

    def test_overwriting_an_object_of_an_incompatible_type_is_reported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The public_id belongs to another type that lacks the provided field -> per-object failure."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(
            OTHER_TYPE_ID, 'import-obj-other',
            fields=[{'type': 'text', 'name': 'other-field', 'label': 'Other'}],
        ))
        self._seed_object(database_manager, database_name, OTHER_TYPE_ID)

        response = rest_api.post(
            f'{BASE_URL}/', data=self._overwrite_form(ACTIVE_TYPE_ID), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK

        body = response.get_json()

        assert body['success_imports'] == 0
        (failure,) = body['failed_imports']
        assert 'does not support' in failure['errors'][0]
        # the stored object of the other type is untouched
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': EXISTING_OBJECT_ID})
        assert stored['type_id'] == OTHER_TYPE_ID

    def test_unused_public_id_is_imported_under_that_id(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Nothing lives at that public_id, so the object is created with it."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._overwrite_form(ACTIVE_TYPE_ID), content_type='multipart/form-data',
        )

        assert response.get_json()['failed_imports'] == []
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': EXISTING_OBJECT_ID})
        assert stored is not None and stored['type_id'] == ACTIVE_TYPE_ID


CHOICE_TYPE_ID: int = 47304  # a type with a select and a radio field
MDS_OBJECT_ID: int = 47360


class TestChoiceFieldOptions:
    """A choice field's options live on the field itself - the import must read and write them there."""

    @pytest.fixture(name='choice_type', autouse=True)
    def fixture_choice_type(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a Type whose select / radio options are stored the way the model defines them."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(
            CHOICE_TYPE_ID, 'import-obj-choice',
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'select', 'name': 'tier', 'label': 'Tier',
                 'options': [{'name': 'gold', 'label': 'Gold'}, {'name': 'silver', 'label': 'Silver'}]},
                {'type': 'radio', 'name': 'env', 'label': 'Env',
                 'options': [{'name': 'prod', 'label': 'Prod'}, {'name': 'test', 'label': 'Test'}]},
            ],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': ['dg-name', 'tier', 'env']}],
        ))
        yield

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        imported_ids = [doc['public_id'] for doc in objects.find({'type_id': CHOICE_TYPE_ID})]

        types.delete_many({'public_id': CHOICE_TYPE_ID})
        objects.delete_many({'type_id': CHOICE_TYPE_ID})
        database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
            .delete_many({'object_id': {'$in': imported_ids}})

    @staticmethod
    def _form(csv_body: bytes) -> dict[str, Any]:
        """A CSV import mapping the three columns onto the type's fields."""
        return {
            'file': (BytesIO(csv_body), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({
                'type_id': CHOICE_TYPE_ID,
                'mapping': [
                    {'name': 'dg-name', 'value': 0, 'type': 'field'},
                    {'name': 'tier', 'value': 1, 'type': 'field'},
                    {'name': 'env', 'value': 2, 'type': 'field'},
                ],
            }),
        }

    def test_a_valid_radio_value_is_accepted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An option the Type actually defines must import - reading the wrong key rejected them all."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form(b'dg-name,tier,env\nhost-1,gold,prod\n'),
            content_type='multipart/form-data',
        )
        body = response.get_json()

        assert body['failed_imports'] == []
        assert body['success_imports'] == 1

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'type_id': CHOICE_TYPE_ID})
        values = {field['name']: field['value'] for field in stored['fields']}

        assert values['env'] == 'prod'
        assert values['tier'] == 'gold'

    def test_an_unknown_radio_value_is_still_rejected(self, rest_api) -> None:
        """The rule itself is unchanged: a value outside the options is not allowed."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form(b'dg-name,tier,env\nhost-1,gold,staging\n'),
            content_type='multipart/form-data',
        )

        (failure,) = response.get_json()['failed_imports']

        assert failure['errors'] == ["Field 'env': 'staging' is not an allowed option"]

    def test_a_known_select_value_does_not_touch_the_type(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An option that already exists must not be re-added anywhere."""
        rest_api.post(
            f'{BASE_URL}/', data=self._form(b'dg-name,tier,env\nhost-1,gold,prod\n'),
            content_type='multipart/form-data',
        )

        stored_type = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': CHOICE_TYPE_ID})
        tier = next(field for field in stored_type['fields'] if field['name'] == 'tier')

        assert tier['options'] == [{'name': 'gold', 'label': 'Gold'}, {'name': 'silver', 'label': 'Silver'}]
        assert 'extras' not in tier  # no phantom option list beside the real one

    def test_an_unknown_select_value_extends_the_types_real_option_list(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The documented behaviour: a new select value becomes an option the frontend offers."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form(b'dg-name,tier,env\nhost-1,bronze,prod\n'),
            content_type='multipart/form-data',
        )

        assert response.get_json()['failed_imports'] == []

        stored_type = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': CHOICE_TYPE_ID})
        tier = next(field for field in stored_type['fields'] if field['name'] == 'tier')

        assert {'name': 'bronze', 'label': 'bronze'} in tier['options']
        assert 'extras' not in tier


class TestUnknownMultiDataSection:
    """An object may only carry multi-data sections its Type defines."""

    @staticmethod
    def _json_form(body: list[dict[str, Any]]) -> dict[str, Any]:
        """A JSON import of the given objects into the active target type."""
        return {
            'file': (BytesIO(json.dumps(body).encode()), 'import.json'),
            'file_format': 'json',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': ACTIVE_TYPE_ID}),
        }

    def test_a_section_the_type_does_not_define_is_rejected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Its rows would be stored and never rendered again, so the object is refused."""
        body = [{
            'fields': [{'name': 'dg-name', 'value': 'host-z'}],
            'multi_data_sections': [{
                'section_id': 'no-such-section', 'highest_id': 1,
                # a field the type DOES define, so the field-level rule does not catch it
                'values': [{'multi_data_id': 1, 'data': [{'name': 'dg-name', 'value': 'row'}]}],
            }],
        }]

        response = rest_api.post(
            f'{BASE_URL}/', data=self._json_form(body), content_type='multipart/form-data',
        )

        (failure,) = response.get_json()['failed_imports']

        assert failure['errors'] == ["Multi-data section(s) not defined on the type: ['no-such-section']"]
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'type_id': ACTIVE_TYPE_ID}) is None

    def test_an_object_without_multi_data_sections_is_unaffected(self, rest_api) -> None:
        """The rule only looks at sections the object actually carries."""
        body = [{'fields': [{'name': 'dg-name', 'value': 'host-z'}]}]

        response = rest_api.post(
            f'{BASE_URL}/', data=self._json_form(body), content_type='multipart/form-data',
        )

        assert response.get_json()['failed_imports'] == []


class TestImporterConfigIsClientInput:
    """A malformed importer config is a bad request, not a server fault."""

    @staticmethod
    def _form(importer_config: dict[str, Any]) -> dict[str, Any]:
        """A minimal CSV import with the given importer config."""
        return {
            'file': (BytesIO(CSV_BODY), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps(importer_config),
        }

    def test_an_unexpected_config_key_returns_400(self, rest_api) -> None:
        """A typo used to reach the config constructor and surface as a 500."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form({'type_id': ACTIVE_TYPE_ID, 'typo_key': 1}),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('bound', ['start_element', 'max_elements'])
    def test_a_negative_batch_bound_returns_400(self, rest_api, bound: str) -> None:
        """A negative start would slice the TAIL of the batch, a negative maximum means no limit."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form({'type_id': ACTIVE_TYPE_ID, bound: -5}),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('bound', ['start_element', 'max_elements'])
    def test_zero_is_a_valid_bound(self, rest_api, bound: str) -> None:
        """Zero is the documented default for both - no offset, no limit."""
        response = rest_api.post(
            f'{BASE_URL}/', data=self._form({'type_id': ACTIVE_TYPE_ID, bound: 0}),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK


class TestTargetTypeIsHandedToTheImporter:
    """The route already resolved and authorised the Type, so the import does not read it again."""

    def test_the_importer_carries_the_resolved_type(self, rest_api, monkeypatch) -> None:
        """`resolve_target_type` then answers from it instead of querying."""
        captured: list[Any] = []

        def _capture(importer):
            captured.append(importer)

            return ImporterObjectResponse(message='captured', success_imports=[], failed_imports=[])

        monkeypatch.setattr(f'{_OBJECT_ROUTES}._run_object_import', _capture)

        response = rest_api.post(
            f'{BASE_URL}/', data=_import_form(ACTIVE_TYPE_ID), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK

        (importer,) = captured

        assert importer.target_type is not None
        assert importer.target_type.public_id == ACTIVE_TYPE_ID
        assert importer.resolve_target_type() is importer.target_type


ROUNDTRIP_TYPE_ID: int = 47305
ROUNDTRIP_OBJECT_IDS: list[int] = [47371, 47372]


class TestExportImportRoundTrip:
    """The workflow the feature exists for: a file the export route produced imports back in."""

    @pytest.fixture(name='roundtrip_data', autouse=True)
    def fixture_roundtrip_data(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a Type covering every coercing field kind, plus two objects of it."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        types.insert_one(make_type_doc(
            ROUNDTRIP_TYPE_ID, 'import-obj-roundtrip',
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'number', 'name': 'port', 'label': 'Port'},
                {'type': 'select', 'name': 'tier', 'label': 'Tier',
                 'options': [{'name': 'gold', 'label': 'Gold'}, {'name': 'silver', 'label': 'Silver'}]},
                {'type': 'radio', 'name': 'env', 'label': 'Env',
                 'options': [{'name': 'prod', 'label': 'Prod'}, {'name': 'test', 'label': 'Test'}]},
                {'type': 'date', 'name': 'since', 'label': 'Since'},
                {'type': 'checkbox', 'name': 'managed', 'label': 'Managed'},
            ],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': ['dg-name', 'port', 'tier', 'env', 'since', 'managed']}],
        ))

        for index, object_id in enumerate(ROUNDTRIP_OBJECT_IDS):
            objects.insert_one(make_object_doc(object_id, ROUNDTRIP_TYPE_ID, [
                make_field('dg-name', f'host-{index}'),
                make_field('port', 8080 + index),
                # the second object leaves the optional values empty, so the export writes them out
                # as 'None' and the import has to read them back as empty again
                make_field('tier', 'gold' if index == 0 else None),
                make_field('env', 'prod'),
                make_field('since', datetime(2026, 3, 4, 5, 6, 7) if index == 0 else None),
                make_field('managed', True),
            ]))

        yield

        imported_ids = [doc['public_id'] for doc in objects.find({'type_id': ROUNDTRIP_TYPE_ID})]
        types.delete_many({'public_id': ROUNDTRIP_TYPE_ID})
        objects.delete_many({'type_id': ROUNDTRIP_TYPE_ID})
        database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
            .delete_many({'object_id': {'$in': imported_ids}})

    @staticmethod
    def _export(rest_api, classname: str) -> bytes:
        """Runs the real export route for the seeded type and returns the file."""
        query = json.dumps({'type_id': ROUNDTRIP_TYPE_ID})
        response = rest_api.get(f'/exporter/?filter={query}&classname={classname}')

        assert response.status_code == HTTPStatus.OK

        return response.data

    @staticmethod
    def _csv_mapping(exported: bytes) -> list[dict[str, Any]]:
        """Maps every exported column back onto its field, by header name."""
        header = exported.decode('utf-8').splitlines()[0].split(',')

        return [
            {'name': column, 'value': index,
             'type': 'property' if column in ('public_id', 'active') else 'field'}
            for index, column in enumerate(header)
        ]

    def test_a_json_export_imports_as_new_objects(self, rest_api) -> None:
        """Every value the export wrote is accepted again, including the choice fields."""
        exported = self._export(rest_api, 'JsonExportFormat')

        form = {
            'file': (BytesIO(exported), 'objects.json'),
            'file_format': 'json',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': ROUNDTRIP_TYPE_ID}),
        }
        payload = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data').get_json()

        assert payload['failed_imports'] == []
        assert payload['success_imports'] == len(ROUNDTRIP_OBJECT_IDS)

    def test_a_csv_export_overwrites_the_objects_it_came_from(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """With overwrite on, the round trip is a no-op: the same objects, the same values."""
        exported = self._export(rest_api, 'CsvExportFormat')

        form = {
            'file': (BytesIO(exported), 'objects.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({
                'type_id': ROUNDTRIP_TYPE_ID, 'overwrite_public': True,
                'mapping': self._csv_mapping(exported),
            }),
        }
        payload = rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data').get_json()

        assert payload['failed_imports'] == []

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        assert objects.count_documents({'type_id': ROUNDTRIP_TYPE_ID}) == len(ROUNDTRIP_OBJECT_IDS)

        stored = objects.find_one({'public_id': ROUNDTRIP_OBJECT_IDS[0]})
        values = {field['name']: field['value'] for field in stored['fields']}

        assert values['dg-name'] == 'host-0'
        assert values['port'] == 8080                                   # cast back to a number
        assert values['tier'] == 'gold'                                 # select option kept
        assert values['env'] == 'prod'                                  # radio option accepted
        assert values['since'] == datetime(2026, 3, 4, 5, 6, 7)         # date parsed back
        assert values['managed'] is True                                # checkbox parsed back

    def test_empty_values_survive_the_csv_round_trip(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The export writes an unfilled value as an empty cell; the import must store it as None."""
        exported = self._export(rest_api, 'CsvExportFormat')

        form = {
            'file': (BytesIO(exported), 'objects.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({
                'type_id': ROUNDTRIP_TYPE_ID, 'overwrite_public': True,
                'mapping': self._csv_mapping(exported),
            }),
        }
        rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': ROUNDTRIP_OBJECT_IDS[1]})
        values = {field['name']: field['value'] for field in stored['fields']}

        assert values['tier'] is None
        assert values['since'] is None

    def test_the_round_trip_leaves_the_type_untouched(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """No select option is invented on the way through - not even for an empty cell."""
        exported = self._export(rest_api, 'CsvExportFormat')

        form = {
            'file': (BytesIO(exported), 'objects.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({
                'type_id': ROUNDTRIP_TYPE_ID, 'overwrite_public': True,
                'mapping': self._csv_mapping(exported),
            }),
        }
        rest_api.post(f'{BASE_URL}/', data=form, content_type='multipart/form-data')

        stored_type = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': ROUNDTRIP_TYPE_ID})
        tier = next(field for field in stored_type['fields'] if field['name'] == 'tier')

        assert tier['options'] == [{'name': 'gold', 'label': 'Gold'}, {'name': 'silver', 'label': 'Silver'}]
        assert 'extras' not in tier
