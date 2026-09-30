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
What an edit of a CmdbObject records about itself

Every write that edits a CmdbObject on a user's behalf owes the object three things beside the change
itself: a version bump, the edit stamp (``last_edit_time`` / ``editor_id``) and, once it is stored, a
change-log entry and an UPDATE webhook. The REST object update does all of it in its pipeline; a
feature that writes objects directly - the IPAM unassign writes - builds the same parts from here.

The first two belong to the write and are computed before it: ``plan_object_edit`` picks the bump
from the field-level diff (``compute_object_version``) into a ``PlannedEdit``, and ``build_edit_stamp``
names who edited when. The last two run after the write, in the route layer, which is where the log
and webhook helpers live. ``hand_over_object_writes`` reads the written objects back in one query and
passes each, as an ``ObjectWrite``, to an ``ObjectWriteCallback`` - which is how a framework
orchestrator reaches the route layer without importing it. The hand-over is best-effort like the log
and webhook it feeds: a failed read-back is logged under ``OBJECT_LOG_LOST_MARKER``, never raised.
"""
import copy
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Callable, NamedTuple

from cmdb.manager import ObjectsManager
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_LOST_MARKER
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.user_model.cmdb_user import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


class PlannedEdit(NamedTuple):
    """
    What an edit of one CmdbObject will record, computed before the write

    Attributes:
        before (CmdbObject): The object as it was read before the write
        version (str): The version the edit bumps the object to
        changes (dict[str, Any]): The field-level diff (``{'old': [...], 'new': [...]}``)
    """
    before: CmdbObject
    version: str
    changes: dict[str, Any]


class ObjectWrite(NamedTuple):
    """
    One stored edit of a CmdbObject, as the change log and the UPDATE webhook need it

    Attributes:
        before (CmdbObject): The object as it was read before the write
        after (CmdbObject): The object as it was read back after the write; carries the new version
        changes (dict[str, Any]): The field-level diff (``{'old': [...], 'new': [...]}``)
    """
    before: CmdbObject
    after: CmdbObject
    changes: dict[str, Any]


ObjectWriteCallback = Callable[[ObjectWrite], None]

# Decides whether a document read back after a batch write carries that batch's edit
WrittenCheck = Callable[[dict[str, Any], PlannedEdit], bool]


def compute_object_version(current_object: CmdbObject, updated_object: CmdbObject) -> tuple[str, dict[str, Any]]:
    """
    Derives the field-level diff and applies the resulting semantic version bump

    The bump is chosen from how many fields changed relative to the total field count: a single
    changed field is a PATCH, all fields a MAJOR, more than half a MINOR, and anything else a PATCH.
    ``updated_object`` is mutated in place with the new version, which is what makes the edit log's
    ``get_version()`` read agree with the version written into the document. Returning the string
    alone would leave the log recording every edit one bump behind

    Args:
        current_object (CmdbObject): The stored object before the update
        updated_object (CmdbObject): The candidate object after the update

    Returns:
        tuple[str, dict[str, Any]]: The new version string and the diff (as returned by ``/``)
    """
    changes: dict[str, Any] = current_object / updated_object

    changed_count: int = len(changes['new'])
    field_count: int = len(updated_object.fields)

    if changed_count == 1:
        version_type = updated_object.VERSIONING_PATCH
    elif changed_count == field_count:
        version_type = updated_object.VERSIONING_MAJOR
    elif changed_count > (field_count / 2):
        version_type = updated_object.VERSIONING_MINOR
    else:
        version_type = updated_object.VERSIONING_PATCH

    return updated_object.update_version(version_type), changes


def plan_object_edit(before_doc: dict[str, Any], after_doc: dict[str, Any]) -> PlannedEdit:
    """
    Computes what an edit of one stored CmdbObject document will record, before it is written

    Both documents are copied before they are read into a CmdbObject, because reading one normalises
    the document in place - the caller's documents are left as they were

    Args:
        before_doc (dict[str, Any]): The stored document
        after_doc (dict[str, Any]): The same document with the edit applied

    Returns:
        PlannedEdit: The object before the edit, the version the edit bumps it to, and the diff
    """
    before: CmdbObject = CmdbObject.from_data(copy.deepcopy(before_doc))
    updated: CmdbObject = CmdbObject.from_data(copy.deepcopy(after_doc))

    new_version, changes = compute_object_version(before, updated)

    return PlannedEdit(before, new_version, changes)


def build_edit_stamp(request_user: CmdbUser | None, edit_time: datetime | None = None) -> dict[str, Any]:
    """
    Builds the ``last_edit_time`` / ``editor_id`` values an edit writes onto a CmdbObject

    An internal caller with no request user stamps only the time: there is nobody to credit

    Args:
        request_user (CmdbUser | None): The CmdbUser making the edit, or None
        edit_time (datetime | None): The time to record; now (UTC) when None

    Returns:
        dict[str, Any]: The keys to ``$set`` alongside the edit
    """
    stamp: dict[str, Any] = {
        CmdbObjectKey.LAST_EDIT_TIME.value: edit_time or datetime.now(timezone.utc),
    }

    if request_user is not None:
        stamp[CmdbObjectKey.EDITOR_ID.value] = request_user.public_id

    return stamp


def load_object_writes(
        objects_manager: ObjectsManager,
        plans: dict[int, PlannedEdit],
        is_written: WrittenCheck | None = None,
    ) -> list[ObjectWrite]:
    """
    Reads the edited CmdbObjects back in one query and pairs each with its plan

    ``plans`` is keyed by public_id. An object that is gone by the time it is read back is left out,
    and so is one that ``is_written`` rejects - a batch write that skipped some of its targets passes
    the check that tells its own edits apart. Without one, every object read back counts as written

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        plans (dict[int, PlannedEdit]): The edits that were written, by public_id
        is_written (WrittenCheck | None): Whether a read-back document carries its plan's edit.
            Defaults to None (all of them do)

    Returns:
        list[ObjectWrite]: One entry per written object, in the order of ``plans``
    """
    if not plans:
        return []

    after_docs: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID.value: {'$in': list(plans)}},
        as_dict=True,
    )
    by_id: dict[int, dict[str, Any]] = {doc[CmdbObjectKey.PUBLIC_ID.value]: doc for doc in after_docs}

    writes: list[ObjectWrite] = []

    for public_id, plan in plans.items():
        after_doc: dict[str, Any] | None = by_id.get(public_id)

        if after_doc is None or (is_written is not None and not is_written(after_doc, plan)):
            continue

        writes.append(ObjectWrite(plan.before, CmdbObject.from_data(after_doc), plan.changes))

    return writes


def hand_over_object_writes(
        objects_manager: ObjectsManager,
        plans: dict[int, PlannedEdit],
        on_write: ObjectWriteCallback | None,
        is_written: WrittenCheck | None = None,
    ) -> None:
    """
    Hands every stored edit to ``on_write``, best-effort

    Runs after the objects are already stored, so nothing here may fail the request: a read-back that
    fails is logged under ``OBJECT_LOG_LOST_MARKER`` once per object whose change-log entry it costs,
    and never raised. No callback, or no plans, reads nothing

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        plans (dict[int, PlannedEdit]): The edits that were written, by public_id
        on_write (ObjectWriteCallback | None): Receives each written object; None skips the read-back
        is_written (WrittenCheck | None): See ``load_object_writes``. Defaults to None
    """
    if on_write is None or not plans:
        return

    try:
        writes: list[ObjectWrite] = load_object_writes(objects_manager, plans, is_written)
    except Exception:  # pylint: disable=broad-exception-caught
        for public_id in plans:
            LOGGER.error(
                "%s action=%s object_id=%s: %s",
                OBJECT_LOG_LOST_MARKER, LogAction.EDIT.name, public_id, 'the edited object could not be read back',
                exc_info=True,
            )

        return

    for write in writes:
        on_write(write)
