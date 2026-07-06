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
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsRight(BaseRight):
    """
    Base class for general ISMS rights
    """
    MIN_LEVEL = Levels.PERMISSION
    PREFIX = f'{BaseRight.PREFIX}.isms'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(level, name, description=description)

# -------------------------------------------------------------------------------------------------------------------- #

class RiskClassRight(IsmsRight):
    """
    Base class for IsmsRiskClass rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskClass'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class LikelihoodRight(IsmsRight):
    """
    Base class for IsmsLikelihood rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.likelihood'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ImpactRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.impact'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ImpactCategoryRight(IsmsRight):
    """
    Base class for IsmsImpactCategory rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.impactCategory'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ProtectionGoalRight(IsmsRight):
    """
    Base class for IsmsProtectionGoal rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.protectionGoal'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class RiskMatrixRight(IsmsRight):
    """
    Base class for IsmsRiskMatrix rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskMatrix'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ThreatRight(IsmsRight):
    """
    Base class for IsmsThreat rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.threat'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class VulnerabilityRight(IsmsRight):
    """
    Base class for IsmsVulnerability rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.vulnerability'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class RiskRight(IsmsRight):
    """
    Base class for IsmsRisk rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.risk'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ControlMeasureRight(IsmsRight):
    """
    Base class for IsmsControlMeasure rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasure'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class RiskAssessmentRight(IsmsRight):
    """
    Base class for IsmsRiskAssessment rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.riskAssessment'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ControlMeasureAssignmentRight(IsmsRight):
    """
    Base class for IsmsControlMeasureAssignment rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.controlMeasureAssignment'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class IsmsReportRight(IsmsRight):
    """
    Base class for IsmsImpact rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{IsmsRight.PREFIX}.report'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)
