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
Unit tests for build_ra_naming (risk_assessment_routes)

The helper is pure (no database): given an IsmsRiskAssessment and the pre-fetched risk / object /
person lookup maps, it resolves the display names for the assessment's ``naming`` block.
"""
from types import SimpleNamespace
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_routes import build_ra_naming
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

RISKS: dict[int, str] = {1: 'MyRisk'}
OBJECT_GROUPS: dict[int, str] = {20: 'MyObjectGroup'}
OBJECT_SUMMARIES: dict[int, str] = {30: 'Obj summary'}
PERSONS: dict[int, str] = {40: 'Alice', 41: 'Bob'}
RESPONSIBLE_PERSONS: dict[int, str] = {50: 'Carol'}
RESPONSIBLE_PERSON_GROUPS: dict[int, str] = {60: 'Ops Team'}


def _ra(**fields: Any) -> SimpleNamespace:
    """Builds an IsmsRiskAssessment-like stub with sensible neutral defaults."""
    defaults: dict[str, Any] = {
        'risk_id': 1,
        'object_id_ref_type': ObjectReferenceType.OBJECT,
        'object_id': 30,
        'interviewed_persons': [],
        'responsible_persons_id': None,
        'responsible_persons_id_ref_type': PersonReferenceType.PERSON,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def _naming(risk_assessment: SimpleNamespace) -> dict[str, Any]:
    """Runs build_ra_naming with the shared lookup maps."""
    return build_ra_naming(
        risk_assessment, RISKS, OBJECT_GROUPS, OBJECT_SUMMARIES,
        PERSONS, RESPONSIBLE_PERSONS, RESPONSIBLE_PERSON_GROUPS,
    )


def test_resolves_risk_name() -> None:
    """The risk id resolves to its name."""
    assert _naming(_ra())['risk_id_name'] == 'MyRisk'


def test_object_reference_resolves_summary_line() -> None:
    """An OBJECT-typed assessment resolves the object's summary line (and no group name)."""
    naming = _naming(_ra(object_id_ref_type=ObjectReferenceType.OBJECT, object_id=30))

    assert naming['object_id_name'] == 'Obj summary'
    assert naming['object_group_id_name'] is None


def test_object_group_reference_resolves_group_name() -> None:
    """An OBJECT_GROUP-typed assessment resolves the object group's name (and no object summary)."""
    naming = _naming(_ra(object_id_ref_type=ObjectReferenceType.OBJECT_GROUP, object_id=20))

    assert naming['object_group_id_name'] == 'MyObjectGroup'
    assert naming['object_id_name'] is None


def test_interviewed_persons_resolve_to_names() -> None:
    """Interviewed person ids resolve to their display names; unknown ids are dropped."""
    naming = _naming(_ra(interviewed_persons=[40, 41, 999]))

    assert naming['interviewed_persons_names'] == ['Alice', 'Bob']


def test_responsible_person_resolves_name() -> None:
    """A PERSON responsible id resolves via the responsible persons map."""
    naming = _naming(_ra(responsible_persons_id=50, responsible_persons_id_ref_type=PersonReferenceType.PERSON))

    assert naming['responsible_persons_id_name'] == 'Carol'


def test_responsible_person_group_resolves_name() -> None:
    """A PERSON_GROUP responsible id resolves via the responsible person groups map."""
    naming = _naming(
        _ra(responsible_persons_id=60, responsible_persons_id_ref_type=PersonReferenceType.PERSON_GROUP)
    )

    assert naming['responsible_persons_id_name'] == 'Ops Team'
