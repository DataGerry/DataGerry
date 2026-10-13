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
What a configuration reset clears - the ONE list the reset and the import's precondition both read

Each `ResetTarget` names a collection, which of its documents the reset deletes, and the public_id counter that is
set back afterwards. The import asks the same list whether anything is left (`find_non_empty_targets`), so the two
cannot disagree about what "reset" means.

The list is ordered dependents first, definitions last. The reset cannot be undone (the deleted documents are not
kept), so it is made re-run safe instead: a reset that stops midway leaves the type definitions in place, and
running it again finishes the job.

What stays: users, groups, persons, the root location, the predefined section templates and report category, the
ISMS catalogues, the extendable options and every media file that is not attached to an object. A counter is set
back to the highest public_id still stored, so it reads 0 for a cleared collection and stays above what is kept
(the root location keeps id 1).

The assistant's one-time marker is cleared by the reset route itself: its settings section is named in the
transport layer, which this module may not import
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from cmdb.manager.base_manager import BaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.port_model import CmdbPort
from cmdb.models.port_connection_model import CmdbPortConnection
from cmdb.models.port_interface_link_model import CmdbPortInterfaceLink
from cmdb.models.rack_model import CmdbRackMount
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.ci_explorer_model.ci_explorer_profile import CmdbCiExplorerProfile
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MEDIA_FILE_REFERENCE_TYPE_PATH,
    OBJECT_REFERENCE_TYPE,
)
from cmdb.database.database_services.database_services_constants import BootstrapDocumentKey
from cmdb.framework.configuration_transfer.configuration_transfer_constants import NOT_PREDEFINED
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ResetTarget:
    """
    One collection's part of a configuration reset

    Attributes:
        collection (str): The collection the documents are read from and deleted in
        criteria (dict[str, Any]): Which of its documents the reset deletes; empty means all of them
        counter (str | None): The `_id` of the public_id counter set back after the delete; None leaves it alone
        gridfs_bucket (str | None): The GridFS bucket the documents are file documents of - deleted through GridFS so
                                    their chunks go with them; None for a plain collection
        blocks_import (bool): Whether a document left here refuses an import. False for what a user produces
                              merely by using the reset system before the import (their table settings)
    """
    collection: str
    criteria: dict[str, Any] = field(default_factory=dict)
    counter: str | None = None
    gridfs_bucket: str | None = None
    blocks_import: bool = True


    def deletion_criteria(self) -> dict[str, Any]:
        """
        Returns the criteria of the documents the reset deletes, as a copy the caller may change

        Returns:
            dict[str, Any]: The criteria
        """
        return deepcopy(self.criteria)


def _cleared(model: Any, criteria: dict[str, Any] | None = None, blocks_import: bool = True) -> ResetTarget:
    """
    The reset target of a collection whose matching documents are deleted and whose counter is set back

    Args:
        model (Any): The model class owning the collection (its `COLLECTION` is both collection and counter id)
        criteria (dict[str, Any] | None): Which documents are deleted; None deletes all of them
        blocks_import (bool): Whether a leftover document refuses an import

    Returns:
        ResetTarget: The target
    """
    return ResetTarget(model.COLLECTION, criteria or {}, model.COLLECTION, blocks_import=blocks_import)


# Dependents first, definitions last - see the module docstring for why the order matters
RESET_TARGETS: tuple[ResetTarget, ...] = (
    _cleared(CmdbWebhookEvent),
    _cleared(CmdbWebhook),
    _cleared(IsmsControlMeasureAssignment),
    _cleared(IsmsRiskAssessment),
    # Only the attachments: free-standing files and folders stay, and with them the media library's counter
    ResetTarget(
        f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}',
        {MEDIA_FILE_REFERENCE_TYPE_PATH: OBJECT_REFERENCE_TYPE},
        gridfs_bucket=MediaFile.COLLECTION,
    ),
    _cleared(CmdbObjectRelationLog),
    _cleared(CmdbObjectRelation),
    _cleared(CmdbPortInterfaceLink),
    _cleared(CmdbPortConnection),
    _cleared(CmdbPort),
    _cleared(CmdbRackMount),
    _cleared(CmdbLocation, {LocationKey.PUBLIC_ID.value: {'$ne': RootLocationDefault.PUBLIC_ID}}),
    _cleared(CmdbMetaLog),
    _cleared(CmdbObjectGroup),
    _cleared(CmdbObject),
    _cleared(CmdbReport),
    _cleared(CmdbReportCategory, {BootstrapDocumentKey.PREDEFINED.value: NOT_PREDEFINED}),
    _cleared(CmdbCiExplorerProfile),
    _cleared(DocapiTemplate),
    _cleared(CmdbUserSetting, blocks_import=False),
    _cleared(CmdbRelation),
    _cleared(CmdbCategory),
    _cleared(CmdbType),
    _cleared(CmdbSectionTemplate, {SectionTemplateKey.PREDEFINED.value: NOT_PREDEFINED}),
)


def find_non_empty_targets(manager: BaseManager, targets: tuple[ResetTarget, ...] = RESET_TARGETS) -> list[str]:
    """
    Names every target that still holds a document the reset would delete

    One existence check per target (a count capped at 1), never a full count

    Args:
        manager (BaseManager): Any manager of the tenant's database - only its cross-collection count is used
        targets (tuple[ResetTarget, ...]): The targets to check, the reset list by default

    Raises:
        BaseManagerGetError: When a count fails

    Returns:
        list[str]: The collections of the non-empty targets, in list order
    """
    return [target.collection for target in targets
            if manager.count_from_other_collection(target.collection, target.deletion_criteria(), limit=1)]


def find_import_blockers(manager: BaseManager, targets: tuple[ResetTarget, ...] = RESET_TARGETS) -> list[str]:
    """
    Names every target whose leftover documents refuse an import - the import's precondition

    Args:
        manager (BaseManager): Any manager of the tenant's database
        targets (tuple[ResetTarget, ...]): The targets to check, the reset list by default

    Raises:
        BaseManagerGetError: When a count fails

    Returns:
        list[str]: The collections that are not empty yet, in list order; empty when the import may run
    """
    return find_non_empty_targets(manager, tuple(target for target in targets if target.blocks_import))
