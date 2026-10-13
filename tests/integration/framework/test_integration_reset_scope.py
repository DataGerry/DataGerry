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
Integration tests of the configuration reset scope against a real MongoDB

On a scratch database of its own (the session database carries seeded and left-over documents): what the reset
keeps never counts as left over, one document per target makes every target count, in list order, and the
criteria are answered by the server the way the reset will ask them - the root location, a predefined flag and an
unattached media file are told apart by the query, not by Python
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.configuration_transfer import RESET_TARGETS, find_import_blockers, find_non_empty_targets
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MediaFileKey,
    MediaFileMetadataKey,
    OBJECT_REFERENCE_TYPE,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
from cmdb.models.extendable_option_model import CmdbExtendableOption
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-reset-scope'
PUBLIC_ID_KEY: str = 'public_id'
LEFT_OVER_ID: int = 2
PREDEFINED_KEY: str = SectionTemplateKey.PREDEFINED.value
MEDIA_FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
OTHER_REFERENCE_TYPE: str = 'folder-note'


def _media_file(reference_type: str | None) -> dict[str, Any]:
    """A GridFS file document with the given reference kind"""
    return {PUBLIC_ID_KEY: LEFT_OVER_ID, MediaFileKey.METADATA.value: {
        MediaFileMetadataKey.REFERENCE_TYPE.value: reference_type,
    }}


# One document per collection the reset keeps - none of them may count as left over
KEPT_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    CmdbLocation.COLLECTION: [{LocationKey.PUBLIC_ID.value: RootLocationDefault.PUBLIC_ID}],
    CmdbSectionTemplate.COLLECTION: [{PUBLIC_ID_KEY: 1, PREDEFINED_KEY: True}],
    CmdbReportCategory.COLLECTION: [{PUBLIC_ID_KEY: 1, PREDEFINED_KEY: True}],
    MEDIA_FILES_COLLECTION: [_media_file(None), _media_file(OTHER_REFERENCE_TYPE)],
    CmdbUser.COLLECTION: [{PUBLIC_ID_KEY: 1}],
    CmdbExtendableOption.COLLECTION: [{PUBLIC_ID_KEY: 1}],
}

# The document that makes a target count, where a bare public_id would not
LEFT_OVER_DOCUMENTS: dict[str, dict[str, Any]] = {
    CmdbLocation.COLLECTION: {LocationKey.PUBLIC_ID.value: LEFT_OVER_ID},
    CmdbSectionTemplate.COLLECTION: {PUBLIC_ID_KEY: LEFT_OVER_ID, PREDEFINED_KEY: False},
    MEDIA_FILES_COLLECTION: _media_file(OBJECT_REFERENCE_TYPE),
}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A database of this module's own, dropped before and after each test"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    database_manager.connector.client.drop_database(scratch)

    yield scratch

    database_manager.connector.client.drop_database(scratch)


def _manager(database_manager: MongoDatabaseManager, scratch: str) -> BaseManager:
    """Any manager of the scratch database"""
    return BaseManager(CmdbType.COLLECTION, database_manager, scratch)


def _seed(database_manager: MongoDatabaseManager, scratch: str, documents: dict[str, list[dict[str, Any]]]) -> None:
    """Inserts the documents raw, per collection"""
    for collection, rows in documents.items():
        database_manager.get_collection(collection, scratch).insert_many([dict(row) for row in rows])


def _seed_left_overs(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One document per reset target that the target's criteria match"""
    _seed(database_manager, scratch, {
        target.collection: [LEFT_OVER_DOCUMENTS.get(target.collection, {PUBLIC_ID_KEY: LEFT_OVER_ID})]
        for target in RESET_TARGETS
    })


def test_an_empty_database_has_nothing_left(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """No collection at all -> no target counts, the import may run"""
    manager: BaseManager = _manager(database_manager, scratch)

    assert not find_non_empty_targets(manager)
    assert not find_import_blockers(manager)


def test_what_the_reset_keeps_is_not_left_over(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Root location, predefined template and category, unattached media, users and options do not count"""
    _seed(database_manager, scratch, KEPT_DOCUMENTS)
    manager: BaseManager = _manager(database_manager, scratch)

    assert not find_non_empty_targets(manager)
    assert not find_import_blockers(manager)


def test_every_target_counts_in_list_order(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One matching document per target, beside the kept ones -> every target named, in list order"""
    _seed(database_manager, scratch, KEPT_DOCUMENTS)
    _seed_left_overs(database_manager, scratch)
    manager: BaseManager = _manager(database_manager, scratch)
    every_collection: list[str] = [target.collection for target in RESET_TARGETS]

    assert find_non_empty_targets(manager) == every_collection
    assert find_import_blockers(manager) == [c for c in every_collection if c != CmdbUserSetting.COLLECTION]


def test_an_absent_predefined_flag_counts_as_user_made(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """A section template or report category without the flag is the user's - and left over"""
    _seed(database_manager, scratch, {
        CmdbSectionTemplate.COLLECTION: [{PUBLIC_ID_KEY: LEFT_OVER_ID}],
        CmdbReportCategory.COLLECTION: [{PUBLIC_ID_KEY: LEFT_OVER_ID}],
    })

    assert find_import_blockers(_manager(database_manager, scratch)) == [
        CmdbReportCategory.COLLECTION,
        CmdbSectionTemplate.COLLECTION,
    ]


def test_left_over_user_settings_do_not_block_the_import(database_manager: MongoDatabaseManager,
                                                         scratch: str) -> None:
    """Settings written after the reset are left over, but the import still may run"""
    _seed(database_manager, scratch, {CmdbUserSetting.COLLECTION: [{PUBLIC_ID_KEY: LEFT_OVER_ID}]})
    manager: BaseManager = _manager(database_manager, scratch)

    assert find_non_empty_targets(manager) == [CmdbUserSetting.COLLECTION]
    assert not find_import_blockers(manager)
