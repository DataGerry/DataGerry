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
Functional coverage for the /import/type routes

Both verbs share a partial-report contract: every uploaded entry is processed independently and the
response body maps the failed entries to a diagnostic message, so one bad entry never discards the
rest of the batch. Covers create (add_type): types are inserted with server-assigned public_ids;
update (update_type): existing types are updated, an unknown public_id is reported instead of silently
succeeding, and an entry without a public_id is keyed by its position rather than raising; the
special_type rules (known value, unique marker, immutable across an update); the name / field /
section rules and the silent repairs (default icon, cleared dangling cross-type references); plus the
missing-upload, malformed-JSON and non-list-payload -> 400 guards on both verbs.
"""
import json
import re
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField
from tests.utils.ipam_doc_builders import make_type_doc, make_object_doc, make_field
# -------------------------------------------------------------------------------------------------------------------- #

CREATE_URL: str = '/import/type/create/'
UPDATE_URL: str = '/import/type/update/'

ADMIN_PUBLIC_ID: int = 1  # the user the rest_api fixture authenticates as
FOREIGN_AUTHOR_ID: int = 777  # a user id from the system the type was exported from
FOREIGN_EDITOR_ID: int = 888
LOCAL_AUTHOR_ID: int = 5  # the author already stored on this system before an import update
SPECIAL_TYPE_ID: int = 47413
CURRENT_YEAR: int = 2026

NEW_TYPE_NAME: str = 'imported-type-new'
SECOND_TYPE_NAME: str = 'imported-type-second'
UPDATE_TYPE_ID: int = 47411
MISSING_TYPE_ID: int = 47412
UPDATED_LABEL: str = 'imported-type-updated-label'
STORED_VERSION: str = '2.5.0'  # a version already bumped on this system, set by no import

TEMPLATE_ID: int = 47430
TEMPLATE_NAME: str = 'dg-import-contact'

RECONCILED_OBJECT_ID: int = 47420  # an object of the updated type, reconciled by the side effects
RECONCILED_LOCATION_ID: int = 47421

ALL_TYPE_IDS: list[int] = [UPDATE_TYPE_ID, MISSING_TYPE_ID, SPECIAL_TYPE_ID]
ALL_TYPE_NAMES: list[str] = [NEW_TYPE_NAME, SECOND_TYPE_NAME]


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any types created / updated by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
            {'$or': [{'public_id': {'$in': ALL_TYPE_IDS}}, {'name': {'$in': ALL_TYPE_NAMES}}]}
        )
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
            {'public_id': RECONCILED_OBJECT_ID}
        )
        database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
            {'public_id': RECONCILED_LOCATION_ID}
        )
        database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name).delete_many(
            {'public_id': TEMPLATE_ID}
        )

    _purge()
    yield
    _purge()


def _upload_form(types: list[Any]) -> dict[str, Any]:
    """Builds the form payload the import routes expect (a JSON list under 'uploadFile')."""
    return {'uploadFile': json.dumps(types, default=str)}


def _raw_upload_form(payload: Any) -> dict[str, Any]:
    """Builds an upload form around any payload, so a non-list body can be sent."""
    return {'uploadFile': json.dumps(payload, default=str)}


class TestAddType:
    """POST /import/type/create/ inserts uploaded types and collects per-type failures."""

    def test_creates_type(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid type upload is inserted and no errors are collected."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')  # the route assigns a fresh public_id

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored is not None

    def test_authorship_is_rewritten_onto_the_importer(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The importing user becomes the author; the source system's user ids are not carried over."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['author_id'] = FOREIGN_AUTHOR_ID
        payload['editor_id'] = FOREIGN_EDITOR_ID
        payload['last_edit_time'] = '2020-01-01T00:00:00'

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored['author_id'] == ADMIN_PUBLIC_ID
        assert stored['editor_id'] is None
        assert stored['last_edit_time'] is None

    def test_invalid_entry_is_collected_not_aborted(self, rest_api) -> None:
        """An invalid type entry is recorded in the error collection instead of failing the request."""
        response = rest_api.post(CREATE_URL, data=_upload_form([{}]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1

    def test_error_message_carries_detail(self, rest_api) -> None:
        """A collected create failure names the reason, not just a generic sentence."""
        # named (so the name rules pass) but with an unusable acl, which CmdbType.from_data rejects
        response = rest_api.post(
            CREATE_URL,
            data=_upload_form([{'name': 'broken-type', 'acl': 'not-a-dict'}]),
            content_type='multipart/form-data',
        )

        (message,) = response.get_json().values()
        assert message.startswith('Failed to create a Type instance from the provided data:')
        assert len(message) > len('Failed to create a Type instance from the provided data:')

    def test_valid_entry_survives_an_invalid_sibling(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """One unusable entry does not stop the remaining entries of the batch from being inserted."""
        valid = make_type_doc(0, SECOND_TYPE_NAME)
        valid.pop('public_id')

        response = rest_api.post(
            CREATE_URL, data=_upload_form([{}, valid]), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': SECOND_TYPE_NAME})
        assert stored is not None

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """A create with no uploadFile is rejected with 400."""
        assert rest_api.post(CREATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_non_list_upload_returns_400(self, rest_api) -> None:
        """A single type object instead of a list is rejected with 400 rather than iterated by key."""
        assert rest_api.post(
            CREATE_URL, data=_raw_upload_form(make_type_doc(0, NEW_TYPE_NAME)), content_type='multipart/form-data'
        ).status_code == HTTPStatus.BAD_REQUEST


class TestUpdateType:
    """POST /import/type/update/ updates existing types from the upload."""

    def test_updates_existing_type(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload for an existing type applies the update."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['label'] == UPDATED_LABEL

    def test_importer_is_recorded_as_the_editor(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update records the importer as the editor rather than re-attributing authorship."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['editor_id'] = FOREIGN_EDITOR_ID
        updated['last_edit_time'] = '2020-01-01T00:00:00'

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = types.find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['editor_id'] == ADMIN_PUBLIC_ID
        assert stored['last_edit_time'] is not None
        assert stored['last_edit_time'].year >= CURRENT_YEAR  # server-stamped, not the uploaded 2020

    def test_stored_author_and_creation_time_survive_the_update(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The uploaded author_id / creation_time never overwrite how the type came to exist here."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        seed = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        seed['author_id'] = LOCAL_AUTHOR_ID
        types.insert_one(seed)
        original_creation_time = types.find_one({'public_id': UPDATE_TYPE_ID})['creation_time']

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['author_id'] = FOREIGN_AUTHOR_ID
        updated['creation_time'] = '2020-01-01T00:00:00'
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored = types.find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['author_id'] == LOCAL_AUTHOR_ID          # not the uploaded FOREIGN_AUTHOR_ID
        assert stored['creation_time'] == original_creation_time
        assert stored['label'] == UPDATED_LABEL                # the rest of the type still replaced

    def test_unknown_public_id_is_reported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Updating a type that does not exist is reported instead of silently succeeding."""
        payload = make_type_doc(MISSING_TYPE_ID, 'imported-type-missing')

        response = rest_api.post(UPDATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {
            str(MISSING_TYPE_ID): f'No Type with public_id {MISSING_TYPE_ID} exists, it can not be updated!'
        }
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': MISSING_TYPE_ID})
        assert stored is None  # the failed update must not have upserted the type

    def test_invalid_entry_is_collected_not_aborted(self, rest_api) -> None:
        """An entry the update cannot apply is collected, keyed by its position."""
        # an update is applied by public_id, and this entry carries none
        response = rest_api.post(
            UPDATE_URL,
            data=_upload_form([{'name': 'broken-type'}]),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        (key, message), = response.get_json().items()
        assert key == 'entry_0'  # no public_id to key on - the position is used instead of raising
        assert message == 'No Type with public_id None exists, it can not be updated!' 

    def test_valid_entry_survives_an_invalid_sibling(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """One unusable entry does not stop the remaining entries of the batch from being updated."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(
            UPDATE_URL, data=_upload_form([{}, updated]), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        assert list(response.get_json()) == ['entry_0']
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['label'] == UPDATED_LABEL

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """An update with no uploadFile is rejected with 400."""
        assert rest_api.post(UPDATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_non_list_upload_returns_400(self, rest_api) -> None:
        """A single type object instead of a list is rejected with 400 rather than iterated by key."""
        assert rest_api.post(
            UPDATE_URL,
            data=_raw_upload_form(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')),
            content_type='multipart/form-data',
        ).status_code == HTTPStatus.BAD_REQUEST


class TestSpecialTypeRules:
    """special_type is validated, unique and immutable across the import routes.

    These run on an IPAM-licensed instance so the licence gate (covered separately in
    test_functional_ipam_importer_gating) is out of the way and the other rules are what is exercised.
    """

    @pytest.fixture(autouse=True)
    def _licensed(self, monkeypatch) -> None:
        """Unlocks IPAM so the special-type rules other than the licence gate are reachable."""
        monkeypatch.setattr(
            LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM
        )

    def test_unknown_special_type_is_rejected(self, rest_api) -> None:
        """Only a known SpecialType value may be assigned."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['special_type'] = 'NOT_A_SPECIAL_TYPE'

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'not a valid special Type' in message

    def test_special_type_can_only_exist_once(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A marker already claimed by a stored type cannot be imported again."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET))

        payload = make_type_doc(0, NEW_TYPE_NAME, SpecialType.SUBNET)
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'already exists' in message
        assert types.find_one({'name': NEW_TYPE_NAME}) is None

    def test_duplicate_special_type_within_one_upload_is_rejected_once(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Two entries claiming the same marker: the first is imported, the second reported."""
        first = make_type_doc(0, NEW_TYPE_NAME, SpecialType.VLAN)
        first.pop('public_id')
        second = make_type_doc(0, SECOND_TYPE_NAME, SpecialType.VLAN)
        second.pop('public_id')

        response = rest_api.post(
            CREATE_URL, data=_upload_form([first, second]), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        assert types.find_one({'name': NEW_TYPE_NAME}) is not None
        assert types.find_one({'name': SECOND_TYPE_NAME}) is None

    def test_update_declaring_another_special_type_is_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The marker is immutable, so a different one is reported instead of silently ignored."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET))

        updated = make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.VLAN)
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'can not be changed by an import' in message

        stored = types.find_one({'public_id': SPECIAL_TYPE_ID})

        assert stored['special_type'] == SpecialType.SUBNET.value  # unchanged
        assert stored['label'] != UPDATED_LABEL  # the entry was refused as a whole

    def test_update_clearing_the_stored_special_type_is_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload omitting special_type would strip the marker, so it is refused too."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET))

        updated = make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet')
        updated.pop('special_type')

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'can not be changed by an import' in message
        assert types.find_one({'public_id': SPECIAL_TYPE_ID})['special_type'] == SpecialType.SUBNET.value

    def test_re_importing_the_same_special_type_is_applied(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The normal round trip: an exported special type carries its own marker and updates fine."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET))

        updated = make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET)
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = types.find_one({'public_id': SPECIAL_TYPE_ID})

        assert stored['special_type'] == SpecialType.SUBNET.value
        assert stored['label'] == UPDATED_LABEL


class TestFieldAndSectionRules:
    """Field-name uniqueness, section-name uniqueness and one-section-per-field over HTTP."""

    def test_duplicate_field_name_is_rejected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A type whose fields repeat a name is not imported."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'text', 'name': 'dg-name', 'label': 'Name again'},
            ],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['dg-name']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'Duplicate field name(s)' in message
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME}) is None

    def test_duplicate_section_name_is_rejected(self, rest_api) -> None:
        """Two sections may not share a name."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}, {'type': 'text', 'name': 'b', 'label': 'B'}],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']},
                {'type': 'section', 'name': 'main', 'label': 'Main 2', 'fields': ['b']},
            ],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert 'Duplicate section name(s)' in message

    def test_field_without_a_section_is_rejected(self, rest_api) -> None:
        """Every field must be assigned to a section."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}, {'type': 'text', 'name': 'orphan', 'label': 'O'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "not assigned to any section: ['orphan']" in message

    def test_field_in_two_sections_is_rejected(self, rest_api) -> None:
        """A field may not be claimed by two sections."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}],
            sections=[
                {'type': 'section', 'name': 'one', 'label': 'One', 'fields': ['a']},
                {'type': 'section', 'name': 'two', 'label': 'Two', 'fields': ['a']},
            ],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert 'more than one section' in message

    def test_ref_section_type_is_accepted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A ref-section type imports fine - its implicit '<section>-field' is not an orphan."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'a', 'label': 'A'},
                {'type': 'ref-section-field', 'name': 'refsec-field', 'label': 'Ref'},
            ],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']},
                {'type': 'ref-section', 'name': 'refsec', 'label': 'Ref Section',
                 'reference': {'type_id': 1, 'section_name': 'main', 'selected_fields': []},
                 'fields': []},
            ],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME}) is not None

    def test_update_enforces_the_structure_too(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update replaces fields and sections, so it is structurally validated as well."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        broken = make_type_doc(
            UPDATE_TYPE_ID, 'imported-type-update',
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}],
            sections=[],
        )

        response = rest_api.post(UPDATE_URL, data=_upload_form([broken]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'not assigned to any section' in message


class TestNameAndFieldTypeRules:
    """The type name must be unique, and every field must declare a known type."""

    def test_duplicate_type_name_is_rejected_on_create(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A name a stored type already holds blocks the create."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME))

        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'already exists' in message
        assert types.count_documents({'name': NEW_TYPE_NAME}) == 1  # nothing added

    def test_a_type_may_keep_its_own_name_on_update(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Re-importing a type under its own name is not a name conflict."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME))

        updated = make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME)
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['label'] == UPDATED_LABEL

    def test_update_onto_another_types_name_is_rejected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Renaming a type onto a name another type already holds is refused."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_many([
            make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME),
            make_type_doc(MISSING_TYPE_ID, SECOND_TYPE_NAME),
        ])

        renamed = make_type_doc(UPDATE_TYPE_ID, SECOND_TYPE_NAME)

        response = rest_api.post(UPDATE_URL, data=_upload_form([renamed]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'already exists' in message
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['name'] == NEW_TYPE_NAME

    def test_unknown_field_type_is_rejected(self, rest_api) -> None:
        """A field declaring a type outside FieldType is refused."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'not-a-type', 'name': 'a', 'label': 'A'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert 'a (not-a-type)' in message

    def test_section_referencing_an_undefined_field_is_rejected(self, rest_api) -> None:
        """A section may only name fields the type defines."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a', 'ghost']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "does not define: ['ghost']" in message or "not define: ['ghost']" in message


class TestUploadAndNameCompletenessRules:
    """An unusable upload is a 400; a type without a name is a per-entry error."""

    @pytest.mark.parametrize('url', [CREATE_URL, UPDATE_URL], ids=['create', 'update'])
    def test_malformed_json_returns_400(self, rest_api, url: str) -> None:
        """An upload that is not valid JSON is a bad request, not an internal error."""
        response = rest_api.post(
            url, data={'uploadFile': '[{"name": '}, content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('name', ['', '   '], ids=['empty', 'blank'])
    def test_type_without_a_name_is_rejected(self, rest_api, name: str) -> None:
        """A blank type name is reported as such instead of as a model failure."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['name'] = name

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert message == 'The Type data does not contain a name!'

    def test_nameless_field_is_rejected(self, rest_api) -> None:
        """A field without a name has no identifier, so the type is refused."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}, {'type': 'text', 'name': '', 'label': 'B'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert 'without a name at position(s): [1]' in message


class TestSectionContentRules:
    """A section must declare a known type and hold at least one field."""

    def test_unknown_section_type_is_rejected(self, rest_api) -> None:
        """A mistyped section marker would silently be imported as a plain section."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}],
            sections=[{'type': 'mutli-data-section', 'name': 'main', 'label': 'Main', 'fields': ['a']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert 'main (mutli-data-section)' in message

    def test_empty_section_is_rejected(self, rest_api) -> None:
        """A section holding no field at all is refused."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'a', 'label': 'A'}],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']},
                {'type': 'section', 'name': 'empty', 'label': 'Empty', 'fields': []},
            ],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "without any field: ['empty']" in message

    def test_undefined_summary_field_is_rejected(self, rest_api) -> None:
        """The summary line may only name fields the type defines."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['render_meta']['summary'] = {'fields': ['ghost']}

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "summary references field(s) the Type does not define: ['ghost']" in message

    def test_undefined_external_link_field_is_rejected(self, rest_api) -> None:
        """An external link may only interpolate fields the type defines."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['render_meta']['externals'] = [
            {'name': 'wiki', 'href': 'http://example.org/{}', 'label': 'Wiki', 'fields': ['ghost']},
        ]

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "External link(s) reference field(s) the Type does not define: ['ghost']" in message


class TestImportRepairs:
    """Parts of an upload that say nothing about its quality are repaired instead of reported."""

    @staticmethod
    def _ref_section_payload(public_id: int, referenced_type_id: int) -> dict[str, Any]:
        """A type whose second section references a section of another type."""
        payload = make_type_doc(
            public_id, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'a', 'label': 'A'},
                {'type': 'ref-section-field', 'name': 'ref-1-field', 'label': 'Reference'},
            ],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a']},
                {
                    'type': 'ref-section', 'name': 'ref-1', 'label': 'Reference', 'fields': [],
                    'reference': {
                        'type_id': referenced_type_id, 'section_name': 'main', 'selected_fields': ['a'],
                    },
                },
            ],
        )

        return payload

    def test_missing_icon_is_defaulted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A type imported without an icon is stored with the placeholder icon."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['render_meta'].pop('icon')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored['render_meta']['icon'] == 'fas fa-cube'

    def test_uploaded_icon_is_kept(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An icon the upload brings survives the import unchanged."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['render_meta']['icon'] = 'fas fa-server'

        rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored['render_meta']['icon'] == 'fas fa-server'

    def test_dangling_reference_is_cleared_instead_of_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A ref-section pointing at a type of the source system is reset, and the type is imported."""
        payload = self._ref_section_payload(0, MISSING_TYPE_ID)
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored['render_meta']['sections'][1]['reference'] == {
            'type_id': None, 'section_name': None, 'selected_fields': [],
        }

    def test_resolvable_reference_survives(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A reference to a type that exists here is left alone."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, SECOND_TYPE_NAME))

        payload = self._ref_section_payload(0, UPDATE_TYPE_ID)
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}
        stored = types.find_one({'name': NEW_TYPE_NAME})
        assert stored['render_meta']['sections'][1]['reference']['type_id'] == UPDATE_TYPE_ID

    def test_dangling_ref_types_are_pruned_on_update(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update prunes the reference-field targets that do not exist on this system."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_many([
            make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME),
            make_type_doc(SPECIAL_TYPE_ID, SECOND_TYPE_NAME),
        ])

        updated = make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=[{'type': 'ref', 'name': 'owner', 'label': 'Owner',
                     'ref_types': [SPECIAL_TYPE_ID, MISSING_TYPE_ID]}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['owner']}],
        )

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['fields'][0]['ref_types'] == [SPECIAL_TYPE_ID]


class TestOptionalTypeFields:
    """public_id / active / selectable_as_parent / version / label / CI-Explorer / acl are optional."""

    OPTIONAL_KEYS: tuple[str, ...] = (
        'active', 'selectable_as_parent', 'version', 'label',
        'ci_explorer_label', 'ci_explorer_color', 'acl',
    )

    @staticmethod
    def _stored(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
        """Reads back the type the test imported."""
        return database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

    def test_a_bare_type_imports_with_every_default(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload bringing none of the optional fields is imported, not refused."""
        payload = make_type_doc(0, NEW_TYPE_NAME)

        for key in (*self.OPTIONAL_KEYS, 'public_id'):
            payload.pop(key, None)

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}

        stored = self._stored(database_manager, database_name)

        assert stored['active'] is True
        assert stored['selectable_as_parent'] is True
        assert stored['version'] == CmdbType.DEFAULT_VERSION
        assert stored['label'] == NEW_TYPE_NAME.title()
        assert stored['ci_explorer_label'] is None
        assert re.fullmatch(r'#[0-9A-F]{6}', stored['ci_explorer_color'])
        assert stored['acl'] == {'activated': False, 'groups': {'includes': {}}}

    def test_uploaded_public_id_is_replaced_by_a_fresh_one(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The exporting system's id is dropped; this system assigns the id."""
        payload = make_type_doc(MISSING_TYPE_ID, NEW_TYPE_NAME)

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}
        assert self._stored(database_manager, database_name)['public_id'] != MISSING_TYPE_ID

    def test_provided_optional_values_survive(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Whatever the upload does bring is kept, except the server-owned version."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload.update({
            'active': False,
            'selectable_as_parent': False,
            'label': 'Imported Label',
            'ci_explorer_label': 'IMP',
            'ci_explorer_color': '#123ABC',
            # group 2 is the predefined 'user' group, so the grant resolves and the ACL stays on
            'acl': {'activated': True, 'groups': {'includes': {'2': ['READ']}}},
        })

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = self._stored(database_manager, database_name)

        assert stored['active'] is False
        assert stored['selectable_as_parent'] is False
        assert stored['label'] == 'Imported Label'
        assert stored['ci_explorer_label'] == 'IMP'
        assert stored['ci_explorer_color'] == '#123ABC'
        assert stored['acl']['activated'] is True

    def test_string_flags_are_parsed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The lenient import spellings are accepted for both flags."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['active'] = 'false'
        payload['selectable_as_parent'] = 'yes'

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = self._stored(database_manager, database_name)

        assert stored['active'] is False
        assert stored['selectable_as_parent'] is True

    def test_unusable_flag_is_reported(self, rest_api) -> None:
        """A flag that is not a boolean at all fails the entry."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['active'] = 'maybe'

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert message == "Invalid value for 'active': 'maybe'"

    def test_uploaded_version_is_overwritten_on_create(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The version is server-owned on create, exactly as in the object import."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['version'] = '9.9.9'

        rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert self._stored(database_manager, database_name)['version'] == CmdbType.DEFAULT_VERSION

    def test_stored_version_survives_an_update(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update leaves the stored version alone, like the stored author and creation time."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        stored_type = make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME)
        stored_type['version'] = STORED_VERSION
        types.insert_one(stored_type)

        updated = make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME)
        updated['version'] = '9.9.9'
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = types.find_one({'public_id': UPDATE_TYPE_ID})

        assert stored['version'] == STORED_VERSION  # neither the uploaded nor the default version
        assert stored['label'] == UPDATED_LABEL  # the rest of the type was still replaced

    def test_update_defaults_the_optional_fields_too(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update replaces the type wholesale, so it gets the same defaults as a create."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME))

        updated = make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME)

        for key in self.OPTIONAL_KEYS:
            updated.pop(key, None)

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = types.find_one({'public_id': UPDATE_TYPE_ID})

        assert stored['active'] is True
        assert stored['selectable_as_parent'] is True
        assert stored['label'] == NEW_TYPE_NAME.title()
        assert stored['ci_explorer_label'] is None
        assert re.fullmatch(r'#[0-9A-F]{6}', stored['ci_explorer_color'])
        assert stored['acl'] == {'activated': False, 'groups': {'includes': {}}}


class TestImportUpdateReconcilesStoredData:
    """An import update replaces the Type wholesale, so it owes its Objects the same follow-up work
    the normal update route performs."""

    @staticmethod
    def _seed_type_with_object(
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Seeds a two-field type plus one object of it, both fields filled."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'text', 'name': 'city', 'label': 'City'},
            ],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': ['dg-name', 'city']}],
        ))
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            make_object_doc(RECONCILED_OBJECT_ID, UPDATE_TYPE_ID, [
                make_field('dg-name', 'host-1'), make_field('city', 'Berlin'),
            ])
        )

    @staticmethod
    def _updated_type(fields: list[dict[str, Any]]) -> dict[str, Any]:
        """The upload replacing the seeded type with the given field set."""
        return make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=fields,
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': [field['name'] for field in fields]}],
        )

    def test_a_removed_field_is_dropped_from_the_types_objects(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Without the realign step the object would keep a field its type no longer defines."""
        self._seed_type_with_object(database_manager, database_name)

        updated = self._updated_type([{'type': 'text', 'name': 'dg-name', 'label': 'Name'}])

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})
        stored_names = {field['name'] for field in stored['fields']}

        assert stored_names == {'dg-name'}

    def test_an_added_field_is_seeded_on_the_types_objects(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A newly declared field reaches every existing object, seeded with its default value."""
        self._seed_type_with_object(database_manager, database_name)

        updated = self._updated_type([
            {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
            {'type': 'text', 'name': 'city', 'label': 'City'},
            {'type': 'text', 'name': 'room', 'label': 'Room', 'value': 'unknown'},
        ])

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})
        stored_fields = {field['name']: field['value'] for field in stored['fields']}

        assert stored_fields['room'] == 'unknown'
        assert stored_fields['dg-name'] == 'host-1'  # untouched

    def test_a_metadata_only_update_leaves_the_objects_alone(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The realign is gated on the field-name set, so a pure label edit sweeps nothing."""
        self._seed_type_with_object(database_manager, database_name)

        updated = self._updated_type([
            {'type': 'text', 'name': 'dg-name', 'label': 'Renamed label'},
            {'type': 'text', 'name': 'city', 'label': 'City'},
        ])

        rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})
        stored_fields = {field['name']: field['value'] for field in stored['fields']}

        assert stored_fields == {'dg-name': 'host-1', 'city': 'Berlin'}

    def test_the_types_locations_follow_a_label_change(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """label / icon / selectable changes are propagated to the type's CmdbLocations."""
        self._seed_type_with_object(database_manager, database_name)
        database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one({
            'public_id': RECONCILED_LOCATION_ID,
            'name': 'loc-1',
            'parent': 1,
            'object_id': RECONCILED_OBJECT_ID,
            'type_id': UPDATE_TYPE_ID,
            'type_label': 'Old label',
            'type_icon': 'fa-cube',
            'type_selectable': True,
        })

        updated = self._updated_type([
            {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
            {'type': 'text', 'name': 'city', 'label': 'City'},
        ])
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_LOCATION_ID})

        assert stored['type_label'] == UPDATED_LABEL


