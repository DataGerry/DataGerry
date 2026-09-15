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
Unit tests for cmdb.manager.persons_manager and cmdb.manager.person_groups_manager

Pure tests: no Mongo. **One module for the two managers on purpose.** They are mirror images - the same
two-sided membership seen from each end, and the same ISMS cleanup for a deleted reference target - so
the shared rules are asserted once against a ``_Side`` describing the manager, and what belongs to one
side only gets its own test.

What is pinned here:

  - **the delete cascade is complete and ordered.** Clearing the ISMS references and removing the
    entity from the counterpart collection both happen BEFORE the document is deleted. The counterpart
    step used to be a second call made by the delete route, so a person deleted through any other path
    stayed listed in every group
  - the cascade's failure surfaces as the manager's own delete error, rather than as whatever pymongo
    raised
  - the reciprocal membership methods forward to the shared helper with this side's collection and
    array key - the pairing that a copy-paste between the twins would get wrong
  - **the assessor and the interviewed persons are the person's alone**: a group is never either, and
    asserting it here is what keeps a later "harmonisation" of the twins from adding them
"""
from typing import Any, Callable, NamedTuple
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey, PersonReferenceType
from cmdb.errors.manager.persons_manager import PersonsManagerDeleteError
from cmdb.errors.manager.person_groups_manager import PersonGroupsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

PERSONS_PATH: str = 'cmdb.manager.persons_manager'
PERSON_GROUPS_PATH: str = 'cmdb.manager.person_groups_manager'
DB_NAME: str = 'testdb'
ENTITY_ID: int = 7


class _Side(NamedTuple):
    """One half of the person / person-group pair, and everything a shared test needs to address it"""
    manager: type
    module_path: str
    own_collection: str
    own_array_key: str
    counterpart_collection: str
    counterpart_array_key: str
    reference_type: PersonReferenceType
    delete_error: type[Exception]
    cascade_step_names: tuple[str, str, str]
    clear_risk_assessments: Callable[[Any, int], None]
    clear_assignments: Callable[[Any, int], None]
    remove_from_counterpart: Callable[[Any, int], None]
    add_to_documents: Callable[[Any, int, Any], None]
    remove_from_documents: Callable[[Any, int, Any], None]


SIDES: list[_Side] = [
    _Side(
        PersonsManager,
        PERSONS_PATH,
        CmdbPerson.COLLECTION,
        PersonKey.GROUPS.value,
        CmdbPersonGroup.COLLECTION,
        PersonGroupKey.GROUP_MEMBERS.value,
        PersonReferenceType.PERSON,
        PersonsManagerDeleteError,
        (
            'remove_person_from_risk_assessments',
            'remove_person_from_control_measure_assignments',
            'remove_person_from_person_groups',
        ),
        PersonsManager.remove_person_from_risk_assessments,
        PersonsManager.remove_person_from_control_measure_assignments,
        PersonsManager.remove_person_from_person_groups,
        PersonsManager.add_group_to_persons,
        PersonsManager.delete_group_from_persons,
    ),
    _Side(
        PersonGroupsManager,
        PERSON_GROUPS_PATH,
        CmdbPersonGroup.COLLECTION,
        PersonGroupKey.GROUP_MEMBERS.value,
        CmdbPerson.COLLECTION,
        PersonKey.GROUPS.value,
        PersonReferenceType.PERSON_GROUP,
        PersonGroupsManagerDeleteError,
        (
            'remove_person_group_from_risk_assessments',
            'remove_person_group_from_control_measure_assignments',
            'remove_person_group_from_persons',
        ),
        PersonGroupsManager.remove_person_group_from_risk_assessments,
        PersonGroupsManager.remove_person_group_from_control_measure_assignments,
        PersonGroupsManager.remove_person_group_from_persons,
        PersonGroupsManager.add_person_to_groups,
        PersonGroupsManager.delete_person_from_groups,
    ),
]

SIDE_IDS: list[str] = [side.manager.__name__ for side in SIDES]


def _stub(side: _Side) -> MagicMock:
    """A manager stub carrying the three attributes the cascade methods read"""
    manager = MagicMock(spec=side.manager)
    manager.dbm = MagicMock()
    manager.db_name = DB_NAME
    manager.collection = side.own_collection

    return manager


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestDeleteCascade:
    """What deleting one half of the pair entails, and in which order."""

    def test_clears_every_reference_before_deleting_the_document(self, side: _Side) -> None:
        """
        The document goes last, so an interrupted cascade leaves it in place

        The opposite order would leave references to an entity that no longer exists and no way to
        find them again; this way the next attempt simply repeats the whole cascade.
        """
        manager = _stub(side)
        order: list[str] = []

        for step_name in side.cascade_step_names:
            getattr(manager, step_name).side_effect = (
                lambda *_, step=step_name: order.append(step)
            )

        manager.delete_item.side_effect = lambda *_: order.append('delete') or True

        side.manager.delete_with_follow_up(manager, ENTITY_ID)

        assert order.index('delete') == len(order) - 1
        assert set(side.cascade_step_names) <= set(order)

    def test_removes_the_entity_from_the_counterpart_collection(self, side: _Side) -> None:
        """
        The half that used to live in the delete route

        Any caller other than that route - a bulk delete, an importer, a future route - left the
        deleted entity listed on every counterpart document.
        """
        manager = _stub(side)

        side.manager.delete_with_follow_up(manager, ENTITY_ID)

        getattr(manager, side.cascade_step_names[2]).assert_called_once_with(ENTITY_ID)

    def test_returns_what_the_delete_reported(self, side: _Side) -> None:
        """The cascade does not swallow a delete that matched no document."""
        manager = _stub(side)
        manager.delete_item.return_value = False

        assert side.manager.delete_with_follow_up(manager, ENTITY_ID) is False

    def test_a_failing_cascade_step_surfaces_as_the_managers_delete_error(self, side: _Side) -> None:
        """
        The cascade was unwrapped on both person managers while its ObjectGroup twin was wrapped

        The same pymongo failure therefore reached the route as a mapped 400 for one entity and as an
        unmapped 500 for the other two.
        """
        manager = _stub(side)
        getattr(manager, side.cascade_step_names[0]).side_effect = RuntimeError('boom')

        with pytest.raises(side.delete_error):
            side.manager.delete_with_follow_up(manager, ENTITY_ID)

        manager.delete_item.assert_not_called()

    def test_the_original_error_survives_as_the_cause(self, side: _Side) -> None:
        """A wrapper that loses the pymongo error loses the only description of what went wrong."""
        manager = _stub(side)
        original = RuntimeError('boom')
        getattr(manager, side.cascade_step_names[0]).side_effect = original

        with pytest.raises(side.delete_error) as caught:
            side.manager.delete_with_follow_up(manager, ENTITY_ID)

        assert caught.value.__cause__ is original


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestReciprocalMembership:
    """The add / remove pair, and the collection each side writes."""

    def test_adds_to_its_own_collection_under_its_own_array_key(self, side: _Side) -> None:
        """
        The pairing a copy-paste between the twins gets wrong

        PersonsManager maintains 'groups' on management.person; PersonGroupsManager maintains
        'group_members' on management.personGroup. Swapping either half writes into a key that does
        not exist.
        """
        manager = _stub(side)

        with patch(f'{side.module_path}.add_member_to_documents') as mock_add:
            side.add_to_documents(manager, ENTITY_ID, [1, 2])

        assert mock_add.call_args.args[2] == side.own_collection
        assert mock_add.call_args.args[3] == side.own_array_key
        assert mock_add.call_args.args[4] == ENTITY_ID
        assert mock_add.call_args.args[5] == [1, 2]

    def test_removes_from_its_own_collection_under_its_own_array_key(self, side: _Side) -> None:
        """The mirror of the add, including the optional selection passed straight through."""
        manager = _stub(side)

        with patch(f'{side.module_path}.remove_member_from_documents') as mock_remove:
            side.remove_from_documents(manager, ENTITY_ID, [3])

        assert mock_remove.call_args.args[2] == side.own_collection
        assert mock_remove.call_args.args[3] == side.own_array_key
        assert mock_remove.call_args.args[5] == [3]

    def test_the_counterpart_cleanup_writes_the_other_collection(self, side: _Side) -> None:
        """
        Written directly rather than through the other manager, which a manager must not depend on

        It is still the same helper, so the two directions cannot drift apart.
        """
        manager = _stub(side)

        with patch(f'{side.module_path}.remove_member_from_documents') as mock_remove:
            side.remove_from_counterpart(manager, ENTITY_ID)

        assert mock_remove.call_args.args[2] == side.counterpart_collection
        assert mock_remove.call_args.args[3] == side.counterpart_array_key


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestIsmsReferenceCleanup:
    """Which ISMS references each side clears, and as which reference type."""

    def test_clears_the_polymorphic_assessment_fields_as_its_own_reference_type(self, side: _Side) -> None:
        """Each side identifies itself, so the other's references are never touched."""
        manager = _stub(side)

        with patch(f'{side.module_path}.clear_polymorphic_risk_assessment_references') as mock_clear:
            side.clear_risk_assessments(manager, ENTITY_ID)

        assert mock_clear.call_args.args[2] == IsmsRiskAssessment.COLLECTION
        assert mock_clear.call_args.args[3] == ENTITY_ID
        assert mock_clear.call_args.args[4] is side.reference_type

    def test_clears_the_assignment_reference_as_its_own_reference_type(self, side: _Side) -> None:
        """The single polymorphic field of the assignment, same rule."""
        manager = _stub(side)

        with patch(f'{side.module_path}.clear_control_measure_assignment_reference') as mock_clear:
            side.clear_assignments(manager, ENTITY_ID)

        assert mock_clear.call_args.args[2] == IsmsControlMeasureAssignment.COLLECTION
        assert mock_clear.call_args.args[3] == ENTITY_ID
        assert mock_clear.call_args.args[4] is side.reference_type


