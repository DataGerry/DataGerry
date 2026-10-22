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
`GET /objects/references/<id>` - both halves of the listing obey the caller's READ ACL and the caller's filter

The referenced object is the seed's VISIBLE object. It is referenced by a plain ref field (the seed's SUMMARY_REF
object) and from multi-data-section rows: of a Type only the admin group may read, of a readable Type, of an
inactive object of that Type - and a decoy holds the id in a text field of a row, which is no reference. Requested
as a group with the object view right and no READ on the hidden Type, and as the admin
"""
from datetime import datetime, timezone
from http import HTTPStatus
from json import dumps
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.routes_helper import ONLY_ACTIVE_OBJECTS_PARAM
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

HIDDEN_MDS_TYPE_ID: int = 89581
VISIBLE_MDS_TYPE_ID: int = 89582
HIDDEN_MDS_ID: int = 89583
VISIBLE_MDS_ID: int = 89584
INACTIVE_MDS_ID: int = 89585
DECOY_MDS_ID: int = 89586
MDS_TYPE_IDS: list[int] = [HIDDEN_MDS_TYPE_ID, VISIBLE_MDS_TYPE_ID]
MDS_OBJECT_IDS: list[int] = [HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID, DECOY_MDS_ID]

SECRET_FIELD: str = 'secret'
SECRET_VALUE: str = 'mds-reference-value'
HIDDEN_SECRET_VALUE: str = 'mds-reference-hidden-secret'
MDS_SECTION: str = 'rows'
MDS_REF_FIELD: str = 'row-ref'
MDS_NOTE_FIELD: str = 'row-note'

URL: str = f'/objects/references/{seed.VISIBLE_ID}'
FIELD_REFERRER_ID: int = seed.SUMMARY_REF_ID


def _mds_type(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A Type with a secret text field and a multi-data section holding a ref field (to VISIBLE) and a text field."""
    return {
        'public_id': public_id, 'name': f'mds-reference-{public_id}', 'label': f'MDS Reference {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [
            {'type': FieldType.TEXT.value, 'name': SECRET_FIELD, 'label': 'Secret'},
            {'type': FieldType.REFERENCE.value, 'name': MDS_REF_FIELD, 'label': 'Ref',
             'ref_types': [seed.VISIBLE_TYPE_ID]},
            {'type': FieldType.TEXT.value, 'name': MDS_NOTE_FIELD, 'label': 'Note'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [
                {'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [SECRET_FIELD]},
                {'type': SectionType.MDS_SECTION.value, 'name': MDS_SECTION, 'label': 'Rows',
                 'fields': [MDS_REF_FIELD, MDS_NOTE_FIELD]},
            ],
            'summary': {'fields': [SECRET_FIELD]},
            'externals': [],
        },
        'acl': acl,
    }


def _mds_object(public_id: int, type_id: int, row_field: str, active: bool = True,
                value: str = SECRET_VALUE) -> dict[str, Any]:
    """An object named `value` whose one MDS row holds VISIBLE's public_id in `row_field`."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': active, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': FieldType.TEXT.value, 'name': SECRET_FIELD, 'value': value}],
        'multi_data_sections': [{'section_id': MDS_SECTION, 'values': [
            {'multi_data_id': 0, 'data': [{'name': row_field, 'value': seed.VISIBLE_ID}]},
        ]}],
    }


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes what this module writes on top of the location seed."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': MDS_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': MDS_OBJECT_IDS}})


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The location seed, the two MDS Types and their referrers, and the view right for the editor."""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    _purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_many([
        _mds_type(HIDDEN_MDS_TYPE_ID, {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}),
        _mds_type(VISIBLE_MDS_TYPE_ID, {'activated': False, 'groups': {'includes': {}}}),
    ])
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        _mds_object(HIDDEN_MDS_ID, HIDDEN_MDS_TYPE_ID, MDS_REF_FIELD, value=HIDDEN_SECRET_VALUE),
        _mds_object(VISIBLE_MDS_ID, VISIBLE_MDS_TYPE_ID, MDS_REF_FIELD),
        _mds_object(INACTIVE_MDS_ID, VISIBLE_MDS_TYPE_ID, MDS_REF_FIELD, active=False),
        _mds_object(DECOY_MDS_ID, VISIBLE_MDS_TYPE_ID, MDS_NOTE_FIELD),
    ])
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': ObjectRightName.VIEW.value}},
    )
    yield
    _purge(database_manager, database_name)
    seed.purge(database_manager, database_name)


