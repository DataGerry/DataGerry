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
Unit tests for cmdb.framework.person_types.person_isms_cleanup

The person / group targets by the marker they carry, the risk-owner count per kind, and the references cleared: the
polymorphic keys by id AND ref_type, the person-only keys for persons alone - a scalar nulled, the list pulled
"""
from typing import Any
from unittest.mock import MagicMock, call

from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.framework.person_types.person_isms_cleanup import (
    clear_isms_person_references,
    count_owned_risk_assessments,
    marked_targets,
)
# -------------------------------------------------------------------------------------------------------------------- #

RA: str = 'isms.riskAssessment'
CMA: str = 'isms.controlMeasureAssignment'
PERSON = PersonReferenceType.PERSON
GROUP = PersonReferenceType.PERSON_GROUP


def _polymorphic(key: str, kind: PersonReferenceType, ids: list[int]) -> dict[str, Any]:
    """A polymorphic key's filter"""
    return {key: {'$in': ids}, f'{key}_ref_type': kind.value}


def test_marked_targets_by_the_marker_each_object_carries() -> None:
    """Persons and groups apart, everything else skipped"""
    documents = [
        {'public_id': 1, 'special_type': 'PERSON'}, {'public_id': 2, 'special_type': 'RACK'},
        {'public_id': 3, 'special_type': 'PERSON_GROUP'}, {'public_id': 4}, {'public_id': 5, 'special_type': 'PERSON'},
    ]

    assert marked_targets(documents) == {PERSON: [1, 5], GROUP: [3]}


def test_the_owned_count_asks_each_kind_by_id_and_ref_type() -> None:
    """One count per kind, summed"""
    manager = MagicMock()
    manager.count_from_other_collection.side_effect = [2, 1]

    assert count_owned_risk_assessments(manager, {PERSON: [1], GROUP: [3]}) == 3
    assert manager.count_from_other_collection.call_args_list == [
        call(RA, _polymorphic('risk_owner_id', PERSON, [1])), call(RA, _polymorphic('risk_owner_id', GROUP, [3])),
    ]


def test_no_targets_count_nothing() -> None:
    """No read"""
    manager = MagicMock()

    assert count_owned_risk_assessments(manager, {}) == 0
    manager.count_from_other_collection.assert_not_called()


def test_a_deleted_person_leaves_every_reference() -> None:
    """Polymorphic keys nulled with ref_type, the assessor nulled, the interviewed pulled - both collections"""
    manager = MagicMock()

    clear_isms_person_references(manager, {PERSON: [1, 2]})

    assert manager.update_many.call_args_list == [
        call(_polymorphic('risk_owner_id', PERSON, [1, 2]), {'risk_owner_id': None}, collection=RA),
        call(_polymorphic('responsible_persons_id', PERSON, [1, 2]), {'responsible_persons_id': None}, collection=RA),
        call(_polymorphic('auditor_id', PERSON, [1, 2]), {'auditor_id': None}, collection=RA),
        call({'risk_assessor_id': {'$in': [1, 2]}}, {'risk_assessor_id': None}, collection=RA),
        call(_polymorphic('responsible_for_implementation_id', PERSON, [1, 2]),
             {'responsible_for_implementation_id': None}, collection=CMA),
    ]
    manager.update_many_raw.assert_called_once_with(
        {'interviewed_persons': {'$in': [1, 2]}}, {'$pull': {'interviewed_persons': {'$in': [1, 2]}}}, collection=RA,
    )


def test_a_deleted_group_leaves_the_polymorphic_references_only() -> None:
    """No person-only key is touched"""
    manager = MagicMock()

    clear_isms_person_references(manager, {GROUP: [3]})

    assert {entry.args[0].get('responsible_persons_id_ref_type') for entry in manager.update_many.call_args_list
            if 'responsible_persons_id' in entry.args[0]} == {'PERSON_GROUP'}
    assert manager.update_many.call_count == 4
    manager.update_many_raw.assert_not_called()
