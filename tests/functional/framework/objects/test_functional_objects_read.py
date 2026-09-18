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
Functional smoke for the ``/objects`` read and listing routes

What a caller gets back rather than what a write accepts: the rendered payloads, the
``?view=values`` projection, the reference and MDS-reference lookups, the object counts, and the
listing's own parameters - the active-only filter, the ``objectIDs`` validation, the two ``?filter=``
shapes, and the ACL that decides both the rows and the ``total`` beside them
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    MDS_REF_TYPE_ID,
    MISSING_OBJECT_ID,
    NAME_FIELD,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_VALUES,
    ORIGINAL_VALUE,
    ROUTE_URL,
    SEED_AUTHOR_ID,
    SEED_VERSION,
    TYPE_ID,
    UPDATED_VALUE,
    drop_object,
    insert_object_doc,
    mds_ref_type_doc,
    mds_referencing_object_doc,
    object_doc,
    object_payload,
    type_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

MDS_SECTION_NAME: str = 'mds-values-section'

MDS_ROW_FIELD: str = 'mds-row-field'

MDS_ROW_VALUES: list[str] = ['row-one', 'row-two']


class TestRenderedTypeInformation:
    """The rendered object view carries the Type's capability flags."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one object directly via the DB before each test and removes it after."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_GET)

    def test_type_information_carries_uses_ports_and_selectable_as_parent(self, rest_api) -> None:
        """
        Both flags reach the client through the render result

        Without them a client rendering an object has to fetch the CmdbType separately to learn
        whether to show the ports panel - on a view whose payload was built from that very type.
        The seeded type sets neither flag, so this also pins the default a type document without
        them renders as.
        """
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        type_information = response.get_json()['type_information']
        assert type_information['uses_ports'] is False
        assert type_information['selectable_as_parent'] is True

    def test_type_information_carries_the_port_section_index(self, rest_api) -> None:
        """
        Where the ports panel sits reaches the client with the flag that decides whether it renders

        The seeded type document carries no `port_section_index` at all - the shape of every type
        before updater_20260918 - so this also pins what such a document renders as.
        """
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['type_information']['port_section_index'] == 0

    def test_the_port_section_index_follows_the_stored_type(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Placing the ports section on the Type changes what the rendered object reports"""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.update_one({'public_id': TYPE_ID}, {'$set': {'uses_ports': True, 'port_section_index': 2}})
        try:
            response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}')

            assert response.get_json()['type_information']['port_section_index'] == 2
        finally:
            types.update_one(
                {'public_id': TYPE_ID},
                {'$set': {'uses_ports': False}, '$unset': {'port_section_index': ''}},
            )

    def test_uses_ports_follows_the_stored_type(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Enabling the flag on the Type changes what the rendered object reports"""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.update_one({'public_id': TYPE_ID}, {'$set': {'uses_ports': True}})
        try:
            response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}')

            assert response.get_json()['type_information']['uses_ports'] is True
        finally:
            types.update_one({'public_id': TYPE_ID}, {'$set': {'uses_ports': False}})


def _object_doc_with_mds(public_id: int, value: str) -> dict[str, Any]:
    """Builds a CmdbObject doc carrying one MDS section with two rows, for the value-view tests."""
    document = object_doc(public_id, value)
    document['multi_data_sections'] = [{
        'section_id': MDS_SECTION_NAME,
        'highest_id': len(MDS_ROW_VALUES),
        'values': [
            {
                'multi_data_id': index + 1,
                'data': [{'name': MDS_ROW_FIELD, 'value': row_value, 'type': 'text'}],
            }
            for index, row_value in enumerate(MDS_ROW_VALUES)
        ],
    }]
    return document


class TestGetObjectValueView:
    """``?view=values`` reshapes fields and multi_data_sections into name-keyed maps."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one object with an MDS section before each test and removes it after."""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            _object_doc_with_mds(OBJECT_ID_FOR_VALUES, ORIGINAL_VALUE),
        )
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_VALUES)

    def test_single_returns_name_keyed_fields(self, rest_api) -> None:
        """The single route answers 200 with fields as a name to value map."""
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=values')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['fields'] == {NAME_FIELD: ORIGINAL_VALUE}

    def test_single_returns_name_keyed_mds_rows(self, rest_api) -> None:
        """Each MDS section becomes one key holding its rows as name to value maps, in stored order."""
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=values')

        assert response.get_json()['multi_data_sections'] == {
            MDS_SECTION_NAME: [{MDS_ROW_FIELD: row_value} for row_value in MDS_ROW_VALUES],
        }

    def test_single_keeps_the_other_top_level_keys(self, rest_api) -> None:
        """Only the two field-carrying keys change shape; the identity keys are passed through."""
        body = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=values').get_json()

        assert body['public_id'] == OBJECT_ID_FOR_VALUES
        assert body['type_id'] == TYPE_ID
        assert body['active'] is True

    def test_single_drops_type_and_row_identity(self, rest_api) -> None:
        """
        The view is read-only, and this is what makes it so

        A field entry loses its 'type' and an MDS row loses its 'multi_data_id', so the payload can
        not be written back - which is the documented contract of the mode.
        """
        body = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=values').get_json()

        assert body['fields'] == {NAME_FIELD: ORIGINAL_VALUE}
        for row in body['multi_data_sections'][MDS_SECTION_NAME]:
            assert list(row) == [MDS_ROW_FIELD]

    def test_single_default_is_still_the_render_view(self, rest_api) -> None:
        """
        Omitting the parameter must not change the historical response

        The frontend reads this route without a view parameter, so the rendered envelope has to stay.
        """
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'object_information' in body
        assert isinstance(body['fields'], list)

    def test_single_render_is_accepted_explicitly(self, rest_api) -> None:
        """An explicit ``view=render`` is the same as omitting it."""
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=render')

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json()['fields'], list)

    def test_single_native_is_refused_with_400(self, rest_api) -> None:
        """
        ``native`` has its own route, so this one refuses it rather than serving a second address

        Refused loudly instead of silently rendering, so a caller can not believe it got the stored
        document when it did not.
        """
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=native')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_single_unknown_view_is_refused_with_400(self, rest_api) -> None:
        """An unknown view value is a 400, not a silently rendered response."""
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_VALUES}?view=nonsense')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_single_missing_object_still_returns_404(self, rest_api) -> None:
        """The view parameter does not change what a missing id answers."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}?view=values')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_list_returns_name_keyed_results(self, rest_api) -> None:
        """The list route serves the same shape inside its usual results envelope."""
        response = rest_api.get(f'{ROUTE_URL}/?view=values')

        assert response.status_code == HTTPStatus.OK
        seeded = next(entry for entry in response.get_json()['results']
                      if entry['public_id'] == OBJECT_ID_FOR_VALUES)
        assert seeded['fields'] == {NAME_FIELD: ORIGINAL_VALUE}
        assert seeded['multi_data_sections'] == {
            MDS_SECTION_NAME: [{MDS_ROW_FIELD: row_value} for row_value in MDS_ROW_VALUES],
        }

    def test_list_unknown_view_is_refused_with_400(self, rest_api) -> None:
        """The list route keeps its own 400 on an unknown view."""
        response = rest_api.get(f'{ROUTE_URL}/?view=nonsense')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_native_still_returns_the_stored_arrays(self, rest_api) -> None:
        """``view=native`` is untouched by the new mode: fields stay a list of triples."""
        response = rest_api.get(f'{ROUTE_URL}/?view=native')

        assert response.status_code == HTTPStatus.OK
        seeded = next(entry for entry in response.get_json()['results']
                      if entry['public_id'] == OBJECT_ID_FOR_VALUES)
        assert isinstance(seeded['fields'], list)
        assert seeded['fields'][0]['name'] == NAME_FIELD


RENDERED_GET_ID: int = 9440

COUNT_DELTA_ID: int = 9441

COUNT_TYPE_IDS: list[int] = [9442, 9443]

MDS_REF_ID: int = 9444

REFERENCES_HAPPY_ID: int = 9452


# A second type carrying a ref field that points at TYPE_ID, used to exercise the references route
REF_TYPE_ID: int = 9402

REF_FIELD: str = 'ref-field'

REF_TARGET_OBJECT_ID: int = 9460

REF_SOURCE_OBJECT_ID: int = 9461


def _ref_type_doc() -> dict[str, Any]:
    """Builds a CmdbType doc whose single field is a ref pointing at TYPE_ID."""
    return {
        'public_id': REF_TYPE_ID,
        'name': f'ref-type-{REF_TYPE_ID}',
        'label': 'Ref Type',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        'fields': [{'type': 'ref', 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [TYPE_ID]}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [REF_FIELD]}],
            'summary': {'fields': [REF_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
    }


def _referencing_object_doc(public_id: int, target_id: int) -> dict[str, Any]:
    """Builds a CmdbObject of REF_TYPE_ID whose ref field points at the given target object id."""
    return {
        'public_id': public_id,
        'type_id': REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'ref', 'name': REF_FIELD, 'value': target_id}],
        'creation_time': datetime.now(timezone.utc),
    }


MDS_REF_TARGET_ID: int = 9462

MDS_REF_SOURCE_ID: int = 9463


class TestGetRenderedObject:
    """GET /objects/<id> returns the rendered single-object representation."""

    def test_get_rendered_single_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET for a seeded object returns 200 and a body carrying its object_id."""
        insert_object_doc(database_manager, database_name, RENDERED_GET_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/{RENDERED_GET_ID}')

            assert response.status_code == HTTPStatus.OK
            assert str(RENDERED_GET_ID) in response.get_data(as_text=True)
        finally:
            drop_object(database_manager, database_name, RENDERED_GET_ID)

    def test_get_rendered_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND


class TestObjectCounts:
    """GET /objects/count and /objects/count/<type_id> return increasing integer counts."""

    def test_global_count_increases_after_insert(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Inserting one object raises the global count by exactly one."""
        before = rest_api.get(f'{ROUTE_URL}/count').get_json()
        insert_object_doc(database_manager, database_name, COUNT_DELTA_ID, ORIGINAL_VALUE)
        try:
            after = rest_api.get(f'{ROUTE_URL}/count')
            assert after.status_code == HTTPStatus.OK
            assert after.get_json() == before + 1
        finally:
            drop_object(database_manager, database_name, COUNT_DELTA_ID)

    def test_count_for_type_increases_by_inserted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The per-type count rises by the number of objects inserted for that type."""
        before = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').get_json()
        for public_id in COUNT_TYPE_IDS:
            insert_object_doc(database_manager, database_name, public_id, ORIGINAL_VALUE)
        try:
            after = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}')
            assert after.status_code == HTTPStatus.OK
            assert after.get_json() == before + len(COUNT_TYPE_IDS)
        finally:
            for public_id in COUNT_TYPE_IDS:
                drop_object(database_manager, database_name, public_id)


class TestMdsReferenceRoutes:
    """GET /objects/<id>/mds_reference[s] render the MDS reference summary for an object."""

    def test_single_mds_reference(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A seeded object returns 200 for its MDS reference summary."""
        insert_object_doc(database_manager, database_name, MDS_REF_ID, ORIGINAL_VALUE)
        try:
            assert rest_api.get(f'{ROUTE_URL}/{MDS_REF_ID}/mds_reference').status_code == HTTPStatus.OK
        finally:
            drop_object(database_manager, database_name, MDS_REF_ID)

    def test_single_mds_reference_missing_returns_404(self, rest_api) -> None:
        """A missing object returns 404 for the MDS reference summary."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_reference').status_code == HTTPStatus.NOT_FOUND

    def test_multi_mds_references_keyed_by_id(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The multi route returns 200 and a mapping that includes the requested id."""
        insert_object_doc(database_manager, database_name, MDS_REF_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/{MDS_REF_ID}/mds_references')

            assert response.status_code == HTTPStatus.OK
            assert str(MDS_REF_ID) in response.get_json()
        finally:
            drop_object(database_manager, database_name, MDS_REF_ID)


class TestObjectReferencesHappyPath:
    """GET /objects/references/<id> returns a paged envelope for an existing object."""

    def test_references_of_existing_object_returns_envelope(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object with no referrers returns 200 and an empty results list (not a 500/404)."""
        insert_object_doc(database_manager, database_name, REFERENCES_HAPPY_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{REFERENCES_HAPPY_ID}')

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert 'results' in body
            assert body['results'] == []
        finally:
            drop_object(database_manager, database_name, REFERENCES_HAPPY_ID)

    def test_references_returns_referencing_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object pointed at by another object's ref field appears in its references list."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_ref_type_doc())
        objects.insert_one(object_doc(REF_TARGET_OBJECT_ID, ORIGINAL_VALUE))
        objects.insert_one(_referencing_object_doc(REF_SOURCE_OBJECT_ID, REF_TARGET_OBJECT_ID))
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{REF_TARGET_OBJECT_ID}')

            assert response.status_code == HTTPStatus.OK
            result_ids = [result['public_id'] for result in response.get_json()['results']]
            assert REF_SOURCE_OBJECT_ID in result_ids
        finally:
            objects.delete_many({'public_id': {'$in': [REF_TARGET_OBJECT_ID, REF_SOURCE_OBJECT_ID]}})
            types.delete_one({'public_id': REF_TYPE_ID})

    def test_references_returns_mds_referencing_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object referencing the target via a multi-data-section ref field is also returned."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(mds_ref_type_doc())
        objects.insert_one(object_doc(MDS_REF_TARGET_ID, ORIGINAL_VALUE))
        objects.insert_one(mds_referencing_object_doc(MDS_REF_SOURCE_ID, MDS_REF_TARGET_ID))
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{MDS_REF_TARGET_ID}')

            assert response.status_code == HTTPStatus.OK
            result_ids = [result['public_id'] for result in response.get_json()['results']]
            assert MDS_REF_SOURCE_ID in result_ids
        finally:
            objects.delete_many({'public_id': {'$in': [MDS_REF_TARGET_ID, MDS_REF_SOURCE_ID]}})
            types.delete_one({'public_id': MDS_REF_TYPE_ID})


class TestActiveOnlyFilter:
    """`onlyActiveObjCookie` narrows the list, the counts and the reference route to active objects."""

    INACTIVE_ID: int = 9431

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds one active and one inactive object of the module's type."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        inactive = object_doc(self.INACTIVE_ID, ORIGINAL_VALUE)
        inactive['active'] = False
        objects.insert_one(inactive)
        yield
        objects.delete_many({'public_id': {'$in': [OBJECT_ID_FOR_GET, self.INACTIVE_ID]}})

    def test_list_excludes_inactive_objects(self, rest_api) -> None:
        """The list route appends an active-only $match, so the inactive object is not returned."""
        response = rest_api.get(f'{ROUTE_URL}/?onlyActiveObjCookie=true')

        assert response.status_code == HTTPStatus.OK
        returned = {entry['public_id'] for entry in response.get_json()['results']}
        assert self.INACTIVE_ID not in returned

    def test_list_with_a_filter_still_excludes_inactive_objects(self, rest_api) -> None:
        """A caller-supplied filter dict is wrapped into a stage and the active stage appended to it."""
        response = rest_api.get(
            f'{ROUTE_URL}/?onlyActiveObjCookie=true&filter={{"type_id": {TYPE_ID}}}'
        )

        assert response.status_code == HTTPStatus.OK
        returned = {entry['public_id'] for entry in response.get_json()['results']}
        assert self.INACTIVE_ID not in returned
        assert OBJECT_ID_FOR_GET in returned

    def test_total_count_excludes_inactive_objects(self, rest_api) -> None:
        """GET /count honours the active-only filter."""
        with_inactive = rest_api.get(f'{ROUTE_URL}/count').get_json()
        active_only = rest_api.get(f'{ROUTE_URL}/count?onlyActiveObjCookie=true').get_json()

        assert active_only < with_inactive

    def test_type_count_excludes_inactive_objects(self, rest_api) -> None:
        """GET /count/<type_id> honours the active-only filter."""
        with_inactive = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').get_json()
        active_only = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}?onlyActiveObjCookie=true').get_json()

        assert active_only == with_inactive - 1

    def test_references_route_accepts_the_active_filter(self, rest_api) -> None:
        """The reference route appends the same stage; an object with no references returns an empty page."""
        response = rest_api.get(f'{ROUTE_URL}/references/{OBJECT_ID_FOR_GET}?onlyActiveObjCookie=true')

        assert response.status_code == HTTPStatus.OK


class TestObjectIdsValidation:
    """The two `objectIDs` encodings both refuse an unusable id instead of failing with a 500."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)

    @pytest.mark.parametrize('raw_id', ['abc', '0', '-1', '1.5'], ids=['text', 'zero', 'negative', 'float'])
    def test_bulk_update_rejects_an_unusable_id(self, rest_api, raw_id: str) -> None:
        """`int()` on a junk id used to raise into the catch-all and answer 500 (regression)."""
        response = rest_api.put(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}?objectIDs={raw_id}',
            json=object_payload(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_bulk_update_accepts_repeated_parameters(self, rest_api) -> None:
        """The frontend sends objectIDs as repeated parameters; both targets are updated."""
        response = rest_api.put(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}'
            f'?objectIDs={OBJECT_ID_FOR_UPDATE}&objectIDs={OBJECT_ID_FOR_UPDATE}',
            json=object_payload(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE),
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert len(response.get_json()['results']) == 2

    @pytest.mark.parametrize('raw_ids', ['abc', '1,abc', '0'], ids=['text', 'mixed', 'zero'])
    def test_mds_references_rejects_an_unusable_id(self, rest_api, raw_ids: str) -> None:
        """A junk id in the comma-joined list used to be dropped silently."""
        response = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}/mds_references?objectIDs={raw_ids}')

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestListFilterShapes:
    """A caller-supplied filter reaches the list / reference routes as a dict OR as a pipeline."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_GET)

    def test_list_accepts_a_pipeline_filter_with_the_active_filter(self, rest_api) -> None:
        """A filter that already IS a stage list only gets the active stage appended."""
        response = rest_api.get(
            f'{ROUTE_URL}/?onlyActiveObjCookie=true&filter=[{{"$match": {{"type_id": {TYPE_ID}}}}}]'
        )

        assert response.status_code == HTTPStatus.OK
        assert OBJECT_ID_FOR_GET in {entry['public_id'] for entry in response.get_json()['results']}

    def test_references_accepts_a_pipeline_filter(self, rest_api) -> None:
        """The reference route takes the same two filter shapes."""
        response = rest_api.get(
            f'{ROUTE_URL}/references/{OBJECT_ID_FOR_GET}?filter=[{{"$match": {{"type_id": {TYPE_ID}}}}}]'
        )

        assert response.status_code == HTTPStatus.OK


DENIED_TYPE_ID: int = 9402

DENIED_OBJECT_IDS: list[int] = [9431, 9432]

READABLE_OBJECT_ID: int = 9433

ADMIN_GROUP_ID: int = 1


def _denied_type_doc() -> dict[str, Any]:
    """The seed type with an activated ACL granting the caller's group everything except READ."""
    doc = type_doc()
    doc['public_id'] = DENIED_TYPE_ID
    doc['name'] = 'route-smoke-denied-type'
    doc['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['CREATE', 'UPDATE', 'DELETE']}}}

    return doc


class TestListingTotalUnderAcl:
    """
    The rows and the `total` beside them obey the same ACL

    Until the rule moved into the criteria, `iterate_query` handed the user and the permission to the
    data aggregation only and built the count from the criteria alone — so a restricted caller was
    told how many Objects of Types they may not see exist, and the pager offered pages that came back
    empty.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Two objects of an unreadable type and one of the readable seed type."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        types.insert_one(_denied_type_doc())
        for object_id in DENIED_OBJECT_IDS:
            denied_object = object_doc(object_id, ORIGINAL_VALUE)
            denied_object['type_id'] = DENIED_TYPE_ID
            objects.insert_one(denied_object)
        objects.insert_one(object_doc(READABLE_OBJECT_ID, ORIGINAL_VALUE))

        yield

        types.delete_one({'public_id': DENIED_TYPE_ID})
        objects.delete_many({'public_id': {'$in': DENIED_OBJECT_IDS + [READABLE_OBJECT_ID]}})

    def test_denied_objects_are_absent_from_the_rows(self, rest_api) -> None:
        """The precondition: the ACL really does exclude them."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')
        listed = [result['public_id'] for result in response.get_json()['results']]

        assert response.status_code == HTTPStatus.OK
        assert READABLE_OBJECT_ID in listed
        assert not set(DENIED_OBJECT_IDS) & set(listed)

    def test_the_total_matches_the_rows_it_was_returned_with(self, rest_api) -> None:
        """An unpaginated listing's total is the number of rows the caller actually got."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')
        body = response.get_json()

        assert body['total'] == len(body['results'])

    def test_the_total_counts_only_the_readable_ones(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Narrowed to this test's own three documents, the answer is an exact number: one of three."""
        seeded = DENIED_OBJECT_IDS + [READABLE_OBJECT_ID]
        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents(
            {'public_id': {'$in': seeded}}
        )

        body = rest_api.get(f'{ROUTE_URL}/?limit=0&filter={{"public_id":{{"$in":{seeded}}}}}').get_json()

        assert stored == 3
        assert body['total'] == 1
        assert [result['public_id'] for result in body['results']] == [READABLE_OBJECT_ID]

    def test_the_header_total_agrees_with_the_body(self, rest_api) -> None:
        """X-Total-Count is built from the same total, so the pager and the body cannot disagree."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')

        assert int(response.headers['X-Total-Count']) == len(response.get_json()['results'])

    def test_a_paginated_listing_offers_no_empty_page(self, rest_api) -> None:
        """
        The total drives the page count, so an inflated one offers pages with nothing on them

        With a page size of 1 the last page a correct total advertises must still hold a row.
        """
        body = rest_api.get(f'{ROUTE_URL}/?limit=1&page=1').get_json()
        last_page = body['total']

        response = rest_api.get(f'{ROUTE_URL}/?limit=1&page={last_page}')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()['results']) == 1
