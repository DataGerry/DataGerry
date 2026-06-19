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

Covers the route-layer concerns: create (rejects predefined / invalid type / duplicate),
read single + list, update (persists, pins the identity, refuses a predefined option), and the
delete guards (missing -> 404, predefined -> 400, in-use -> 400, otherwise success).
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.models.isms_model.isms_risk import IsmsRisk
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
