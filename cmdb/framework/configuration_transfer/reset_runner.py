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
Runs a configuration reset: walks the reset list in order, deletes each target's documents and sets its counter back

Nothing here is compensated - the deleted documents are not kept. The run is re-run safe instead: every target is
deleted by its criteria and its counter derived from what is still stored, so running the reset again after a
failure midway deletes what is left and reaches the same end state. The list's order (definitions last) makes sure
a failed run leaves a system that still has its types.

A GridFS target is deleted in rounds of `RESET_DELETE_BATCH_SIZE` files, each through the shared
``gridfs_helper.delete_gridfs_files``: the chunks of a round first, then its file documents. A run that stops between
the two leaves file documents without chunks, which the next run deletes - never chunks without a file document,
which nothing would find again
"""
from typing import Any

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.gridfs_helper import delete_gridfs_files
from cmdb.framework.configuration_transfer.configuration_transfer_constants import RESET_DELETE_BATCH_SIZE
from cmdb.framework.configuration_transfer.reset_scope import RESET_TARGETS, ResetTarget
# -------------------------------------------------------------------------------------------------------------------- #

MONGO_ID_KEY: str = '_id'


def delete_gridfs_target(manager: BaseManager, target: ResetTarget, batch_size: int = RESET_DELETE_BATCH_SIZE) -> int:
    """
    Deletes every file a GridFS target matches, chunks first, in rounds of at most `batch_size` files

    Args:
        manager (BaseManager): Any manager of the tenant's database
        target (ResetTarget): The target; `collection` is the bucket's file collection, `gridfs_bucket` the bucket
        batch_size (int): How many files one round deletes

    Raises:
        BaseManagerGetError: When the file documents could not be read
        BaseManagerDeleteError: When chunks or file documents could not be deleted

    Returns:
        int: The number of file documents deleted
    """
    deleted: int = 0

    while True:
        files: list[dict[str, Any]] = manager.get_many_from_other_collection(
            target.collection, direction=1, limit=batch_size, projection={MONGO_ID_KEY: 1},
            criteria=target.deletion_criteria(),
        )

        if not files:
            return deleted

        deleted += delete_gridfs_files(manager, target.gridfs_bucket, [file[MONGO_ID_KEY] for file in files])


def clear_target(manager: BaseManager, target: ResetTarget) -> int:
    """
    Deletes the documents one reset target matches and sets its counter back, if it has one

    Args:
        manager (BaseManager): Any manager of the tenant's database
        target (ResetTarget): The target

    Raises:
        BaseManagerGetError: When a GridFS target's files could not be read
        BaseManagerDeleteError: When the documents could not be deleted
        BaseManagerUpdateError: When the counter could not be set back

    Returns:
        int: The number of documents deleted
    """
    if target.gridfs_bucket:
        deleted: int = delete_gridfs_target(manager, target)
    else:
        deleted = manager.delete_many_from_other_collection(target.collection, target.deletion_criteria()).deleted_count

    if target.counter:
        manager.reset_public_id_counter_of(target.collection, target.counter)

    return deleted


def run_reset(manager: BaseManager, targets: tuple[ResetTarget, ...] = RESET_TARGETS) -> dict[str, int]:
    """
    Clears every reset target, in list order

    Stops at the first failure and raises it: the targets before it are cleared, the rest untouched - running the
    reset again finishes the job

    Args:
        manager (BaseManager): Any manager of the tenant's database
        targets (tuple[ResetTarget, ...]): The targets to clear, the reset list by default

    Raises:
        BaseManagerGetError: When a GridFS target's files could not be read
        BaseManagerDeleteError: When documents could not be deleted
        BaseManagerUpdateError: When a counter could not be set back

    Returns:
        dict[str, int]: The number of documents deleted per collection, in list order
    """
    return {target.collection: clear_target(manager, target) for target in targets}
