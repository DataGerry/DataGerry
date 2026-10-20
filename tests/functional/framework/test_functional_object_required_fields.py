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
Functional coverage of the required-field rule on the ``/objects`` write routes

A CmdbType field flagged ``required`` may not be saved without a value - the rule the object form
applies in the frontend and the importer applies to an uploaded row. These tests drive the real HTTP
routes (POST, PUT, bulk PUT, PATCH) against a seeded type carrying a required top-level field and a
required multi-data-section field, and assert both halves: the empty write is refused with 400 and
leaves the stored object untouched, while a value the user actually chose (0, False) is accepted
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

TYPE_ID: int = 9630
TYPE_NAME: str = 'required-fields-type'

REQUIRED_FIELD: str = 'req-name'      # required text field of the plain section
OPTIONAL_FIELD: str = 'opt-note'      # optional text field of the plain section
REQUIRED_FLAG: str = 'req-flag'       # required checkbox - False is a chosen value, not a gap
ROW_FIELD: str = 'req-row'            # required text field of the multi-data section
MDS_SECTION: str = 'req-rows'

OBJECT_ID: int = 9631
BULK_OBJECT_IDS: list[int] = [9632, 9633]
ALL_OBJECT_IDS: list[int] = [OBJECT_ID] + BULK_OBJECT_IDS

SEED_VALUE: str = 'seeded'
AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

MISSING_VALUE_MESSAGE: str = 'Missing value for required field(s)'


