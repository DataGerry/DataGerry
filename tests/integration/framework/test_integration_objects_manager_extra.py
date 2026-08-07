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
Integration tests for ObjectsManager methods not covered by the CRUD suite

Pins, against a real MongoDB: the ISMS risk-assessment cascade on object deletion
(delete_object_from_risk_assessment_cascade), the multi_data_sections bulk write
(bulk_update_multi_data_sections), and the batched object lookup (get_objects_lookup)
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.type_model import CmdbType
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9701
NAME_FIELD: str = 'name-field'

# Risk-assessment cascade ids
CASCADE_OBJECT_ID: int = 9710
OTHER_OBJECT_ID: int = 9711
TARGET_RA_ID: int = 9731
OTHER_RA_ID: int = 9732
TARGET_CMA_ID: int = 9741
OTHER_CMA_ID: int = 9742

# Bulk MDS update ids
MDS_OBJECT_IDS: list[int] = [9751, 9752]

# Lookup ids
LOOKUP_OBJECT_IDS: list[int] = [9761, 9762]
LOOKUP_MISSING_ID: int = 9769

# clear_location_field_for_objects ids
LOC_CLEAR_WITH_LOCATION_IDS: list[int] = [9771, 9772]
LOC_CLEAR_NO_LOCATION_ID: int = 9773
LOCATION_FIELD_NAME: str = 'dg_location'

# set_location_field_for_objects ids
LOC_SET_WITH_LOCATION_IDS: list[int] = [9774, 9775]
LOC_SET_SEED_PARENT_ID: int = 42
LOC_SET_NEW_PARENT_ID: int = 77

# count_objects_grouped_by_type ids
GROUP_TYPE_ID_A: int = 9781
GROUP_TYPE_ID_B: int = 9782
GROUP_A_OBJECT_IDS: list[int] = [9791, 9792, 9793]
GROUP_B_OBJECT_IDS: list[int] = [9794]

# batched risk-assessment cascade ids
BATCH_OBJECT_IDS: list[int] = [9810, 9811]
BATCH_UNRELATED_OBJECT_ID: int = 9812
BATCH_RA_IDS: list[int] = [9831, 9832]
BATCH_UNRELATED_RA_ID: int = 9833
BATCH_CMA_IDS: list[int] = [9841, 9842]
BATCH_UNRELATED_CMA_ID: int = 9843

# delete_object type-reuse ids
REUSE_OBJECT_ID: int = 9851
REUSE_TYPE_ID: int = 9852