class TestImportCreateWiresSpecialTypes:
    """A SpecialType imported as a new Type is cross-wired like a hand-created one."""

    @pytest.fixture(autouse=True)
    def _licensed(self, monkeypatch) -> None:
        """Unlocks IPAM so a special type may be imported at all."""
        monkeypatch.setattr(
            LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM
        )

    def test_importing_a_supernet_registers_it_on_the_stored_subnet(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The stored SUBNET's supernet reference field gains the imported type's public_id."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(
            SPECIAL_TYPE_ID, SECOND_TYPE_NAME, SpecialType.SUBNET,
            fields=[{'type': 'ref', 'name': SubnetField.PARENT_SUPERNET.value,
                     'label': 'Supernet', 'ref_types': []}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': [SubnetField.PARENT_SUPERNET.value]}],
        ))

        payload = make_type_doc(0, NEW_TYPE_NAME, SpecialType.SUPERNET)
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        imported_id = types.find_one({'name': NEW_TYPE_NAME})['public_id']
        subnet = types.find_one({'public_id': SPECIAL_TYPE_ID})
        supernet_field = next(
            field for field in subnet['fields'] if field['name'] == SubnetField.PARENT_SUPERNET.value
        )

        assert supernet_field['ref_types'] == [imported_id]


class TestImportUpdateGuards:
    """An import update refuses the same edits the normal update route refuses."""

    LOCATION_FIELD: dict[str, Any] = {'type': 'location', 'name': 'dg_location', 'label': 'Location'}
    NAME_FIELD: dict[str, Any] = {'type': 'text', 'name': 'dg-name', 'label': 'Name'}

    @classmethod
    def _type_doc(cls, fields: list[dict[str, Any]], selectable: bool = True) -> dict[str, Any]:
        """A type document carrying the given fields, all in one section."""
        doc = make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=fields,
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': [field['name'] for field in fields]}],
        )
        doc['selectable_as_parent'] = selectable

        return doc

    @staticmethod
    def _seed_placed_object(
        database_manager: MongoDatabaseManager, database_name: str, location_value: Any,
    ) -> None:
        """Seeds one object of the type that holds a location value."""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            make_object_doc(RECONCILED_OBJECT_ID, UPDATE_TYPE_ID, [
                make_field('dg-name', 'host-1'), make_field('dg_location', location_value),
            ])
        )

    def test_removing_the_location_field_is_refused_while_objects_use_it(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The stored location values would be orphaned, so the entry is reported."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD]))
        self._seed_placed_object(database_manager, database_name, 1)

        response = rest_api.post(
            UPDATE_URL, data=_upload_form([self._type_doc([self.NAME_FIELD])]),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'Cannot remove the location field' in message
        # nothing was written: the type still declares the location field
        stored_fields = {field['name'] for field in types.find_one({'public_id': UPDATE_TYPE_ID})['fields']}
        assert 'dg_location' in stored_fields

    def test_removing_the_location_field_is_allowed_when_unused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """With no object holding a location value the field may go."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD]))
        self._seed_placed_object(database_manager, database_name, None)

        response = rest_api.post(
            UPDATE_URL, data=_upload_form([self._type_doc([self.NAME_FIELD])]),
            content_type='multipart/form-data',
        )

        assert response.get_json() == {}
        stored_fields = {field['name'] for field in types.find_one({'public_id': UPDATE_TYPE_ID})['fields']}
        assert stored_fields == {'dg-name'}

    def test_disabling_selectable_as_parent_is_refused_while_objects_are_placed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A placed object of the type blocks the true -> false transition."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD]))
        self._seed_placed_object(database_manager, database_name, 1)

        updated = self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD], selectable=False)

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert "Cannot disable 'selectable as parent'" in message
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['selectable_as_parent'] is True

    def test_disabling_selectable_as_parent_is_allowed_when_nothing_is_placed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Without a placed object the flag may be turned off."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD]))

        updated = self._type_doc([self.NAME_FIELD, self.LOCATION_FIELD], selectable=False)

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['selectable_as_parent'] is False

    def test_a_non_dict_entry_is_reported_not_a_500(self, rest_api) -> None:
        """An entry that is not a Type object at all stays inside the partial report."""
        response = rest_api.post(
            UPDATE_URL, data=_upload_form(['not-a-type']), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert message == 'This entry is not a Type object!'


class TestImportUpdateLicenceGate:
    """Touching a Type that IS an IPAM special type here requires the licence, whatever the upload says."""

    @pytest.fixture(autouse=True)
    def _unlicensed(self, monkeypatch) -> None:
        """Locks every feature, IPAM included."""
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

    def test_a_stored_special_type_cannot_be_updated_unlicensed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload omitting the marker used to slip past the gate - the stored type decides now."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet', SpecialType.SUBNET))

        updated = make_type_doc(SPECIAL_TYPE_ID, 'stored-subnet')
        updated.pop('special_type')
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (message,) = response.get_json().values()
        assert 'IPAM feature is not licensed' in message
        assert types.find_one({'public_id': SPECIAL_TYPE_ID})['label'] != UPDATED_LABEL

    def test_an_ordinary_type_is_unaffected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The gate only applies to special types - ordinary ones import on any licence."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME))

        updated = make_type_doc(UPDATE_TYPE_ID, NEW_TYPE_NAME)
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}
        assert types.find_one({'public_id': UPDATE_TYPE_ID})['label'] == UPDATED_LABEL


class TestFieldContentRules:
    """Labels, choice options and the location field are checked on every uploaded Type."""

    @staticmethod
    def _payload(fields: list[dict[str, Any]]) -> dict[str, Any]:
        """A create upload whose single section holds the given fields."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=fields,
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': [field['name'] for field in fields]}],
        )
        payload.pop('public_id')

        return payload

    def _post(self, rest_api, fields: list[dict[str, Any]]):
        """Uploads a create with the given fields."""
        return rest_api.post(
            CREATE_URL, data=_upload_form([self._payload(fields)]), content_type='multipart/form-data',
        )

    def test_unlabelled_field_is_rejected(self, rest_api) -> None:
        """Every field needs a label."""
        response = self._post(rest_api, [{'type': 'text', 'name': 'host'}])

        (message,) = response.get_json().values()
        assert "without a label: ['host']" in message

    def test_unlabelled_section_is_rejected(self, rest_api) -> None:
        """Every section needs a label."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'host', 'label': 'Host'}],
            sections=[{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )
        payload.pop('public_id')

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert "Section(s) without a label: ['main']" in message

    def test_choice_field_without_options_is_rejected(self, rest_api) -> None:
        """A select with nothing to pick from can never hold a value."""
        response = self._post(rest_api, [{'type': 'select', 'name': 'choice', 'label': 'Choice'}])

        (message,) = response.get_json().values()
        assert "select/radio without usable options: ['choice']" in message

    def test_choice_field_with_options_is_accepted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """One well-formed option is enough."""
        response = self._post(rest_api, [
            {'type': 'radio', 'name': 'choice', 'label': 'Choice',
             'options': [{'name': 'a', 'label': 'A'}]},
        ])

        assert response.get_json() == {}
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME}) is not None

    def test_two_location_fields_are_rejected(self, rest_api) -> None:
        """A Type may declare at most one location field."""
        response = self._post(rest_api, [
            {'type': 'location', 'name': 'dg_location', 'label': 'Location'},
            {'type': 'location', 'name': 'where', 'label': 'Where'},
        ])

        (message,) = response.get_json().values()
        assert 'at most one location field' in message

    def test_a_differently_named_location_field_is_rejected(self, rest_api) -> None:
        """The location value is resolved by the reserved name, so another name is never read."""
        response = self._post(rest_api, [{'type': 'location', 'name': 'where', 'label': 'Where'}])

        (message,) = response.get_json().values()
        assert "is reserved for the location field" in message

    def test_the_reserved_name_on_a_text_field_is_rejected(self, rest_api) -> None:
        """A text field called dg_location would be mistaken for the location field."""
        response = self._post(rest_api, [{'type': 'text', 'name': 'dg_location', 'label': 'Not a location'}])

        (message,) = response.get_json().values()
        assert "is reserved for the location field" in message


class TestCrossSystemReferencesAreCleaned:
    """ACL groups and global section templates name things of the exporting system."""

    def test_an_unknown_acl_group_grant_is_dropped(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A grant to a group that does not exist here is silently removed."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['acl'] = {'activated': True, 'groups': {'includes': {'2': ['READ'], '4711': ['UPDATE']}}}

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        # group 2 is the predefined 'user' group and survives; 4711 exists on no system here
        assert stored['acl']['groups']['includes'] == {'2': ['READ']}

    def test_an_unknown_global_template_claim_is_dropped(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The inlined section stays, the claim to a template nobody has does not."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['global_template_ids'] = ['dg-template-that-does-not-exist']

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        assert stored['global_template_ids'] == []
        assert len(stored['render_meta']['sections']) == 1  # the inlined section is untouched

    def test_a_known_template_tops_the_type_up_with_its_missing_fields(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The template gained a field since the export, so the imported Type gets it too."""
        templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
        templates.insert_one({
            'public_id': TEMPLATE_ID,
            'name': TEMPLATE_NAME,
            'label': 'Contact',
            'type': 'section',
            'is_global': True,
            'predefined': False,
            'fields': [
                {'type': 'text', 'name': 'dg-contact-mail', 'label': 'Mail'},
                {'type': 'text', 'name': 'dg-contact-phone', 'label': 'Phone'},
            ],
        })

        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'dg-contact-mail', 'label': 'Mail'}],
            sections=[{'type': 'section', 'name': TEMPLATE_NAME, 'label': 'Contact',
                       'fields': ['dg-contact-mail']}],
        )
        payload.pop('public_id')
        payload['global_template_ids'] = [TEMPLATE_NAME]

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        assert [field['name'] for field in stored['fields']] == ['dg-contact-mail', 'dg-contact-phone']
        assert stored['render_meta']['sections'][0]['fields'] == ['dg-contact-mail', 'dg-contact-phone']
        assert stored['global_template_ids'] == [TEMPLATE_NAME]


