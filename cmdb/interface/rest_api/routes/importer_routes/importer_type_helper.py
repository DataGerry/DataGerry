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

Holds the upload parsing shared by the create and update routes plus the two per-entry steps that
orchestrate everything else. Each step handles exactly one uploaded entry and reports its outcome as
a message string instead of aborting, so a single bad entry never kills the rest of the batch

The work an entry goes through, and where it lives:

    1. (update only) the stored Type is read - it decides whether there is anything to update at all,
       and both the guards and the side effects need that pre-update state
    2. the rules that judge the upload  -> `importer_type_rules`
    3. the repairs that fix it silently -> `importer_type_repairs`
    4. `repaired_structure_error` re-checks what the repairs completed - a global section template
       can contribute field definitions that no rule ever saw
    5. (update only) the rules that need the stored Type -> `stored_type_update_blocker`
    6. the write itself, here
    7. the persistence side effects, here (delegating to the normal Type routes' own helpers)

Both managers the steps need are resolved ONCE per request by the route and passed down, in the same
order everywhere: `types_manager` then `section_templates_manager`, preceded by `request_user` where
a route helper needs it. (`apply_type_update_side_effects` still resolves the managers it needs
through the ManagerProvider itself - it belongs to the normal Type routes and is shared as-is.)

The user ids in an upload belong to the system the type was exported from, so authorship is always
re-derived here. A create is fresh authorship by the importer (`stamp_import_authorship`); an update
records the importer as the editor (`stamp_import_edit`) and leaves the stored author, creation time
and version alone, since those describe how the type came to exist on this system - they are simply
kept out of the update payload (IMPORT_UPDATE_PRESERVED_FIELDS), which a `$set` leaves untouched

Writing the type is not the end of the work: an import owes the stored data the same follow-up the
normal type routes perform, so `apply_import_create_side_effects` /
`apply_import_update_side_effects` run afterwards (SpecialType wiring, object / MDS / location
reconciliation, dropped-section-template cleanup). They delegate to the very helpers
`types_routes` uses, so the two write paths cannot drift apart
"""
import json
from json import JSONDecodeError
from typing import Any
from logging import Logger, getLogger
from datetime import datetime, timezone
from bson import json_util
from flask import abort
from werkzeug.wrappers import Request

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.framework.ipam.special_type_wiring import handle_special_types
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    compute_removed_global_templates,
    apply_type_update_side_effects,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import (
    validate_create_entry,
    validate_update_entry,
    validate_type_structure,
    stored_type_update_blocker,
    as_public_id,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_repairs import (
    strip_uploaded_public_id,
    normalize_imported_type,
    resolve_global_templates,
)
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
        HTTPException: 400 if the upload form field is missing, empty, not valid JSON, or does not
                       decode to a list

    Returns:
        list[Any]: The decoded payload, normally a list of type dictionaries
    """
    upload = source_request.form.get(TypeImporterFormField.UPLOAD_FILE.value)

    if not upload:
        abort(400, TypeImportError.NO_UPLOAD_FILE.value)

    try:
        decoded_upload = json.loads(upload, object_hook=json_util.object_hook)
    except JSONDecodeError as err:
        # An unparsable upload is a bad request, not a server fault - without this it would reach the
        # route's catch-all and be reported as a 500
        abort(400, TypeImportError.MALFORMED_JSON.format(detail=err))

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
    edit, not an authorship event, so only the edit fields are written. The stored author, creation
    time and version are preserved separately, by keeping them out of the update payload entirely
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
    author, creation time, version and special_type survive without this step having to read them.
    That is also what makes special_type immutable: an update cannot change it, whatever the upload
    says - and the update path refuses an upload that tries (`stored_type_update_blocker`)

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


def apply_import_create_side_effects(
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    type_entry: dict[str, Any],
) -> None:
    """
    Runs the persistence side effects that follow creating a CmdbType by import

    Mirrors what `types_routes.insert_cmdb_type` does after its insert. Only a SpecialType has any:
    `handle_special_types` cross-wires the IPAM types' `ref_types` and refreshes the
    'dg-ipam-interface' section template, so an imported SUPERNET / SUBNET / VLAN is wired up the
    same way a hand-created one is. Without it the imported type exists but no other type can
    reference it until somebody re-saves it in the UI

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        section_templates_manager (SectionTemplatesManager): db interface for the section templates
        type_entry (dict[str, Any]): The imported type entry, carrying its assigned public_id

    Raises:
        Exception: Whatever the wiring raises - the caller reports it, the type is already created
    """
    special_type = type_entry.get(TypeSchemaKey.SPECIAL_TYPE.value)

    if not special_type:
        return

    handle_special_types(
        types_manager,
        special_type,
        section_templates_manager,
        type_entry[TypeSchemaKey.PUBLIC_ID.value],
    )


def apply_import_update_side_effects(
    request_user: CmdbUser,
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    old_type: CmdbType,
    type_entry: dict[str, Any],
) -> None:
    """
    Runs the persistence side effects that follow replacing a CmdbType by import

    An import update replaces the fields and sections wholesale, exactly like the normal update
    route, so it owes the stored data the same follow-up work: dropped global section templates are
    removed, SpecialType wiring is re-applied, label / icon / selectable changes are propagated to
    the type's CmdbLocations, MDS field changes reach the objects' rows, and every object of the type
    is re-aligned with the new field set (with the removed fields stripped from its reports). Without
    this an import silently leaves every existing object holding fields the type no longer defines

    The re-read is deliberate: the update payload omits IMPORT_UPDATE_PRESERVED_FIELDS, so only the
    stored document says what the type now really is - `special_type` in particular is NOT what the
    upload carried

    Args:
        request_user (CmdbUser): The user performing the import
        types_manager (TypesManager): db interface for CmdbTypes
        section_templates_manager (SectionTemplatesManager): db interface for the section templates
        old_type (CmdbType): The state of the CmdbType before the update
        type_entry (dict[str, Any]): The uploaded entry, read for its global_template_ids

    Raises:
        Exception: Whatever a side effect raises - the caller reports it, the type is already updated
    """
    updated_type: CmdbType | None = types_manager.get_type_instance(old_type.public_id)

    if not updated_type:
        # Deleted between the update and this read - there is nothing left to reconcile
        return

    removed_templates = compute_removed_global_templates(
        old_type,
        _templates_the_update_still_claims(section_templates_manager, old_type, type_entry),
    )

    apply_type_update_side_effects(request_user, types_manager, old_type, updated_type, removed_templates)


def _templates_the_update_still_claims(
    section_templates_manager: SectionTemplatesManager,
    old_type: CmdbType,
    type_entry: dict[str, Any],
) -> set[str]:
    """
    Works out which global section templates the update leaves the CmdbType claiming

    Not simply the uploaded `global_template_ids`: `reconcile_global_templates` has already dropped
    the claims naming a template that does not exist here, and the cleanup this feeds treats a
    disappeared claim as "the user removed the section" - it would delete the inlined section, its
    field definitions AND the stored values from every object of the type. A claim the repair dropped
    is therefore counted as still claimed, so only a template the user really took off the type is
    cleaned up. The distinction costs one query, and only when a claim actually disappeared

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for the section templates
        old_type (CmdbType): The state of the CmdbType before the update
        type_entry (dict[str, Any]): The uploaded entry, after the repairs

    Raises:
        BaseManagerGetError: If the template lookup fails

    Returns:
        set[str]: The template names to treat as still claimed by the CmdbType
    """
    uploaded_claims: set[str] = set(type_entry.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or [])
    disappeared: set[str] = set(old_type.global_template_ids or []) - uploaded_claims

    if not disappeared:
        return uploaded_claims

    resolvable = set(resolve_global_templates(section_templates_manager, sorted(disappeared)))

    return uploaded_claims | (disappeared - resolvable)


def repaired_structure_error(type_entry: dict[str, Any]) -> str | None:
    """
    Re-checks the structure of an entry the repairs have completed

    The rules judge what the upload carried; `reconcile_global_templates` then copies field
    definitions out of a stored global section template into it. Those definitions are never
    validated on the way in, so a template written before a rule existed (a field with no label, an
    unknown field type, a choice field without options, a second location field) would slip past
    every rule the same field would have been rejected for in the upload itself

    Only the structural rules are re-run: nothing a repair does can change the type name, its
    uniqueness or its special_type

    Args:
        type_entry (dict[str, Any]): The uploaded entry, after the repairs

    Returns:
        str | None: The findings, worded as a repair failure, or None when the entry is still sound
    """
    structure_error = validate_type_structure(type_entry)

    if not structure_error:
        return None

    return TypeImportError.REPAIRED_TYPE_INVALID.format(detail=structure_error)


def prepare_create_entry(
    type_entry: dict[str, Any],
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    ipam_locked: bool,
) -> str | None:
    """
    Runs everything a CREATE entry goes through before it is written

    Args:
        type_entry (dict[str, Any]): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used by the rules and the repairs
        section_templates_manager (SectionTemplatesManager): Manager used by the template repair
        ipam_locked (bool): Whether the IPAM feature is blocked for this request

    Returns:
        str | None: The first finding, or None when the entry is ready to be inserted
    """
    return (
        validate_create_entry(type_entry, types_manager, ipam_locked)
        or _repair_entry(type_entry, types_manager, section_templates_manager)
    )


def prepare_update_entry(
    type_entry: dict[str, Any],
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    ipam_locked: bool,
) -> str | None:
    """
    Runs everything an UPDATE entry goes through before it is written

    The same shape as the create path with the update's own rule set; the rules that need the stored
    type are separate (`stored_type_update_blocker`), because they also need the CmdbType built from
    this entry

    Args:
        type_entry (dict[str, Any]): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used by the rules and the repairs
        section_templates_manager (SectionTemplatesManager): Manager used by the template repair
        ipam_locked (bool): Whether the IPAM feature is blocked for this request

    Returns:
        str | None: The first finding, or None when the entry is ready to be written
    """
    return (
        validate_update_entry(type_entry, types_manager, ipam_locked)
        or _repair_entry(type_entry, types_manager, section_templates_manager)
    )


def _repair_entry(
    type_entry: dict[str, Any],
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
) -> str | None:
    """
    Applies the repairs to an entry the rules accepted, then re-checks what they completed

    Args:
        type_entry (dict[str, Any]): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used by the reference and ACL repairs
        section_templates_manager (SectionTemplatesManager): Manager used by the template repair

    Returns:
        str | None: A repair failure or a finding on the completed entry, else None
    """
    try:
        normalize_imported_type(type_entry, types_manager, section_templates_manager)
    except Exception as err:
        LOGGER.error("[_repair_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.NORMALIZATION_FAILED.format(detail=err)

    return repaired_structure_error(type_entry)


def read_type_to_update(
    type_entry: dict[str, Any],
    types_manager: TypesManager,
) -> tuple[CmdbType | None, str | None]:
    """
    Reads the stored CmdbType an update entry addresses

    Runs before the rules and the repairs: an entry naming a Type that does not exist here has
    nothing to be judged against and no reason to cost the four queries the rules and repairs
    otherwise spend. The result is also what the guards and the side effects diff against later

    Args:
        type_entry (dict[str, Any]): A single entry of the uploaded payload
        types_manager (TypesManager): Manager used to read the stored CmdbType

    Returns:
        tuple[CmdbType | None, str | None]: The stored CmdbType, or None plus the message to report
    """
    public_id = as_public_id(type_entry.get(TypeSchemaKey.PUBLIC_ID.value))

    try:
        old_type: CmdbType | None = types_manager.get_type_instance(public_id) if public_id else None
    except Exception as err:
        LOGGER.error("[read_type_to_update] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return None, TypeImportError.UPDATE_FAILED.format(detail=err)

    if not old_type:
        return None, TypeImportError.TYPE_NOT_FOUND.format(
            public_id=type_entry.get(TypeSchemaKey.PUBLIC_ID.value),
        )

    return old_type, None


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
    section_templates_manager: SectionTemplatesManager,
    request_user: CmdbUser,
    ipam_locked: bool = False,
) -> str | None:
    """
    Creates a single CmdbType from one uploaded entry

    A fresh public_id and creation timestamp are assigned server side, so any public_id present in
    the upload is dropped up front, and the authorship is rewritten onto the importing user. Failures
    are reported rather than raised so the remaining entries of the batch are still processed

    The entry is validated first (special_type, structure, flags, name), then normalized
    (`normalize_imported_type`), then written, and finally wired up
    (`apply_import_create_side_effects`) exactly as the normal create route does

    Args:
        type_entry (Any): A single entry of the uploaded payload, expected to be a type dictionary
        types_manager (TypesManager): Manager used to assign the public_id and insert the CmdbType
        section_templates_manager (SectionTemplatesManager): Manager used by the repairs and the
                                                             SpecialType wiring
        request_user (CmdbUser): The user performing the import (its public_id becomes the author)
        ipam_locked (bool): Whether the IPAM feature is blocked, rejecting special-type entries

    Returns:
        str | None: An error message if the entry could not be imported, None on success
    """
    if not isinstance(type_entry, dict):
        # Everything below reads the entry as a Type document; without this an unusable entry would
        # reach the public_id assignment, burn a value off the counter and be reported as an
        # assignment failure instead of as what it is
        return TypeImportError.NOT_A_TYPE_ENTRY.value

    # The public_id is server-owned on this path, so the uploaded one goes before anything reads it
    strip_uploaded_public_id(type_entry)

    # Judged before anything is assigned, so a rejected entry does not consume a public_id
    entry_error = prepare_create_entry(type_entry, types_manager, section_templates_manager, ipam_locked)

    if entry_error:
        return entry_error

    try:
        type_entry[TypeSchemaKey.PUBLIC_ID.value] = types_manager.get_new_type_public_id()
        type_entry[TypeSchemaKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        stamp_import_authorship(type_entry, request_user.public_id)
    except Exception as err:
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.PUBLIC_ID_ASSIGNMENT_FAILED.format(detail=err)

    try:
        new_type = CmdbType.from_data(type_entry)
    except Exception as err:
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.INVALID_TYPE_DATA.format(detail=err)

    try:
        types_manager.insert_type(new_type)
    except Exception as err:
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.IMPORT_FAILED.format(detail=err)

    try:
        apply_import_create_side_effects(types_manager, section_templates_manager, type_entry)
    except Exception as err:
        # The Type itself is already stored, so this is reported as a follow-up failure, not as a
        # failed import - re-importing it would only create a duplicate
        LOGGER.error("[create_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.CREATE_SIDE_EFFECTS_FAILED.format(detail=err)

    return None


def update_type_from_entry(
    type_entry: Any,
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    request_user: CmdbUser,
    ipam_locked: bool = False,
) -> str | None:
    """
    Updates a single existing CmdbType from one uploaded entry

    Replacing a type by import is an edit, not an authorship event: the importing user is recorded as
    the editor, while the stored author and creation time are preserved by keeping them out of the
    update payload. Everything else the upload carries replaces the stored value

    The same rules and repairs as on the create path apply - an update replaces the fields and
    sections wholesale, so the replacement has to be as sound as a new type - plus the rules that
    need the stored type (`stored_type_update_blocker`), checked once it has been read

    The type is read before it is written: `apply_import_update_side_effects` needs the pre-update
    state to work out what changed, and that read doubles as the existence check (the update does not
    upsert, so an unknown public_id would otherwise match nothing and look like a success).
    Failures are reported rather than raised so the remaining entries of the batch are still processed

    Args:
        type_entry (Any): A single entry of the uploaded payload, expected to be a type dictionary
        types_manager (TypesManager): Manager used to write the update
        section_templates_manager (SectionTemplatesManager): Manager used by the repairs
        request_user (CmdbUser): The user performing the import (recorded as the editor)
        ipam_locked (bool): Whether the IPAM feature is blocked, rejecting special-type entries

    Returns:
        str | None: An error message if the entry could not be updated, None on success
    """
    if not isinstance(type_entry, dict):
        # Everything below reads the entry as a Type document; without this an unusable entry would
        # raise out of the batch loop instead of being reported like any other bad entry
        return TypeImportError.NOT_A_TYPE_ENTRY.value

    # Read first: the type has to exist before anything is judged or repaired, and both the guards
    # and the side effects need this pre-update state anyway
    old_type, read_error = read_type_to_update(type_entry, types_manager)

    if read_error:
        return read_error

    entry_error = prepare_update_entry(type_entry, types_manager, section_templates_manager, ipam_locked)

    if entry_error:
        return entry_error

    try:
        stamp_import_edit(type_entry, request_user.public_id)
        update_type_instance = CmdbType.from_data(type_entry)
    except Exception as err:
        LOGGER.error("[update_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.INVALID_TYPE_DATA.format(detail=err)

    blocker = stored_type_update_blocker(request_user, old_type, update_type_instance, ipam_locked)

    if blocker:
        return blocker

    try:
        update_payload = build_import_update_payload(update_type_instance)
        update_result = types_manager.update_type(old_type.public_id, update_payload)

        if update_result.matched_count == 0:
            # Deleted between the read and the write
            return TypeImportError.TYPE_NOT_FOUND.format(public_id=old_type.public_id)
    except Exception as err:
        LOGGER.error("[update_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.UPDATE_FAILED.format(detail=err)

    try:
        apply_import_update_side_effects(
            request_user, types_manager, section_templates_manager, old_type, type_entry,
        )
    except Exception as err:
        # The Type itself is already updated, so this is reported as a follow-up failure - the stored
        # Objects / Locations may be left half-reconciled and the entry should not simply be re-run
        LOGGER.error("[update_type_from_entry] Exception: %s. Type: %s.", err, type(err), exc_info=True)
        return TypeImportError.UPDATE_SIDE_EFFECTS_FAILED.format(detail=err)

    return None
