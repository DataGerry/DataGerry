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
Integration tests for the CmdbObject field value rules against a real MongoDB

Three things only a real database shows:

- **the rules of a stored type.** The cap and the pattern are derived from the CmdbType as the
  TypesManager reads it back, so a regex that survived the round trip is the regex that is applied
- **what counts as unchanged.** The update pipeline compares the candidate with the stored object as
  ``CmdbObject.to_json`` serialises it after a real read - top-level values and multi-data-section rows
  both - so an oversized value written before the rules existed passes an edit that leaves it alone
- **the importer's context.** ``build_import_type_context`` over the stored type carries the same
  rules, so an imported row is judged exactly like a POST - including the pattern's time limit, each row with
  its own budget
"""
import time
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.framework.importer.helper.object_import_validator import (
    build_import_type_context,
    normalize_and_validate_object,
)
from cmdb.framework.object_field_value_constants import FieldValueError
from cmdb.framework.object_field_value_rules import build_field_value_rules, collect_object_value_errors
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, TEXT_VALUE_MAX_LENGTH
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9650
OBJECT_ID: int = 9651
AUTHOR_ID: int = 1
VERSION: str = '1.0.0'

TEXT_FIELD: str = 'iv-text'
CODE_FIELD: str = 'iv-code'
ROW_FIELD: str = 'iv-row'
MDS_SECTION: str = 'iv-rows'
CODE_REGEX: str = r'[A-Z]{2}-\d+'

TOO_LONG_TEXT: str = 'x' * (TEXT_VALUE_MAX_LENGTH + 1)
INVALID_CODE: str = 'ab-1'
VALID_CODE: str = 'AB-1'

ADMIN: CmdbUser = CmdbUser(public_id=AUTHOR_ID, user_name='admin', active=True, group_id=1)


def _type_document() -> dict[str, Any]:
    """A type with a capped text field, a patterned field and a patterned multi-data-section field."""
    return {
        'public_id': TYPE_ID,
        'name': 'field-value-rules-integration',
        'label': 'Field Value Rules Integration',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': TEXT_FIELD, 'label': 'Text'},
            {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': CODE_REGEX},
            {'type': 'text', 'name': ROW_FIELD, 'label': 'Row', 'regex': CODE_REGEX},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [
                {'type': 'section', 'name': 'information', 'label': 'Information', 'fields': [TEXT_FIELD, CODE_FIELD]},
                {'type': 'multi-data-section', 'name': MDS_SECTION, 'label': 'Rows', 'fields': [ROW_FIELD]},
            ],
            'summary': {'fields': [TEXT_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': VERSION,
    }


def _object_document(text: str, code: str, row: str) -> dict[str, Any]:
    """An object of the type, with one multi-data-section row."""
    return {
        'public_id': OBJECT_ID,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': 'text', 'name': TEXT_FIELD, 'value': text},
            {'type': 'text', 'name': CODE_FIELD, 'value': code},
            {'type': 'text', 'name': ROW_FIELD, 'value': None},
        ],
        'multi_data_sections': [{
            'section_id': MDS_SECTION,
            'highest_id': 1,
            'values': [{'multi_data_id': 1, 'data': [{'type': 'text', 'name': ROW_FIELD, 'value': row}]}],
        }],
    }


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """Pushes the REST API app context so ManagerProvider resolves its database manager."""
    with rest_api.application.app_context():
        yield


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Stores the type and an object written before the rules - oversized, non-matching values."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': OBJECT_ID})

    _purge()
    types.insert_one(_type_document())
    objects.insert_one(_object_document(TOO_LONG_TEXT, INVALID_CODE, INVALID_CODE))
    yield
    _purge()


def _stored_type() -> CmdbType:
    """The type as the TypesManager reads it back."""
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, ADMIN)

    return CmdbType.from_data(types_manager.get_type(TYPE_ID))


def _stored_object() -> dict[str, Any]:
    """The object as the update pipeline sees it: a real read, serialised by CmdbObject.to_json."""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, ADMIN)

    return CmdbObject.to_json(objects_manager.get_object(OBJECT_ID, as_dict=False))


class TestTheRulesOfAStoredType:
    """The cap and the pattern, derived from the type read back from the collection."""

    def test_the_regex_survives_the_round_trip(self) -> None:
        """The stored regex is the one applied, and the one the message quotes"""
        rules = build_field_value_rules(_stored_type().get_fields())

        assert rules[CODE_FIELD].regex == CODE_REGEX
        assert rules[TEXT_FIELD].max_length == TEXT_VALUE_MAX_LENGTH

    def test_a_new_object_with_the_old_values_is_refused(self) -> None:
        """Without a stored object to compare with, every value is judged - each field once"""
        errors = collect_object_value_errors(
            _object_document(TOO_LONG_TEXT, INVALID_CODE, INVALID_CODE),
            build_field_value_rules(_stored_type().get_fields()),
        )

        assert len(errors) == 3


class TestWhatCountsAsUnchanged:
    """The stored object, read and serialised the way the update pipeline does it."""

    def test_an_edit_leaving_the_old_values_alone_passes(self) -> None:
        """Top-level values and the row both compare equal after the real round trip"""
        candidate: dict[str, Any] = _stored_object()

        assert collect_object_value_errors(
            candidate, build_field_value_rules(_stored_type().get_fields()), _stored_object(),
        ) == []

    def test_a_changed_row_value_is_judged(self) -> None:
        """Only the value the edit changed is reported"""
        candidate: dict[str, Any] = _stored_object()
        candidate['multi_data_sections'][0]['values'][0]['data'][0]['value'] = 'still-wrong'

        errors = collect_object_value_errors(
            candidate, build_field_value_rules(_stored_type().get_fields()), _stored_object(),
        )

        assert len(errors) == 1
        assert ROW_FIELD in errors[0]


class TestTheImporterContext:
    """build_import_type_context over the stored type."""

    def test_an_imported_row_is_judged_like_a_post(self) -> None:
        """The same messages the REST path gives"""
        working_object: dict[str, Any] = {
            'type_id': TYPE_ID, 'active': True,
            'fields': [{'name': TEXT_FIELD, 'value': 'fine'}, {'name': CODE_FIELD, 'value': INVALID_CODE}],
        }

        errors = normalize_and_validate_object(
            working_object, None, AUTHOR_ID, build_import_type_context(_stored_type()),
        )

        assert FieldValueError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=CODE_REGEX) in errors

    def test_a_valid_row_imports(self) -> None:
        """The control"""
        working_object: dict[str, Any] = {
            'type_id': TYPE_ID, 'active': True,
            'fields': [{'name': TEXT_FIELD, 'value': 'fine'}, {'name': CODE_FIELD, 'value': VALID_CODE}],
        }

        assert normalize_and_validate_object(
            working_object, None, AUTHOR_ID, build_import_type_context(_stored_type()),
        ) == []


TIME_LIMIT_TYPE_ID: int = 9659
BACKTRACKING_REGEX: str = '(a|aa)+b'
BACKTRACKING_VALUE: str = 'a' * 60
IMPORT_ROW_LIMIT_SECONDS: float = 1.5


@pytest.fixture(name='time_limit_type')
def fixture_time_limit_type(database_manager: MongoDatabaseManager, database_name: str):
    """A stored type whose code field declares a backtracking pattern"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    document: dict[str, Any] = _type_document()
    document.update({'public_id': TIME_LIMIT_TYPE_ID, 'name': 'iv-time-limit', 'label': 'IV Time Limit'})
    document['fields'] = [
        {'type': 'text', 'name': TEXT_FIELD, 'label': 'Text'},
        {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': BACKTRACKING_REGEX},
        {'type': 'text', 'name': ROW_FIELD, 'label': 'Row'},
    ]
    types.delete_many({'public_id': TIME_LIMIT_TYPE_ID})
    types.insert_one(document)

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, CmdbUser(
        public_id=AUTHOR_ID, user_name='admin', active=True, group_id=1,
    ))
    yield CmdbType.from_data(types_manager.get_type(TIME_LIMIT_TYPE_ID))

    types.delete_many({'public_id': TIME_LIMIT_TYPE_ID})


