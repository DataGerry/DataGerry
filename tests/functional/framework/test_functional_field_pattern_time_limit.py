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
Functional coverage of the field pattern's time limit on the REST write routes

A field's pattern is written by whoever may edit the type and run against values anyone with object rights supplies.
A catastrophically backtracking one used to hold a gunicorn worker until gunicorn killed it; now each match has a
timeout and each write a budget. Pinned here, through the real routes:

- POST / PUT of an object whose patterned field carries a value the pattern cannot decide on in time answer 400 with
  the timeout message - well inside a second - and store nothing
- a value of the same pattern that decides normally is stored
- POST /types/ with a default the pattern cannot decide on in time is refused the same way
"""
import time
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.object_field_value_constants import (
    FieldDefaultError,
    FieldValueError,
    PATTERN_WRITE_BUDGET_SECONDS,
)
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9681
NEW_TYPE_ID: int = 9682
OBJECT_ID: int = 9683
ALL_TYPE_IDS: list[int] = [TYPE_ID, NEW_TYPE_ID]

CODE_FIELD: str = 'tl-code'
BACKTRACKING_REGEX: str = '(a|aa)+b'
BACKTRACKING_VALUE: str = 'a' * 60          # undecidable in time: hours without a limit
MATCHING_VALUE: str = 'aaab'
ROUTE_LIMIT_SECONDS: float = PATTERN_WRITE_BUDGET_SECONDS + 1.0   # the budget plus the route's own work


def _fields(default: Any = None) -> list[dict[str, Any]]:
    """One text field declaring the backtracking pattern, optionally with a default."""
    field: dict[str, Any] = {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': BACKTRACKING_REGEX}

    if default is not None:
        field['value'] = default

    return [field]


def _sections() -> list[dict[str, Any]]:
    """One section showing the field."""
    return [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [CODE_FIELD]}]


def _object_payload(value: str) -> dict[str, Any]:
    """A POST / PUT /objects/ body carrying the value."""
    return {'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'type': 'text', 'name': CODE_FIELD, 'value': value}]}


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the patterned type; removes every type, object and log this module creates."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': OBJECT_ID})
        database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many({'object_id': OBJECT_ID})

    _purge()
    types.insert_one(make_type_doc(TYPE_ID, 'time-limit-type', fields=_fields(), sections=_sections()))
    yield types, objects
    _purge()


def _timed(call) -> tuple[Any, float]:
    """The response of a call and the seconds it took."""
    started: float = time.monotonic()
    response = call()

    return response, time.monotonic() - started


class TestObjectWrites:
    """POST / PUT /objects/."""

    def test_a_create_the_pattern_cannot_decide_is_refused_in_time(self, rest_api, db) -> None:
        """400 with the timeout message, inside the budget - and nothing is stored"""
        _, objects = db

        response, elapsed = _timed(lambda: rest_api.post('/objects/', json=_object_payload(BACKTRACKING_VALUE)))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == FieldValueError.PATTERN_TIMEOUT.format(
            field=CODE_FIELD, regex=BACKTRACKING_REGEX)
        assert elapsed < ROUTE_LIMIT_SECONDS
        assert objects.count_documents({'public_id': OBJECT_ID}) == 0

    def test_a_value_the_pattern_decides_is_stored(self, rest_api, db) -> None:
        """The same pattern is still enforced on an ordinary value"""
        _, objects = db

        assert rest_api.post('/objects/', json=_object_payload(MATCHING_VALUE)).status_code == HTTPStatus.OK
        assert objects.count_documents({'public_id': OBJECT_ID}) == 1

    def test_an_update_the_pattern_cannot_decide_is_refused_and_the_object_stays(self, rest_api, db) -> None:
        """PUT: 400 in time, the stored value kept"""
        _, objects = db
        assert rest_api.post('/objects/', json=_object_payload(MATCHING_VALUE)).status_code == HTTPStatus.OK

        response, elapsed = _timed(
            lambda: rest_api.put(f'/objects/{OBJECT_ID}', json=_object_payload(BACKTRACKING_VALUE)),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert elapsed < ROUTE_LIMIT_SECONDS
        assert objects.find_one({'public_id': OBJECT_ID})['fields'][0]['value'] == MATCHING_VALUE


class TestTypeWrites:
    """POST /types/."""

    def test_a_default_the_pattern_cannot_decide_is_refused_in_time(self, rest_api, db) -> None:
        """The type write's default check gets the same limit and its own wording"""
        types, _ = db
        payload: dict[str, Any] = make_type_doc(NEW_TYPE_ID, 'time-limit-new', fields=_fields(BACKTRACKING_VALUE),
                                                sections=_sections())
        payload.pop('creation_time', None)

        response, elapsed = _timed(lambda: rest_api.post('/types/', json=payload))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == FieldDefaultError.PATTERN_TIMEOUT.format(
            field=CODE_FIELD, regex=BACKTRACKING_REGEX)
        assert elapsed < ROUTE_LIMIT_SECONDS
        assert types.count_documents({'public_id': NEW_TYPE_ID}) == 0
