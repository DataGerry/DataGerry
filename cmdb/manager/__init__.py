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
This module provides all refactored Managers of DataGerry (refactoring still in process)
"""
from cmdb.manager.categories_manager import CategoriesManager
from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.manager.locations_manager import LocationsManager
from cmdb.manager.logs_manager import LogsManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.object_relations_manager import ObjectRelationsManager
from cmdb.manager.object_relation_logs_manager import ObjectRelationLogsManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.manager.report_categories_manager import ReportCategoriesManager
from cmdb.manager.reports_manager import ReportsManager
from cmdb.manager.rights_manager import RightsManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.manager.security_manager import SecurityManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.users_manager import UsersManager
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.manager.webhooks_manager import WebhooksManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.manager.ci_explorer_profile_manager import CiExplorerProfileManager
from cmdb.manager.oidc_request_manager import OidcRequestManager

# System Managers
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager

# ISMS Managers
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.manager.isms_manager.vulnerability_manager import VulnerabilityManager
from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager

# OpenCelium Managers
from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager
from cmdb.manager.open_celium_managers.oc_connector_manager import OcConnectorManager
from cmdb.manager.open_celium_managers.oc_invoker_manager import OcInvokerManager
from cmdb.manager.open_celium_managers.oc_template_manager import OcTemplateManager
from cmdb.manager.open_celium_managers.oc_connection_manager import OcConnectionManager
from cmdb.manager.open_celium_managers.oc_scheduler_manager import OcSchedulerManager
from cmdb.manager.open_celium_managers.oc_license_manager import OcLicenseManager
from cmdb.manager.open_celium_managers.oc_connection_log_manager import OcConnectionLogManager

from cmdb.manager.system_manager.dg_service_portal_manager import DgServicePortalManager
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CategoriesManager',
    'CiExplorerProfileManager',
    'DocapiTemplatesManager',
    'GroupsManager',
    'LocationsManager',
    'LogsManager',
    'MediaFilesManager',
    'ObjectsManager',
    'ObjectRelationsManager',
    'ObjectRelationLogsManager',
    'RelationsManager',
    'ReportCategoriesManager',
    'ReportsManager',
    'RightsManager',
    'SectionTemplatesManager',
    'SecurityManager',
    'SettingsManager',
    'TypesManager',
    'UsersManager',
    'WebhooksEventManager',
    'WebhooksManager',
    'RiskClassManager',
    'LikelihoodManager',
    'ImpactManager',
    'ImpactCategoryManager',
    'ProtectionGoalManager',
    'RiskMatrixManager',
    'ExtendableOptionsManager',
    'ObjectGroupsManager',
    'ThreatManager',
    'VulnerabilityManager',
    'UserSettingsManager',
    'RiskManager',
    'ControlMeasureManager',
    'PersonsManager',
    'PersonGroupsManager',
    'RiskAssessmentManager',
    'ControlMeasureAssignmentManager',
    'CachedUserManager',
    'OcBaseManager',
    'OcConnectorManager',
    'OcInvokerManager',
    'OcTemplateManager',
    'OcConnectionManager',
    'OcSchedulerManager',
    'OcLicenseManager',
    'DgServicePortalManager',
    'OcConnectionLogManager',
    'OidcRequestManager',
]
