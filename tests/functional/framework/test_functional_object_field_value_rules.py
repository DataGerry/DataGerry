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
Functional coverage of the field value rules on the ``/objects`` write routes

A text or textarea value may not be longer than its field kind's cap, and a value must match the regex
its field declares - rules the object form applied alone before. These tests drive the real routes
(POST, PUT, bulk PUT, PATCH) against a seeded type with a plain text field, a textarea, a patterned
field and a patterned multi-data-section field, and assert both halves: a broken rule is refused with
400 and leaves the stored object untouched, a valid value is stored. Also pinned: an update is not
refused over a value it leaves as it was stored
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.object_field_value_constants import FieldValueError, MDS_SECTION_SUFFIX
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, TEXT_VALUE_MAX_LENGTH, TEXTAREA_VALUE_MAX_LENGTH
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

TYPE_ID: int = 9640
OBJECT_ID: int = 9641
BULK_OBJECT_IDS: list[int] = [9642, 9643]
ALL_OBJECT_IDS: list[int] = [OBJECT_ID] + BULK_OBJECT_IDS

TEXT_FIELD: str = 'fv-text'
NOTES_FIELD: str = 'fv-notes'
CODE_FIELD: str = 'fv-code'
ROW_FIELD: str = 'fv-row'
MDS_SECTION: str = 'fv-rows'
CODE_REGEX: str = '[A-Z]{2,4}'

SEED_TEXT: str = 'seeded'
VALID_CODE: str = 'ABC'
INVALID_CODE: str = 'abc'
TOO_LONG_TEXT: str = 'x' * (TEXT_VALUE_MAX_LENGTH + 1)
TOO_LONG_NOTES: str = 'n' * (TEXTAREA_VALUE_MAX_LENGTH + 1)
AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'


