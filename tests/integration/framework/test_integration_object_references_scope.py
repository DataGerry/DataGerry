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
Integration tests for the scoped reference listing against a real MongoDB

Seeds a referenced object, a field referrer, and MDS referrers of a Type only the admin group may read and of a
readable Type (one of them inactive), a decoy holding the id in a text field of a row, and an object of the
readable Type whose row holds another id. Asserts what `ObjectsManager.get_mds_references_for_object`, its
pipeline and `references()` answer: the denied Types leave at the Type stage, the join loads only the holders of
the id, the caller's stages judge the objects, and all three reads of `references()` are scoped alike
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.manager import ObjectsManager
from cmdb.manager.objects_reference_helper import build_mds_reference_pipeline
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

REFERENCED_TYPE_ID: int = 89801
HIDDEN_MDS_TYPE_ID: int = 89802
VISIBLE_MDS_TYPE_ID: int = 89803
FIELD_REF_TYPE_ID: int = 89804
TYPE_IDS: list[int] = [REFERENCED_TYPE_ID, HIDDEN_MDS_TYPE_ID, VISIBLE_MDS_TYPE_ID, FIELD_REF_TYPE_ID]

REFERENCED_ID: int = 89811
HIDDEN_MDS_ID: int = 89812
VISIBLE_MDS_ID: int = 89813
INACTIVE_MDS_ID: int = 89814
DECOY_MDS_ID: int = 89815
FIELD_REFERRER_ID: int = 89816
OTHER_ROW_ID: int = 89817
OBJECT_IDS: list[int] = [REFERENCED_ID, HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID, DECOY_MDS_ID,
                         FIELD_REFERRER_ID, OTHER_ROW_ID]

READER_GROUP_ID: int = 89841
REF_FIELD: str = 'row-ref'
NOTE_FIELD: str = 'row-note'
FIELD_REF: str = 'points-at'
MDS_SECTION: str = 'rows'
DENIED: list[int] = [HIDDEN_MDS_TYPE_ID]


def _type(public_id: int, fields: list[dict[str, Any]], sections: list[dict[str, Any]],
          admin_only: bool = False) -> dict[str, Any]:
    """A stored CmdbType; `admin_only` grants READ to the admin group alone."""
    acl: dict[str, Any] = {'activated': admin_only, 'groups': {'includes': (
        {str(ADMIN_GROUP_ID): ['READ']} if admin_only else {}
    )}}

    return {
        'public_id': public_id, 'name': f'refs-scope-{public_id}', 'label': f'Refs {public_id}', 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0', 'fields': fields,
        'render_meta': {'icon': '', 'sections': sections, 'summary': {'fields': []}, 'externals': []}, 'acl': acl,
    }


def _mds_type(public_id: int, admin_only: bool = False) -> dict[str, Any]:
    """A Type whose multi-data section holds a ref field to the referenced Type and a text field."""
    return _type(public_id, [
        {'type': FieldType.REFERENCE.value, 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [REFERENCED_TYPE_ID]},
        {'type': FieldType.TEXT.value, 'name': NOTE_FIELD, 'label': 'Note'},
    ], [{'type': SectionType.MDS_SECTION.value, 'name': MDS_SECTION, 'label': 'Rows',
         'fields': [REF_FIELD, NOTE_FIELD]}], admin_only)