def _list(rest_api, as_reader: bool, query: str = '') -> tuple[list[int], int, list[dict[str, Any]]]:
    """The listed public_ids (sorted), the total and the rows, as the reader or as the admin."""
    user: dict[str, Any] = {'user': seed.location_editor()} if as_reader else {}
    response = rest_api.get(f'{URL}?limit=0{query}', **user)

    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.get_json()

    return sorted(_row_id(row) for row in body['results']), body['total'], body['results']


def _row_id(row: dict[str, Any]) -> int:
    """The object a row answers: a stored document's public_id, or a render's object_information."""
    if 'public_id' in row:
        return row['public_id']

    return row['object_information']['object_id']


def _filter(criteria: dict[str, Any]) -> str:
    """The query part carrying a client filter."""
    return f'&filter={dumps(criteria)}'


class TestTheObjectAcl:
    """An MDS referrer of a Type the caller may not read is not listed, and does not count."""

    def test_the_reader_does_not_see_the_hidden_referrer(self, rest_api) -> None:
        """The field referrer and the readable MDS referrers only"""
        ids, total, rows = _list(rest_api, as_reader=True)

        assert ids == sorted([FIELD_REFERRER_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID])
        assert total == len(ids)
        assert HIDDEN_SECRET_VALUE not in str(rows)

    def test_the_admin_sees_every_referrer(self, rest_api) -> None:
        """The control: the denial is by Type"""
        ids, total, _ = _list(rest_api, as_reader=False)

        assert ids == sorted([FIELD_REFERRER_ID, HIDDEN_MDS_ID, VISIBLE_MDS_ID, INACTIVE_MDS_ID])
        assert total == len(ids)

    @pytest.mark.parametrize('view', ['native', 'values', 'render'])
    def test_no_view_answers_the_hidden_referrer(self, rest_api, view: str) -> None:
        """The page is read scoped, whatever the view"""
        ids, _, _ = _list(rest_api, as_reader=True, query=f'&view={view}')

        assert HIDDEN_MDS_ID not in ids

    def test_a_paged_reader_counts_only_what_it_may_read(self, rest_api) -> None:
        """The total behind a page of one is the readable union"""
        response = rest_api.get(f'{URL}?limit=1&page=1&sort=public_id&order=-1', user=seed.location_editor())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['total'] == 3
        assert [row['public_id'] for row in response.get_json()['results']] == [INACTIVE_MDS_ID]

    def test_the_hidden_object_is_also_refused_directly(self, rest_api) -> None:
        """The listing now agrees with the single read"""
        response = rest_api.get(f'/objects/{HIDDEN_MDS_ID}', user=seed.location_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestTheFilterRunsOnTheObjects:
    """The caller's filter and search stages narrow the MDS half's objects, as they do the field half's."""

    def test_only_active_objects_leaves_the_inactive_mds_referrer_out(self, rest_api) -> None:
        """The only-active stage judged the Types before, which are all active"""
        ids, total, _ = _list(rest_api, as_reader=False, query=f'&{ONLY_ACTIVE_OBJECTS_PARAM}=true')

        assert ids == sorted([FIELD_REFERRER_ID, HIDDEN_MDS_ID, VISIBLE_MDS_ID])
        assert total == len(ids)

    def test_a_filter_on_an_object_key_matches_the_objects(self, rest_api) -> None:
        """A public_id filter names the object - it matched a Type of that id before"""
        ids, _, _ = _list(rest_api, as_reader=False, query=_filter({'public_id': VISIBLE_MDS_ID}))

        assert ids == [VISIBLE_MDS_ID]

    def test_a_type_filter_keeps_that_types_referrers(self, rest_api) -> None:
        """The references-by-type view's filter: the object's own type_id"""
        ids, _, _ = _list(rest_api, as_reader=False, query=_filter({'type_id': VISIBLE_MDS_TYPE_ID}))

        assert ids == sorted([VISIBLE_MDS_ID, INACTIVE_MDS_ID])

    def test_a_type_filter_on_a_hidden_type_answers_nothing_to_the_reader(self, rest_api) -> None:
        """The filter cannot reach past the ACL"""
        ids, total, _ = _list(rest_api, as_reader=True, query=_filter({'type_id': HIDDEN_MDS_TYPE_ID}))

        assert (ids, total) == ([], 0)


class TestAnMdsRowMustHoldAReference:
    """The join narrows to the objects holding the id; the row confirmation keeps only ref fields."""

    def test_an_id_in_a_text_field_of_a_row_is_no_reference(self, rest_api) -> None:
        """The decoy holds the id, but not in a ref field"""
        ids, _, _ = _list(rest_api, as_reader=False)

        assert DECOY_MDS_ID not in ids
