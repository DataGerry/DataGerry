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
The writes of the object import: the batched insert of its new objects and the overwrite of a stored one

A chunk of new objects (none carries a public_id) costs one id reservation and one unordered insert, and every
object's outcome stays its own: an object the model cannot hold or the database refuses is answered by its
position in the chunk, while the others are written.

An overwrite is one atomic replace of the stored document under its public_id (``replace_stored_object``), so a
refused or interrupted write leaves the stored object exactly as it was. It is an edit of that object
(``plan_overwrite``): who created it and when are kept, the importer is stamped as its editor, and its version is
bumped by what changed
"""
from typing import Any

from pymongo.results import UpdateResult

from cmdb.manager import ObjectsManager
from cmdb.manager.objects_manager import OBJECT_DOCUMENT_ERRORS
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.object_edit import PlannedEdit, build_edit_stamp, plan_object_edit

from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.errors.manager.objects_manager import ObjectsManagerInsertError, ObjectsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

def serialise_new_objects(
        documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int], dict[int, Exception]]:
    """
    Builds the stored form of every object - what ``ObjectsManager.insert_object`` stores - one object at a time

    Args:
        documents (list[dict[str, Any]]): The normalised objects, each with its public_id

    Returns:
        tuple[list[dict[str, Any]], list[int], dict[int, Exception]]: The stored forms, the position in
            ``documents`` of each of them, and an ObjectsManagerInsertError by position for every object the
            model could not hold
    """
    serialised: list[dict[str, Any]] = []
    positions: list[int] = []
    failures: dict[int, Exception] = {}

    for position, document in enumerate(documents):
        try:
            serialised.append(CmdbObject.to_json(CmdbObject.from_data(document)))
            positions.append(position)
        except OBJECT_DOCUMENT_ERRORS as err:
            failures[position] = ObjectsManagerInsertError(err)

    return serialised, positions, failures


def insert_new_objects(objects_manager: ObjectsManager, documents: list[dict[str, Any]]) -> dict[int, Exception]:
    """
    Writes new objects with one id reservation and one unordered insert, answering which were not written

    Every object gets its public_id from the reserved block, in order, written into the document; an id whose
    object is then refused stays spent. The type was guarded by the caller - nothing here reads it

    Args:
        objects_manager (ObjectsManager): Reserves the ids and inserts the objects
        documents (list[dict[str, Any]]): The normalised objects, none carrying a public_id; changed in place

    Raises:
        BaseManagerGetError: If the ids could not be reserved - nothing was written
        BaseManagerInsertError: If the insert failed as a whole - which objects were written is not known
        DocumentLockTimeoutError / DocumentNetworkError: A transient failure of the insert, as above

    Returns:
        dict[int, Exception]: The error of every object not written, by its position in ``documents``
    """
    public_ids: list[int] = objects_manager.reserve_public_ids(len(documents))

    for document, public_id in zip(documents, public_ids, strict=True):
        document[CmdbObjectKey.PUBLIC_ID.value] = public_id

    serialised, positions, failures = serialise_new_objects(documents)

    for index, error in objects_manager.insert_many_reporting(serialised).items():
        failures[positions[index]] = error

    return failures


def plan_overwrite(
        stored: dict[str, Any],
        imported: dict[str, Any],
        request_user: CmdbUser) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Builds the document an overwrite stores in place of the stored object, and the diff its EDIT log records

    The overwrite is an edit of the stored object, recorded the way the object PUT records one: the stored
    ``author_id`` and ``creation_time`` are kept, ``last_edit_time`` / ``editor_id`` name the importer, and the
    stored version is bumped by what changed - kept when nothing did. Every other key is the imported row's.
    Neither argument is changed

    Args:
        stored (dict[str, Any]): The stored object being overwritten
        imported (dict[str, Any]): The normalised imported object, carrying the same public_id
        request_user (CmdbUser): The user running the import

    Raises:
        ObjectsManagerUpdateError: If the model cannot hold the stored or the imported object

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: The document to store, and the diff
    """
    replacement: dict[str, Any] = dict(imported)
    replacement[CmdbObjectKey.AUTHOR_ID.value] = stored.get(CmdbObjectKey.AUTHOR_ID.value)
    replacement[CmdbObjectKey.CREATION_TIME.value] = stored.get(CmdbObjectKey.CREATION_TIME.value)
    # The bump is applied to the candidate's version, so it has to start from the stored one
    replacement[CmdbObjectKey.VERSION.value] = stored.get(CmdbObjectKey.VERSION.value)
    replacement.update(build_edit_stamp(request_user))

    try:
        planned: PlannedEdit = plan_object_edit(stored, replacement)
    except OBJECT_DOCUMENT_ERRORS as err:
        raise ObjectsManagerUpdateError(err) from err

    replacement[CmdbObjectKey.VERSION.value] = planned.version

    return replacement, planned.changes


def replace_stored_object(objects_manager: ObjectsManager, document: dict[str, Any]) -> bool:
    """
    Writes an object over the stored object of its public_id with one atomic replace

    The whole stored document is replaced and its ``_id`` kept: a key the document lacks is gone afterwards, and
    a failed write changes nothing. The types were guarded by the caller - nothing here reads them

    Args:
        objects_manager (ObjectsManager): Replaces the object
        document (dict[str, Any]): The object to store, carrying the public_id it is stored under

    Raises:
        ObjectsManagerUpdateError: If the model cannot hold the object or the database refused the write
        DocumentLockTimeoutError / DocumentNetworkError: A transient failure of the write

    Returns:
        bool: True when the object was replaced, False when no object carries the public_id any more
    """
    try:
        stored_form: dict[str, Any] = CmdbObject.to_json(CmdbObject.from_data(document))
        result: UpdateResult = objects_manager.replace(document[CmdbObjectKey.PUBLIC_ID.value], stored_form)
    except (BaseManagerUpdateError, *OBJECT_DOCUMENT_ERRORS) as err:
        raise ObjectsManagerUpdateError(err) from err

    return result.matched_count > 0
