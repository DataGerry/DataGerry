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
Functional smoke for patching multi-data-section rows through ``/objects``

An MDS row is not a field: the rows live under ``multi_data_sections`` keyed by the section's name,
and a PATCH can create, edit or delete them. They are covered apart from the ordinary field patch
because the failure they guard against is their own - a row set replaced wholesale, or a section id
that no longer resolves
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    MDS_REF_FIELD,
    MDS_REF_TYPE_ID,
    ORIGINAL_VALUE,
    ROUTE_URL,
    SEED_AUTHOR_ID,
    SEED_VERSION,
    mds_ref_type_doc,
    mds_referencing_object_doc,
    object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

MDS_ROWS_SOURCE_ID: int = 9466

MDS_ROWS_TARGET_ID: int = 9467

MDS_ROWS_TARGET_ID_2: int = 9468

MDS_EMPTY_SOURCE_ID: int = 9469

MDS_SECTION_ID: str = 'mds-section'


def _mds_object_two_rows(public_id: int, target_id: int) -> dict[str, Any]:
    """An MDS-ref object carrying two rows (multi_data_id 1 and 2), highest_id 2."""
    doc = mds_referencing_object_doc(public_id, target_id)
    doc['multi_data_sections'][0]['highest_id'] = 2
    doc['multi_data_sections'][0]['values'].append({
        'multi_data_id': 2,
        'data': [{'type': 'ref', 'name': MDS_REF_FIELD, 'value': target_id}],
    })
    return doc


def _mds_object_no_rows(public_id: int) -> dict[str, Any]:
    """An object of the MDS-ref type that has no multi_data_sections container yet."""
    return {
        'public_id': public_id,
        'type_id': MDS_REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [],
        'multi_data_sections': [],
        'creation_time': datetime.now(timezone.utc),
    }


class TestPatchMdsRows:
    """PATCH applies created/edited/deleted MDS rows in one call, with backend-assigned ids."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the MDS-ref type, two ref targets, a source with two rows and one with no rows."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(mds_ref_type_doc())
        objects.insert_one(object_doc(MDS_ROWS_TARGET_ID, ORIGINAL_VALUE))
        objects.insert_one(object_doc(MDS_ROWS_TARGET_ID_2, ORIGINAL_VALUE))
        objects.insert_one(_mds_object_two_rows(MDS_ROWS_SOURCE_ID, MDS_ROWS_TARGET_ID))
        objects.insert_one(_mds_object_no_rows(MDS_EMPTY_SOURCE_ID))
        yield
        objects.delete_many(
            {'public_id': {'$in': [
                MDS_ROWS_SOURCE_ID, MDS_ROWS_TARGET_ID, MDS_ROWS_TARGET_ID_2, MDS_EMPTY_SOURCE_ID,
            ]}}
        )
        types.delete_one({'public_id': MDS_REF_TYPE_ID})

    def test_patch_creates_edits_and_deletes_rows_in_one_call(self, rest_api) -> None:
        """Create appends a backend-numbered row (highest_id -> 3), edit updates row 1, delete drops row 2."""
        response = rest_api.patch(
            f'{ROUTE_URL}/{MDS_ROWS_SOURCE_ID}',
            json={
                'created_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID}]},
                ],
                'edited_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'multi_data_id': 1,
                     'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID_2}]},
                ],
                'deleted_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'multi_data_id': 2},
                ],
            },
        )

        assert response.status_code == HTTPStatus.ACCEPTED

        follow_up = rest_api.get(f'{ROUTE_URL}/native/{MDS_ROWS_SOURCE_ID}')
        stored = CmdbObject.from_data(follow_up.get_json())
        section = stored.multi_data_sections[0]

        # row 2 deleted, row 1 kept, a new row 3 created (highest_id was 2 -> assigned 3)
        assert {row['multi_data_id'] for row in section['values']} == {1, 3}
        assert section['highest_id'] == 3

        rows_by_id = {row['multi_data_id']: row for row in section['values']}
        edited_value = next(f['value'] for f in rows_by_id[1]['data'] if f['name'] == MDS_REF_FIELD)
        created_value = next(f['value'] for f in rows_by_id[3]['data'] if f['name'] == MDS_REF_FIELD)
        assert edited_value == MDS_ROWS_TARGET_ID_2
        assert created_value == MDS_ROWS_TARGET_ID

    def test_patch_first_row_add_seeds_section_container(self, rest_api) -> None:
        """Creating a row in a declared section the object lacks seeds the container with row 1."""
        response = rest_api.patch(
            f'{ROUTE_URL}/{MDS_EMPTY_SOURCE_ID}',
            json={'created_mds_rows': [
                {'section_id': MDS_SECTION_ID, 'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID}]},
            ]},
        )

        assert response.status_code == HTTPStatus.ACCEPTED

        follow_up = rest_api.get(f'{ROUTE_URL}/native/{MDS_EMPTY_SOURCE_ID}')
        stored = CmdbObject.from_data(follow_up.get_json())
        section = next(s for s in stored.multi_data_sections if s['section_id'] == MDS_SECTION_ID)
        assert section['highest_id'] == 1
        assert section['values'][0]['multi_data_id'] == 1
