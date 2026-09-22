"""
Unit tests for cmdb.database.updater.versions.updater_20260916

Pure tests with a mocked MongoDatabaseManager. What matters here is the ordering and the choices,
not the I/O:

* the duplicate-group pipeline groups on BOTH halves of a file's identity - the filename AND the
  folder - because the same name in two folders is legal and must not be reported as a clash
* which duplicate keeps the name: the lowest public_id, with a member carrying none sorting last
* a duplicate is RENAMED, never deleted - it is uploaded content, not a label
* the rename picks the first free `copy_(n)_` name in that folder and never stacks prefixes
* the renaming runs BEFORE the index build, because MongoDB refuses to build a unique index over a
  collection that still holds duplicates
* the index spec is read from the model rather than copied into the migration, and an index that is
  already unique is left alone so a second run is a no-op
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    MediaFileKey,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
    LEGACY_MEDIA_FILE_NAME_INDEX_NAME,
)
from cmdb.database.updater.versions.updater_20260916 import (
    GROUP_IDENTITY_KEY,
    GROUP_MEMBERS_KEY,
    IDENTITY_FILENAME_KEY,
    IDENTITY_PARENT_KEY,
    MEDIA_FILES_COLLECTION,
    MEMBER_ID_KEY,
    MEMBER_PUBLIC_ID_KEY,
    Update20260916,
    build_free_name,
    deduplicate_media_files,
    find_duplicate_file_groups,
    rebuild_filename_index,
    select_keeper,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'


def _new() -> Update20260916:
    """Builds the updater without its real __init__ (the caller attaches the mocks it needs)"""
    return Update20260916.__new__(Update20260916)


def _member(document_id: str, public_id: Any = None) -> dict[str, Any]:
    """One member of a duplicate group, shaped like the aggregation output"""
    return {
        MEMBER_ID_KEY: document_id,
        MEMBER_PUBLIC_ID_KEY: public_id,
    }


def _group(filename: Any, parent: Any, members: list[dict[str, Any]]) -> dict[str, Any]:
    """One duplicate group, shaped like the aggregation output"""
    return {
        GROUP_IDENTITY_KEY: {
            IDENTITY_FILENAME_KEY: filename,
            IDENTITY_PARENT_KEY: parent,
        },
        GROUP_MEMBERS_KEY: members,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                               find_duplicate_file_groups                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindDuplicateFileGroups:
    """The aggregation that decides what counts as a duplicate."""

    def test_it_targets_the_gridfs_files_collection(self) -> None:
        """The bucket name holds no documents; `.files` does."""
        dbm = MagicMock()
        dbm.aggregate.return_value = []

        find_duplicate_file_groups(dbm, DB_NAME)

        assert dbm.aggregate.call_args[0][0] == MEDIA_FILES_COLLECTION
        assert MEDIA_FILES_COLLECTION.endswith('.files')

    def test_it_groups_on_both_identity_halves(self) -> None:
        """Grouping on the filename alone would report two folders' same-named files as a clash."""
        dbm = MagicMock()
        dbm.aggregate.return_value = []

        find_duplicate_file_groups(dbm, DB_NAME)

        pipeline = dbm.aggregate.call_args[0][2]
        group_id = pipeline[0]['$group'][GROUP_IDENTITY_KEY]

        assert group_id[IDENTITY_FILENAME_KEY] == f'${MediaFileKey.FILENAME.value}'
        assert group_id[IDENTITY_PARENT_KEY] == f'${MEDIA_FILE_PARENT_PATH}'

    def test_it_keeps_only_groups_with_more_than_one_member(self) -> None:
        """A file that is alone in its folder is not a duplicate."""
        dbm = MagicMock()
        dbm.aggregate.return_value = []

        find_duplicate_file_groups(dbm, DB_NAME)

        pipeline = dbm.aggregate.call_args[0][2]

        assert pipeline[1]['$match'] == {f'{GROUP_MEMBERS_KEY}.1': {'$exists': True}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     select_keeper                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSelectKeeper:
    """Which of several identically-named files keeps the name."""

    def test_the_lowest_public_id_wins(self) -> None:
        """The oldest entry, and the one an existing reference is most likely to point at."""
        keeper = select_keeper([_member('b', 9), _member('a', 3), _member('c', 7)])

        assert keeper == 'a'

    def test_a_member_without_a_public_id_never_wins(self) -> None:
        """A malformed document must not displace a well-formed file."""
        keeper = select_keeper([_member('broken'), _member('good', 5)])

        assert keeper == 'good'

    def test_it_is_deterministic_for_one_member(self) -> None:
        """A single-member list still answers that member."""
        assert select_keeper([_member('only', 1)]) == 'only'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    build_free_name                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFreeName:
    """The rename scheme, mirroring `create_attachment_name` in the routes."""

    def test_a_free_name_is_returned_unchanged(self) -> None:
        """Nothing is renamed that does not have to be."""
        assert build_free_name('diagram.png', set()) == 'diagram.png'

    def test_the_first_clash_becomes_copy_1(self) -> None:
        """The same prefix the upload route would have applied."""
        assert build_free_name('diagram.png', {'diagram.png'}) == 'copy_(1)_diagram.png'

    def test_it_walks_until_the_folder_has_no_such_name(self) -> None:
        """Three files of the same name need three distinct results."""
        taken = {'diagram.png', 'copy_(1)_diagram.png'}

        assert build_free_name('diagram.png', taken) == 'copy_(2)_diagram.png'

    def test_it_does_not_stack_prefixes(self) -> None:
        """A re-run must not produce 'copy_(2)_copy_(1)_diagram.png'."""
        taken = {'diagram.png', 'copy_(1)_diagram.png', 'copy_(2)_diagram.png'}

        assert build_free_name('diagram.png', taken) == 'copy_(3)_diagram.png'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                deduplicate_media_files                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeduplicateMediaFiles:
    """The renaming half."""

    @patch('cmdb.database.updater.versions.updater_20260916.taken_names_in_folder')
    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_it_renames_every_member_but_the_keeper(self, groups, taken) -> None:
        """Two duplicates of one name leave one untouched and rename the other."""
        dbm = MagicMock()
        groups.return_value = [_group('diagram.png', 0, [_member('a', 3), _member('b', 9)])]
        taken.return_value = {'diagram.png'}

        renamed = deduplicate_media_files(dbm, DB_NAME)

        assert renamed == 1
        assert dbm.update.call_count == 1

    @patch('cmdb.database.updater.versions.updater_20260916.taken_names_in_folder')
    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_it_never_deletes(self, groups, taken) -> None:
        """A media file is uploaded content: it keeps its bytes, its public_id and its references."""
        dbm = MagicMock()
        groups.return_value = [_group('diagram.png', 0, [_member('a', 3), _member('b', 9)])]
        taken.return_value = {'diagram.png'}

        deduplicate_media_files(dbm, DB_NAME)

        dbm.delete.assert_not_called()
        dbm.delete_many.assert_not_called()

    @patch('cmdb.database.updater.versions.updater_20260916.taken_names_in_folder')
    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_it_addresses_the_rename_by_document_id(self, groups, taken) -> None:
        """`_id` is always present; public_id is what a malformed document may be missing."""
        dbm = MagicMock()
        groups.return_value = [_group('diagram.png', 0, [_member('keeper', 1), _member('loser', 2)])]
        taken.return_value = {'diagram.png'}

        deduplicate_media_files(dbm, DB_NAME)

        criteria = dbm.update.call_args[0][2]
        data = dbm.update.call_args[0][3]

        assert criteria == {'_id': 'loser'}
        assert data == {MediaFileKey.FILENAME.value: 'copy_(1)_diagram.png'}

    @patch('cmdb.database.updater.versions.updater_20260916.taken_names_in_folder')
    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_two_losers_get_two_different_names(self, groups, taken) -> None:
        """The name taken by the first rename is not offered to the second."""
        dbm = MagicMock()
        groups.return_value = [
            _group('diagram.png', 0, [_member('keeper', 1), _member('l1', 2), _member('l2', 3)]),
        ]
        taken.return_value = {'diagram.png'}

        deduplicate_media_files(dbm, DB_NAME)

        written = [call[0][3][MediaFileKey.FILENAME.value] for call in dbm.update.call_args_list]

        assert written == ['copy_(1)_diagram.png', 'copy_(2)_diagram.png']
        assert len(set(written)) == 2

    @patch('cmdb.database.updater.versions.updater_20260916.taken_names_in_folder')
    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_a_group_without_a_usable_filename_is_left_alone(self, groups, taken) -> None:
        """There is no free name to build from nothing; the operator is told instead."""
        dbm = MagicMock()
        groups.return_value = [_group(None, 0, [_member('a', 1), _member('b', 2)])]

        renamed = deduplicate_media_files(dbm, DB_NAME)

        assert renamed == 0
        dbm.update.assert_not_called()
        taken.assert_not_called()

    @patch('cmdb.database.updater.versions.updater_20260916.find_duplicate_file_groups')
    def test_no_duplicates_writes_nothing(self, groups) -> None:
        """A second run finds nothing to do."""
        dbm = MagicMock()
        groups.return_value = []

        assert deduplicate_media_files(dbm, DB_NAME) == 0
        dbm.update.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                rebuild_filename_index                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRebuildFilenameIndex:
    """The index half."""

    def test_it_creates_the_index_when_absent(self) -> None:
        """The ordinary case: no database has ever carried this index."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {}

        assert rebuild_filename_index(dbm, DB_NAME) is True
        dbm.create_indexes.assert_called_once()

    def test_it_reads_the_spec_from_the_model(self) -> None:
        """Copying the spec into the migration would let the two drift apart."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {}

        rebuild_filename_index(dbm, DB_NAME)

        created = dbm.create_indexes.call_args[0][2][0]
        declared = next(
            index for index in MediaFile.INDEX_KEYS
            if index['name'] == MEDIA_FILE_FILENAME_PARENT_INDEX_NAME
        )

        assert created.document['name'] == declared['name']
        assert created.document['unique'] is True

    def test_an_already_unique_index_is_left_alone(self) -> None:
        """A second run must not drop and rebuild a correct index."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {
            MEDIA_FILE_FILENAME_PARENT_INDEX_NAME: {'unique': True},
        }

        assert rebuild_filename_index(dbm, DB_NAME) is False
        dbm.create_indexes.assert_not_called()
        dbm.drop_index.assert_not_called()

    def test_a_non_unique_index_of_the_same_name_is_rebuilt(self) -> None:
        """A unique flag cannot be added in place."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {
            MEDIA_FILE_FILENAME_PARENT_INDEX_NAME: {},
        }

        assert rebuild_filename_index(dbm, DB_NAME) is True
        dbm.drop_index.assert_called_once_with(
            MEDIA_FILES_COLLECTION, DB_NAME, MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
        )
        dbm.create_indexes.assert_called_once()

    def test_the_legacy_name_index_is_dropped_when_present(self) -> None:
        """It indexed a key no document carries, so nothing can depend on it."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {LEGACY_MEDIA_FILE_NAME_INDEX_NAME: {'unique': True}}

        rebuild_filename_index(dbm, DB_NAME)

        dbm.drop_index.assert_any_call(
            MEDIA_FILES_COLLECTION, DB_NAME, LEGACY_MEDIA_FILE_NAME_INDEX_NAME,
        )

    def test_a_missing_declaration_builds_nothing(self) -> None:
        """Defensive: if the model stops declaring the index, the migration must not invent one."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {}

        with patch.object(MediaFile, 'INDEX_KEYS', []):
            assert rebuild_filename_index(dbm, DB_NAME) is False

        dbm.create_indexes.assert_not_called()

    def test_the_legacy_index_is_not_dropped_when_absent(self) -> None:
        """Housekeeping only; a database that never had it is untouched."""
        dbm = MagicMock()
        dbm.get_index_info.return_value = {}

        rebuild_filename_index(dbm, DB_NAME)

        for drop_call in dbm.drop_index.call_args_list:
            assert drop_call[0][2] != LEGACY_MEDIA_FILE_NAME_INDEX_NAME


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    Update20260916                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStartUpdate:
    """The order of the two halves, and the version bump."""

    @patch('cmdb.database.updater.versions.updater_20260916.rebuild_filename_index')
    @patch('cmdb.database.updater.versions.updater_20260916.deduplicate_media_files')
    def test_it_deduplicates_before_building_the_index(self, dedupe, rebuild) -> None:
        """MongoDB refuses to build a unique index over a collection that still holds duplicates."""
        order: list[str] = []
        dedupe.side_effect = lambda *_: order.append('dedupe') or 0
        rebuild.side_effect = lambda *_: order.append('index') or True

        updater = _new()
        updater.dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        updater.start_update()

        assert order == ['dedupe', 'index']

    @patch('cmdb.database.updater.versions.updater_20260916.rebuild_filename_index')
    @patch('cmdb.database.updater.versions.updater_20260916.deduplicate_media_files')
    def test_it_bumps_the_version_last(self, dedupe, rebuild) -> None:
        """A crash between the halves must leave the version untouched so the next boot starts over."""
        dedupe.return_value = 0
        rebuild.return_value = True

        updater = _new()
        updater.dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        updater.start_update()

        updater.increase_updater_version.assert_called_once_with(20260916)

    @patch('cmdb.database.updater.versions.updater_20260916.deduplicate_media_files')
    def test_a_failure_does_not_bump_the_version(self, dedupe) -> None:
        """The whole point of bumping last."""
        dedupe.side_effect = RuntimeError('boom')

        updater = _new()
        updater.dbm = MagicMock()
        updater.db_name = DB_NAME
        updater.increase_updater_version = MagicMock()

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()

    def test_the_creation_date_matches_the_module(self) -> None:
        """The registry, the module name and this value have to agree."""
        assert _new().creation_date() == 20260916

    def test_it_describes_what_it_does(self) -> None:
        """The description is what the progress output shows while the migration runs."""
        assert 'MediaFile' in _new().description()
