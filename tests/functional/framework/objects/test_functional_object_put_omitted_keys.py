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
Functional tests of what a PUT /objects/<id> does with the keys its body leaves out

The update schema has no defaults, so a key the body does not send keeps the stored value: the multi-data rows,
the active state, the type and the author. The version is the server's - bumped from the stored one, whatever the
body says. A key the body sends still replaces the stored value whole, and a bulk PUT that sends no rows leaves
every target its own. The body's comment - never a stored key - goes on every target's edit log
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    MDS_REF_TYPE_ID,
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROUTE_URL,
    TYPE_ID,
    UPDATED_VALUE,
    mds_ref_type_doc,
    mds_referencing_object_doc,
    object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

PLAIN_OBJECT_ID: int = 9435
MDS_OBJECT_ID: int = 9436
OTHER_MDS_OBJECT_ID: int = 9437
REF_TARGET_ID: int = 9438
SEEDED_IDS: list[int] = [PLAIN_OBJECT_ID, MDS_OBJECT_ID, OTHER_MDS_OBJECT_ID, REF_TARGET_ID]

# Stored values no default could produce: a version past 1.0.0, an inactive state, an author other than the caller
STORED_VERSION: str = '4.2.7'
BUMPED_VERSION: str = '4.2.8'
STORED_AUTHOR_ID: int = 5
SENT_VERSIONS: list[str] = ['99.0.0', 'abc']
PUT_COMMENT: str = 'Assigned 10.0.0.5 to 10.0.0.0/24'


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds an inactive plain object at STORED_VERSION by STORED_AUTHOR_ID, and two objects of the MDS type whose rows
    differ (each points at REF_TARGET_ID from a different row id); removes them and the MDS type afterwards
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(mds_ref_type_doc())
    objects.insert_one(object_doc(REF_TARGET_ID, ORIGINAL_VALUE))
    objects.insert_one({**object_doc(PLAIN_OBJECT_ID, ORIGINAL_VALUE),
                        'version': STORED_VERSION, 'active': False, 'author_id': STORED_AUTHOR_ID})
    # Each section with its row-id counter, as every write now stores it
    first = mds_referencing_object_doc(MDS_OBJECT_ID, REF_TARGET_ID)
    first['multi_data_sections'][0]['highest_id'] = 1
    objects.insert_one(first)
    other = mds_referencing_object_doc(OTHER_MDS_OBJECT_ID, REF_TARGET_ID)
    other['multi_data_sections'][0]['values'][0]['multi_data_id'] = 2
    other['multi_data_sections'][0]['highest_id'] = 2
    objects.insert_one(other)
    yield objects
    objects.delete_many({'public_id': {'$in': SEEDED_IDS}})
    types.delete_one({'public_id': MDS_REF_TYPE_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': SEEDED_IDS}},
    )


def _changed_fields() -> list[dict[str, Any]]:
    """The plain object's one field with a new value"""
    return [{'type': 'text', 'name': NAME_FIELD, 'value': UPDATED_VALUE}]


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """The stored document"""
    return objects.find_one({'public_id': public_id})


class TestOmittedKeysKeepTheStoredValue:
    """Absent from the body, present in the database afterwards"""

    def test_omitted_rows_are_kept(self, rest_api, objects: Any) -> None:
        """The single PUT no longer wipes the rows it does not send"""
        stored_rows = _stored(objects, MDS_OBJECT_ID)['multi_data_sections']

        response = rest_api.put(f'{ROUTE_URL}/{MDS_OBJECT_ID}', json={'fields': []})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, MDS_OBJECT_ID)['multi_data_sections'] == stored_rows

    def test_sent_rows_still_replace_the_stored_ones(self, rest_api, objects: Any) -> None:
        """A full replace stays one: an empty list deletes every row"""
        response = rest_api.put(f'{ROUTE_URL}/{MDS_OBJECT_ID}', json={'fields': [], 'multi_data_sections': []})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, MDS_OBJECT_ID)['multi_data_sections'] == []

    def test_an_omitted_active_keeps_the_object_inactive(self, rest_api, objects: Any,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """No silent re-activation, and no ACTIVE_CHANGE log"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields()})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['active'] is False
        logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
        assert logs.count_documents({'object_id': PLAIN_OBJECT_ID, 'action_name': LogAction.ACTIVE_CHANGE.name}) == 0

    def test_a_sent_active_still_changes_the_state(self, rest_api, objects: Any) -> None:
        """The caller (admin) holds the activation right"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields(), 'active': True})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['active'] is True

    def test_an_omitted_type_keeps_the_stored_type(self, rest_api, objects: Any) -> None:
        """No longer a 400 naming None"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields()})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['type_id'] == TYPE_ID

    def test_an_omitted_author_is_accepted_and_kept(self, rest_api, objects: Any) -> None:
        """author_id is the server's: not required, and the stored one stays"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields()})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['author_id'] == STORED_AUTHOR_ID

    def test_a_sent_author_is_ignored(self, rest_api, objects: Any) -> None:
        """Sent, it is purged like every server-owned key"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}',
                                json={'fields': _changed_fields(), 'author_id': STORED_AUTHOR_ID + 1})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['author_id'] == STORED_AUTHOR_ID


class TestTheVersionIsTheServers:
    """The bump starts from the stored version, never from the body's"""

    def test_an_omitted_version_bumps_the_stored_one(self, rest_api, objects: Any) -> None:
        """Not reset to 1.0.1"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields()})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['version'] == BUMPED_VERSION

    @pytest.mark.parametrize('sent', SENT_VERSIONS)
    def test_a_sent_version_is_ignored(self, rest_api, objects: Any, sent: str) -> None:
        """Neither a jump to 99.0.1 nor a 500 for a version that cannot be parsed"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields(), 'version': sent})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['version'] == BUMPED_VERSION

    def test_a_save_that_changes_nothing_keeps_the_stored_version(self, rest_api, objects: Any) -> None:
        """No change, no bump - and no reset either"""
        unchanged = [{'type': 'text', 'name': NAME_FIELD, 'value': ORIGINAL_VALUE}]

        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': unchanged, 'version': '1.0.0'})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(objects, PLAIN_OBJECT_ID)['version'] == STORED_VERSION


def test_a_bulk_put_without_rows_keeps_each_targets_own(rest_api, objects: Any) -> None:
    """Not sent, not judged: two objects with different rows both keep theirs"""
    rows = {public_id: _stored(objects, public_id)['multi_data_sections']
            for public_id in (MDS_OBJECT_ID, OTHER_MDS_OBJECT_ID)}
    assert rows[MDS_OBJECT_ID] != rows[OTHER_MDS_OBJECT_ID]

    response = rest_api.put(f'{ROUTE_URL}/{MDS_OBJECT_ID}', json={'fields': []},
                            query_string={'objectIDs': [MDS_OBJECT_ID, OTHER_MDS_OBJECT_ID]})

    assert response.status_code == HTTPStatus.ACCEPTED
    for public_id, stored_rows in rows.items():
        assert _stored(objects, public_id)['multi_data_sections'] == stored_rows


def _edit_log_comments(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[Any]:
    """The comments of the object's edit log entries"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    return [entry['comment'] for entry in logs.find({'object_id': public_id, 'action_name': LogAction.EDIT.name})]


class TestThePutComment:
    """The edit-log comment a PUT body carries"""

    def test_the_comment_reaches_the_edit_log(self, rest_api, objects: Any, database_manager: MongoDatabaseManager,
                                              database_name: str) -> None:
        """The IPAM assign-IP dialog's comment, for one"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}',
                                json={'fields': _changed_fields(), 'comment': PUT_COMMENT})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _edit_log_comments(database_manager, database_name, PLAIN_OBJECT_ID) == [PUT_COMMENT]

    def test_the_comment_is_never_stored_on_the_object(self, rest_api, objects: Any) -> None:
        """Taken off for the log"""
        rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields(), 'comment': PUT_COMMENT})

        assert 'comment' not in _stored(objects, PLAIN_OBJECT_ID)

    @pytest.mark.parametrize('body_extra', [{}, {'comment': None}], ids=['absent', 'null'])
    def test_without_a_comment_the_log_comment_is_empty(self, rest_api, objects: Any,
                                                         database_manager: MongoDatabaseManager, database_name: str,
                                                         body_extra: dict[str, Any]) -> None:
        """Absent or null, the edit log records ''"""
        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json={'fields': _changed_fields(), **body_extra})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _edit_log_comments(database_manager, database_name, PLAIN_OBJECT_ID) == ['']

    def test_a_bulk_put_puts_the_comment_on_every_target(self, rest_api, objects: Any,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """One comment, one edit log per target"""
        targets = [MDS_OBJECT_ID, OTHER_MDS_OBJECT_ID]

        response = rest_api.put(f'{ROUTE_URL}/{MDS_OBJECT_ID}', json={'fields': [], 'comment': PUT_COMMENT},
                                query_string={'objectIDs': targets})

        assert response.status_code == HTTPStatus.ACCEPTED
        for public_id in targets:
            assert _edit_log_comments(database_manager, database_name, public_id) == [PUT_COMMENT]

