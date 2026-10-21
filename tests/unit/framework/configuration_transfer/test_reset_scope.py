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
Unit tests for cmdb.framework.configuration_transfer.reset_scope

Pure tests: no Mongo, no Flask. What is pinned here: every registered collection is either on the reset list or
deliberately kept (a new collection fails the census until someone decides), the list keeps the root location, the
predefined section templates and report category and every unattached media file, the definitions come after
everything that references them, only the user settings let an import through, and the checks ask one capped
existence count per target, in list order
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.configuration_transfer import (
    RESET_TARGETS,
    ResetTarget,
    find_import_blockers,
    find_non_empty_targets,
    has_import_blockers,
)
from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_COLLECTIONS
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MEDIA_FILE_REFERENCE_TYPE_PATH,
    OBJECT_REFERENCE_TYPE,
)
from cmdb.models.user_management_constants import __COLLECTIONS__ as USER_MANAGEMENT_COLLECTIONS
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_model import CmdbObject
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.reports_model.report_constants import ReportCategoryKey
from cmdb.models.ci_explorer_model.ci_explorer_profile import CmdbCiExplorerProfile
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.person_model.cmdb_person import CmdbPerson
from cmdb.models.person_group_model.cmdb_person_group import CmdbPersonGroup
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.isms_model import (
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
)
# -------------------------------------------------------------------------------------------------------------------- #

MEDIA_FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
PREDEFINED_FLAG: str = SectionTemplateKey.PREDEFINED.value
NOT_PREDEFINED: dict[str, Any] = {'$ne': True}

# What the reset leaves alone on purpose - none of it references a CmdbType, a CmdbObject or the other cleared data
KEPT_COLLECTIONS: set[str] = {
    CmdbUser.COLLECTION,
    CmdbUserGroup.COLLECTION,
    CmdbPerson.COLLECTION,
    CmdbPersonGroup.COLLECTION,
    CmdbExtendableOption.COLLECTION,
    IsmsRisk.COLLECTION,
    IsmsThreat.COLLECTION,
    IsmsVulnerability.COLLECTION,
    IsmsControlMeasure.COLLECTION,
    IsmsRiskClass.COLLECTION,
    IsmsLikelihood.COLLECTION,
    IsmsImpact.COLLECTION,
    IsmsImpactCategory.COLLECTION,
    IsmsProtectionGoal.COLLECTION,
    IsmsRiskMatrix.COLLECTION,
}

# The definitions: the reset deletes these last so a reset that stops midway can be run again
DEFINITION_COLLECTIONS: list[str] = [
    CmdbRelation.COLLECTION,
    CmdbCategory.COLLECTION,
    CmdbType.COLLECTION,
    CmdbSectionTemplate.COLLECTION,
]

# Reference types (or nothing) but no CmdbObject, so they may be deleted after the objects
OBJECT_FREE_COLLECTIONS: list[str] = [
    CmdbReport.COLLECTION,
    CmdbReportCategory.COLLECTION,
    CmdbCiExplorerProfile.COLLECTION,
    DocapiTemplate.COLLECTION,
    CmdbUserSetting.COLLECTION,
]

TARGET_BY_COLLECTION: dict[str, ResetTarget] = {target.collection: target for target in RESET_TARGETS}
FIRST: ResetTarget = ResetTarget('first.collection', {'kind': 1}, 'first.collection')
SECOND: ResetTarget = ResetTarget('second.collection', {'kind': 2}, blocks_import=False)
THIRD: ResetTarget = ResetTarget('third.collection')


def _counting_manager(counts: dict[str, int]) -> MagicMock:
    """A manager whose cross-collection count answers per collection"""
    manager: MagicMock = MagicMock()
    manager.count_from_other_collection.side_effect = lambda collection, criteria, limit=None: counts[collection]

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ResetTarget                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_target_clears_everything_and_blocks_the_import_by_default() -> None:
    """No criteria, no counter, no GridFS bucket, blocks an import"""
    target: ResetTarget = ResetTarget(THIRD.collection)

    assert (target.criteria, target.counter, target.gridfs_bucket, target.blocks_import) == ({}, None, None, True)


def test_deletion_criteria_is_a_copy_the_caller_may_change() -> None:
    """Changing the returned criteria (nested too) leaves the target untouched"""
    target: ResetTarget = ResetTarget(FIRST.collection, {'nested': {'$ne': 1}})
    criteria: dict[str, Any] = target.deletion_criteria()
    criteria['nested']['$ne'] = 2

    assert target.criteria == {'nested': {'$ne': 1}}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the reset list                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_registered_collection_is_decided() -> None:
    """Each registered collection is either reset or deliberately kept - never both, never neither"""
    registered: set[str] = {model.COLLECTION for model in FRAMEWORK_COLLECTIONS + USER_MANAGEMENT_COLLECTIONS}
    registered.add(MEDIA_FILES_COLLECTION)
    reset: set[str] = set(TARGET_BY_COLLECTION)

    assert not reset & KEPT_COLLECTIONS
    assert registered - reset - KEPT_COLLECTIONS == set()
    assert reset - registered == set()


def test_each_collection_is_listed_once() -> None:
    """A collection on the list twice would be deleted and counted twice"""
    assert len(TARGET_BY_COLLECTION) == len(RESET_TARGETS)


def test_the_root_location_is_kept() -> None:
    """Every location but the root goes"""
    assert TARGET_BY_COLLECTION[CmdbLocation.COLLECTION].criteria == {
        LocationKey.PUBLIC_ID.value: {'$ne': RootLocationDefault.PUBLIC_ID}
    }


@pytest.mark.parametrize('collection,flag', [
    (CmdbSectionTemplate.COLLECTION, PREDEFINED_FLAG),
    (CmdbReportCategory.COLLECTION, ReportCategoryKey.PREDEFINED.value),
])
def test_the_predefined_documents_are_kept(collection: str, flag: str) -> None:
    """The predefined section templates and report category stay; an absent flag counts as not predefined"""
    assert TARGET_BY_COLLECTION[collection].criteria == {flag: NOT_PREDEFINED}


def test_only_the_object_attachments_go_through_gridfs() -> None:
    """Attached media files are deleted as GridFS files; the library's counter stays"""
    target: ResetTarget = TARGET_BY_COLLECTION[MEDIA_FILES_COLLECTION]

    assert target.criteria == {MEDIA_FILE_REFERENCE_TYPE_PATH: OBJECT_REFERENCE_TYPE}
    assert target.gridfs_bucket == MediaFile.COLLECTION
    assert target.counter is None
    assert [t.collection for t in RESET_TARGETS if t.gridfs_bucket] == [MEDIA_FILES_COLLECTION]


def test_every_plain_collection_sets_back_its_own_counter() -> None:
    """A collection's counter id is the collection's name"""
    assert all(target.counter == target.collection for target in RESET_TARGETS if not target.gridfs_bucket)


def test_only_the_user_settings_let_an_import_through() -> None:
    """Using the reset system before the import writes table settings - they must not refuse the import"""
    assert [target.collection for target in RESET_TARGETS if not target.blocks_import] == [CmdbUserSetting.COLLECTION]


def test_the_definitions_come_last() -> None:
    """Relations, categories, types, then the section templates the types claim - after everything else"""
    assert [target.collection for target in RESET_TARGETS[-len(DEFINITION_COLLECTIONS):]] == DEFINITION_COLLECTIONS


def test_the_objects_go_after_everything_that_references_them() -> None:
    """Between the objects and the definitions only collections that reference no object"""
    collections: list[str] = [target.collection for target in RESET_TARGETS]
    between: list[str] = collections[collections.index(CmdbObject.COLLECTION) + 1:-len(DEFINITION_COLLECTIONS)]

    assert between == OBJECT_FREE_COLLECTIONS

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the checks                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_find_non_empty_targets_names_the_non_empty_ones_in_list_order() -> None:
    """Each target counted once with its criteria and limit=1; the empty ones are left out"""
    manager: MagicMock = _counting_manager({FIRST.collection: 1, SECOND.collection: 0, THIRD.collection: 1})

    assert find_non_empty_targets(manager, (FIRST, SECOND, THIRD)) == [FIRST.collection, THIRD.collection]
    assert [call.args + (call.kwargs['limit'],) for call in manager.count_from_other_collection.call_args_list] == [
        (FIRST.collection, FIRST.criteria, 1),
        (SECOND.collection, SECOND.criteria, 1),
        (THIRD.collection, THIRD.criteria, 1),
    ]


def test_find_non_empty_targets_reads_the_reset_list_by_default() -> None:
    """Without targets every reset target is asked"""
    manager: MagicMock = _counting_manager({target.collection: 0 for target in RESET_TARGETS})

    assert not find_non_empty_targets(manager)
    assert manager.count_from_other_collection.call_count == len(RESET_TARGETS)


def test_find_import_blockers_skips_the_targets_that_let_an_import_through() -> None:
    """A leftover in a non-blocking target is not asked about, the blocking ones are named"""
    manager: MagicMock = _counting_manager({FIRST.collection: 1, SECOND.collection: 1, THIRD.collection: 0})

    assert find_import_blockers(manager, (FIRST, SECOND, THIRD)) == [FIRST.collection]
    assert SECOND.collection not in [call.args[0] for call in manager.count_from_other_collection.call_args_list]


def test_find_import_blockers_reads_the_reset_list_by_default() -> None:
    """Without targets every blocking reset target is asked, the user settings are not"""
    manager: MagicMock = _counting_manager({target.collection: 1 for target in RESET_TARGETS})

    assert CmdbUserSetting.COLLECTION not in find_import_blockers(manager)
    assert manager.count_from_other_collection.call_count == len(RESET_TARGETS) - 1


def test_has_import_blockers_is_false_when_every_blocking_target_is_empty() -> None:
    """Every blocking target asked, none answers"""
    manager: MagicMock = _counting_manager({FIRST.collection: 0, SECOND.collection: 1, THIRD.collection: 0})

    assert has_import_blockers(manager, (FIRST, SECOND, THIRD)) is False
    assert [call.args[0] for call in manager.count_from_other_collection.call_args_list] == [
        FIRST.collection, THIRD.collection,
    ]


def test_has_import_blockers_stops_at_the_first_leftover() -> None:
    """The first non-empty blocking target answers; the rest are not counted"""
    manager: MagicMock = _counting_manager({FIRST.collection: 1, SECOND.collection: 0, THIRD.collection: 1})

    assert has_import_blockers(manager, (FIRST, SECOND, THIRD)) is True
    assert manager.count_from_other_collection.call_count == 1


def test_has_import_blockers_agrees_with_find_import_blockers_on_the_reset_list() -> None:
    """The yes / no answer and the named list come from the same targets"""
    for leftover in RESET_TARGETS:
        counts: dict[str, int] = {target.collection: 0 for target in RESET_TARGETS}
        counts[leftover.collection] = 1

        assert has_import_blockers(_counting_manager(counts)) is bool(find_import_blockers(_counting_manager(counts)))