class TestUnknownTemplateClaimDoesNotDestroyData:
    """A claim the repair drops must not be mistaken for a section the user removed."""

    TEMPLATE_SECTION: str = 'dg-import-orphaned'

    @classmethod
    def _stored_doc(cls) -> dict[str, Any]:
        """A Type carrying an inlined template section and claiming that template."""
        return make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'text', 'name': 'dg-contact-mail', 'label': 'Mail'},
            ],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['dg-name']},
                {'type': 'section', 'name': cls.TEMPLATE_SECTION, 'label': 'Contact',
                 'fields': ['dg-contact-mail']},
            ],
            global_template_ids=[cls.TEMPLATE_SECTION],
        )

    def _seed(self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Stores that Type plus one object holding both field values."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(self._stored_doc())
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            make_object_doc(RECONCILED_OBJECT_ID, UPDATE_TYPE_ID, [
                make_field('dg-name', 'host-1'), make_field('dg-contact-mail', 'a@b.c'),
            ])
        )

    def test_re_importing_it_keeps_the_section_the_fields_and_the_values(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The template is gone from the catalogue, so nothing about the Type changed - keep it all."""
        self._seed(database_manager, database_name)

        response = rest_api.post(
            UPDATE_URL, data=_upload_form([self._stored_doc()]), content_type='multipart/form-data',
        )

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        stored_object = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})

        assert stored['global_template_ids'] == []  # the claim is dropped, the template is unknown
        assert [section['name'] for section in stored['render_meta']['sections']] \
            == ['main', self.TEMPLATE_SECTION]
        assert [field['name'] for field in stored['fields']] == ['dg-name', 'dg-contact-mail']
        assert {field['name'] for field in stored_object['fields']} == {'dg-name', 'dg-contact-mail'}

    def test_a_template_the_user_really_removed_is_still_cleaned_up(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A claim dropped by the upload while the template DOES exist is a real removal."""
        templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
        templates.insert_one({
            'public_id': TEMPLATE_ID,
            'name': self.TEMPLATE_SECTION,
            'label': 'Contact',
            'type': 'section',
            'is_global': True,
            'predefined': False,
            'fields': [{'type': 'text', 'name': 'dg-contact-mail', 'label': 'Mail'}],
        })
        self._seed(database_manager, database_name)

        updated = make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['dg-name']}],
        )

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        stored_object = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})

        assert [section['name'] for section in stored['render_meta']['sections']] == ['main']
        assert [field['name'] for field in stored['fields']] == ['dg-name']
        assert {field['name'] for field in stored_object['fields']} == {'dg-name'}


