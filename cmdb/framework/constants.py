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
This module represents the core system of the CMDB.
All initializations and specifications for creating objects,
object types and their fields are controlled here.
Except for the managers, this module can be used completely modular.
The respective DAO is used to apply the attributes and to convert
the elements for the database.
"""
from typing import Any

from cmdb.models.object_model import CmdbObject
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.object_link_model import CmdbObjectLink
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_log import CmdbLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.ci_explorer_model.ci_explorer_profile import CmdbCiExplorerProfile
from cmdb.models.isms_model import (
    IsmsRiskClass,
    IsmsLikelihood,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsThreat,
    IsmsVulnerability,
    IsmsControlMeasure,
    IsmsRiskMatrix,
    IsmsRiskAssessment,
    IsmsControlMeasureAssignment,
)
# -------------------------------------------------------------------------------------------------------------------- #

CmdbLog.register_log_type(CmdbObjectLog.__name__, CmdbObjectLog)

# List of init collections
__COLLECTIONS__: list[Any] = [
    CmdbObject,
    CmdbType,
    CmdbCategory,
    CmdbCiExplorerProfile,
    CmdbMetaLog,
    CmdbObjectLink,
    CmdbLocation,
    CmdbSectionTemplate,
    CmdbReportCategory,
    CmdbReport,
    CmdbWebhook,
    CmdbWebhookEvent,
    CmdbRelation,
    CmdbObjectRelation,
    CmdbObjectRelationLog,
    CmdbObjectGroup,
    CmdbExtendableOption,
    IsmsRisk,
    IsmsThreat,
    IsmsVulnerability,
    IsmsControlMeasure,
    IsmsRiskClass,
    IsmsLikelihood,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsProtectionGoal,
    IsmsRiskMatrix,
    IsmsRiskAssessment,
    IsmsControlMeasureAssignment,
]
