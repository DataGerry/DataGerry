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
Functional tests for the ``/extendable_options`` REST routes

Covers the route-layer concerns: create (rejects predefined / invalid type / duplicate, and still
answers 400 when only the database catches the duplicate), read single + list, update (persists,
pins the identity, refuses a predefined option), and the delete guards (missing -> 404,
predefined -> 400, in-use -> 400, otherwise success).
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    OptionType,
    OPTION_TYPE_VALUE_INDEX_NAME,
)
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.errors.manager.extendable_options_manager import (
    ExtendableOptionsManagerInsertError,
    ExtendableOptionsManagerGetError,
    ExtendableOptionsManagerUpdateError,
    ExtendableOptionsManagerDeleteError,
    ExtendableOptionsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/extendable_options'

OPTION_ID_FOR_GET: int = 9821
OPTION_ID_FOR_UPDATE: int = 9822
OPTION_ID_FOR_DELETE: int = 9823
OPTION_ID_PREDEFINED: int = 9824
OPTION_ID_IN_USE: int = 9825
OPTION_ID_DUPLICATE: int = 9826
MISSING_OPTION_ID: int = 9899
BOGUS_BODY_ID: int = 88888

RISK_ID_USING_OPTION: int = 9871

ORIGINAL_VALUE: str = 'func-option'
UPDATED_VALUE: str = 'func-option-updated'

ALL_OPTION_IDS: list[int] = [
    OPTION_ID_FOR_GET, OPTION_ID_FOR_UPDATE, OPTION_ID_FOR_DELETE,
    OPTION_ID_PREDEFINED, OPTION_ID_IN_USE, OPTION_ID_DUPLICATE, BOGUS_BODY_ID,
]


def _option_doc(public_id: int, value: str = ORIGINAL_VALUE, predefined: bool = False) -> dict[str, Any]:
    """Builds a CmdbExtendableOption doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'value': value,
        'option_type': OptionType.RISK.value,
        'predefined': predefined,
    }


def _payload(value: str = ORIGINAL_VALUE, predefined: bool = False, **overrides: Any) -> dict[str, Any]:
    """Builds a POST/PUT JSON body satisfying CmdbExtendableOption.SCHEMA."""
    body: dict[str, Any] = {
        'value': value,
        'option_type': OptionType.RISK.value,
        'predefined': predefined,
    }
    body.update(overrides)

    return body


def _options(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the extendable-option collection handle."""
    return database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes all seeded options + the in-use risk doc after each test."""
    yield
    _options(database_manager, database_name).delete_many({'public_id': {'$in': ALL_OPTION_IDS}})
    database_manager.get_collection(IsmsRisk.COLLECTION, database_name).delete_one(
        {'public_id': RISK_ID_USING_OPTION}
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      CREATE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreate:
    """POST /extendable_options/ rejects predefined / invalid type / duplicates, else creates."""

    def test_create_returns_id(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid create returns the new public_id and persists predefined=False."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(value='created-option'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        new_id = response.json['result_id']
        try:
            stored = _options(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['value'] == 'created-option'
            assert stored['predefined'] is False
        finally:
            _options(database_manager, database_name).delete_one({'public_id': new_id})

    def test_create_predefined_returns_400(self, rest_api) -> None:
        """Creating a predefined option via the API is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json=_payload(predefined=True)).status_code == HTTPStatus.BAD_REQUEST

    def test_create_invalid_option_type_returns_400(self, rest_api) -> None:
        """An unknown option_type is rejected with 400."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(option_type='NOT_A_REAL_TYPE'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_duplicate_value_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Creating a second option with the same value + option_type is rejected with 400."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_DUPLICATE, 'dupe-value'))

        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(value='dupe-value'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_duplicate_caught_only_by_the_index_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str, monkeypatch,
    ) -> None:
        """A duplicate that slips past the pre-check is still refused, by the unique index.

        This is the race the index exists for: option_value_exists is a read followed by a write, so
        a concurrent writer can store the value in between. Patching the pre-check to miss the
        existing option reproduces that without threads. The route must answer 400, not 500."""
        options = _options(database_manager, database_name)
        options.insert_one(_option_doc(OPTION_ID_DUPLICATE, 'index-guarded-value'))

        # The test database is built without the declared indexes, so build the one under test
        created_index: bool = OPTION_TYPE_VALUE_INDEX_NAME not in options.index_information()

        if created_index:
            database_manager.create_indexes(
                CmdbExtendableOption.COLLECTION, database_name, CmdbExtendableOption.get_index_keys(),
            )

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options'
            '.extendable_option_routes.option_value_exists',
            lambda *_args, **_kwargs: False,
        )

        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_payload(value='index-guarded-value'))

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert options.count_documents({'value': 'index-guarded-value'}) == 1
        finally:
            if created_index:
                options.drop_index(OPTION_TYPE_VALUE_INDEX_NAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRead:
    """GET single + list."""

    def test_get_single_returns_option(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET for a seeded option returns 200 and its value."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_GET, 'readable'))

        response = rest_api.get(f'{ROUTE_URL}/{OPTION_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.json['result']['value'] == 'readable'

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OPTION_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_envelope(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET list returns a results envelope including the seeded option."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_GET, 'listed'))

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert 'results' in response.json


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      UPDATE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdate:
    """PUT pins the identity to the URL id and refuses predefined options."""

    def test_update_persists_value_and_pins_identity(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A forged body public_id is ignored: the value updates and the identity stays the URL id."""
        options = _options(database_manager, database_name)
        options.insert_one(_option_doc(OPTION_ID_FOR_UPDATE))

        response = rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}',
            json=_payload(value=UPDATED_VALUE, public_id=BOGUS_BODY_ID),
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert options.find_one({'public_id': BOGUS_BODY_ID}) is None
        stored = options.find_one({'public_id': OPTION_ID_FOR_UPDATE})
        assert stored['value'] == UPDATED_VALUE

    def test_update_predefined_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Editing a predefined option is rejected with 400 and leaves it unchanged."""
        options = _options(database_manager, database_name)
        options.insert_one(_option_doc(OPTION_ID_PREDEFINED, 'system-option', predefined=True))

        response = rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_PREDEFINED}',
            json=_payload(value='changed', predefined=True),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert options.find_one({'public_id': OPTION_ID_PREDEFINED})['value'] == 'system-option'

    def test_update_keeping_same_value_succeeds(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Re-saving an option with its value unchanged succeeds (regression: self-match used to 400)."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_UPDATE))

        response = rest_api.put(f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(value=ORIGINAL_VALUE))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_update_to_value_of_another_option_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Updating to a value already used by a different option is rejected with 400."""
        options = _options(database_manager, database_name)
        options.insert_one(_option_doc(OPTION_ID_FOR_UPDATE, ORIGINAL_VALUE))
        options.insert_one(_option_doc(OPTION_ID_DUPLICATE, 'taken-value'))

        response = rest_api.put(f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(value='taken-value'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_option_type_change_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Changing the option_type of an existing option is rejected with 400."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_UPDATE))

        response = rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}',
            json=_payload(option_type=OptionType.OBJECT_GROUP.value),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_predefined_flag_change_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Flipping the predefined flag of an existing option is rejected with 400."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_UPDATE))

        response = rest_api.put(f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(predefined=True))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent option returns 404."""
        assert rest_api.put(
            f'{ROUTE_URL}/{MISSING_OPTION_ID}', json=_payload(),
        ).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      DELETE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDelete:
    """DELETE guards: success, missing 404, predefined 400, in-use 400."""

    def test_delete_removes_option(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A free option is deleted and then unretrievable."""
        options = _options(database_manager, database_name)
        options.insert_one(_option_doc(OPTION_ID_FOR_DELETE, 'deletable'))

        response = rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert options.find_one({'public_id': OPTION_ID_FOR_DELETE}) is None

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a missing id returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OPTION_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_predefined_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A predefined option cannot be deleted (400)."""
        _options(database_manager, database_name).insert_one(
            _option_doc(OPTION_ID_PREDEFINED, 'system-option', predefined=True)
        )

        assert rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_PREDEFINED}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_in_use_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A RISK option still referenced by a risk (category_id) cannot be deleted (400)."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_IN_USE, 'used-option'))
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name).insert_one(
            {'public_id': RISK_ID_USING_OPTION, 'category_id': OPTION_ID_IN_USE}
        )

        assert rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_IN_USE}').status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR MAPPING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses (400 typed / 500 unexpected)."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'insert_item',
                            _raiser(ExtendableOptionsManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload(value='x')).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_retrieval_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerGetError while retrieving the created option surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'insert_item', lambda *_a, **_k: 12345)
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item',
                            _raiser(ExtendableOptionsManagerGetError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload(value='x')).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_retrieval_none_returns_404(self, rest_api, monkeypatch) -> None:
        """A None result while retrieving the created option surfaces as 404."""
        monkeypatch.setattr(ExtendableOptionsManager, 'insert_item', lambda *_a, **_k: 12345)
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item', lambda *_a, **_k: None)

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload(value='x')).status_code == HTTPStatus.NOT_FOUND

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ExtendableOptionsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload(value='x')).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'iterate_items',
                            _raiser(ExtendableOptionsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ExtendableOptionsManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item',
                            _raiser(ExtendableOptionsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OPTION_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OPTION_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerGetError while loading the option to update surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item',
                            _raiser(ExtendableOptionsManagerGetError('boom')))

        assert rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(),
        ).status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An ExtendableOptionsManagerUpdateError on update surfaces as 400."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_UPDATE))
        monkeypatch.setattr(ExtendableOptionsManager, 'update_item',
                            _raiser(ExtendableOptionsManagerUpdateError('boom')))

        assert rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(value=UPDATED_VALUE),
        ).status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An unexpected error on update surfaces as 500."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_UPDATE))
        monkeypatch.setattr(ExtendableOptionsManager, 'update_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(
            f'{ROUTE_URL}/{OPTION_ID_FOR_UPDATE}', json=_payload(value=UPDATED_VALUE),
        ).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ExtendableOptionsManagerGetError while loading the option to delete surfaces as 400."""
        monkeypatch.setattr(ExtendableOptionsManager, 'get_item',
                            _raiser(ExtendableOptionsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An ExtendableOptionsManagerDeleteError on delete surfaces as 400."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_DELETE))
        monkeypatch.setattr(ExtendableOptionsManager, 'delete_item',
                            _raiser(ExtendableOptionsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An unexpected error on delete surfaces as 500."""
        _options(database_manager, database_name).insert_one(_option_doc(OPTION_ID_FOR_DELETE))
        monkeypatch.setattr(ExtendableOptionsManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{OPTION_ID_FOR_DELETE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR
