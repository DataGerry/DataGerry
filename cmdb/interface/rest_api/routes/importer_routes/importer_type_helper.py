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
Helper functions for the CmdbType import REST routes

Holds the upload parsing shared by the create and update routes plus the per-entry create/update
steps. Each per-entry helper handles exactly one uploaded entry and reports its outcome as a message
string instead of aborting, so a single bad entry never kills the rest of the batch

The user ids in an upload belong to the system the type was exported from, so authorship is always
re-derived here. A create is fresh authorship by the importer (`stamp_import_authorship`); an update
records the importer as the editor (`stamp_import_edit`) and leaves the stored author and creation
time alone, since those describe how the type came to exist on this system
"""
import json
from typing import Any
from logging import Logger, getLogger
from datetime import datetime, timezone
from bson import json_util
from flask import abort
from werkzeug.wrappers import Request

from cmdb.manager import TypesManager

from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    UNKNOWN_TYPE_ERROR_KEY_TEMPLATE,
    IMPORT_UPDATE_PRESERVED_FIELDS,
    TypeImporterFormField,
    TypeImportError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def parse_uploaded_types(source_request: Request) -> list[Any]:
    """
    Reads the uploaded type payload from the multipart request and decodes it from JSON

    The payload is decoded with the BSON object hook so exported extended-JSON values (dates in
    particular) are restored to their Python equivalents. A top-level JSON list is required: iterating
    a single uploaded type (a dict) would silently walk its keys instead of its types, so that case is
    rejected with a clear message rather than reported as a batch of unusable entries

    Args:
        source_request (Request): The incoming request carrying the upload form field

    Raises:
        HTTPException: 400 if the upload form field is missing, empty, or does not decode to a list

    Returns:
        list[Any]: The decoded payload, normally a list of type dictionaries
    """
    upload = source_request.form.get(TypeImporterFormField.UPLOAD_FILE.value)

    if not upload:
        abort(400, TypeImportError.NO_UPLOAD_FILE.value)

    decoded_upload = json.loads(upload, object_hook=json_util.object_hook)

    if not isinstance(decoded_upload, list):
        abort(400, TypeImportError.INVALID_UPLOAD_PAYLOAD.value)

    return decoded_upload


def stamp_import_authorship(type_entry: dict[str, Any], author_id: int) -> None:
    """
    Rewrites a newly imported type's authorship onto the importing user, in place

    The author_id / editor_id in an exported type refer to users of the system it came from, which
    generally do not exist here. Creating a type by import is therefore treated as fresh authorship on
    this system: the importing user becomes the author, and the foreign edit history is dropped rather
    than carried over as ids that resolve to nobody

    Args:
        type_entry (dict[str, Any]): A single uploaded type entry, modified in place
        author_id (int): public_id of the CmdbUser performing the import

    Raises:
        TypeError: If the entry is not a dictionary (a malformed upload entry)
    """
    type_entry[TypeSchemaKey.AUTHOR_ID.value] = author_id
    type_entry[TypeSchemaKey.EDITOR_ID.value] = None
    type_entry[TypeSchemaKey.LAST_EDIT_TIME.value] = None


def stamp_import_edit(type_entry: dict[str, Any], editor_id: int) -> None:
    """
    Records the importing user as the editor of a type being replaced by import, in place

    The counterpart of `stamp_import_authorship` for the update path: replacing an existing type is an
    edit, not an authorship event, so only the edit fields are written. The stored author and creation
    time are preserved separately, by keeping them out of the update payload entirely
    (see IMPORT_UPDATE_PRESERVED_FIELDS)

    Args:
        type_entry (dict[str, Any]): A single uploaded type entry, modified in place
        editor_id (int): public_id of the CmdbUser performing the import

    Raises:
        TypeError: If the entry is not a dictionary (a malformed upload entry)
    """
    type_entry[TypeSchemaKey.EDITOR_ID.value] = editor_id
    type_entry[TypeSchemaKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)


def build_import_update_payload(update_type: CmdbType) -> dict[str, Any]:
    """
    Serializes a validated CmdbType into the document an import update writes

    Every field the uploaded type carries is written except IMPORT_UPDATE_PRESERVED_FIELDS. Since the
    manager applies the payload with `$set`, an omitted field is simply not touched, so the stored
    author and creation time survive the import without having to be read back first

    Args:
        update_type (CmdbType): The validated type built from the uploaded entry

    Raises:
        CmdbTypeToJsonError: If the CmdbType could not be serialized

    Returns:
        dict[str, Any]: The update payload, without the preserved fields
    """
    update_payload: dict[str, Any] = CmdbType.to_json(update_type)

    for preserved_field in IMPORT_UPDATE_PRESERVED_FIELDS:
        update_payload.pop(preserved_field, None)

    return update_payload


def special_type_license_error(type_entry: Any, ipam_locked: bool) -> str | None:
    """
    Reports an uploaded entry that would install an IPAM special type on an unlicensed instance

    Mirrors `types_helper.enforce_special_type_license`, which guards every other type write, but
    reports instead of aborting so one locked entry does not discard the rest of the upload. The
    licence state is the same for the whole request, so the caller evaluates it once and passes it in

    Only the UPLOADED entry's special_type is inspected. The normal update route additionally consults
    the STORED type's marker, which would cost a per-entry read here; the vector that matters - putting
    a special type onto an unlicensed instance - is the uploaded value

    Args:
        type_entry (Any): A single entry of the uploaded payload
        ipam_locked (bool): Whether the IPAM feature is currently blocked for this request

    Returns:
        str | None: An error message if the entry may not be imported, None when it is allowed
    """
    if not ipam_locked or not isinstance(type_entry, dict):
        return None

    special_type = type_entry.get(TypeSchemaKey.SPECIAL_TYPE.value)

    if not special_type:
        return None

    return TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type=special_type)


def resolve_error_key(type_entry: Any, index: int) -> str:
    """
    Determines the error-collection key under which a failed entry is reported

    The public_id is preferred so the caller can match the failure to the uploaded type. Entries that
    are not a dictionary, or that carry no public_id yet (a create upload, or a malformed entry), fall
    back to their position in the upload so building the report can never raise

    Args:
        type_entry (Any): A single entry of the uploaded payload
        index (int): The position of the entry within the uploaded payload

    Returns:
        str: The key to report this entry's failure under
    """
    if isinstance(type_entry, dict):
        public_id = type_entry.get(TypeSchemaKey.PUBLIC_ID.value)

        if public_id is not None:
            return str(public_id)

    return UNKNOWN_TYPE_ERROR_KEY_TEMPLATE.format(index=index)


def create_type_from_entry(
    type_entry: Any,
    types_manager: TypesManager,
    author_id: int,
    ipam_locked: bool = False,
) -> str | None:
    """
    Creates a single CmdbType from one uploaded entry

    A fresh public_id and creation timestamp are assigned server side, so any public_id present in the
    upload is overwritten, and the authorship is rewritten onto the importing user. Failures are
    reported rather than raised so the remaining entries of the batch are still processed

    Args:
        type_entry (Any): A single entry of the uploaded payload, expected to be a type dictionary
        types_manager (TypesManager): Manager used to assign the public_id and insert the CmdbType
        author_id (int): public_id of the CmdbUser performing the import
        ipam_locked (bool): Whether the IPAM feature is blocked, rejecting special-type entries

    Returns:
        str | None: An error message if the entry could not be imported, None on success
    """
    # Checked before anything is assigned, so a rejected entry does not consume a public_id
    license_error = special_type_license_error(type_entry, ipam_locked)

    if license_error:
        return license_error

    try:
        type_entry[TypeSchemaKey.PUBLIC_ID.value] = types_manager.get_new_type_public_id()
        type_entry[TypeSchemaKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        stamp_import_authorship(type_entry, author_id)
    except Exception as err:
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.PUBLIC_ID_ASSIGNMENT_FAILED.format(detail=err)

    try:
        types_manager.insert_type(CmdbType.from_data(type_entry))
    except Exception as err:
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.IMPORT_FAILED.format(detail=err)

    return None


def update_type_from_entry(
    type_entry: Any,
    types_manager: TypesManager,
    editor_id: int,
    ipam_locked: bool = False,
) -> str | None:
    """
    Updates a single existing CmdbType from one uploaded entry

    Replacing a type by import is an edit, not an authorship event: the importing user is recorded as
    the editor, while the stored author and creation time are preserved by keeping them out of the
    update payload. Everything else the upload carries replaces the stored value

    The update does not upsert, so a public_id that does not exist matches nothing and would look
    like a success. That case is detected from the UpdateResult's `matched_count` rather than by a
    separate existence query. Failures are reported rather than raised so the remaining entries of
    the batch are still processed

    Args:
        type_entry (Any): A single entry of the uploaded payload, expected to be a type dictionary
        types_manager (TypesManager): Manager used to write the update
        editor_id (int): public_id of the CmdbUser performing the import
        ipam_locked (bool): Whether the IPAM feature is blocked, rejecting special-type entries

    Returns:
        str | None: An error message if the entry could not be updated, None on success
    """
    license_error = special_type_license_error(type_entry, ipam_locked)

    if license_error:
        return license_error

    try:
        stamp_import_edit(type_entry, editor_id)
        update_type_instance = CmdbType.from_data(type_entry)
    except Exception as err:
        LOGGER.error("[update_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.INVALID_TYPE_DATA.format(detail=err)

    try:
        update_payload = build_import_update_payload(update_type_instance)
        update_result = types_manager.update_type(update_type_instance.public_id, update_payload)

        if update_result.matched_count == 0:
            return TypeImportError.TYPE_NOT_FOUND.format(public_id=update_type_instance.public_id)
    except Exception as err:
        LOGGER.error("[update_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.UPDATE_FAILED.format(detail=err)

    return None
