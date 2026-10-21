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
Integration tests: the two reads by ``metadata.reference`` are served by the reference index

With the indexes a boot builds (``built_media_library_indexes``), the attachment list's filter (an object view's badge
and dialog: ``{reference, reference_type}`` through ``generate_metadata_filter``) and the detach an object delete runs
(``build_detach_objects_criteria``) each use the ``reference`` index - no collection scan - and find a file whose
reference is stored as one id and one whose reference is a list holding it
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.media_library.media_file_keys import MEDIA_FILE_REFERENCE_INDEX_NAME, OBJECT_REFERENCE_TYPE
from cmdb.manager.media_files_manager import MEDIA_FILES_COLLECTION, build_detach_objects_criteria
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import generate_metadata_filter

from tests.utils.media_library_indexes import built_media_library_indexes
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 88821
OTHER_OBJECT_ID: int = 88822

SCALAR_FILE_ID: int = 88831
LIST_FILE_ID: int = 88832
UNRELATED_FILE_ID: int = 88833
FILE_IDS: list[int] = [SCALAR_FILE_ID, LIST_FILE_ID, UNRELATED_FILE_ID]

METADATA_PARAMETER: str = 'metadata'


def _file(public_id: int, reference: Any) -> dict[str, Any]:
    """A stored media file document attached to ``reference``"""
    return {'public_id': public_id, 'filename': f'reference-index-{public_id}.txt',
            'metadata': {'reference': reference, 'reference_type': OBJECT_REFERENCE_TYPE, 'parent': None,
                         'folder': False}}


@pytest.fixture(name='files')
def fixture_files(database_manager: MongoDatabaseManager, database_name: str):
    """One file referencing the object by id, one by a list, one unrelated; the boot's indexes built"""
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    files.delete_many({'public_id': {'$in': FILE_IDS}})
    files.insert_many([
        _file(SCALAR_FILE_ID, OBJECT_ID),
        _file(LIST_FILE_ID, [OTHER_OBJECT_ID, OBJECT_ID]),
        _file(UNRELATED_FILE_ID, OTHER_OBJECT_ID),
    ])

    with built_media_library_indexes(database_manager, database_name):
        yield files

    files.delete_many({'public_id': {'$in': FILE_IDS}})


def _assert_served_by_the_reference_index(files: Any, criteria: dict[str, Any]) -> None:
    """The winning plan names the reference index and scans no collection"""
    plan: str = str(files.find(criteria).explain()['queryPlanner']['winningPlan'])

    assert MEDIA_FILE_REFERENCE_INDEX_NAME in plan
    assert 'COLLSCAN' not in plan


def _found(files: Any, criteria: dict[str, Any]) -> set[int]:
    """The seeded files the criteria match"""
    return {document['public_id'] for document in files.find(criteria)} & set(FILE_IDS)


def test_the_attachment_list_uses_the_reference_index(files) -> None:
    """The filter an object view sends: its id as the reference, 'object' as the kind"""
    criteria: dict[str, Any] = generate_metadata_filter(
        METADATA_PARAMETER, params={'reference': OBJECT_ID, 'reference_type': OBJECT_REFERENCE_TYPE},
    )

    _assert_served_by_the_reference_index(files, criteria)
    assert _found(files, criteria) == {SCALAR_FILE_ID, LIST_FILE_ID}


def test_the_object_delete_detach_uses_the_reference_index(files) -> None:
    """The detach's criteria for the deleted objects"""
    criteria: dict[str, Any] = build_detach_objects_criteria([OBJECT_ID])

    _assert_served_by_the_reference_index(files, criteria)
    assert _found(files, criteria) == {SCALAR_FILE_ID, LIST_FILE_ID}
