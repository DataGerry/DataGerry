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
Functional coverage for the /export/type routes

Covers exporting all types (JSON attachment envelope), exporting by comma-separated public_ids, the
invalid-id-format -> 400 guard, and the manager-error -> 400 mappings (TypesManagerGetError on both
the all-types and by-ids routes).
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.models.type_model import CmdbType
from cmdb.errors.manager.types_manager import TypesManagerGetError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_ALL_URL: str = '/export/type/'
TYPE_ID: int = 47601


@pytest.fixture(autouse=True)
def _seed_type(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one exportable type, cleaning it up after each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(make_type_doc(TYPE_ID, 'export-type'))
    yield
    types.delete_many({'public_id': TYPE_ID})


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _ids_of(response: Any) -> list[int]:
    """Parses the JSON attachment body into a list of exported type public_ids."""
    return [entry['public_id'] for entry in json.loads(response.get_data(as_text=True))]


class TestExportAllTypes:
    """POST /export/type/ returns every type as a JSON attachment."""

    def test_exports_all_types(self, rest_api) -> None:
        """The export succeeds, is a JSON attachment, and includes the seeded type."""
        response = rest_api.post(EXPORT_ALL_URL)

        assert response.status_code == HTTPStatus.OK
        assert 'attachment' in response.headers['Content-Disposition']
        assert TYPE_ID in _ids_of(response)

    def test_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while fetching types surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_all_types', _raiser(TypesManagerGetError('boom')))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while fetching types surfaces as 500."""
        monkeypatch.setattr(TypesManager, 'get_all_types', _raiser(RuntimeError('boom')))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestExportTypesByIds:
    """POST /export/type/<ids> returns the selected types."""

    def test_exports_selected_type(self, rest_api) -> None:
        """Exporting by a single public_id returns that type."""
        response = rest_api.post(f'/export/type/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == [TYPE_ID]

    def test_invalid_id_format_returns_400(self, rest_api) -> None:
        """A non-numeric id in the path is rejected with 400."""
        assert rest_api.post('/export/type/not-a-number').status_code == HTTPStatus.BAD_REQUEST

    def test_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while fetching the selected types surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_types_by', _raiser(TypesManagerGetError('boom')))

        assert rest_api.post(f'/export/type/{TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while fetching the selected types surfaces as 500."""
        monkeypatch.setattr(TypesManager, 'get_types_by', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'/export/type/{TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
