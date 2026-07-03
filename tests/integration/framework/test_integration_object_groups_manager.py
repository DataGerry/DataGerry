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
Integration tests for the ObjectGroupsManager database-backed follow-up methods.

Covers ``remove_ids_from_groups`` (``$pull`` of CmdbObject/CmdbType public_ids from the
``assigned_ids`` of every group of a given ObjectGroupMode, single value and list, with STATIC /
DYNAMIC scoping), ``delete_object_group_from_risk_assessment_cascade`` (drops every RiskAssessment
that references the deleted group plus the ControlMeasureAssignments hanging off those assessments,
and the no-match early return), and ``delete_with_follow_up`` (the cascade followed by the group
delete itself).
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectGroupMode, ObjectReferenceType
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.errors.manager.object_groups_manager import ObjectGroupsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

STATIC_GROUP_ID: int = 95601
DYNAMIC_GROUP_ID: int = 95602

RISK_ASSESSMENT_ID: int = 95611
OTHER_RISK_ASSESSMENT_ID: int = 95612

CMA_ID: int = 95621
OTHER_CMA_ID: int = 95622

ALL_GROUP_IDS: list[int] = [STATIC_GROUP_ID, DYNAMIC_GROUP_ID]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID, OTHER_RISK_ASSESSMENT_ID]
ALL_CMA_IDS: list[int] = [CMA_ID, OTHER_CMA_ID]