def _object_doc(
    public_id: int,
    value: str = 'x',
    mds: list[dict[str, Any]] | None = None,
    type_id: int = TYPE_ID,
) -> dict[str, Any]:
    """Builds a complete CmdbObject doc (deserialisable via CmdbObject.from_data)."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}],
        'multi_data_sections': mds or [],
    }


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                  delete_object_from_risk_assessment_cascade                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRiskAssessmentCascade:
    """Deleting an object removes its RiskAssessments + ControlMeasureAssignments, and only those."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a target RA+CMA (for CASCADE_OBJECT_ID) and an unrelated RA+CMA, cleaned up after."""
        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

        risk_assessments.insert_many([
            {'public_id': TARGET_RA_ID, 'object_id_ref_type': ObjectReferenceType.OBJECT.value,
             'object_id': CASCADE_OBJECT_ID},
            {'public_id': OTHER_RA_ID, 'object_id_ref_type': ObjectReferenceType.OBJECT.value,
             'object_id': OTHER_OBJECT_ID},
        ])
        assignments.insert_many([
            {'public_id': TARGET_CMA_ID, 'risk_assessment_id': TARGET_RA_ID},
            {'public_id': OTHER_CMA_ID, 'risk_assessment_id': OTHER_RA_ID},
        ])
        yield
        risk_assessments.delete_many({'public_id': {'$in': [TARGET_RA_ID, OTHER_RA_ID]}})
        assignments.delete_many({'public_id': {'$in': [TARGET_CMA_ID, OTHER_CMA_ID]}})

    def test_cascade_removes_only_the_targets(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The target object's RA + CMA are deleted; the unrelated object's RA + CMA survive."""
        objects_manager.delete_object_from_risk_assessment_cascade(CASCADE_OBJECT_ID)

        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

        assert risk_assessments.find_one({'public_id': TARGET_RA_ID}) is None
        assert assignments.find_one({'public_id': TARGET_CMA_ID}) is None
        # Unrelated object's rows are untouched
        assert risk_assessments.find_one({'public_id': OTHER_RA_ID}) is not None
        assert assignments.find_one({'public_id': OTHER_CMA_ID}) is not None

    def test_cascade_is_noop_when_object_has_no_risk_assessments(self, objects_manager: ObjectsManager) -> None:
        """An object with no RiskAssessments returns cleanly without touching anything."""
        objects_manager.delete_object_from_risk_assessment_cascade(LOOKUP_MISSING_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       bulk_update_multi_data_sections                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkUpdateMultiDataSections:
    """The bulk write replaces each object's multi_data_sections in one round-trip."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two objects with empty multi_data_sections, removed after the test."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.insert_many([_object_doc(public_id, mds=[]) for public_id in MDS_OBJECT_IDS])
        yield
        objects.delete_many({'public_id': {'$in': MDS_OBJECT_IDS}})

    def test_bulk_update_persists_new_multi_data_sections(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Each object's multi_data_sections are overwritten with the supplied content."""
        new_mds = [{'section_id': 'mds-section', 'values': [{'multi_data_id': 1, 'data': []}]}]
        updated = [CmdbObject.from_data(_object_doc(public_id, mds=new_mds)) for public_id in MDS_OBJECT_IDS]

        objects_manager.bulk_update_multi_data_sections(updated)

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        for public_id in MDS_OBJECT_IDS:
            stored = objects.find_one({'public_id': public_id})
            assert stored['multi_data_sections'] == new_mds

    def test_bulk_update_empty_list_is_noop(self, objects_manager: ObjectsManager) -> None:
        """An empty list performs no write and does not raise."""
        objects_manager.bulk_update_multi_data_sections([])


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_objects_lookup                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetObjectsLookup:
    """get_objects_lookup returns the requested objects keyed by public_id, missing ids absent."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two objects, removed after the test."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.insert_many([_object_doc(public_id) for public_id in LOOKUP_OBJECT_IDS])
        yield
        objects.delete_many({'public_id': {'$in': LOOKUP_OBJECT_IDS}})

    def test_lookup_keys_present_objects_and_skips_missing(self, objects_manager: ObjectsManager) -> None:
        """Found ids map to CmdbObject instances; a missing id is simply absent from the dict."""
        result = objects_manager.get_objects_lookup(LOOKUP_OBJECT_IDS + [LOOKUP_MISSING_ID])

        assert set(result) == set(LOOKUP_OBJECT_IDS)
        assert all(isinstance(obj, CmdbObject) for obj in result.values())
        assert result[LOOKUP_OBJECT_IDS[0]].public_id == LOOKUP_OBJECT_IDS[0]


# -------------------------------------------------------------------------------------------------------------------- #
#                                       clear_location_field_for_objects                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestClearLocationFieldForObjects:
    """Resets the location-type field value to None for the given objects, leaving others untouched."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two objects carrying a populated location field + one without any location field."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        for public_id in LOC_CLEAR_WITH_LOCATION_IDS:
            doc = _object_doc(public_id)
            doc['fields'].append({'name': LOCATION_FIELD_NAME, 'type': 'location', 'value': 42})
            objects.insert_one(doc)

        objects.insert_one(_object_doc(LOC_CLEAR_NO_LOCATION_ID))
        yield
        objects.delete_many(
            {'public_id': {'$in': LOC_CLEAR_WITH_LOCATION_IDS + [LOC_CLEAR_NO_LOCATION_ID]}}
        )

    def test_clears_location_value_only_on_targets(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The location field value becomes None on each target; a text-only object is unaffected."""
        objects_manager.clear_location_field_for_objects(LOC_CLEAR_WITH_LOCATION_IDS)

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        for public_id in LOC_CLEAR_WITH_LOCATION_IDS:
            doc = objects.find_one({'public_id': public_id})
            location_field = next(field for field in doc['fields'] if field['name'] == LOCATION_FIELD_NAME)
            assert location_field['value'] is None

        # An object without a location field is untouched (still just its text field)
        untouched = objects.find_one({'public_id': LOC_CLEAR_NO_LOCATION_ID})
        assert all(field['name'] != LOCATION_FIELD_NAME for field in untouched['fields'])

    def test_empty_list_is_noop(self, objects_manager: ObjectsManager) -> None:
        """An empty id list performs no update and does not raise."""
        objects_manager.clear_location_field_for_objects([])


# -------------------------------------------------------------------------------------------------------------------- #
#                                        set_location_field_for_objects                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSetLocationFieldForObjects:
    """Sets the location-type field value to a given parent id for the targets (re-parent mirror)."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds two objects carrying a populated location field pointing at the seed parent."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        for public_id in LOC_SET_WITH_LOCATION_IDS:
            doc = _object_doc(public_id)
            doc['fields'].append(
                {'name': LOCATION_FIELD_NAME, 'type': 'location', 'value': LOC_SET_SEED_PARENT_ID}
            )
            objects.insert_one(doc)
        yield
        objects.delete_many({'public_id': {'$in': LOC_SET_WITH_LOCATION_IDS}})

    def test_sets_location_value_on_targets(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The location field value becomes the new parent id on each target object."""
        objects_manager.set_location_field_for_objects(LOC_SET_WITH_LOCATION_IDS, LOC_SET_NEW_PARENT_ID)

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        for public_id in LOC_SET_WITH_LOCATION_IDS:
            doc = objects.find_one({'public_id': public_id})
            location_field = next(field for field in doc['fields'] if field['name'] == LOCATION_FIELD_NAME)
            assert location_field['value'] == LOC_SET_NEW_PARENT_ID

    def test_empty_list_is_noop(self, objects_manager: ObjectsManager) -> None:
        """An empty id list performs no update and does not raise."""
        objects_manager.set_location_field_for_objects([], LOC_SET_NEW_PARENT_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_objects_grouped_by_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCountObjectsGroupedByType:
    """Counts every CmdbObject grouped by its type_id in a single aggregation."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds three objects of one type and one object of another, removed after the test."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.insert_many(
            [_object_doc(public_id, type_id=GROUP_TYPE_ID_A) for public_id in GROUP_A_OBJECT_IDS]
            + [_object_doc(public_id, type_id=GROUP_TYPE_ID_B) for public_id in GROUP_B_OBJECT_IDS]
        )
        yield
        objects.delete_many({'public_id': {'$in': GROUP_A_OBJECT_IDS + GROUP_B_OBJECT_IDS}})

    def test_groups_counts_by_type_id(self, objects_manager: ObjectsManager) -> None:
        """The seeded type_ids report the exact number of objects inserted for each."""
        counts = objects_manager.count_objects_grouped_by_type()

        assert counts.get(GROUP_TYPE_ID_A) == len(GROUP_A_OBJECT_IDS)
        assert counts.get(GROUP_TYPE_ID_B) == len(GROUP_B_OBJECT_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                  delete_objects_from_risk_assessment_cascade                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBatchedRiskAssessmentCascade:
    """The batched cascade removes RAs + CMAs for a whole id list, leaving unrelated rows intact."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds one RA+CMA per batched object plus an unrelated RA+CMA, cleaned up after."""
        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

        risk_assessments.insert_many([
            {'public_id': BATCH_RA_IDS[0], 'object_id_ref_type': ObjectReferenceType.OBJECT.value,
             'object_id': BATCH_OBJECT_IDS[0]},
            {'public_id': BATCH_RA_IDS[1], 'object_id_ref_type': ObjectReferenceType.OBJECT.value,
             'object_id': BATCH_OBJECT_IDS[1]},
            {'public_id': BATCH_UNRELATED_RA_ID, 'object_id_ref_type': ObjectReferenceType.OBJECT.value,
             'object_id': BATCH_UNRELATED_OBJECT_ID},
        ])
        assignments.insert_many([
            {'public_id': BATCH_CMA_IDS[0], 'risk_assessment_id': BATCH_RA_IDS[0]},
            {'public_id': BATCH_CMA_IDS[1], 'risk_assessment_id': BATCH_RA_IDS[1]},
            {'public_id': BATCH_UNRELATED_CMA_ID, 'risk_assessment_id': BATCH_UNRELATED_RA_ID},
        ])
        yield
        risk_assessments.delete_many({'public_id': {'$in': BATCH_RA_IDS + [BATCH_UNRELATED_RA_ID]}})
        assignments.delete_many({'public_id': {'$in': BATCH_CMA_IDS + [BATCH_UNRELATED_CMA_ID]}})

    def test_batched_cascade_removes_all_targets_only(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Both batched objects' RAs + CMAs are deleted in one call; the unrelated pair survives."""
        objects_manager.delete_objects_from_risk_assessment_cascade(BATCH_OBJECT_IDS)

        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

        assert risk_assessments.count_documents({'public_id': {'$in': BATCH_RA_IDS}}) == 0
        assert assignments.count_documents({'public_id': {'$in': BATCH_CMA_IDS}}) == 0
        assert risk_assessments.find_one({'public_id': BATCH_UNRELATED_RA_ID}) is not None
        assert assignments.find_one({'public_id': BATCH_UNRELATED_CMA_ID}) is not None

    def test_batched_cascade_empty_list_is_noop(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An empty id list performs no delete."""
        objects_manager.delete_objects_from_risk_assessment_cascade([])

        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        assert risk_assessments.count_documents({'public_id': {'$in': BATCH_RA_IDS}}) == len(BATCH_RA_IDS)

    def test_batched_cascade_no_match_is_noop(self, objects_manager: ObjectsManager) -> None:
        """Ids with no RiskAssessments return cleanly without touching anything."""
        objects_manager.delete_objects_from_risk_assessment_cascade([LOOKUP_MISSING_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                     delete_object with a reused object_type                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def _reuse_type_doc(active: bool) -> dict[str, Any]:
    """Builds a minimal CmdbType doc (active flag configurable) for the delete_object reuse tests."""
    return {
        'public_id': REUSE_TYPE_ID,
        'name': 'reuse-type',
        'label': 'Reuse Type',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': active,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


class TestDeleteObjectTypeReuse:
    """delete_object uses a caller-supplied object_type instead of re-fetching it."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds an ACTIVE type + one object of it, removed after the test."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_reuse_type_doc(active=True))
        objects.insert_one(_object_doc(REUSE_OBJECT_ID, type_id=REUSE_TYPE_ID))
        yield
        types.delete_one({'public_id': REUSE_TYPE_ID})
        objects.delete_many({'public_id': REUSE_OBJECT_ID})

    def test_supplied_inactive_type_drives_the_deactivated_check(self, objects_manager: ObjectsManager) -> None:
        """A supplied INACTIVE type raises AccessDeniedError even though the STORED type is active."""
        inactive_type: CmdbType = CmdbType.from_data(_reuse_type_doc(active=False))

        with pytest.raises(AccessDeniedError):
            objects_manager.delete_object(REUSE_OBJECT_ID, object_type=inactive_type)

    def test_without_supplied_type_uses_stored_active_type(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """With no supplied type the stored (active) type is resolved and the object is deleted."""
        assert objects_manager.delete_object(REUSE_OBJECT_ID) is True

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        assert objects.find_one({'public_id': REUSE_OBJECT_ID}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                    __merge_mds_references sort robustness (B2)                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMergeMdsReferencesSortRobustness:
    """The reference-merge sort tolerates a None sort value instead of raising a TypeError."""

    def test_sort_with_none_values_does_not_raise(self, objects_manager: ObjectsManager) -> None:
        """Objects whose sort attribute is None sort to one end rather than crashing the merge."""
        obj_with_value: CmdbObject = CmdbObject.from_data(_object_doc(1))
        obj_with_none: CmdbObject = CmdbObject.from_data(_object_doc(2))
        obj_with_value.author_id = 5
        obj_with_none.author_id = None

        obj_result = SimpleNamespace(results=[obj_with_none, obj_with_value], total=2)

        # __merge_mds_references is name-mangled; no MDS results, sort by the mixed None/int attribute
        merged = objects_manager._ObjectsManager__merge_mds_references(  # pylint: disable=protected-access
            [], obj_result, 0, 0, 'author_id', 1,
        )

        assert merged.total == 2
        assert {obj.public_id for obj in merged.results} == {1, 2}


# -------------------------------------------------------------------------------------------------------------------- #
#                                    read helpers: grouping / field-sets / summaries                                  #
# -------------------------------------------------------------------------------------------------------------------- #
SUMMARY_TYPE_ID: int = 9861
SUMMARY_OBJECT_ID: int = 9862
GROUP_VALUE_OBJECT_IDS: list[int] = [9882, 9883]
GROUP_VALUE_TYPE_ID: int = 9884
REF_TARGET_TYPE_ID: int = 9891
REF_TARGET_OBJECT_ID: int = 9892
REF_SOURCE_TYPE_ID: int = 9893
REF_SOURCE_OBJECT_ID: int = 9894
REF_FIELD_NAME: str = 'ref-field'


def _full_type_doc(
    public_id: int,
    summary_fields: list[str] | None = None,
    extra_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a deserialisable CmdbType doc with an optional summary (field names) + extra fields."""
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}]
    if extra_fields:
        fields += extra_fields

    return {
        'public_id': public_id,
        'name': f'type-{public_id}',
        'label': f'Type {public_id}',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields,
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': summary_fields or []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


class TestGroupObjectsByValue:
    """group_objects_by_value groups access-verified objects by a field, sorted by count desc."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a type + two objects of it, removed after the test."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_full_type_doc(GROUP_VALUE_TYPE_ID))
        objects.insert_many([_object_doc(pid, type_id=GROUP_VALUE_TYPE_ID) for pid in GROUP_VALUE_OBJECT_IDS])
        yield
        types.delete_one({'public_id': GROUP_VALUE_TYPE_ID})
        objects.delete_many({'public_id': {'$in': GROUP_VALUE_OBJECT_IDS}})

    def test_groups_by_type_id(self, objects_manager: ObjectsManager) -> None:
        """The seeded type appears as a group whose count matches the seeded objects."""
        groups = objects_manager.group_objects_by_value('type_id', {'type_id': GROUP_VALUE_TYPE_ID})

        seeded = next(group for group in groups if group['_id'] == GROUP_VALUE_TYPE_ID)
        assert seeded['count'] == len(GROUP_VALUE_OBJECT_IDS)


class TestSummaryLines:
    """get_summary_line and get_summary_lines_lookup compose the type-label + summary-field line."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a type with a summary field + one object carrying that field's value."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_full_type_doc(SUMMARY_TYPE_ID, summary_fields=[NAME_FIELD]))
        objects.insert_one(_object_doc(SUMMARY_OBJECT_ID, value='hello', type_id=SUMMARY_TYPE_ID))
        yield
        types.delete_one({'public_id': SUMMARY_TYPE_ID})
        objects.delete_many({'public_id': SUMMARY_OBJECT_ID})

    def test_get_summary_line_includes_label_and_value(self, objects_manager: ObjectsManager) -> None:
        """The composed line carries the type label and the summary field value."""
        line = objects_manager.get_summary_line(SUMMARY_OBJECT_ID)

        assert 'hello' in line
        assert str(SUMMARY_OBJECT_ID) in line

    def test_get_summary_line_empty_public_id_returns_empty(self, objects_manager: ObjectsManager) -> None:
        """A falsy public_id yields the empty default line."""
        assert objects_manager.get_summary_line(0) == ""

    def test_lookup_resolves_requested_ids(self, objects_manager: ObjectsManager) -> None:
        """get_summary_lines_lookup returns a line for the requested (resolvable) id."""
        result = objects_manager.get_summary_lines_lookup([SUMMARY_OBJECT_ID])

        assert SUMMARY_OBJECT_ID in result
        assert 'hello' in result[SUMMARY_OBJECT_ID]

    def test_lookup_with_supplied_docs_skips_fetch(
        self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """When object_docs are supplied the per-id fetch is skipped and lines are still composed."""
        docs = list(database_manager.get_collection(CmdbObject.COLLECTION, database_name).find(
            {'public_id': SUMMARY_OBJECT_ID}
        ))

        result = objects_manager.get_summary_lines_lookup([SUMMARY_OBJECT_ID], object_docs=docs)

        assert SUMMARY_OBJECT_ID in result

    def test_lookup_empty_ids_returns_empty(self, objects_manager: ObjectsManager) -> None:
        """An empty id list short-circuits to an empty mapping."""
        assert objects_manager.get_summary_lines_lookup([]) == {}

    def test_unset_summary_value_yields_the_bare_prefix(
        self, objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Regression: an object whose summary field carries no value rendered as '#<id> - None'.

        Reproduces what the rack overview showed for a real object ('#264 - None'): the summary field
        exists on the type but the object's entry for it is unset.
        """
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        unset_object_id: int = SUMMARY_OBJECT_ID + 1
        doc = _object_doc(unset_object_id, value='x', type_id=SUMMARY_TYPE_ID)

        for field in doc['fields']:
            if field['name'] == NAME_FIELD:
                field['value'] = None

        objects.insert_one(doc)

        try:
            line = objects_manager.get_summary_line(unset_object_id, with_type=False)

            assert line == f'#{unset_object_id}'
            assert 'None' not in line
        finally:
            objects.delete_one({'public_id': unset_object_id})


class TestReferences:
    """references resolves the CmdbObjects that point at a given object via a ref field."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a target object + a source type/object whose ref field points at the target."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        types.insert_one(_full_type_doc(REF_TARGET_TYPE_ID))
        types.insert_one(_full_type_doc(
            REF_SOURCE_TYPE_ID,
            extra_fields=[{'type': 'ref', 'name': REF_FIELD_NAME, 'label': 'Ref', 'ref_types': [REF_TARGET_TYPE_ID]}],
        ))

        objects.insert_one(_object_doc(REF_TARGET_OBJECT_ID, type_id=REF_TARGET_TYPE_ID))

        source_doc = _object_doc(REF_SOURCE_OBJECT_ID, type_id=REF_SOURCE_TYPE_ID)
        source_doc['fields'].append({'type': 'ref', 'name': REF_FIELD_NAME, 'value': REF_TARGET_OBJECT_ID})
        objects.insert_one(source_doc)
        yield
        types.delete_many({'public_id': {'$in': [REF_TARGET_TYPE_ID, REF_SOURCE_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': [REF_TARGET_OBJECT_ID, REF_SOURCE_OBJECT_ID]}})

    def test_returns_the_referencing_object(self, objects_manager: ObjectsManager) -> None:
        """The source object that references the target is returned by references()."""
        target: CmdbObject = CmdbObject.from_data(
            objects_manager.get_object(REF_TARGET_OBJECT_ID, as_dict=True)
        )

        result = objects_manager.references(target, criteria=[], limit=0, skip=0, sort='public_id', order=1)

        assert REF_SOURCE_OBJECT_ID in {obj.public_id for obj in result.results}
