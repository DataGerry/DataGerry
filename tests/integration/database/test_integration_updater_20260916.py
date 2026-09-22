"""
Integration tests for cmdb.database.updater.versions.updater_20260916 against a real MongoDB

Reproduces a pre-migration media library: `media.libary.files` carries no unique index and holds
duplicates in three shapes - two files with the same name in the SAME folder, three files with the
same name at the library ROOT (where the parent is null), and two files sharing a name across two
DIFFERENT folders, which is legal and must survive untouched.

Asserts the migration keeps the lowest public_id's name, renames the rest with the routes' own
`copy_(n)_` scheme, leaves the cross-folder pair alone, builds the unique index on the `.files`
collection, bumps the persisted updater version, is idempotent on a second run, and that a duplicate
is refused afterwards. That refusal is the guarantee the whole migration exists to establish.
"""
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260916 import (
    MEDIA_FILES_COLLECTION,
    Update20260916,
)
from cmdb.framework.media_library.media_file_keys import (
    MediaFileKey,
    MediaFileMetadataKey,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
    LEGACY_MEDIA_FILE_NAME_INDEX_NAME,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Two files of the same name inside one folder: the lowest public_id keeps it
FOLDER_ID: int = 7
CLASH_NAME: str = 'integration-duplicate-diagram.png'
CLASH_KEEPER_ID: int = 999510
CLASH_LOSER_ID: int = 999512

# Three files of the same name at the ROOT, where the parent is null - a unique index treats every
# missing value as the same null, so these collide too
ROOT_NAME: str = 'integration-duplicate-root.png'
ROOT_KEEPER_ID: int = 999520
ROOT_LOSER_ONE_ID: int = 999522
ROOT_LOSER_TWO_ID: int = 999524

# The same name in two DIFFERENT folders: legal, and the reason the index is on the pair
CROSS_NAME: str = 'integration-cross-folder.png'
CROSS_FOLDER_A: int = 11
CROSS_FOLDER_B: int = 12
CROSS_A_ID: int = 999530
CROSS_B_ID: int = 999532

FILE_IDS: list[int] = [
    CLASH_KEEPER_ID, CLASH_LOSER_ID,
    ROOT_KEEPER_ID, ROOT_LOSER_ONE_ID, ROOT_LOSER_TWO_ID,
    CROSS_A_ID, CROSS_B_ID,
]

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'
UPDATER_VERSION: int = 20260916


def _file_doc(public_id: int, filename: str, parent: Any) -> dict[str, Any]:
    """Builds a GridFS-shaped MediaFile document"""
    return {
        MediaFileKey.PUBLIC_ID.value: public_id,
        MediaFileKey.FILENAME.value: filename,
        MediaFileKey.METADATA.value: {
            MediaFileMetadataKey.PARENT.value: parent,
            MediaFileMetadataKey.AUTHOR_ID.value: 1,
            MediaFileMetadataKey.FOLDER.value: False,
        },
    }


def _name_of(files, public_id: int) -> str:
    """Reads one file's current filename"""
    return files.find_one({MediaFileKey.PUBLIC_ID.value: public_id})[MediaFileKey.FILENAME.value]


@pytest.fixture(name='pre_migration_files', autouse=True)
def fixture_pre_migration_files(database_manager: MongoDatabaseManager, database_name: str):
    """
    Recreates a pre-migration collection: no unique index, plus duplicates in three shapes

    The unique index has to be absent before the duplicates can be inserted at all - which is exactly
    the state every database created before this migration is in.
    """
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    def _purge() -> None:
        files.delete_many({MediaFileKey.PUBLIC_ID.value: {'$in': FILE_IDS}})

    def _drop_index(name: str) -> None:
        if name in files.index_information():
            files.drop_index(name)

    _purge()
    _drop_index(MEDIA_FILE_FILENAME_PARENT_INDEX_NAME)
    _drop_index(LEGACY_MEDIA_FILE_NAME_INDEX_NAME)

    files.insert_many([
        _file_doc(CLASH_KEEPER_ID, CLASH_NAME, FOLDER_ID),
        _file_doc(CLASH_LOSER_ID, CLASH_NAME, FOLDER_ID),
        _file_doc(ROOT_KEEPER_ID, ROOT_NAME, None),
        _file_doc(ROOT_LOSER_ONE_ID, ROOT_NAME, None),
        _file_doc(ROOT_LOSER_TWO_ID, ROOT_NAME, None),
        _file_doc(CROSS_A_ID, CROSS_NAME, CROSS_FOLDER_A),
        _file_doc(CROSS_B_ID, CROSS_NAME, CROSS_FOLDER_B),
    ])

    yield files

    _purge()
    _drop_index(MEDIA_FILE_FILENAME_PARENT_INDEX_NAME)

    if previous_setting is None:
        settings.delete_one({'_id': UPDATER_SETTINGS_ID})
    else:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)