def _type_doc() -> dict[str, Any]:
    """Builds the CmdbType whose required fields the routes must enforce."""
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Required Fields Type',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': REQUIRED_FIELD, 'label': 'Name', 'required': True},
            {'type': 'text', 'name': OPTIONAL_FIELD, 'label': 'Note'},
            {'type': 'checkbox', 'name': REQUIRED_FLAG, 'label': 'Flag', 'required': True},
            {'type': 'text', 'name': ROW_FIELD, 'label': 'Row', 'required': True},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [
                {
                    'type': 'section',
                    'name': 'information',
                    'label': 'Information',
                    'fields': [REQUIRED_FIELD, OPTIONAL_FIELD, REQUIRED_FLAG],
                },
                {'type': 'multi-data-section', 'name': MDS_SECTION, 'label': 'Rows', 'fields': [ROW_FIELD]},
            ],
            'summary': {'fields': [REQUIRED_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _payload(
        public_id: int,
        value: Any = SEED_VALUE,
        flag: Any = True,
        multi_data_sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a complete object payload; the required values are the caller's to break."""
    payload: dict[str, Any] = {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': REQUIRED_FIELD, 'value': value},
            {'type': 'checkbox', 'name': REQUIRED_FLAG, 'value': flag},
        ],
    }

    if multi_data_sections is not None:
        payload['multi_data_sections'] = multi_data_sections

    return payload


def _mds_section(row_value: Any) -> list[dict[str, Any]]:
    """Builds the object's multi-data section carrying a single row with the given required value."""
    return [{
        'section_id': MDS_SECTION,
        'highest_id': 1,
        'values': [{'multi_data_id': 1, 'data': [{'type': 'text', 'name': ROW_FIELD, 'value': row_value}]}],
    }]


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType used by every test and removes it plus all test objects afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(_type_doc())
    yield
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    # Every accepted write logs; the log routes page through the whole collection, so the logs this
    # suite produced are removed with its objects
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': ALL_OBJECT_IDS}}
    )


def _drop_objects(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes every object of the seeded type, for per-test cleanup."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'type_id': TYPE_ID})


def _stored_value(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> Any:
    """Reads the stored value of the required field straight from the collection."""
    stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})

    return next(field['value'] for field in stored['fields'] if field['name'] == REQUIRED_FIELD)


@pytest.fixture(name='seeded_object')
def fixture_seeded_object(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Creates one valid object through the route and removes every test object afterwards."""
    response = rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID))
    assert response.status_code == HTTPStatus.OK
    yield
    _drop_objects(database_manager, database_name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostRequiredFields:
    """POST /objects/ refuses to create an object whose required fields carry no value."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, database_manager: MongoDatabaseManager, database_name: str):
        """Drops whatever a test managed to create."""
        yield
        _drop_objects(database_manager, database_name)

    @pytest.mark.parametrize('value', ['', None])
    def test_empty_required_value_is_rejected(self, rest_api, value: Any) -> None:
        """An empty string and an explicit null are both refused with 400."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID, value=value))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert REQUIRED_FIELD in response.get_json()['message']

    def test_a_required_field_the_payload_omits_is_rejected(self, rest_api) -> None:
        """A payload that does not carry the required field at all is refused with 400."""
        payload = _payload(OBJECT_ID)
        payload['fields'] = [{'type': 'text', 'name': OPTIONAL_FIELD, 'value': 'x'}]

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert REQUIRED_FIELD in response.get_json()['message']

    def test_nothing_is_created_when_the_write_is_refused(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The refusal happens before the write: no object is left behind."""
        rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID, value=''))

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
            {'public_id': OBJECT_ID}
        )

        assert stored is None

    def test_a_row_leaving_its_required_field_empty_is_rejected(self, rest_api) -> None:
        """A multi-data row without a value for its required field is refused, naming the section."""
        response = rest_api.post(
            f'{ROUTE_URL}/', json=_payload(OBJECT_ID, multi_data_sections=_mds_section('')),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert MDS_SECTION in response.get_json()['message']

    def test_a_complete_object_is_created(self, rest_api) -> None:
        """The control: every required field carrying a value still creates the object."""
        response = rest_api.post(
            f'{ROUTE_URL}/', json=_payload(OBJECT_ID, multi_data_sections=_mds_section('row value')),
        )

        assert response.status_code == HTTPStatus.OK

    def test_a_section_without_rows_requires_nothing(self, rest_api) -> None:
        """An empty multi-data section is an empty section, not a missing value."""
        empty_section = [{'section_id': MDS_SECTION, 'highest_id': 0, 'values': []}]

        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID, multi_data_sections=empty_section))

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize('flag', [False, 0])
    def test_a_falsy_but_chosen_value_is_accepted(self, rest_api, flag: Any) -> None:
        """An unchecked required checkbox is a value the user chose, so the create goes through."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(OBJECT_ID, flag=flag))

        assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutRequiredFields:
    """PUT /objects/<id> refuses to blank a required field of an existing object."""

    def test_blanking_a_required_field_is_rejected(self, rest_api, seeded_object) -> None:
        """A full update that empties the required field answers 400."""
        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, value=''))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert REQUIRED_FIELD in response.get_json()['message']

    def test_the_stored_value_survives_a_rejected_update(
        self,
        rest_api,
        seeded_object,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The refusal happens before the write, so the stored object keeps its value."""
        rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, value=''))

        assert _stored_value(database_manager, database_name, OBJECT_ID) == SEED_VALUE

    def test_a_valid_update_still_goes_through(
        self,
        rest_api,
        seeded_object,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The control: a new value for the required field is stored as usual."""
        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=_payload(OBJECT_ID, value='changed'))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_value(database_manager, database_name, OBJECT_ID) == 'changed'

    def test_a_bulk_update_is_rejected_for_every_target(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The shared payload of a bulk update is validated too - no target is written."""
        try:
            for public_id in BULK_OBJECT_IDS:
                assert rest_api.post(f'{ROUTE_URL}/', json=_payload(public_id)).status_code == HTTPStatus.OK

            query = '&'.join(f'objectIDs={public_id}' for public_id in BULK_OBJECT_IDS)
            response = rest_api.put(
                f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}?{query}', json=_payload(BULK_OBJECT_IDS[0], value=''),
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
            for public_id in BULK_OBJECT_IDS:
                assert _stored_value(database_manager, database_name, public_id) == SEED_VALUE
        finally:
            _drop_objects(database_manager, database_name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        PATCH                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPatchRequiredFields:
    """PATCH /objects/<id> is validated on the merged object, not on the subset it carries."""

    def test_blanking_a_required_field_is_rejected(self, rest_api, seeded_object) -> None:
        """A patch that empties the required field answers 400."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': REQUIRED_FIELD, 'value': ''}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert MISSING_VALUE_MESSAGE in response.get_json()['message']

    def test_a_patch_that_leaves_the_required_field_alone_is_accepted(self, rest_api, seeded_object) -> None:
        """A required field the patch does not mention keeps its stored value, so the patch passes."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': OPTIONAL_FIELD, 'value': 'x'}]})

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_a_created_row_without_its_required_value_is_rejected(self, rest_api, seeded_object) -> None:
        """A new multi-data row must carry its section's required fields like any other row."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID}', json={
            'created_mds_rows': [{'section_id': MDS_SECTION, 'data': [{'name': ROW_FIELD, 'value': ''}]}],
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert MDS_SECTION in response.get_json()['message']
