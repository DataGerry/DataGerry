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
from cmdb.models.right_model.base_right import BaseRight, DefaultLevelRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsRight(DefaultLevelRight):
    """
    Base class for general ISMS rights
    """
    MIN_LEVEL = Levels.PERMISSION
    PREFIX = f'{BaseRight.PREFIX}.isms'

# -------------------------------------------------------------------------------------------------------------------- #

class RiskClassRight(IsmsRight):
    """
    Base class for IsmsRiskClass rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskClass'


class LikelihoodRight(IsmsRight):
    """
    Base class for IsmsLikelihood rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.likelihood'


class ImpactRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.impact'


class ImpactCategoryRight(IsmsRight):
    """
    Base class for IsmsImpactCategory rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.impactCategory'


class ProtectionGoalRight(IsmsRight):
    """
    Base class for IsmsProtectionGoal rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.protectionGoal'


class RiskMatrixRight(IsmsRight):
    """
    Base class for IsmsRiskMatrix rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskMatrix'


class ThreatRight(IsmsRight):
    """
    Base class for IsmsThreat rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.threat'


class VulnerabilityRight(IsmsRight):
    """
    Base class for IsmsVulnerability rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.vulnerability'


class RiskRight(IsmsRight):
    """
    Base class for IsmsRisk rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.risk'


class ControlMeasureRight(IsmsRight):
    """
    Base class for IsmsControlMeasure rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasure'


class RiskAssessmentRight(IsmsRight):
    """
    Base class for IsmsRiskAssessment rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskAssessment'


class ControlMeasureAssignmentRight(IsmsRight):
    """
    Base class for IsmsControlMeasureAssignment rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasureAssignment'


class IsmsReportRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.report'


class IsmsImportRight(IsmsRight):
    """
    Base class for ISMS import rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{IsmsRight.PREFIX}.import'