@pytest.fixture(name='migrated')
def fixture_migrated(database_manager: MongoDatabaseManager, database_name: str, pre_migration_files):
    """Runs the migration once and hands back the files collection"""
    Update20260916(database_manager, database_name).start_update()

    return pre_migration_files


class TestRenaming:
    """What happens to the duplicates."""

    def test_the_lowest_public_id_keeps_its_name(self, migrated) -> None:
        """The oldest entry, and the one an existing reference is most likely to point at."""
        assert _name_of(migrated, CLASH_KEEPER_ID) == CLASH_NAME

    def test_the_other_member_is_renamed(self, migrated) -> None:
        """Exactly the name the upload route would have given it."""
        assert _name_of(migrated, CLASH_LOSER_ID) == f'copy_(1)_{CLASH_NAME}'

    def test_nothing_is_deleted(self, migrated) -> None:
        """A media file is uploaded content: every document survives."""
        found = migrated.count_documents({MediaFileKey.PUBLIC_ID.value: {'$in': FILE_IDS}})

        assert found == len(FILE_IDS)

    def test_three_root_duplicates_become_three_distinct_names(self, migrated) -> None:
        """A null parent is a value like any other, so the root collides too."""
        names = {
            _name_of(migrated, ROOT_KEEPER_ID),
            _name_of(migrated, ROOT_LOSER_ONE_ID),
            _name_of(migrated, ROOT_LOSER_TWO_ID),
        }

        assert names == {ROOT_NAME, f'copy_(1)_{ROOT_NAME}', f'copy_(2)_{ROOT_NAME}'}

    def test_the_same_name_in_two_folders_is_left_alone(self, migrated) -> None:
        """The whole reason the index is on the pair and not on the filename."""
        assert _name_of(migrated, CROSS_A_ID) == CROSS_NAME
        assert _name_of(migrated, CROSS_B_ID) == CROSS_NAME


class TestIndex:
    """The index the migration exists to build."""

    def test_the_unique_index_is_built(self, migrated) -> None:
        """On the `.files` collection - the bucket name holds no documents."""
        info = migrated.index_information()

        assert MEDIA_FILE_FILENAME_PARENT_INDEX_NAME in info
        assert info[MEDIA_FILE_FILENAME_PARENT_INDEX_NAME].get('unique') is True

    def test_the_index_covers_both_identity_halves(self, migrated) -> None:
        """Filename first, so a lookup by name alone can still use it as a prefix."""
        keys = migrated.index_information()[MEDIA_FILE_FILENAME_PARENT_INDEX_NAME]['key']

        assert [key for key, _ in keys] == [MediaFileKey.FILENAME.value, MEDIA_FILE_PARENT_PATH]

    def test_a_duplicate_is_refused_afterwards(self, migrated) -> None:
        """The guarantee the whole migration exists to establish."""
        with pytest.raises(DuplicateKeyError):
            migrated.insert_one(_file_doc(999599, CLASH_NAME, FOLDER_ID))

    def test_the_same_name_in_another_folder_is_still_accepted(self, migrated) -> None:
        """The index must not forbid what the application considers legal."""
        migrated.insert_one(_file_doc(999598, CLASH_NAME, CROSS_FOLDER_A))

        assert _name_of(migrated, 999598) == CLASH_NAME

        migrated.delete_one({MediaFileKey.PUBLIC_ID.value: 999598})


class TestVersionAndRerun:
    """The bookkeeping, and running it twice."""

    def test_it_bumps_the_persisted_version(
        self, migrated, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Each updater records its own completion; nothing else does it for it."""
        settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
        stored = settings.find_one({'_id': UPDATER_SETTINGS_ID})

        assert stored['version'] == UPDATER_VERSION

    def test_a_second_run_changes_nothing(
        self, migrated, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Re-run safety: an interrupted migration is restarted from the top on the next boot."""
        before = {
            public_id: _name_of(migrated, public_id) for public_id in FILE_IDS
        }

        Update20260916(database_manager, database_name).start_update()

        after = {
            public_id: _name_of(migrated, public_id) for public_id in FILE_IDS
        }

        assert after == before

    def test_a_second_run_leaves_the_index_in_place(
        self, migrated, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An already-unique index is left alone rather than dropped and rebuilt."""
        Update20260916(database_manager, database_name).start_update()

        info = migrated.index_information()

        assert info[MEDIA_FILE_FILENAME_PARENT_INDEX_NAME].get('unique') is True