class TestWhatOnlyAPersonCanBe:
    """The two assessment references a CmdbPersonGroup can never hold."""

    def test_the_assessor_is_nulled_without_asking_for_a_reference_type(self) -> None:
        """
        'risk_assessor_id' can only ever be a person, so there is no ref_type sibling to filter on

        Filtering on one anyway would clear nothing, since the key does not exist on the document.
        """
        manager = _stub(SIDES[0])

        with patch(f'{PERSONS_PATH}.clear_polymorphic_risk_assessment_references'), \
             patch(f'{PERSONS_PATH}.remove_member_from_documents'):
            PersonsManager.remove_person_from_risk_assessments(manager, ENTITY_ID)

        manager.dbm.update_many.assert_called_once_with(
            IsmsRiskAssessment.COLLECTION,
            DB_NAME,
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: ENTITY_ID},
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: None},
        )

    def test_the_person_is_pulled_out_of_the_interviewed_persons_list(self) -> None:
        """
        A list of persons, so the reference is removed rather than nulled

        Nulling an entry would leave a hole in the list; the assessment simply has one interviewee
        fewer.
        """
        manager = _stub(SIDES[0])

        with patch(f'{PERSONS_PATH}.clear_polymorphic_risk_assessment_references'), \
             patch(f'{PERSONS_PATH}.remove_member_from_documents') as mock_remove:
            PersonsManager.remove_person_from_risk_assessments(manager, ENTITY_ID)

        assert mock_remove.call_args.args[2] == IsmsRiskAssessment.COLLECTION
        assert mock_remove.call_args.args[3] == RiskAssessmentKey.INTERVIEWED_PERSONS.value

    def test_a_person_group_touches_neither_of_them(self) -> None:
        """
        The twins are not symmetric here, and the difference is deliberate

        A group is never the assessor and never appears among the interviewed persons, so its cascade
        has two steps where the person's has four.
        """
        manager = _stub(SIDES[1])

        with patch(f'{PERSON_GROUPS_PATH}.clear_polymorphic_risk_assessment_references'):
            PersonGroupsManager.remove_person_group_from_risk_assessments(manager, ENTITY_ID)

        manager.dbm.update_many.assert_not_called()
        manager.dbm.update_many_pull.assert_not_called()