@pytest.fixture(name='object_groups_manager')
def fixture_object_groups_manager(database_manager: MongoDatabaseManager) -> ObjectGroupsManager:
    """Provides an ObjectGroupsManager wired to the test database."""
    return ObjectGroupsManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any groups / risk assessments / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CMA_IDS}})

    _purge()
    yield
    _purge()


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _group(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Returns a seeded CmdbObjectGroup document."""
    return database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


def _seed_group(database_manager: MongoDatabaseManager, database_name: str,
                public_id: int, group_type: ObjectGroupMode, assigned_ids: list[int]) -> None:
    """Seeds a CmdbObjectGroup document with the given membership mode and assigned ids."""
    _insert(database_manager, database_name, CmdbObjectGroup.COLLECTION, {
        'public_id': public_id,
        'name': f'Group-{public_id}',
        'group_type': group_type,
        'assigned_ids': assigned_ids,
        'categories': [],
    })


class TestRemoveIdsFromGroups:
    """remove_ids_from_groups $pulls the given public_id(s) from the matching group_type only."""

    def test_removes_single_id_from_static_groups_only(self, object_groups_manager: ObjectGroupsManager,
                                                        database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
        """A single id is pulled from STATIC groups while a DYNAMIC group with the same id is untouched."""
        _seed_group(database_manager, database_name, STATIC_GROUP_ID, ObjectGroupMode.STATIC, [1, 2, 3])
        _seed_group(database_manager, database_name, DYNAMIC_GROUP_ID, ObjectGroupMode.DYNAMIC, [1, 2, 3])

        object_groups_manager.remove_ids_from_groups(2, ObjectGroupMode.STATIC)

        assert _group(database_manager, database_name, STATIC_GROUP_ID)['assigned_ids'] == [1, 3]
        assert _group(database_manager, database_name, DYNAMIC_GROUP_ID)['assigned_ids'] == [1, 2, 3]

    def test_removes_list_of_ids(self, object_groups_manager: ObjectGroupsManager,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A list of ids is pulled from every matching STATIC group in a single call."""
        _seed_group(database_manager, database_name, STATIC_GROUP_ID, ObjectGroupMode.STATIC, [1, 2, 3, 4])

        object_groups_manager.remove_ids_from_groups([1, 3], ObjectGroupMode.STATIC)

        assert _group(database_manager, database_name, STATIC_GROUP_ID)['assigned_ids'] == [2, 4]

    def test_scopes_to_dynamic_groups(self, object_groups_manager: ObjectGroupsManager,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Passing DYNAMIC only affects DYNAMIC groups, leaving STATIC groups untouched."""
        _seed_group(database_manager, database_name, STATIC_GROUP_ID, ObjectGroupMode.STATIC, [7, 8])
        _seed_group(database_manager, database_name, DYNAMIC_GROUP_ID, ObjectGroupMode.DYNAMIC, [7, 8])

        object_groups_manager.remove_ids_from_groups(7, ObjectGroupMode.DYNAMIC)

        assert _group(database_manager, database_name, STATIC_GROUP_ID)['assigned_ids'] == [7, 8]
        assert _group(database_manager, database_name, DYNAMIC_GROUP_ID)['assigned_ids'] == [8]


class TestDeleteCascade:
    """delete_object_group_from_risk_assessment_cascade removes referencing RAs and their CMAs."""

    def _seed_referencing_graph(self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Seeds a RA referencing the group (+ its CMA) and an unrelated RA (+ its CMA) that must survive."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'object_id_ref_type': ObjectReferenceType.OBJECT_GROUP,
            'object_id': STATIC_GROUP_ID,
        })
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': OTHER_RISK_ASSESSMENT_ID,
            'object_id_ref_type': ObjectReferenceType.OBJECT,
            'object_id': STATIC_GROUP_ID,
        })
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, {
            'public_id': CMA_ID,
            'risk_assessment_id': RISK_ASSESSMENT_ID,
        })
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, {
            'public_id': OTHER_CMA_ID,
            'risk_assessment_id': OTHER_RISK_ASSESSMENT_ID,
        })

    def _exists(self, database_manager: MongoDatabaseManager, database_name: str,
                collection: str, public_id: int) -> bool:
        """Returns whether a document with the given public_id exists in the collection."""
        return database_manager.get_collection(collection, database_name)\
            .find_one({'public_id': public_id}) is not None

    def test_deletes_referencing_ra_and_its_cma(self, object_groups_manager: ObjectGroupsManager,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """The RA referencing the group and its CMA are deleted; unrelated RA/CMA survive."""
        self._seed_referencing_graph(database_manager, database_name)

        object_groups_manager.delete_object_group_from_risk_assessment_cascade(STATIC_GROUP_ID)

        assert not self._exists(database_manager, database_name, IsmsRiskAssessment.COLLECTION, RISK_ASSESSMENT_ID)
        assert not self._exists(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CMA_ID)
        assert self._exists(database_manager, database_name,
                            IsmsRiskAssessment.COLLECTION, OTHER_RISK_ASSESSMENT_ID)
        assert self._exists(database_manager, database_name,
                            IsmsControlMeasureAssignment.COLLECTION, OTHER_CMA_ID)

    def test_no_matching_risk_assessments_is_a_noop(self, object_groups_manager: ObjectGroupsManager,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """With no RA referencing the group, the cascade returns without touching any collection."""
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, {
            'public_id': CMA_ID,
            'risk_assessment_id': RISK_ASSESSMENT_ID,
        })

        object_groups_manager.delete_object_group_from_risk_assessment_cascade(DYNAMIC_GROUP_ID)

        assert self._exists(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CMA_ID)


class TestDeleteWithFollowUp:
    """delete_with_follow_up runs the cascade and then deletes the group itself."""

    def test_deletes_group_and_cascade(self, object_groups_manager: ObjectGroupsManager,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The group, its referencing RA and that RA's CMA are all gone after the call."""
        _seed_group(database_manager, database_name, STATIC_GROUP_ID, ObjectGroupMode.STATIC, [1])
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'object_id_ref_type': ObjectReferenceType.OBJECT_GROUP,
            'object_id': STATIC_GROUP_ID,
        })
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, {
            'public_id': CMA_ID,
            'risk_assessment_id': RISK_ASSESSMENT_ID,
        })

        result = object_groups_manager.delete_with_follow_up(STATIC_GROUP_ID)

        assert result is True
        assert _group(database_manager, database_name, STATIC_GROUP_ID) is None
        assert database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .find_one({'public_id': RISK_ASSESSMENT_ID}) is None
        assert database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CMA_ID}) is None

    def test_wraps_failure_in_delete_error(self, object_groups_manager: ObjectGroupsManager,
                                           monkeypatch) -> None:
        """A failure anywhere in the follow-up (here the cascade) surfaces as ObjectGroupsManagerDeleteError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('cascade failed')

        monkeypatch.setattr(object_groups_manager, 'delete_object_group_from_risk_assessment_cascade', _boom)

        with pytest.raises(ObjectGroupsManagerDeleteError):
            object_groups_manager.delete_with_follow_up(STATIC_GROUP_ID)
