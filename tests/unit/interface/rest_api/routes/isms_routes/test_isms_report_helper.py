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
Unit tests for the shared ISMS report aggregation-pipeline fragment builders

These are pure functions (no database) that emit the $lookup/$unwind stages shared by the Risk
Treatment Plan and Risk Assessments reports; the tests pin the collections joined and the field
names so the two reports stay in sync.
"""
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    object_reference_lookup_stages,
    risk_matrix_class_lookup_stages,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestObjectReferenceLookupStages:
    """object_reference_lookup_stages joins the assessed object, its group and its type."""

    def test_joins_object_group_and_type(self) -> None:
        """The three stages look up framework.objects, objectGroups and types under the expected keys."""
        stages = object_reference_lookup_stages()

        joined = {(stage['$lookup']['from'], stage['$lookup']['as']) for stage in stages}

        assert joined == {
            ('framework.objects', 'object'),
            ('framework.objectGroups', 'object_group'),
            ('framework.types', 'object_type'),
        }

    def test_type_lookup_uses_object_type_id(self) -> None:
        """The type lookup keys off the resolved object's type_id."""
        type_stage = next(s for s in object_reference_lookup_stages() if s['$lookup']['as'] == 'object_type')

        assert type_stage['$lookup']['localField'] == 'object.type_id'


class TestRiskMatrixClassLookupStages:
    """risk_matrix_class_lookup_stages resolves a calculation matrix to its cell and risk class."""

    def test_binds_calculation_field_and_output_names(self) -> None:
        """The let bindings read the given calculation field and the outputs use the given names."""
        stages = risk_matrix_class_lookup_stages('risk_calculation_before', 'risk_before', 'risk_before_class')

        matrix_lookup = stages[0]['$lookup']
        assert matrix_lookup['from'] == 'isms.riskMatrix'
        assert matrix_lookup['let'] == {
            'likelihood_id': '$risk_calculation_before.likelihood_id',
            'impact_id': '$risk_calculation_before.maximum_impact_id',
        }
        assert matrix_lookup['as'] == 'risk_before'

        class_lookup = stages[2]['$lookup']
        assert class_lookup['from'] == 'isms.riskClass'
        assert class_lookup['localField'] == 'risk_before.risk_class_id'
        assert class_lookup['as'] == 'risk_before_class'

    def test_emits_lookup_unwind_lookup_unwind(self) -> None:
        """The fragment is exactly: matrix $lookup, $unwind, riskClass $lookup, $unwind."""
        stages = risk_matrix_class_lookup_stages('risk_calculation_after', 'risk_after', 'risk_after_class')

        assert [next(iter(stage)) for stage in stages] == ['$lookup', '$unwind', '$lookup', '$unwind']
        assert stages[1]['$unwind']['path'] == '$risk_after'
        assert stages[3]['$unwind']['path'] == '$risk_after_class'