def _import_row(code: str) -> dict[str, Any]:
    """One imported row of the time-limit type"""
    return {'type_id': TIME_LIMIT_TYPE_ID, 'active': True,
            'fields': [{'name': TEXT_FIELD, 'value': 'fine'}, {'name': CODE_FIELD, 'value': code}]}


class TestTheTimeLimitInTheImporter:
    """Each imported row is judged with its own pattern budget."""

    def test_a_row_the_pattern_cannot_decide_is_refused_with_the_reason(self, time_limit_type: CmdbType) -> None:
        """The timeout message is the row's reason, inside the budget"""
        started: float = time.monotonic()
        errors = normalize_and_validate_object(
            _import_row(BACKTRACKING_VALUE), None, AUTHOR_ID, build_import_type_context(time_limit_type),
        )

        assert time.monotonic() - started < IMPORT_ROW_LIMIT_SECONDS
        assert FieldValueError.PATTERN_TIMEOUT.format(field=CODE_FIELD, regex=BACKTRACKING_REGEX) in errors

    def test_the_next_row_starts_its_own_budget(self, time_limit_type: CmdbType) -> None:
        """A timed-out row does not spend the following row's checks: a matching value still imports"""
        context = build_import_type_context(time_limit_type)
        normalize_and_validate_object(_import_row(BACKTRACKING_VALUE), None, AUTHOR_ID, context)

        assert normalize_and_validate_object(_import_row('aab'), None, AUTHOR_ID, context) == []

    def test_a_row_the_pattern_refuses_is_still_a_mismatch(self, time_limit_type: CmdbType) -> None:
        """A short value is decided, not timed out"""
        errors = normalize_and_validate_object(
            _import_row('aa'), None, AUTHOR_ID, build_import_type_context(time_limit_type),
        )

        assert FieldValueError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=BACKTRACKING_REGEX) in errors
