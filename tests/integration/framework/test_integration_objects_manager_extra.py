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
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
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


def _object_doc(public_id: int, value: str = 'x', mds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a complete CmdbObject doc (deserialisable via CmdbObject.from_data)."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
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
