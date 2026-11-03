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
Integration tests for the media library list read, against a real MongoDB and real GridFS

Through the real ``MediaFilesManager.get_many_media_files`` with the filters the list route builds:

  - the search filter matches its term literally - ``a.b`` finds ``a.b`` and not ``axb``, ``(1`` finds ``report (1)``
  - a metadata filter built by ``build_metadata_filter`` finds a file by its reference, stored as one id or a list
  - the read runs under its time budget: a read that costs more than the budget is stopped by the server and
    arrives as the manager's read error carrying ``DocumentQueryTimeLimitError``
"""
from io import BytesIO
from typing import Any

import pytest
from werkzeug.datastructures import FileStorage

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager.media_files_manager import MediaFileManagerGetError
from cmdb.framework.media_library import MediaFile
from cmdb.manager import media_files_manager as manager_module
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.utils import find_cause
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    build_metadata_filter,
    build_search_filter,
)
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 77
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
CHUNKS_COLLECTION: str = f'{MediaFile.COLLECTION}.chunks'
DOTTED_NAME: str = 'dg-int-lf-a.b'
LOOKALIKE_NAME: str = 'dg-int-lf-axb'
BRACKET_NAME: str = 'dg-int-lf-report (1)'
REFERENCED_NAME: str = 'dg-int-lf-attached'
LISTED_NAME: str = 'dg-int-lf-attached-list'
OBJECT_ID: int = 88931
BURNING_FILES: int = 20
# Each file costs this many additions in the burning filter - far more than a 1 ms budget allows
BURN_LENGTH: int = 200000
TINY_BUDGET_MS: int = 1


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The real manager over a library seeded with this module's files; purged before and after"""
    files = database_manager.get_collection(FILES_COLLECTION, database_name)
    chunks = database_manager.get_collection(CHUNKS_COLLECTION, database_name)

    def _purge() -> None:
        for doc in list(files.find({'metadata.author_id': AUTHOR_ID})):
            chunks.delete_many({'files_id': doc['_id']})
            files.delete_one({'_id': doc['_id']})

    _purge()
    manager = MediaFilesManager(database_manager)

    for name, extra in ((DOTTED_NAME, {}), (LOOKALIKE_NAME, {}), (BRACKET_NAME, {}),
                        (REFERENCED_NAME, {'reference': OBJECT_ID, 'reference_type': 'object'}),
                        (LISTED_NAME, {'reference': [OBJECT_ID, OBJECT_ID + 1], 'reference_type': 'object'})):
        manager.insert_file(FileStorage(stream=BytesIO(b'x'), filename=name, content_type='text/plain'),
                            {'author_id': AUTHOR_ID, **extra})

    yield manager

    _purge()


def _names(manager: MediaFilesManager, criteria: dict[str, Any]) -> set[str]:
    """This module's files the read answers"""
    found = manager.get_many_media_files({'$and': [criteria, {'metadata.author_id': AUTHOR_ID}]}).results
    return {row['filename'] for row in found}


@pytest.mark.parametrize('term, expected', [
    ('a.b', {DOTTED_NAME}), ('(1', {BRACKET_NAME}), ('report (1)', {BRACKET_NAME}), ('[', set()),
], ids=['dot', 'open-bracket', 'brackets', 'square-bracket'])
def test_the_search_matches_literally(manager: MediaFilesManager, term: str, expected: set[str]) -> None:
    """No pattern, and no failed read for an unbalanced bracket"""
    assert _names(manager, build_search_filter(term)) == expected


def test_a_reference_filter_finds_one_id_and_a_list(manager: MediaFilesManager) -> None:
    """The attachment dialog's filter"""
    criteria = build_metadata_filter({'reference': OBJECT_ID, 'reference_type': 'object'})

    assert _names(manager, criteria) == {REFERENCED_NAME, LISTED_NAME}


def test_a_read_past_its_budget_is_stopped_with_the_typed_error(manager: MediaFilesManager, monkeypatch) -> None:
    """The server stops it; the manager's read error carries the time-limit error"""
    monkeypatch.setattr(manager_module, 'QUERY_TIME_LIMIT_MS', TINY_BUDGET_MS)
    for index in range(BURNING_FILES):
        manager.insert_file(FileStorage(stream=BytesIO(b'x'), filename=f'dg-int-lf-burn-{index}'),
                            {'author_id': AUTHOR_ID})
    burning: dict[str, Any] = {'$expr': {'$gte': [{'$reduce': {
        'input': {'$range': [0, BURN_LENGTH]}, 'initialValue': 0, 'in': {'$add': ['$$value', '$$this']},
    }}, 0]}}

    with pytest.raises(MediaFileManagerGetError) as caught:
        manager.get_many_media_files({'$and': [burning, {'metadata.author_id': AUTHOR_ID}]})

    typed = find_cause(caught.value, DocumentQueryTimeLimitError)
    assert typed is not None
    assert typed.time_limit_ms == TINY_BUDGET_MS
