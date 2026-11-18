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
Implementation of base classes of rights for the different components used in Datagerry
"""
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsRight(BaseRight):
    """
    Base class for general ISMS rights
    """
    PREFIX = f'{BaseRight.PREFIX}.isms'

# -------------------------------------------------------------------------------------------------------------------- #

class RiskClassRight(IsmsRight):
    """
    Base class for IsmsRiskClass rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.riskClass'


class LikelihoodRight(IsmsRight):
    """
    Base class for IsmsLikelihood rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.likelihood'


class ImpactRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.impact'


class ImpactCategoryRight(IsmsRight):
    """
    Base class for IsmsImpactCategory rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.impactCategory'


class ProtectionGoalRight(IsmsRight):
    """
    Base class for IsmsProtectionGoal rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.protectionGoal'


class RiskMatrixRight(IsmsRight):
    """
    Base class for IsmsRiskMatrix rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.riskMatrix'


class ThreatRight(IsmsRight):
    """
    Base class for IsmsThreat rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.threat'


class VulnerabilityRight(IsmsRight):
    """
    Base class for IsmsVulnerability rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.vulnerability'


class RiskRight(IsmsRight):
    """
    Base class for IsmsRisk rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.risk'


class ControlMeasureRight(IsmsRight):
    """
    Base class for IsmsControlMeasure rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasure'


class RiskAssessmentRight(IsmsRight):
    """
    Base class for IsmsRiskAssessment rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.riskAssessment'


class ControlMeasureAssignmentRight(IsmsRight):
    """
    Base class for IsmsControlMeasureAssignment rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasureAssignment'


class IsmsReportRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.report'


class IsmsImportRight(IsmsRight):
    """
    Base class for ISMS import rights
    """
    PREFIX = f'{IsmsRight.PREFIX}.import'
