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

Covers exporting all types (JSON attachment envelope), exporting by comma-separated public_ids
(single, multiple and duplicated), the ascending-public_id ordering both routes guarantee, the
invalid-id-format -> 400 guard, and the manager-error -> 400 mappings (TypesManagerGetError on both
the all-types and by-ids routes).
"""
import json
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.models.type_model import CmdbType
from cmdb.errors.models.cmdb_type import CmdbTypeToJsonError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_ALL_URL: str = '/export/type/'
TYPE_ID: int = 47601
SECOND_TYPE_ID: int = 47602
THIRD_TYPE_ID: int = 47603

SEEDED_TYPE_IDS: list[int] = [TYPE_ID, SECOND_TYPE_ID, THIRD_TYPE_ID]


@pytest.fixture(autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds three exportable types, cleaning them up after each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})
    types.insert_many([make_type_doc(type_id, f'export-type-{type_id}') for type_id in SEEDED_TYPE_IDS])
    yield
    types.delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})


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

    def test_export_is_ascending_by_public_id(self, rest_api) -> None:
        """The catalogue is emitted oldest-first so two exports of a system diff cleanly."""
        exported_ids = _ids_of(rest_api.post(EXPORT_ALL_URL))

        assert exported_ids == sorted(exported_ids)

    def test_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while fetching types surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_all_types', _raiser(TypesManagerGetError('boom')))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while fetching types surfaces as 500."""
        monkeypatch.setattr(TypesManager, 'get_all_types', _raiser(RuntimeError('boom')))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_http_exception_is_passed_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised while exporting keeps its own status instead of becoming a 500."""
        monkeypatch.setattr(TypesManager, 'get_all_types', _raiser(NotFound()))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.NOT_FOUND


class TestExportTypesByIds:
    """POST /export/type/<ids> returns the selected types."""

    def test_exports_selected_type(self, rest_api) -> None:
        """Exporting by a single public_id returns that type."""
        response = rest_api.post(f'/export/type/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == [TYPE_ID]

    def test_exports_multiple_selected_types_in_ascending_order(self, rest_api) -> None:
        """A multi-id selection returns every requested type, ordered by public_id not by request."""
        response = rest_api.post(f'/export/type/{THIRD_TYPE_ID},{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == [TYPE_ID, THIRD_TYPE_ID]

    def test_duplicate_ids_export_the_type_once(self, rest_api) -> None:
        """A repeated public_id does not duplicate the type in the export."""
        response = rest_api.post(f'/export/type/{TYPE_ID},{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == [TYPE_ID]

    def test_partially_unknown_selection_exports_the_known_types(self, rest_api) -> None:
        """An unknown public_id in the selection is skipped rather than failing the export."""
        response = rest_api.post(f'/export/type/{TYPE_ID},99999999')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == [TYPE_ID]

    def test_invalid_id_format_returns_400(self, rest_api) -> None:
        """A non-numeric id in the path is rejected with 400."""
        assert rest_api.post('/export/type/not-a-number').status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_id_yields_empty_export(self, rest_api) -> None:
        """Exporting a non-existent id succeeds with an empty JSON list, not an error."""
        response = rest_api.post('/export/type/99999999')

        assert response.status_code == HTTPStatus.OK
        assert _ids_of(response) == []

    def test_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while fetching the selected types surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_types_by', _raiser(TypesManagerGetError('boom')))

        assert rest_api.post(f'/export/type/{TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while fetching the selected types surfaces as 500."""
        monkeypatch.setattr(TypesManager, 'get_types_by', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'/export/type/{TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestSelectionIsReadStrictly:
    """The id segment addresses documents, so it is read strictly rather than leniently."""

    @pytest.mark.parametrize(
        'segment',
        [f' {TYPE_ID} ', f'+{TYPE_ID}', '4_7601', '0', '-1', f'{TYPE_ID},', f',{TYPE_ID}'],
        ids=['padded', 'plus', 'underscore', 'zero', 'negative', 'trailing-comma', 'leading-comma'],
    )
    def test_a_selection_that_is_not_plain_numbers_is_rejected(self, rest_api, segment: str) -> None:
        """`int()` would read most of these as an id the caller never wrote (`4_7601` -> 47601)."""
        response = rest_api.post(f'/export/type/{segment}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_plain_selection_still_exports(self, rest_api) -> None:
        """The strictness only refuses what was ambiguous."""
        response = rest_api.post(f'/export/type/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert len(json.loads(response.data.decode('utf-8'))) == 1


class TestUnserializableTypeFailsTheExport:
    """A Type that cannot be serialized is a data problem, so the export is refused, not shortened."""

    def test_all_types_export_returns_500(self, rest_api, monkeypatch) -> None:
        """A short file that looks complete would be worse than an error."""
        monkeypatch.setattr(CmdbType, 'to_json', _raiser(CmdbTypeToJsonError('boom')))

        assert rest_api.post(EXPORT_ALL_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_by_ids_export_returns_500(self, rest_api, monkeypatch) -> None:
        """Same on the by-ids route."""
        monkeypatch.setattr(CmdbType, 'to_json', _raiser(CmdbTypeToJsonError('boom')))

        assert rest_api.post(f'/export/type/{TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestEmptySelectionCollapsesOntoTheCatalogueExport:
    """An empty id list produces the whole-catalogue URL - the backend cannot tell them apart."""

    def test_an_empty_selection_exports_every_type(self, rest_api) -> None:
        """Pinned as the contract it is: refusing an empty selection is the caller's job."""
        selected: list[int] = []

        response = rest_api.post('/export/type/' + ','.join(str(i) for i in selected))

        assert response.status_code == HTTPStatus.OK
        # not an empty export - this is the all-types route answering
        assert len(json.loads(response.data.decode('utf-8'))) >= 1
