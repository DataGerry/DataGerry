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
Functional tests: what ``POST /types/`` decides about a new Type's identity, through the real REST app

  - the id is the server's: a payload ``public_id`` is dropped and the counter hands one out
  - the name is held once: a create that loses the race to another of the same name is refused by the unique name
    index with the name read's own 400 and stores nothing; any other insert failure keeps its own 400
  - a failed uniqueness read is its own 400, not "the created Type could not be read" and not a 500
  - a SpecialType is held once: a create that loses that race is refused by the partial unique special_type index
    with the read's 400; a type import losing either race reports the entry with its rule's own message
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerInsertError
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.types_manager import TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_NAME_TAKEN_MESSAGE,
    TYPE_SPECIAL_TYPE_TAKEN_MESSAGE,
    TYPE_UNIQUENESS_CHECK_FAILED_MESSAGE,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError
from tests.functional.framework.test_functional_types_route import _type_payload
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
SENT_PUBLIC_ID: int = 97991
TYPE_NAME: str = 'create-identity-type'
OTHER_NAME: str = 'create-identity-other'
IMPORTED_NAME: str = 'create-identity-imported'
IMPORT_URL: str = '/import/type/create/'
CABLE: str = SpecialType.CABLE.value
ALL_NAMES: list[str] = [TYPE_NAME, OTHER_NAME, IMPORTED_NAME]
NAME_KEY: str = TypeSchemaKey.NAME.value
# MongoDB's own index on _id - created with the collection, never dropped
MONGO_ID_INDEX: str = '_id_'
GENERIC_INSERT_MESSAGE: str = 'Failed to insert the new Type into the database!'


def _body(name: str = TYPE_NAME) -> dict[str, Any]:
    """A complete type body carrying a client public_id"""
    body: dict[str, Any] = _type_payload(SENT_PUBLIC_ID, 'Create identity')
    body[NAME_KEY] = name

    return body


def _raiser(error: Exception) -> Any:
    """A replacement that raises the error"""
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return _fail


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The type collection behind its declared indexes, purged of the test's names before and after"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({NAME_KEY: {'$in': ALL_NAMES}})

    _purge()
    # The session builds no declared index; the name and special_type indexes are what decide a race. Every index
    # built here is dropped again - left behind, one would refuse the documents other modules seed
    had_indexes: set[str] = set(collection.index_information())
    database_manager.create_indexes(CmdbType.COLLECTION, database_name, CmdbType.get_index_keys())
    yield collection
    _purge()

    for index_name in set(collection.index_information()) - had_indexes - {MONGO_ID_INDEX}:
        collection.drop_index(index_name)


def test_a_payload_public_id_is_not_the_new_types_id(rest_api, types: Any) -> None:
    """The counter's id, not the sent one"""
    response = rest_api.post(TYPES_URL, json=_body())

    assert response.status_code == HTTPStatus.CREATED
    assert types.find_one({NAME_KEY: TYPE_NAME})['public_id'] != SENT_PUBLIC_ID
    assert not types.count_documents({'public_id': SENT_PUBLIC_ID})


def test_a_create_that_loses_the_race_gets_the_name_reads_400(rest_api, types: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Refused by the index, the same message, one type stored"""
    assert rest_api.post(TYPES_URL, json=_body()).status_code == HTTPStatus.CREATED
    monkeypatch.setattr(TypesManager, 'get_one_by', lambda *_args, **_kwargs: None)

    response = rest_api.post(TYPES_URL, json=_body())

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, TYPE_NAME_TAKEN_MESSAGE.format(name=TYPE_NAME))
    assert types.count_documents({NAME_KEY: TYPE_NAME}) == 1


def test_the_name_read_still_refuses_a_taken_name(rest_api, types: Any) -> None:
    """The ordinary case, before the index is reached"""
    rest_api.post(TYPES_URL, json=_body())

    response = rest_api.post(TYPES_URL, json=_body())

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, TYPE_NAME_TAKEN_MESSAGE.format(name=TYPE_NAME))
    assert types.count_documents({NAME_KEY: TYPE_NAME}) == 1


def test_another_insert_failure_keeps_its_own_400(rest_api, types: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not reported as a taken name"""
    monkeypatch.setattr(TypesManager, 'insert_type', _raiser(TypesManagerInsertError('down')))

    response = rest_api.post(TYPES_URL, json=_body(OTHER_NAME))

    assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, GENERIC_INSERT_MESSAGE)
    assert not types.count_documents({NAME_KEY: OTHER_NAME})


def test_a_failed_name_read_is_its_own_400(rest_api, types: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bare manager error the name read raises - a 500 before"""
    monkeypatch.setattr(TypesManager, 'get_one_by', _raiser(BaseManagerGetError('down')))

    response = rest_api.post(TYPES_URL, json=_body(OTHER_NAME))

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, TYPE_UNIQUENESS_CHECK_FAILED_MESSAGE)
    assert not types.count_documents({NAME_KEY: OTHER_NAME})


def _cable(name: str = TYPE_NAME) -> dict[str, Any]:
    """A CABLE Type body"""
    return {**_body(name), TypeSchemaKey.SPECIAL_TYPE.value: CABLE}


def _miss_both_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The name and SpecialType reads find nothing - as when a concurrent create has not stored them yet"""
    monkeypatch.setattr(TypesManager, 'get_one_by', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(TypesManager, 'check_special_type_exists', lambda *_args, **_kwargs: False)


def _import(rest_api: Any, entry: dict[str, Any]) -> list[str]:
    """POST one entry to the type import; the errors it reports for it"""
    entry = {key: value for key, value in entry.items() if key != 'public_id'}
    response = rest_api.post(IMPORT_URL, data={'uploadFile': json.dumps([entry])}, content_type='multipart/form-data')

    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


class TestTheSpecialTypeIsHeldOnce:
    """The partial unique special_type index behind the read"""

    @pytest.fixture(autouse=True)
    def _ipam_licensed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SpecialType needs the IPAM licence"""
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    def test_a_create_that_loses_the_special_type_race_gets_the_reads_400(
            self, rest_api, types: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refused by the index, the same message, no second CABLE Type"""
        assert rest_api.post(TYPES_URL, json=_cable()).status_code == HTTPStatus.CREATED
        _miss_both_reads(monkeypatch)

        response = rest_api.post(TYPES_URL, json=_cable(OTHER_NAME))

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST, TYPE_SPECIAL_TYPE_TAKEN_MESSAGE.format(special_type=CABLE))
        assert not types.count_documents({NAME_KEY: OTHER_NAME})

    def test_an_import_losing_the_special_type_race_names_the_rule(
            self, rest_api, types: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """SPECIAL_TYPE_EXISTS, not the raw duplicate-key text"""
        rest_api.post(TYPES_URL, json=_cable())
        _miss_both_reads(monkeypatch)

        errors: list[str] = _import(rest_api, _cable(IMPORTED_NAME))

        assert errors == [TypeImportError.SPECIAL_TYPE_EXISTS.format(special_type=CABLE)]
        assert not types.count_documents({NAME_KEY: IMPORTED_NAME})

    def test_an_import_losing_the_name_race_names_the_rule(
            self, rest_api, types: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """TYPE_NAME_EXISTS, not the raw duplicate-key text"""
        rest_api.post(TYPES_URL, json=_body(IMPORTED_NAME))
        _miss_both_reads(monkeypatch)

        errors: list[str] = _import(rest_api, _body(IMPORTED_NAME))

        assert errors == [TypeImportError.TYPE_NAME_EXISTS.format(name=IMPORTED_NAME)]
        assert types.count_documents({NAME_KEY: IMPORTED_NAME}) == 1