def _object(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None,
            row: tuple[str, int] | None = None, active: bool = True) -> dict[str, Any]:
    """A stored CmdbObject, with one MDS row holding `row` (field name, value) when given."""
    sections: list[dict[str, Any]] = [] if row is None else [{'section_id': MDS_SECTION, 'values': [
        {'multi_data_id': 0, 'data': [{'name': row[0], 'value': row[1]}]},
    ]}]

    return {'public_id': public_id, 'type_id': type_id, 'active': active, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': fields or [], 'multi_data_sections': sections}


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded Types and objects - removed after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    purge()
    types.insert_many([
        _type(REFERENCED_TYPE_ID, [], []),
        _mds_type(HIDDEN_MDS_TYPE_ID, admin_only=True),
        _mds_type(VISIBLE_MDS_TYPE_ID),
        _type(FIELD_REF_TYPE_ID, [{'type': FieldType.REFERENCE.value, 'name': FIELD_REF, 'label': 'Ref',
                                   'ref_types': [REFERENCED_TYPE_ID]}],
              [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [FIELD_REF]}]),
    ])
    objects.insert_many([
        _object(REFERENCED_ID, REFERENCED_TYPE_ID),
        _object(HIDDEN_MDS_ID, HIDDEN_MDS_TYPE_ID, row=(REF_FIELD, REFERENCED_ID)),
        _object(VISIBLE_MDS_ID, VISIBLE_MDS_TYPE_ID, row=(REF_FIELD, REFERENCED_ID)),
        _object(INACTIVE_MDS_ID, VISIBLE_MDS_TYPE_ID, row=(REF_FIELD, REFERENCED_ID), active=False),
        _object(DECOY_MDS_ID, VISIBLE_MDS_TYPE_ID, row=(NOTE_FIELD, REFERENCED_ID)),
        _object(OTHER_ROW_ID, VISIBLE_MDS_TYPE_ID, row=(REF_FIELD, OTHER_ROW_ID)),
        _object(FIELD_REFERRER_ID, FIELD_REF_TYPE_ID, fields=[{'name': FIELD_REF, 'value': REFERENCED_ID}]),
    ])
    yield ObjectsManager(database_manager, database_name)
    purge()


def _referenced(objects_manager: ObjectsManager) -> CmdbObject:
    """The referenced object, as the route hands it in."""
    return CmdbObject.from_data(objects_manager.get_object(REFERENCED_ID))


def _ids(rows: list[Any]) -> set[int]:
    """The public_ids of documents or CmdbObjects"""
    return {row['public_id'] if isinstance(row, dict) else row.public_id for row in rows}


def test_the_mds_half_leaves_the_denied_types_out(objects_manager: ObjectsManager) -> None:
    """With the hidden Type denied its referrer is gone; the decoy and the other row never count"""
    referenced = _referenced(objects_manager)

    assert _ids(objects_manager.get_mds_references_for_object(referenced, None, QUERY_TIME_LIMIT_MS, DENIED)) == {
        VISIBLE_MDS_ID, INACTIVE_MDS_ID,
    }
    assert _ids(objects_manager.get_mds_references_for_object(referenced, None)) == {
        HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID,
    }


def test_the_join_loads_only_the_holders_of_the_id(objects_manager: ObjectsManager) -> None:
    """Before the row confirmation: the decoy holds the id and comes back, the other row's object does not"""
    rows = objects_manager.aggregate_within_time_limit(
        build_mds_reference_pipeline(_referenced(objects_manager), None, []), QUERY_TIME_LIMIT_MS,
        collection=CmdbType.COLLECTION,
    )

    assert _ids(rows) == {HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID, DECOY_MDS_ID}


@pytest.mark.parametrize('criteria, expected', [
    ([{'$match': {'active': True}}], {HIDDEN_MDS_ID, VISIBLE_MDS_ID}),
    ([{'$match': {'public_id': VISIBLE_MDS_ID}}], {VISIBLE_MDS_ID}),
    ({'$match': {'type_id': VISIBLE_MDS_TYPE_ID}}, {VISIBLE_MDS_ID, INACTIVE_MDS_ID}),
], ids=['only-active', 'object-id', 'type-id'])
def test_the_callers_stages_judge_the_objects(objects_manager: ObjectsManager, criteria: Any,
                                              expected: set[int]) -> None:
    """Not the Types: every Type is active, and no Type has the object's id"""
    assert _ids(objects_manager.get_mds_references_for_object(_referenced(objects_manager), criteria)) == expected


@pytest.mark.usefixtures('rest_api_app_context')
@pytest.mark.parametrize('group_id, expected', [
    (READER_GROUP_ID, {FIELD_REFERRER_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID}),
    (ADMIN_GROUP_ID, {FIELD_REFERRER_ID, HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID}),
], ids=['reader', 'admin'])
def test_the_listing_is_scoped_for_every_read(objects_manager: ObjectsManager, group_id: int,
                                              expected: set[int]) -> None:
    """The page and the total hold only what the group may READ"""
    user = CmdbUser(public_id=READER_GROUP_ID, user_name='refs-scope', active=True, group_id=group_id)

    result = objects_manager.references(_referenced(objects_manager), [], 0, 0, 'public_id', 1, user,
                                        AccessControlPermission.READ)

    assert _ids(result.results) == expected
    assert result.total == len(expected)
