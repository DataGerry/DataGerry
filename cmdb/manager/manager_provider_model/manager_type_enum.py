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
Enumeration of all avaiable Managers
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class ManagerType(Enum):
    """
    Enum of the different Managers which are used by the API routes
    """
    CATEGORIES = 'CategoriesManager'
    OBJECTS = 'ObjectsManager'
    LOGS = 'LogsManager'
    DOCAPI_TEMPLATES = 'DocapiTemplatesManager'
    USERS = 'UsersManager'
    USER_SETTINGS = 'UserSettingsManager'
    GROUPS = 'GroupsManager'
    MEDIA_FILES = 'MediaFilesManager'
    TYPES = 'TypesManager'
    LOCATIONS = 'LocationsManager'
    SECTION_TEMPLATES = 'SectionTemplatesManager'
    SETTINGS = 'SettingsManager'
    SECURITY = 'SecurityManager'
    REPORT_CATEGORIES = 'ReportCategoriesManager'
    REPORTS = 'ReportsManager'
    WEBHOOKS = 'WebhooksManager'
    WEBHOOKS_EVENT = 'WebhooksEventManager'
    RELATIONS = 'RelationsManager'
    OBJECT_RELATIONS = 'ObjectRelationsManager'
    RACK_MOUNTS = 'RackMountsManager'
    OBJECT_RELATION_LOGS = 'ObjectRelationLogsManager'
    EXTENDABLE_OPTIONS = 'ExtendableOptionsManager'
    OBJECT_GROUP = 'ObjectGroupsManager'
    PERSON = 'PersonsManager'
    PERSON_GROUP = 'PersonGroupsManager'
    CI_EXPLORER_PROFILE = 'CiExplorerProfileManager'

    #ISMS Managers
    RISK_CLASS = 'RiskClassManager'
    LIKELIHOOD = 'LikelihoodManager'
    IMPACT = 'ImpactManager'
    IMPACT_CATEGORY = 'ImpactCategoryManager'
    PROTECTION_GOAL = 'ProtectionGoalManager'
    RISK_MATRIX = 'RiskMatrixManager'
    THREAT = 'ThreatManager'
    VULNERABILITY = 'VulnerabilityManager'
    RISK = 'RiskManager'
    CONTROL_MEASURE = 'ControlMeasureManager'
    RISK_ASSESSMENT = 'RiskAssessmentManager'
    CONTROL_MEASURE_ASSIGNMENT = 'ControlMeasureAssignmentManager'

    # System Managers
    CACHED_USER = 'CachedUserManager'

    # License Managers
    LICENSE_ACTIVATION_REQUESTS = 'LicenseActivationRequestsManager'
    ACTIVE_LICENSE = 'ActiveLicenseManager'
    LICENSE_SERVICE = 'LicenseService'