def _type_doc() -> dict[str, Any]:
    """The CmdbType whose value rules the routes must enforce."""
    return {
        'public_id': TYPE_ID,
        'name': 'field-value-rules-type',
        'label': 'Field Value Rules Type',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': TEXT_FIELD, 'label': 'Text'},
            {'type': 'textarea', 'name': NOTES_FIELD, 'label': 'Notes'},
            {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': CODE_REGEX},
            {'type': 'text', 'name': ROW_FIELD, 'label': 'Row', 'regex': CODE_REGEX},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [
                {'type': 'section', 'name': 'information', 'label': 'Information',
                 'fields': [TEXT_FIELD, NOTES_FIELD, CODE_FIELD]},
                {'type': 'multi-data-section', 'name': MDS_SECTION, 'label': 'Rows', 'fields': [ROW_FIELD]},
            ],
            'summary': {'fields': [TEXT_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _payload(public_id: int, text: Any = SEED_TEXT, notes: Any = '', code: Any = VALID_CODE,
             row: Any = None) -> dict[str, Any]:
    """A complete object payload; the values are the caller's to break."""
    payload: dict[str, Any] = {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': TEXT_FIELD, 'value': text},
            {'type': 'textarea', 'name': NOTES_FIELD, 'value': notes},
            {'type': 'text', 'name': CODE_FIELD, 'value': code},
        ],
    }

    if row is not None:
        payload['multi_data_sections'] = [{
            'section_id': MDS_SECTION,
            'highest_id': 1,
            'values': [{'multi_data_id': 1, 'data': [{'type': 'text', 'name': ROW_FIELD, 'value': row}]}],
        }]

    return payload


@pytest.fixture(scope='module', autouse=True)
def _seed_type(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type for the module; removes it, its objects and their logs afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(_type_doc())
    yield
    types.delete_many({'public_id': TYPE_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': ALL_OBJECT_IDS}}
    )


@pytest.fixture(autouse=True)
def _clean_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the test objects around each test."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    yield
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any] | None:
    """The stored object document."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})


def _stored_value(database_manager: MongoDatabaseManager, database_name: str, public_id: int, name: str) -> Any:
    """The stored top-level value of a field."""
    stored: dict[str, Any] = _stored(database_manager, database_name, public_id)

    return next(field['value'] for field in stored['fields'] if field['name'] == name)


def _insert_directly(database_manager: MongoDatabaseManager, database_name: str, public_id: int,
                     **values: Any) -> None:
    """Stores an object past the routes - the way one written before the rules existed would be stored."""
    document: dict[str, Any] = _payload(public_id, **values)
    document['creation_time'] = datetime.now(timezone.utc)
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(document)


def _too_long_message(field: str, value: str, max_length: int) -> str:
    """The message a value over its cap is refused with."""
    return FieldValueError.TOO_LONG.format(field=field, length=len(value), max_length=max_length)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPost:
    """POST /objects/"""

    def test_valid_values_are_stored(self, rest_api, database_manager: MongoDatabaseManager,
                                     database_name: str) -> None:
        """Every value at or under its cap and matching its pattern"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(
            OBJECT_ID, text='x' * TEXT_VALUE_MAX_LENGTH, notes='n' * TEXTAREA_VALUE_MAX_LENGTH, row=VALID_CODE,
        ))

        assert response.status_code == HTTPStatus.OK
        assert _stored_value(database_manager, database_name, OBJECT_ID, NOTES_FIELD) == 'n' * TEXTAREA_VALUE_MAX_LENGTH

    @pytest.mark.parametrize('values, message', [
        ({'text': TOO_LONG_TEXT}, _too_long_message(TEXT_FIELD, TOO_LONG_TEXT, TEXT_VALUE_MAX_LENGTH)),
        ({'notes': TOO_LONG_NOTES}, _too_long_message(NOTES_FIELD, TOO_LONG_NOTES, TEXTAREA_VALUE_MAX_LENGTH)),
        ({'code': INVALID_CODE}, FieldValueError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=CODE_REGEX)),
        ({'row': INVALID_CODE}, FieldValueError.PATTERN_MISMATCH.format(field=ROW_FIELD, regex=CODE_REGEX)
         + MDS_SECTION_SUFFIX.format(section_id=MDS_SECTION)),
    ], ids=['text-too-long', 'notes-too-long', 'pattern', 'mds-row-pattern'])
    def test_a_broken_rule_is_refused_and_nothing_is_created(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
        values: dict[str, Any], message: str,
    ) -> None:
        """400 naming the field; the refusal comes before the write"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID, **values))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == message
        assert _stored(database_manager, database_name, OBJECT_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPut:
    """PUT /objects/<id>, single and bulk"""

    def test_a_broken_rule_is_refused_and_the_object_stays(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The stored value is kept"""
        _insert_directly(database_manager, database_name, OBJECT_ID)

        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, code=INVALID_CODE))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_value(database_manager, database_name, OBJECT_ID, CODE_FIELD) == VALID_CODE

    def test_a_valid_change_is_stored(self, rest_api, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
        """The control"""
        _insert_directly(database_manager, database_name, OBJECT_ID)

        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, code='XYZ'))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(database_manager, database_name, OBJECT_ID, CODE_FIELD) == 'XYZ'

    def test_a_bulk_update_is_refused_for_every_target(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The shared payload of a bulk update is judged too - no target is written"""
        for public_id in BULK_OBJECT_IDS:
            _insert_directly(database_manager, database_name, public_id)

        query: str = '&'.join(f'objectIDs={public_id}' for public_id in BULK_OBJECT_IDS)
        response = rest_api.put(
            f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}?{query}', json=_payload(BULK_OBJECT_IDS[0], text=TOO_LONG_TEXT),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        for public_id in BULK_OBJECT_IDS:
            assert _stored_value(database_manager, database_name, public_id, TEXT_FIELD) == SEED_TEXT


class TestPatch:
    """PATCH /objects/<id> - the route the Rack view saves its notes through"""

    def test_a_broken_rule_is_refused(self, rest_api, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
        """The merged object is judged, and the stored value is kept"""
        _insert_directly(database_manager, database_name, OBJECT_ID)

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}',
                                  json={'fields': [{'name': NOTES_FIELD, 'value': TOO_LONG_NOTES}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_value(database_manager, database_name, OBJECT_ID, NOTES_FIELD) == ''

    def test_a_valid_change_is_stored(self, rest_api, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
        """The control"""
        _insert_directly(database_manager, database_name, OBJECT_ID)

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': NOTES_FIELD, 'value': 'n'}]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(database_manager, database_name, OBJECT_ID, NOTES_FIELD) == 'n'


# -------------------------------------------------------------------------------------------------------------------- #
#                                               A VALUE STORED EARLIER                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAValueStoredBeforeTheRules:
    """An object written before the cap or the pattern existed can still be edited."""

    def test_another_field_can_be_changed(self, rest_api, database_manager: MongoDatabaseManager,
                                          database_name: str) -> None:
        """The oversized, non-matching values stay; the change to another field is stored"""
        _insert_directly(database_manager, database_name, OBJECT_ID, text=TOO_LONG_TEXT, code=INVALID_CODE)

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': NOTES_FIELD, 'value': 'n'}]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(database_manager, database_name, OBJECT_ID, TEXT_FIELD) == TOO_LONG_TEXT

    def test_the_old_value_is_judged_once_it_is_changed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Replacing it with another oversized value is refused"""
        _insert_directly(database_manager, database_name, OBJECT_ID, text=TOO_LONG_TEXT)

        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, text=TOO_LONG_TEXT + 'y'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_value(database_manager, database_name, OBJECT_ID, TEXT_FIELD) == TOO_LONG_TEXT
