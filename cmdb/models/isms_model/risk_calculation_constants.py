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
Shared document-key constants for the ISMS risk-calculation matrices

An IsmsRiskAssessment carries two risk-calculation matrices, ``risk_calculation_before`` and
``risk_calculation_after``. Each holds an ``impacts`` list (per-impact-category entries referencing
an IsmsImpact) plus the derived ``maximum_impact_id`` / ``maximum_impact_value``. These keys are
persisted in MongoDB and referenced from several ISMS managers; naming them here keeps the managers
free of duplicated string literals that would silently drift apart.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class RiskCalculationKey(BaseStrEnum):
    """
    Field keys inside an IsmsRiskAssessment's risk-calculation matrices

    Members are the raw MongoDB document keys; build dotted paths with ``.value`` (e.g.
    ``f'{RiskCalculationKey.BEFORE.value}.{RiskCalculationKey.MAXIMUM_IMPACT_ID.value}'``).
    """
    BEFORE = 'risk_calculation_before'
    AFTER = 'risk_calculation_after'
    IMPACTS = 'impacts'
    IMPACT_ID = 'impact_id'
    IMPACT_CATEGORY_ID = 'impact_category_id'
    MAXIMUM_IMPACT_ID = 'maximum_impact_id'
    MAXIMUM_IMPACT_VALUE = 'maximum_impact_value'
    LIKELIHOOD_ID = 'likelihood_id'
    LIKELIHOOD_VALUE = 'likelihood_value'


# The two risk-calculation matrices present on every IsmsRiskAssessment, in a fixed order
RISK_CALCULATION_MATRIX_KEYS: tuple[RiskCalculationKey, ...] = (
    RiskCalculationKey.BEFORE,
    RiskCalculationKey.AFTER,
)
