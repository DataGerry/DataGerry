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
Unit tests for cmdb.manager.object_groups_manager.ObjectGroupsManager

Pure tests: no Mongo. The generic CRUD is GenericManager's and is covered there; what is pinned here is
the manager's own two write paths:

  - **the delete cascade removes ISMS documents, not just references.** Every IsmsRiskAssessment that
    assesses the group is deleted, and with it every IsmsControlMeasureAssignment belonging to those
    assessments - a far heavier cascade than the person one, and the reason its filter naming
    ``ObjectReferenceType.OBJECT_GROUP`` matters: without that half, an assessment of the *object* with
    the same public_id would be deleted too
  - the cascade is skipped entirely when no assessment matches, so deleting an unreferenced group is
    one query and one delete
  - **``remove_ids_from_groups`` is mode-scoped.** Deleting objects cleans the STATIC groups, deleting
    a type cleans the DYNAMIC ones, and the call has to say which - the two hold different kinds of id
    in the same key
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_group_model import ObjectGroupKey, ObjectGroupMode, ObjectReferenceType
from cmdb.errors.manager.object_groups_manager import ObjectGroupsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'
GROUP_ID: int = 4
ASSESSMENT_IDS: list[int] = [11, 12]


def _stub() -> MagicMock:
    """An ObjectGroupsManager stub carrying the attributes its own methods read"""
    manager = MagicMock(spec=ObjectGroupsManager)
    manager.dbm = MagicMock()
    manager.db_name = DB_NAME
    manager.dbm.find.return_value = [
        {RiskAssessmentKey.PUBLIC_ID.value: assessment_id} for assessment_id in ASSESSMENT_IDS
    ]

    return manager


class TestDeleteWithFollowUp:
    """The cascade, its ordering and its error wrapping."""

    def test_deletes_the_assessments_before_the_group(self) -> None:
        """
        The group goes last, so an interrupted cascade can be repeated

        Deleting the group first would leave assessments referencing an id that no longer resolves,
        with nothing left to find them by.
        """
        manager = _stub()
        order: list[str] = []
        manager.delete_object_group_from_risk_assessment_cascade.side_effect = (
            lambda *_: order.append('cascade')
        )
        manager.delete_item.side_effect = lambda *_: order.append('delete') or True

        ObjectGroupsManager.delete_with_follow_up(manager, GROUP_ID)

        assert order == ['cascade', 'delete']

    def test_a_failing_cascade_surfaces_as_the_managers_delete_error(self) -> None:
        """The route maps this error to a 400; an unwrapped pymongo error would reach it as a 500."""
        manager = _stub()
        manager.delete_object_group_from_risk_assessment_cascade.side_effect = RuntimeError('boom')

        with pytest.raises(ObjectGroupsManagerDeleteError):
            ObjectGroupsManager.delete_with_follow_up(manager, GROUP_ID)

        manager.delete_item.assert_not_called()

    def test_the_original_error_survives_as_the_cause(self) -> None:
        """
        The wrapper carries the error itself rather than a string of it

        str() reads the same either way, but the type and detail are only there for whoever inspects
        the wrapper if the error object is kept.
        """
        manager = _stub()
        original = RuntimeError('boom')
        manager.delete_object_group_from_risk_assessment_cascade.side_effect = original

        with pytest.raises(ObjectGroupsManagerDeleteError) as caught:
            ObjectGroupsManager.delete_with_follow_up(manager, GROUP_ID)

        assert caught.value.__cause__ is original


class TestRiskAssessmentCascade:
    """Which ISMS documents go with a deleted group."""

    def test_selects_the_assessments_by_id_and_reference_type(self) -> None:
        """
        Both halves of the filter, for the same reason the person cascades pair theirs

        An IsmsRiskAssessment's object_id holds either a CmdbObject or a CmdbObjectGroup; without the
        ref_type half, deleting group 4 would delete the assessments of object 4.
        """
        manager = _stub()

        ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade(manager, GROUP_ID)

        assert manager.dbm.find.call_args.args[2] == {
            RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: ObjectReferenceType.OBJECT_GROUP.value,
            RiskAssessmentKey.OBJECT_ID.value: GROUP_ID,
        }

    def test_reads_only_the_ids_it_needs(self) -> None:
        """Projected to public_id: the cascade needs the ids, not the assessments themselves."""
        manager = _stub()

        ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade(manager, GROUP_ID)

        assert manager.dbm.find.call_args.kwargs['projection'] == {RiskAssessmentKey.PUBLIC_ID.value: 1}

    def test_deletes_the_assessments_and_their_assignments(self) -> None:
        """
        Two bulk deletes keyed on the same id list

        The assignments are found by the assessments they belong to, which is why the assessment ids
        have to be read before anything is deleted.
        """
        manager = _stub()

        ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade(manager, GROUP_ID)

        deletes: list[tuple[Any, ...]] = [call.args for call in manager.delete_many_from_other_collection.call_args_list]

        assert deletes == [
            (
                IsmsRiskAssessment.COLLECTION,
                {RiskAssessmentKey.PUBLIC_ID.value: {'$in': ASSESSMENT_IDS}},
            ),
            (
                IsmsControlMeasureAssignment.COLLECTION,
                {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {'$in': ASSESSMENT_IDS}},
            ),
        ]

    def test_deletes_nothing_when_no_assessment_references_the_group(self) -> None:
        """The common case: an unreferenced group costs one query and no deletes."""
        manager = _stub()
        manager.dbm.find.return_value = []

        ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade(manager, GROUP_ID)

        manager.delete_many_from_other_collection.assert_not_called()


class TestRemoveIdsFromGroups:
    """The cleanup both the object delete and the type delete run."""

    def test_pulls_a_single_id_from_the_groups_of_the_given_mode(self) -> None:
        """A type delete passes one id and DYNAMIC, since a type is only ever in dynamic groups."""
        manager = _stub()

        ObjectGroupsManager.remove_ids_from_groups(manager, 8, ObjectGroupMode.DYNAMIC)

        manager.update_many_pull.assert_called_once_with(
            criteria={
                ObjectGroupKey.GROUP_TYPE.value: ObjectGroupMode.DYNAMIC.value,
                ObjectGroupKey.ASSIGNED_IDS.value: 8,
            },
            update={ObjectGroupKey.ASSIGNED_IDS.value: 8},
        )

    def test_pulls_a_list_of_ids_with_an_in_filter(self) -> None:
        """An object delete may pass many ids at once, and pulls them all in one update."""
        manager = _stub()

        ObjectGroupsManager.remove_ids_from_groups(manager, [8, 9], ObjectGroupMode.STATIC)

        manager.update_many_pull.assert_called_once_with(
            criteria={
                ObjectGroupKey.GROUP_TYPE.value: ObjectGroupMode.STATIC.value,
                ObjectGroupKey.ASSIGNED_IDS.value: {'$in': [8, 9]},
            },
            update={ObjectGroupKey.ASSIGNED_IDS.value: {'$in': [8, 9]}},
        )

    def test_filters_the_mode_as_a_plain_string(self) -> None:
        """
        The stored documents hold plain strings, and the schema now refuses anything but these two

        A group stored with a third value would be reachable by neither of the two cleanups, which is
        what the schema rule exists to prevent.
        """
        manager = _stub()

        ObjectGroupsManager.remove_ids_from_groups(manager, 8, ObjectGroupMode.STATIC)

        assert manager.update_many_pull.call_args.kwargs['criteria'][
            ObjectGroupKey.GROUP_TYPE.value
        ] == 'STATIC'
