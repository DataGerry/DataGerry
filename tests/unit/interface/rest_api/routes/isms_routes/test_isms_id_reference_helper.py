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
Unit tests for isms_id_reference_helper: the id lists an ISMS write names are stored, and named once

Pure tests against a MagicMock manager whose ``get_many_from_other_collection`` answers per collection. Pinned: a
repeated id is refused before anything is read; every unknown id is named with its field (and, in a bulk, its
category) in one 400; each referenced collection is read once; a failed read is its own 400. The module's function
set is pinned
"""
import inspect
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.isms_model import IsmsImpact, IsmsProtectionGoal, IsmsThreat, IsmsVulnerability
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.isms_routes import isms_id_reference_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    REFERENCE_LOOKUP_FAILED_MSG,
    REPEATED_REFERENCED_IDS_MSG,
    UNKNOWN_REFERENCED_IDS_MSG,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_id_reference_helper import (
    bulk_category_entity,
    described_impact_ids,
    guard_impact_description_ids,
    guard_risk_references,
    id_reasons,
    read_missing_ids,
    repeated_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

THREAT_A: int = 11
THREAT_B: int = 12
MISSING_THREAT: int = 19
VULNERABILITY: int = 21
MISSING_VULNERABILITY: int = 29
GOAL: int = 31
IMPACT_A: int = 41
IMPACT_B: int = 42
MISSING_IMPACT: int = 49
CATEGORY_A: int = 51
CATEGORY_B: int = 52
STORED: dict[str, list[int]] = {
    IsmsThreat.COLLECTION: [THREAT_A, THREAT_B],
    IsmsVulnerability.COLLECTION: [VULNERABILITY],
    IsmsProtectionGoal.COLLECTION: [GOAL],
    IsmsImpact.COLLECTION: [IMPACT_A, IMPACT_B],
}


def _manager() -> MagicMock:
    """A manager answering, per collection, the stored ids among the asked ones"""
    manager = MagicMock()
    manager.get_many_from_other_collection.side_effect = lambda collection, projection, criteria: [
        {'public_id': public_id} for public_id in STORED[collection] if public_id in criteria['public_id']['$in']
    ]

    return manager


def _risk(threats: list[int] | None = None, vulnerabilities: list[int] | None = None,
          goals: list[int] | None = None) -> dict[str, Any]:
    """A Risk payload naming the given ids"""
    return {'threats': threats or [], 'vulnerabilities': vulnerabilities or [], 'protection_goals': goals or []}


def _category(*impact_ids: int) -> dict[str, Any]:
    """An ImpactCategory payload describing the given Impacts"""
    return {'impact_descriptions': [{'impact_id': impact_id, 'value': str(impact_id)} for impact_id in impact_ids]}


def _refusal(call: Any) -> HTTPException:
    """The HTTPException a call raises"""
    with pytest.raises(HTTPException) as raised:
        call()

    return raised.value


class TestBuildingBlocks:
    """repeated_ids, id_reasons, described_impact_ids, bulk_category_entity"""

    def test_repeated_ids_are_named_once_sorted(self) -> None:
        """Each repeat once"""
        assert repeated_ids([3, 1, 3, 2, 1, 3]) == [1, 3]
        assert not repeated_ids([1, 2, 3])

    def test_id_reasons_skip_empty_fields(self) -> None:
        """In the given order"""
        assert id_reasons([('b', [2]), ('a', []), ('c', [1, 3])]) == 'b: [2]; c: [1, 3]'
        assert id_reasons([('a', [])]) == ''

    def test_described_impact_ids(self) -> None:
        """One per description, in order; none without descriptions"""
        assert described_impact_ids(_category(IMPACT_B, IMPACT_A)) == [IMPACT_B, IMPACT_A]
        assert described_impact_ids({'impact_descriptions': None}) == []

    def test_bulk_category_entity(self) -> None:
        """Names the item"""
        assert bulk_category_entity(CATEGORY_A) == f'ImpactCategory {CATEGORY_A}'


class TestReadMissingIds:
    """read_missing_ids"""

    def test_answers_the_ids_not_stored(self) -> None:
        """One projected read"""
        manager: MagicMock = _manager()

        assert read_missing_ids(manager, IsmsThreat.COLLECTION, [THREAT_A, MISSING_THREAT], MagicMock()) == {
            MISSING_THREAT,
        }
        manager.get_many_from_other_collection.assert_called_once_with(
            IsmsThreat.COLLECTION, projection={'public_id': 1},
            criteria={'public_id': {'$in': [THREAT_A, MISSING_THREAT]}},
        )

    def test_no_ids_read_nothing(self) -> None:
        """Nothing named"""
        manager: MagicMock = _manager()

        assert read_missing_ids(manager, IsmsThreat.COLLECTION, [], MagicMock()) == set()
        manager.get_many_from_other_collection.assert_not_called()

    def test_a_failed_read_is_its_own_400(self) -> None:
        """Named after what was read"""
        manager = MagicMock()
        manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')
        label = MagicMock(singular='Threat')

        refusal: HTTPException = _refusal(lambda: read_missing_ids(manager, IsmsThreat.COLLECTION, [THREAT_A], label))

        assert (refusal.code, refusal.description) == (
            HTTPStatus.BAD_REQUEST, REFERENCE_LOOKUP_FAILED_MSG.format(label='Threat'),
        )


class TestGuardRiskReferences:
    """guard_risk_references"""

    def test_stored_ids_pass_with_one_read_per_named_collection(self) -> None:
        """An empty list reads nothing"""
        manager: MagicMock = _manager()

        guard_risk_references(manager, _risk([THREAT_A, THREAT_B], [VULNERABILITY]))

        assert [call.args[0] for call in manager.get_many_from_other_collection.call_args_list] == [
            IsmsThreat.COLLECTION, IsmsVulnerability.COLLECTION,
        ]

    def test_every_unknown_id_is_named_with_its_field(self) -> None:
        """One 400, in field order"""
        refusal: HTTPException = _refusal(lambda: guard_risk_references(
            _manager(), _risk([MISSING_THREAT, THREAT_A], [MISSING_VULNERABILITY], [GOAL]),
        ))

        assert (refusal.code, refusal.description) == (HTTPStatus.BAD_REQUEST, UNKNOWN_REFERENCED_IDS_MSG.format(
            entity='Risk', reasons=f'threats: [{MISSING_THREAT}]; vulnerabilities: [{MISSING_VULNERABILITY}]',
        ))

    def test_a_repeated_id_is_refused_before_anything_is_read(self) -> None:
        """The cheap check first"""
        manager: MagicMock = _manager()

        refusal: HTTPException = _refusal(lambda: guard_risk_references(manager, _risk([THREAT_A, THREAT_A],
                                                                                      goals=[GOAL, GOAL])))

        assert refusal.description == REPEATED_REFERENCED_IDS_MSG.format(
            entity='Risk', reasons=f'threats: [{THREAT_A}]; protection_goals: [{GOAL}]',
        )
        manager.get_many_from_other_collection.assert_not_called()

    def test_absent_lists_pass(self) -> None:
        """An EVENT risk names none"""
        guard_risk_references(_manager(), {})


class TestGuardImpactDescriptionIds:
    """guard_impact_description_ids"""

    def test_stored_impacts_pass_with_one_read_for_every_document(self) -> None:
        """The bulk's categories share the read"""
        manager: MagicMock = _manager()

        guard_impact_description_ids(manager, [('A', _category(IMPACT_A)), ('B', _category(IMPACT_B, IMPACT_A))])

        manager.get_many_from_other_collection.assert_called_once()

    def test_an_unknown_impact_is_named_with_its_category(self) -> None:
        """The first document naming one"""
        refusal: HTTPException = _refusal(lambda: guard_impact_description_ids(
            _manager(), [('A', _category(IMPACT_A)), ('ImpactCategory 52', _category(MISSING_IMPACT))],
        ))

        assert refusal.description == UNKNOWN_REFERENCED_IDS_MSG.format(
            entity='ImpactCategory 52', reasons=f'impact_descriptions.impact_id: [{MISSING_IMPACT}]',
        )

    def test_one_impact_described_twice_is_refused_before_the_read(self) -> None:
        """Per category"""
        manager: MagicMock = _manager()

        refusal: HTTPException = _refusal(lambda: guard_impact_description_ids(
            manager, [('ImpactCategory', _category(IMPACT_A, IMPACT_A))],
        ))

        assert refusal.description == REPEATED_REFERENCED_IDS_MSG.format(
            entity='ImpactCategory', reasons=f'impact_descriptions.impact_id: [{IMPACT_A}]',
        )
        manager.get_many_from_other_collection.assert_not_called()

    def test_two_categories_may_describe_the_same_impact(self) -> None:
        """Once per category, not once overall"""
        guard_impact_description_ids(_manager(), [('A', _category(IMPACT_A)), ('B', _category(IMPACT_A))])


def test_the_module_function_set_is_pinned() -> None:
    """A new public function is a deliberate change"""
    functions: set[str] = {
        name for name, member in inspect.getmembers(isms_id_reference_helper, inspect.isfunction)
        if member.__module__ == isms_id_reference_helper.__name__
    }

    assert functions == {
        'bulk_category_entity', 'described_impact_ids', 'guard_impact_description_ids', 'guard_risk_references',
        'id_reasons', 'read_missing_ids', 'repeated_ids',
    }
