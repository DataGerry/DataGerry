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
    step belongs here rather than in the delete route, where a person deleted through any other path
    stayed listed in every group
  - a cascade step's database failure surfaces as the manager's own delete error; a programming error
    propagates as itself
  - the cascade's counterpart cleanup writes the OTHER collection under the other side's array key - the
    pairing that a copy-paste between the twins would get wrong. A create or update writes the other side
    in the route layer (``person_membership_helper.sync_membership``), not through these managers
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
from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.errors.manager.persons_manager import PersonsManagerDeleteError
from cmdb.errors.manager.person_groups_manager import PersonGroupsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

PERSONS_PATH: str = 'cmdb.manager.persons_manager'
PERSON_GROUPS_PATH: str = 'cmdb.manager.person_groups_manager'
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
    ),
]

SIDE_IDS: list[str] = [side.manager.__name__ for side in SIDES]


def _stub(side: _Side) -> MagicMock:
    """A manager stub of one side: the cascade writes through its own (mocked) update methods"""
    manager = MagicMock(spec=side.manager)
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
        The half that belongs to the manager rather than the delete route

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

    @pytest.mark.parametrize('step', [0, 1, 2], ids=['risk_assessments', 'control_measures', 'counterpart'])
    def test_a_failing_cascade_step_surfaces_as_the_managers_delete_error(self, side: _Side, step: int) -> None:
        """
        Every cascade step writes through the manager's own update methods, so its typed failure is wrapped

        The route maps the manager's delete error to a 400, and the document is left in place.
        """
        manager = _stub(side)
        original = BaseManagerUpdateError('boom')
        getattr(manager, side.cascade_step_names[step]).side_effect = original

        with pytest.raises(side.delete_error) as caught:
            side.manager.delete_with_follow_up(manager, ENTITY_ID)

        assert caught.value.__cause__ is original
        manager.delete_item.assert_not_called()

    def test_a_bug_in_a_cascade_step_propagates_as_itself(self, side: _Side) -> None:
        """A programming error is not a database failure: it reaches the route's 500 unwrapped"""
        manager = _stub(side)
        getattr(manager, side.cascade_step_names[0]).side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            side.manager.delete_with_follow_up(manager, ENTITY_ID)

        manager.delete_item.assert_not_called()

    def test_the_documents_own_delete_error_is_not_wrapped_again(self, side: _Side) -> None:
        """delete_item already answers the manager's typed error, so it passes through as itself"""
        manager = _stub(side)
        original = side.delete_error('boom')
        manager.delete_item.side_effect = original

        with pytest.raises(side.delete_error) as caught:
            side.manager.delete_with_follow_up(manager, ENTITY_ID)

        assert caught.value is original


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestCounterpartCleanup:
    """The delete cascade's write into the other side of the membership."""

    def test_the_counterpart_cleanup_writes_the_other_collection(self, side: _Side) -> None:
        """
        Written directly rather than through the other manager, which a manager must not depend on

        It is still the same helper, so the two directions cannot drift apart.
        """
        manager = _stub(side)

        with patch(f'{side.module_path}.remove_member_from_documents') as mock_remove:
            side.remove_from_counterpart(manager, ENTITY_ID)

        assert mock_remove.call_args.args[0] is manager
        assert mock_remove.call_args.args[1] == side.counterpart_collection
        assert mock_remove.call_args.args[2] == side.counterpart_array_key
        assert mock_remove.call_args.args[3] == ENTITY_ID

    def test_the_counterpart_cleanup_reaches_every_listing_document(self, side: _Side) -> None:
        """No selection is passed: the member is pulled from every document of the other side that lists it."""
        manager = _stub(side)

        with patch(f'{side.module_path}.remove_member_from_documents') as mock_remove:
            side.remove_from_counterpart(manager, ENTITY_ID)

        assert len(mock_remove.call_args.args) == 4
        assert 'document_ids' not in mock_remove.call_args.kwargs

    def test_the_managers_offer_no_second_sync_path(self, side: _Side) -> None:
        """The create / update sync lives in the route layer only, where the ledger records its undo."""
        retired = {'update_group_in_persons', 'add_group_to_persons', 'delete_group_from_persons',
                   'update_person_in_groups', 'add_person_to_groups', 'delete_person_from_groups'}

        assert not retired & set(dir(side.manager))


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestIsmsReferenceCleanup:
    """Which ISMS references each side clears, and as which reference type."""

    def test_clears_the_polymorphic_assessment_fields_as_its_own_reference_type(self, side: _Side) -> None:
        """Each side identifies itself, so the other's references are never touched."""
        manager = _stub(side)

        with patch(f'{side.module_path}.clear_polymorphic_risk_assessment_references') as mock_clear:
            side.clear_risk_assessments(manager, ENTITY_ID)

        assert mock_clear.call_args.args[1] == IsmsRiskAssessment.COLLECTION
        assert mock_clear.call_args.args[2] == ENTITY_ID
        assert mock_clear.call_args.args[3] is side.reference_type

    def test_clears_the_assignment_reference_as_its_own_reference_type(self, side: _Side) -> None:
        """The single polymorphic field of the assignment, same rule."""
        manager = _stub(side)

        with patch(f'{side.module_path}.clear_control_measure_assignment_reference') as mock_clear:
            side.clear_assignments(manager, ENTITY_ID)

        assert mock_clear.call_args.args[1] == IsmsControlMeasureAssignment.COLLECTION
        assert mock_clear.call_args.args[2] == ENTITY_ID
        assert mock_clear.call_args.args[3] is side.reference_type


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

        manager.update_many.assert_called_once_with(
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: ENTITY_ID},
            {RiskAssessmentKey.RISK_ASSESSOR_ID.value: None},
            collection=IsmsRiskAssessment.COLLECTION,
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

        assert mock_remove.call_args.args[1] == IsmsRiskAssessment.COLLECTION
        assert mock_remove.call_args.args[2] == RiskAssessmentKey.INTERVIEWED_PERSONS.value

    def test_a_person_group_touches_neither_of_them(self) -> None:
        """
        The twins are not symmetric here, and the difference is deliberate

        A group is never the assessor and never appears among the interviewed persons, so its cascade
        has two steps where the person's has four.
        """
        manager = _stub(SIDES[1])

        with patch(f'{PERSON_GROUPS_PATH}.clear_polymorphic_risk_assessment_references'):
            PersonGroupsManager.remove_person_group_from_risk_assessments(manager, ENTITY_ID)

        manager.update_many.assert_not_called()
        manager.update_many_raw.assert_not_called()