class TestEmptyAclIsSwitchedOff:
    """An ACL granting nothing would hide the Type from everyone."""

    def test_an_acl_left_without_a_grant_is_deactivated(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Every grant named a group of the exporting system, so the list is switched off."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['acl'] = {'activated': True, 'groups': {'includes': {'4711': ['READ']}}}

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        assert stored['acl'] == {'activated': False, 'groups': {'includes': {}}}

    def test_an_upload_carrying_an_empty_active_acl_is_deactivated_too(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The same state, reached without the repair - equally unusable, equally switched off."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['acl'] = {'activated': True, 'groups': {'includes': {}}}

        rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        assert stored['acl']['activated'] is False


class TestRepairedTypesAreRevalidated:
    """What a global template adds is checked too, not only what the upload carried."""

    @staticmethod
    def _seed_template(
        database_manager: MongoDatabaseManager, database_name: str, field: dict[str, Any],
    ) -> None:
        """Seeds a global section template contributing one (deliberately flawed) field."""
        database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name).insert_one({
            'public_id': TEMPLATE_ID,
            'name': TEMPLATE_NAME,
            'label': 'Contact',
            'type': 'section',
            'is_global': True,
            'predefined': False,
            'fields': [field],
        })

    @staticmethod
    def _payload() -> dict[str, Any]:
        """A create upload claiming that template but carrying none of its fields."""
        payload = make_type_doc(
            0, NEW_TYPE_NAME,
            fields=[{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['dg-name']}],
        )
        payload.pop('public_id')
        payload['global_template_ids'] = [TEMPLATE_NAME]

        return payload

    def test_a_template_field_without_a_label_is_reported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A legacy template would otherwise smuggle a field past the label rule."""
        self._seed_template(database_manager, database_name, {'type': 'text', 'name': 'dg-mail'})

        response = rest_api.post(
            CREATE_URL, data=_upload_form([self._payload()]), content_type='multipart/form-data',
        )

        (message,) = response.get_json().values()

        assert message.startswith('Completing this Type from its global section template(s) made it invalid:')
        assert "without a label: ['dg-mail']" in message
        assert database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME}) is None

    def test_a_template_field_with_an_unknown_type_is_reported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Same for a field type no longer known."""
        self._seed_template(
            database_manager, database_name, {'type': 'not-a-type', 'name': 'dg-mail', 'label': 'Mail'},
        )

        response = rest_api.post(
            CREATE_URL, data=_upload_form([self._payload()]), content_type='multipart/form-data',
        )

        (message,) = response.get_json().values()

        assert 'dg-mail (not-a-type)' in message

    def test_a_sound_template_still_imports(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The re-check only refuses what a rule would have refused in the upload itself."""
        self._seed_template(
            database_manager, database_name, {'type': 'text', 'name': 'dg-mail', 'label': 'Mail'},
        )

        response = rest_api.post(
            CREATE_URL, data=_upload_form([self._payload()]), content_type='multipart/form-data',
        )

        assert response.get_json() == {}

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})

        assert [field['name'] for field in stored['fields']] == ['dg-name', 'dg-mail']


class TestExportImportRoundTrip:
    """The headline workflow: a file the export route produced is what the import route consumes."""

    @staticmethod
    def _rich_type() -> dict[str, Any]:
        """A Type exercising the import surface: MDS, choice field, location, summary, external, ACL."""
        doc = make_type_doc(
            UPDATE_TYPE_ID, NEW_TYPE_NAME,
            fields=[
                {'type': 'text', 'name': 'dg-name', 'label': 'Name'},
                {'type': 'select', 'name': 'tier', 'label': 'Tier',
                 'options': [{'name': 'a', 'label': 'A'}, {'name': 'b', 'label': 'B'}]},
                {'type': 'location', 'name': 'dg_location', 'label': 'Location'},
                {'type': 'text', 'name': 'mds-note', 'label': 'Note'},
            ],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main',
                 'fields': ['dg-name', 'tier', 'dg_location']},
                {'type': 'multi-data-section', 'name': 'notes', 'label': 'Notes', 'fields': ['mds-note']},
            ],
        )
        doc['render_meta']['summary'] = {'fields': ['dg-name']}
        doc['render_meta']['externals'] = [
            {'name': 'wiki', 'href': 'http://example.org/{}', 'label': 'Wiki', 'icon': 'fa',
             'fields': ['dg-name']},
        ]
        # group 2 is the predefined 'user' group, so the grant resolves and the ACL stays on
        doc['acl'] = {'activated': True, 'groups': {'includes': {'2': ['READ']}}}

        return doc

    @staticmethod
    def _exported(rest_api, public_id: int) -> list[dict[str, Any]]:
        """Runs the real export route and returns the decoded file."""
        response = rest_api.post(f'/export/type/{public_id}')

        assert response.status_code == HTTPStatus.OK

        return json.loads(response.data.decode('utf-8'))

    def test_an_exported_type_re_imports_as_an_update_unchanged(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Re-importing a Type over itself must be a no-op, not a slow way to lose parts of it."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._rich_type())

        exported = self._exported(rest_api, UPDATE_TYPE_ID)

        response = rest_api.post(
            UPDATE_URL, data=_upload_form(exported), content_type='multipart/form-data',
        )

        assert response.get_json() == {}

        stored = types.find_one({'public_id': UPDATE_TYPE_ID})

        assert [field['name'] for field in stored['fields']] \
            == ['dg-name', 'tier', 'dg_location', 'mds-note']
        assert [section['name'] for section in stored['render_meta']['sections']] == ['main', 'notes']
        assert stored['render_meta']['summary']['fields'] == ['dg-name']
        assert stored['render_meta']['externals'][0]['name'] == 'wiki'
        assert stored['acl'] == {'activated': True, 'groups': {'includes': {'2': ['READ']}}}

    def test_an_exported_type_re_imports_as_a_new_type(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The cross-system case: the same file, renamed, creates a second Type of its own."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._rich_type())

        exported = self._exported(rest_api, UPDATE_TYPE_ID)
        exported[0]['name'] = SECOND_TYPE_NAME

        response = rest_api.post(
            CREATE_URL, data=_upload_form(exported), content_type='multipart/form-data',
        )

        assert response.get_json() == {}

        created = types.find_one({'name': SECOND_TYPE_NAME})

        assert created['public_id'] != UPDATE_TYPE_ID  # a fresh id, not the exported one
        assert [field['name'] for field in created['fields']] \
            == ['dg-name', 'tier', 'dg_location', 'mds-note']
        assert created['author_id'] == ADMIN_PUBLIC_ID
        assert created['version'] == CmdbType.DEFAULT_VERSION
        # the export carries no colour for a Type that never had one, so the import fills one in
        assert re.fullmatch(r'#[0-9A-F]{6}', created['ci_explorer_color'])

    def test_the_objects_of_an_unchanged_type_are_left_alone(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The field set did not change, so the object sweep is skipped entirely."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(self._rich_type())
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            make_object_doc(RECONCILED_OBJECT_ID, UPDATE_TYPE_ID, [
                make_field('dg-name', 'host'), make_field('tier', 'a'),
            ])
        )

        rest_api.post(
            UPDATE_URL, data=_upload_form(self._exported(rest_api, UPDATE_TYPE_ID)),
            content_type='multipart/form-data',
        )

        stored_object = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': RECONCILED_OBJECT_ID})
        stored_values = {field['name']: field['value'] for field in stored_object['fields']}

        assert stored_values == {'dg-name': 'host', 'tier': 'a'}
