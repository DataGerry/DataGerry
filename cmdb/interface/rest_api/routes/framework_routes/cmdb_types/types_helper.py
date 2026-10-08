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
Helper methods for CmdbType API routes

Holds the licence and SpecialType guards, the lookups a route performs before it writes, the
uses_ports / selectable_as_parent / location-field change guards, the payload normalisations a write
applies in place (the ACL block, the ports section index, the CI Explorer label field) and the
persistence side effects an update or a delete owes the rest of the database.

The **reference-section** dependency cluster - who depends on a section, what an edit would break
and the pre-check payload behind it - lives in `types_reference_section_helper`: it is one
self-contained theme, and keeping it here would push this module past pylint's 1,500-line cap. Only
the type-delete guard still reaches across, to ask whether another type references the one being
deleted
"""
from logging import Logger, getLogger
from copy import deepcopy
from typing import Any, Callable

from flask import abort
from werkzeug.exceptions import HTTPException

from cmdb.interface.route_utils import abort_if_too_large
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.types_mds_helper import (
    MdsChangePlan,
    build_mds_alignment_updates,
    build_mds_updates,
    plan_mds_changes,
)
from cmdb.manager import (
    TypesManager,
    LocationsManager,
    ObjectsManager,
    ReportsManager,
    RelationsManager,
    CategoriesManager,
    CiExplorerProfileManager,
    ObjectGroupsManager,
    SectionTemplatesManager,
)

from cmdb.utils import Builder, coerce_whole_number
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.type_constants import DEFAULT_PORT_SECTION_INDEX, MIN_PORT_SECTION_INDEX
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.port_model import PortKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.framework.ci_explorer.label_field import label_field_error, is_label_field_unset
from cmdb.framework.ipam.special_type_wiring import (
    handle_special_types,
    cleanup_type_references_from_all_types,
    cleanup_special_type_template_references,
)
from cmdb.interface.rest_api.responses.response_parameters import (
    BuilderParamKey,
    CollectionParameters,
    TypeIterationParameters,
)
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.report_routes.report_constants import ReportKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import align_objects_to_type
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    describe_section_dependents,
    get_types_referencing_section,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    FIELD_IDENTIFIER_IMMUTABLE_MESSAGE,
    PORT_SECTION_INDEX_INVALID_MESSAGE,
    MDS_SECTION_IDENTIFIER_IMMUTABLE_MESSAGE,
    TYPE_NOT_FOUND_MESSAGE,
    USES_PORTS_DISABLE_MESSAGE,
    UsesPortsUsageKey,
    REFERENCED_TYPE_DELETE_MESSAGE,
    TypeUserDataKey,
    TypeOverviewKey,
    MATCH_STAGE_KEY,
    TypeAlignmentStep,
)
from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.errors.manager.types_manager import TypesManagerAlignmentError, TypesManagerUpdateMDSError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def enforce_special_type_license(request_user: CmdbUser, *special_types: Any) -> None:
    """
    Blocks managing a license-gated special type when its feature is not licensed

    A no-op unless one of the given markers names a license-gated SpecialType; for those it delegates
    to the shared license guard, which aborts with HTTP 403 on-premise when the feature is not
    licensed and is itself a no-op in cloud/local mode. The markers are matched per member rather
    than by the mere presence of a marker. Used by the create/update/delete type routes so the gate
    lives in one place

    Every gated member currently maps to LicenseFeature.IPAM - RACK included (see
    SpecialType.get_license_gated_types)

    Args:
        request_user (CmdbUser): The user performing the type create/edit/delete
        *special_types (Any): The 'special_type' markers the write touches - the stored one, the
            requested one, or both on an update. None and non-SpecialType values are ignored
    """
    required_feature: LicenseFeature | None = special_type_license_feature(*special_types)

    if required_feature is not None:
        abort_if_feature_locked(required_feature, request_user)


def special_type_license_feature(*special_types: Any) -> LicenseFeature | None:
    """
    Reports which LicenseFeature the given SpecialType markers require, if any

    The single statement of "is this SpecialType licensed, and behind what", so the two entrances to
    type creation cannot disagree about it. The type routes turn the answer into a 403
    (enforce_special_type_license above); the assistant turns the same answer into a skipped profile
    (special_helper.drop_locked_profiles) - one rule, two presentations, which is what the type
    importer already does with the routes' own blocker functions.

    Every gated member currently maps to LicenseFeature.IPAM. When a second gating feature exists,
    SpecialType.get_license_gated_types becomes a per-member mapping (its own docstring says so) and
    this is the one place that has to read it.

    Args:
        *special_types (Any): The 'special_type' markers to test. None and non-SpecialType values are
            ignored

    Returns:
        LicenseFeature | None: The feature required by any of the markers, or None when none is gated
    """
    if any(SpecialType.is_license_gated(special_type) for special_type in special_types):
        return LicenseFeature.IPAM

    return None


def enforce_uses_ports_license(request_user: CmdbUser, requested_uses_ports: Any) -> None:
    """
    Blocks turning 'uses_ports' on when the IPAM feature is not licensed

    Port Connectivity is gated by LicenseFeature.IPAM, and 'uses_ports' is the flag that opts a
    CmdbType into it, so it is the flag that has to be guarded: an unlicensed instance may not
    declare a type as port-bearing. Delegates to the shared license guard, which aborts with HTTP 403
    on-premise and is a no-op in cloud/local mode

    Gated on the REQUESTED value only, never on the stored one, which is deliberate and matches the
    rack precedent (`rack_object_hooks`): turning the flag **off** stays possible without the
    license, because cleanup is never blocked. A type that already carries it can therefore always be
    switched back

    Args:
        request_user (CmdbUser): The user performing the type create/edit
        requested_uses_ports (Any): The 'uses_ports' value the payload asks for. Anything falsy -
            including an absent key - is a no-op

    Raises:
        HTTPException: 403 when the payload turns 'uses_ports' on without the IPAM license
    """
    if requested_uses_ports:
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def enforce_rack_selectable_as_parent(special_type: Any, data: dict[str, Any]) -> None:
    """
    Keeps a RACK CmdbType selectable as a parent Location, aborting 400 on an attempt to disable it

    A Rack holds its mounted objects by parenting their location nodes, and
    validate_object_location_change refuses a parent whose type is not selectable_as_parent - so a
    Rack type with the flag off could never have anything placed in it. The flag is therefore not a
    user choice for Racks: an explicit False is rejected, and a missing value is filled in. Mutates
    'data' in place. A no-op for every other type

    Note the existing guard_selectable_as_parent_change only blocks the flip while objects are
    already placed, which would leave a fresh Rack type free to turn it off

    Args:
        special_type (Any): The 'special_type' marker of the type being written
        data (dict[str, Any]): The type payload, updated in place when it is a Rack

    Raises:
        HTTPException: 400 when the payload explicitly disables selectable_as_parent for a Rack
    """
    if special_type != SpecialType.RACK:
        return

    if data.get(TypeSchemaKey.SELECTABLE_AS_PARENT) is False:
        abort(400, "A Rack type must stay selectable as a parent Location, "
                   "otherwise no object could ever be placed in a Rack!")

    data[TypeSchemaKey.SELECTABLE_AS_PARENT] = True


def normalize_port_section_index(data: dict[str, Any]) -> None:
    """
    Validates and completes the 'port_section_index' of a CmdbType payload, in place

    The value is where the frontend draws the (virtual) ports section among the type's own sections:
    0 puts it first, 1 second, and so on. It is presentation state the frontend owns - the backend
    only guarantees it is storable and consistent with 'uses_ports':

    * an absent, null or empty value becomes DEFAULT_PORT_SECTION_INDEX. `POST /types/` stores the
      raw payload (the manager only BSON-round-trips it), so without this a created type would not
      carry the key at all and only the first edit would add it - the same two-shapes-for-one-meaning
      problem `normalize_type_acl` solves for the ACL
    * anything else that is not a whole number of 0 or greater is REFUSED with 400. Lenient coercion
      belongs to the type import, which has no user to report to; an API client sending -1 or 'left'
      has a bug worth hearing about
    * a type that does not use ports is forced back to the default. The index means nothing without
      the flag, and keeping a stale position would resurface it if the flag were ever set again

    Args:
        data (dict[str, Any]): The CmdbType payload, modified in place

    Raises:
        HTTPException: 400 when the payload carries an unusable index
    """
    raw_index: Any = data.get(TypeSchemaKey.PORT_SECTION_INDEX.value)

    if raw_index is None or raw_index == '':
        index: int = DEFAULT_PORT_SECTION_INDEX
    else:
        coerced: int | None = coerce_whole_number(raw_index)

        if coerced is None or coerced < MIN_PORT_SECTION_INDEX:
            abort(400, PORT_SECTION_INDEX_INVALID_MESSAGE.format(value=repr(raw_index)))

        index = coerced

    # The index is only read while the flag is on, so a type without ports always stores the default
    if not data.get(TypeSchemaKey.USES_PORTS.value):
        index = DEFAULT_PORT_SECTION_INDEX

    data[TypeSchemaKey.PORT_SECTION_INDEX.value] = index


def normalize_ci_explorer_label(data: dict[str, Any], old_type: CmdbType | None = None) -> None:
    """
    Validates the CI Explorer label nomination of a CmdbType payload, in place

    ``ci_explorer_label`` is the **name of one of the Type's own fields**, not a string to display:
    the CI Explorer reads that field off every object of the Type and shows its value on the node
    (`ci_explorer.nodes.resolve_title`). A nomination that resolves to nothing renders every node of
    the Type as "Label not selected", which is indistinguishable from never having chosen one - so it
    is caught at the write instead.

    Three outcomes:

    * **usable, or nothing nominated** - kept. An empty string is normalised to None, the stored form
      of "no field chosen", so the key has one spelling in the collection
    * **unusable and newly set** - refused with 400, reporting which names the Type does offer
    * **unusable but UNCHANGED from the stored Type** - cleared to None instead of refused. That is
      the field-was-removed case: an update that drops the nominated field would otherwise be
      refused over a cosmetic key, and the stale nomination has to go anyway. It also repairs, on its
      next save, a Type whose stored nomination is already stale

    Args:
        data (dict[str, Any]): The CmdbType payload, modified in place
        old_type (CmdbType | None): The stored Type on an update; None on a create, where there is no
            previous nomination and every unusable value is therefore a refusal

    Raises:
        HTTPException: 400 when the payload newly nominates a field the Type does not offer
    """
    nominated: Any = data.get(TypeSchemaKey.CI_EXPLORER_LABEL.value)

    if is_label_field_unset(nominated):
        data[TypeSchemaKey.CI_EXPLORER_LABEL.value] = None
        return

    error: str | None = label_field_error(data, nominated)

    if not error:
        return

    # Unchanged from the stored Type: this update did not choose it, it only stopped being resolvable
    if old_type is not None and nominated == old_type.ci_explorer_label:
        LOGGER.info(
            "[normalize_ci_explorer_label] Cleared the stale CI Explorer label field %s of Type ID:%s",
            repr(nominated), old_type.public_id,
        )
        data[TypeSchemaKey.CI_EXPLORER_LABEL.value] = None

        return

    abort(400, error)


def get_type_or_404(types_manager: TypesManager, public_id: int) -> dict[str, Any]:
    """
    Fetches a CmdbType document by public_id, aborting the request with HTTP 404 when it does not exist

    Centralizes the "look it up or 404" pattern shared by the CmdbType read / update routes so
    the lookup and its not-found message stay identical across them. Use
    `get_type_instance_or_404` when a CmdbType object is needed instead

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the CmdbType to fetch

    Raises:
        HTTPException: 404 if no CmdbType has that public_id

    Returns:
        dict[str, Any]: The requested CmdbType document (never None - aborts 404 instead)
    """
    target_type: dict[str, Any] | None = types_manager.get_type(public_id)

    if not target_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return target_type


def get_type_instance_or_404(types_manager: TypesManager, public_id: int) -> CmdbType:
    """
    Fetches a CmdbType by public_id as a hydrated CmdbType, aborting with HTTP 404 when it is missing

    The CmdbType counterpart of `get_type_or_404`, sharing its not-found message so the two are
    indistinguishable to the caller

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the CmdbType to fetch

    Raises:
        HTTPException: 404 if no CmdbType has that public_id

    Returns:
        CmdbType: The requested CmdbType (never None - aborts 404 instead)
    """
    target_type: CmdbType | None = types_manager.get_type_instance(public_id)

    if not target_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return target_type


def get_location_field(target_type: CmdbType) -> dict[str, Any] | None:
    """
    Returns the location-typed field dict of a CmdbType, or None when it has no location field

    A CmdbType has at most one location-typed field (see CLAUDE.md type invariants)

    Args:
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any] | None: The location field dict, or None when absent
    """
    return next(
        (f for f in target_type.get_fields() if f.get(FieldKey.TYPE) == FieldType.LOCATION),
        None,
    )


def verify_type_is_unique(
    types_manager: TypesManager,
    name: str,
    public_id: int | None = None,
    special_type: str | None = None
) -> None:
    """
    Validates that a candidate CmdbType's identifying attributes are unique in the database

    Aborts the request with HTTP 400 when the public_id is already taken, when the name
    collides with an existing CmdbType, when the name is missing, or when another CmdbType
    already carries the given SpecialType marker

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        name (str): Name of the CmdbType which should be created
        public_id (int | None): Pre-assigned public_id of the CmdbType, when present
        special_type (str | None): SpecialType marker of the CmdbType, when present
    """
    # Check public_id already exists
    if public_id:
        possible_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if possible_type:
            abort(400, f"Type with ID:{public_id} already exists!")

    if name:
        # Check name is unique
        type_with_name: dict[str, Any] | None = types_manager.get_one_by({TypeSchemaKey.NAME: name})

        if type_with_name:
            abort(400, f"Type with name:{name} already exists!")
    else:
        abort(400, "Type data does not contain 'name' of the Type!")

    if special_type:
        special_type_exists: bool = types_manager.check_special_type_exists(special_type)

        if special_type_exists:
            abort(400, f"SpecialType: {special_type} already exists!")


def special_type_is_unchanged(old_st: str | None, new_st: str | None) -> bool:
    """
    Reports whether a CmdbType's 'special_type' value is the same before and after an update

    Args:
        old_st (str | None): The 'special_type' before the update
        new_st (str | None): The 'special_type' from the update payload

    Returns:
        bool: True if both sides match (including both being None), False otherwise
    """
    return old_st == new_st


def criteria_constrain_active(client_criteria: dict[str, Any] | list[dict[str, Any]]) -> bool:
    """
    Answers whether the client's own criteria already filter on the ``active`` field

    A dict criteria does when it carries the key at its top level; a list criteria (a pipeline) does
    when any of its ``$match`` stages carries it at the stage's top level. A condition nested deeper -
    inside an ``$and`` / ``$or``, or a later stage the client built - is not looked for: the rule is
    about the plain statements a caller writes, not a query parser

    Args:
        client_criteria (dict[str, Any] | list[dict[str, Any]]): The criteria as the client sent it

    Returns:
        bool: True when the client states its own ``active`` condition
    """
    active_key: str = TypeSchemaKey.ACTIVE.value

    if isinstance(client_criteria, list):
        return any(
            isinstance(stage, dict)
            and isinstance(stage.get(MATCH_STAGE_KEY), dict)
            and active_key in stage[MATCH_STAGE_KEY]
            for stage in client_criteria
        )

    return isinstance(client_criteria, dict) and active_key in client_criteria


def build_type_criteria(
        client_criteria: dict[str, Any] | list[dict[str, Any]],
        active: bool) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Merges the server's ``active`` restriction into the criteria the client sent

    Returns a **new** criteria; the client's own value is never mutated. That matters because the
    same object is echoed back to the caller in the response's ``parameters.filter`` block as
    frontend contract - merging in place would make the server's injected stage look like something
    the client had sent.

    **The client's own ``active`` condition wins.** ``?active=`` defaults to true, so a caller that
    filters on ``active`` itself - ``{"active": false}`` to list inactive types - would otherwise have
    its condition replaced (dict) or contradicted (list) by the flag and get the opposite, or nothing,
    with a 200. When the criteria already constrain ``active`` (`criteria_constrain_active`) they are
    handed back unchanged; the flag applies only to criteria that say nothing about it.

    Otherwise a dict criteria is merged key-wise, a list criteria gets one appended ``$match``, and an
    empty dict stays a dict rather than becoming a two-stage pipeline with an empty ``$match`` in it. A
    falsy ``active`` restricts nothing and the criteria is handed back unchanged

    Args:
        client_criteria (dict[str, Any] | list[dict[str, Any]]): The criteria as the client sent it
        active (bool): The ``active`` flag; only a truthy value restricts the query

    Returns:
        dict[str, Any] | list[dict[str, Any]]: The criteria to query with
    """
    if not active or criteria_constrain_active(client_criteria):
        return client_criteria

    if isinstance(client_criteria, list):
        return [*client_criteria, Builder.match_({TypeSchemaKey.ACTIVE.value: active})]

    return {**client_criteria, TypeSchemaKey.ACTIVE.value: active}


def normalize_type_acl(type_data: dict[str, Any]) -> None:
    """
    Writes the complete ``acl`` block onto a CmdbType payload, in place

    **Why the create route needs this and the others do not.** A type update and a type import both
    hand a `CmdbType` to the manager, so they go through ``CmdbType.from_data`` -> ``to_json`` and
    always store a full ``{'activated': ..., 'groups': {'includes': {...}}}``; the start assistant
    writes that literal itself. ``POST /types/`` hands over the **raw payload**, which the manager
    only BSON-round-trips - so without this a create without an ``acl`` key would store a document
    without one, and the first edit would silently add it: two stored shapes for one meaning, decided
    by whether anyone had edited the type.

    This applies the same normalisation the other three paths get, so a Type's stored ACL does not
    depend on the route it arrived through - ``AccessControlList.normalize_stored``, the reading
    ``updater_20261003`` also wrote back onto every Type stored before this rule. A partial ``acl`` is
    completed rather than rejected: the absent half is exactly what the model defaults, and ``activated``
    defaults to **False**, which grants - access control is opt-in.

    The block's shape has already been judged by the type write schema (``get_type_acl_schema``): a malformed
    one is a 400 before this runs, so completing it cannot fail. An unknown key inside ``acl`` was purged by the
    validator, as the model would drop it

    Args:
        type_data (dict[str, Any]): The CmdbType payload, modified in place
    """
    type_data[TypeSchemaKey.ACL.value] = AccessControlList.normalize_stored(
        type_data.get(TypeSchemaKey.ACL.value)
    )


def build_category_criteria(
        type_params: TypeIterationParameters,
        request_user: CmdbUser) -> dict[str, Any] | None:
    """
    Builds the category membership restriction a types listing was asked for, if any

    The server-side form of the two ``$lookup`` pipelines a client would otherwise post as
    ``?filter=``. Both resolve to a set of type public_ids and then filter this collection on it,
    which is a plain indexed ``$in`` / ``$nin`` instead of a join per request.

    The CategoriesManager is built only when one of the two parameters is actually present, so the
    ordinary listing - which is almost every request - pays for no extra manager and no extra read

    Args:
        type_params (TypeIterationParameters): The received Type request parameters
        request_user (CmdbUser): CmdbUser requesting the listing

    Returns:
        dict[str, Any] | None: The criteria to add, or None when no category filter was requested
    """
    if not type_params.uncategorized and type_params.category is None:
        return None

    categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, request_user)

    if type_params.uncategorized:
        assigned_type_ids: set[int] = categories_manager.get_assigned_type_ids()

        return {TypeSchemaKey.PUBLIC_ID.value: {'$nin': sorted(assigned_type_ids)}}

    category_type_ids: list[int] = categories_manager.get_category_type_ids(type_params.category)

    return {TypeSchemaKey.PUBLIC_ID.value: {'$in': category_type_ids}}


def prepare_builder_parameters(
        type_params: TypeIterationParameters,
        request_user: CmdbUser) -> BuilderParameters:
    """
    Prepares BuilderParameters for running a db query

    Args:
        type_params (TypeIterationParameters): the recieved Type request parameters
        request_user (CmdbUser): CmdbUser requesting the listing; only used to reach the
            CategoriesManager when a category filter was asked for

    Returns:
        BuilderParameters: The prepared BuilderParameters
    """
    builder_args: dict[str, Any] = CollectionParameters.get_builder_params(type_params)

    builder_args[BuilderParamKey.CRITERIA.value] = build_type_criteria(type_params.filter, type_params.active)

    builder_params = BuilderParameters(**builder_args)

    category_criteria: dict[str, Any] | None = build_category_criteria(type_params, request_user)

    if category_criteria:
        builder_params.add_criteria(category_criteria)

    return builder_params


def get_types_user_data(
        user_lookup: dict[int, CmdbUser],
        author_id: int | None = None,
        editor_id: int | None = None
    ) -> dict[str, Any]:
    """
    Formats relevant user data for a type

    Args:
        user_lookup (dict[int, CmdbUser]): lookup table of relevant CmdbUsers
        author_id (int | None, optional): public_id of author CmdbUser
        editor_id (int | None, optional): public_id of last editor CmdbUser

    Returns:
        dict[str, Any]: The formatted data of the author and editor
    """
    user_data: dict[str, Any] = {
        TypeUserDataKey.AUTHOR: None,
        TypeUserDataKey.AUTHOR_IMAGE: None,
        TypeUserDataKey.LAST_EDITOR: None,
        TypeUserDataKey.LAST_EDITOR_IMAGE: None,
    }

    author: CmdbUser = user_lookup.get(author_id)
    last_editor: CmdbUser | None = user_lookup.get(editor_id)

    if author:
        user_data[TypeUserDataKey.AUTHOR] = author.get_display_name()
        user_data[TypeUserDataKey.AUTHOR_IMAGE] = author.image

    if last_editor:
        user_data[TypeUserDataKey.LAST_EDITOR] = last_editor.get_display_name()
        user_data[TypeUserDataKey.LAST_EDITOR_IMAGE] = last_editor.image

    return user_data


def apply_type_changes_to_locations(
    request_user: CmdbUser,
    old_type: CmdbType,
    updated_type: CmdbType,
    force: bool = False,
) -> None:
    """
    Applies the CmdbType's label / icon / selectable to its CmdbLocations

    Only what the update changed is written - or, with ``force``, all three: a type whose earlier save did not
    finish (``alignment_pending``) cannot tell which values its locations still lack. Idempotent either way

    Args:
        request_user (CmdbUser): CmdbUser requesting this data
        old_type (CmdbType): State of the CmdbType before update
        updated_type (CmdbType): State of the CmdbType after update
        force (bool): Write all three values, changed or not. Defaults to False
    """
    field_mapping: dict[str, Any] = {
        LocationKey.TYPE_LABEL: (old_type.label, updated_type.label),
        LocationKey.TYPE_ICON: (old_type.render_meta.icon, updated_type.render_meta.icon),
        LocationKey.TYPE_SELECTABLE: (old_type.selectable_as_parent, updated_type.selectable_as_parent),
    }

    changed_data: dict[str, Any] = {k: new for k, (old, new) in field_mapping.items() if force or old != new}

    # Early out if nothing changed
    if not changed_data:
        return

    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    # Update all affected CmdbLocations
    locations_manager.update_locations_by_type(updated_type.get_public_id(), changed_data)


def apply_type_changes_to_mds(request_user: CmdbUser, old_type: CmdbType, updated_type: dict[str, Any]) -> None:
    """
    Applies a CmdbType's multi-data-section changes to every object of that type

    ``plan_mds_changes`` works out what the edit changes and ``build_mds_updates`` turns that into
    server-side statements, which ``ObjectsManager.apply_raw_updates`` runs - no object is read. A field
    the edit added is appended to every row lacking it, with its declared type and default value; a
    field it dropped is stripped from every row; and a **section** the edit no longer declares is
    removed from the objects, so none keeps rows of a section its type does not have. The statements
    touch only those entries, so an object edit saved meanwhile is not overwritten

    Args:
        request_user (CmdbUser): The user performing the update
        old_type (CmdbType): The existing CmdbType object before changes
        updated_type (dict): The updated CmdbType data

    Raises:
        TypesManagerUpdateMDSError: If the propagation fails - the type is already written by then,
            which is why the route reports it with its own message. The statements before the failing
            one are applied and each is idempotent, so the same edit saved again completes it
    """
    plan: MdsChangePlan = plan_mds_changes(old_type, updated_type)

    if plan.is_empty:
        return

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    try:
        objects_manager.apply_raw_updates(build_mds_updates(old_type.public_id, plan))
    except ObjectsManagerUpdateError as err:
        abort_if_too_large(err)
        raise TypesManagerUpdateMDSError(err) from err


def align_type_mds(request_user: CmdbUser, updated_type: CmdbType) -> None:
    """
    Brings the multi-data sections of every object of a CmdbType in line with the type as it is stored

    The state-based counterpart of ``apply_type_changes_to_mds`` (``build_mds_alignment_updates``): it needs no
    earlier state of the type, so it finishes an update whose propagation failed half-way. Idempotent

    Args:
        request_user (CmdbUser): The user performing the update
        updated_type (CmdbType): The CmdbType as stored

    Raises:
        TypesManagerUpdateMDSError: If a statement fails
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    try:
        objects_manager.apply_raw_updates(build_mds_alignment_updates(updated_type))
    except ObjectsManagerUpdateError as err:
        abort_if_too_large(err)
        raise TypesManagerUpdateMDSError(err) from err


def realign_type_objects_if_fields_changed(
    request_user: CmdbUser,
    old_type: CmdbType,
    updated_type: CmdbType,
    force: bool = False,
) -> None:
    """
    Re-aligns a CmdbType's objects and reports with its field set, only when the field names changed

    A pure metadata edit (label / icon / regex / default value / section reorder) leaves the set of
    field names unchanged, so the potentially large object sweep is skipped. When a field name was
    added or removed, every object of the type gains the newly declared fields (seeded with their
    default ``value``) and loses the fields the type no longer declares, and the removed field names
    are stripped from the type's reports. The matching MDS-row alignment is handled separately by
    ``apply_type_changes_to_mds`` (this reconciles the flat ``fields`` list; that reconciles the
    ``multi_data_sections`` rows)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        updated_type (CmdbType): The CmdbType as just written by the base update
        force (bool): Re-align and clean regardless of what changed (``alignment_pending``). Defaults to False
    """
    realign_type_object_fields(request_user, old_type, updated_type, force)
    clean_type_reports_after_update(request_user, old_type, updated_type, force)


def _field_names(type_instance: CmdbType) -> set[str]:
    """The names of every field a CmdbType declares."""
    return {field[FieldKey.NAME] for field in type_instance.fields}


def realign_type_object_fields(
    request_user: CmdbUser,
    old_type: CmdbType,
    updated_type: CmdbType,
    force: bool = False,
) -> None:
    """
    Re-aligns the flat field set of every object of a CmdbType with the type - when its field names changed

    The sweep is skipped for a pure metadata edit; ``force`` runs it regardless, for a type whose earlier save did
    not finish. ``align_objects_to_type`` is state-based and idempotent

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        updated_type (CmdbType): The CmdbType as written
        force (bool): Re-align even when the field names are unchanged. Defaults to False

    Raises:
        ObjectsManagerUpdateError: If a statement fails
    """
    if not force and _field_names(old_type) == _field_names(updated_type):
        return

    align_objects_to_type(ManagerProvider.get_manager(ManagerType.OBJECTS, request_user), updated_type)


def undeclared_report_field_names(reports_for_type: list[dict[str, Any]], updated_type: CmdbType) -> set[str]:
    """
    The field names the type's reports select or filter on that the type no longer declares

    What a forced cleanup strips when the update that removed them is no longer known. The keys every object
    carries in its own right (``CmdbObjectKey``) are never counted - only type fields can be removed from a type

    Args:
        reports_for_type (list[dict[str, Any]]): The stored reports of the type
        updated_type (CmdbType): The CmdbType as stored

    Returns:
        set[str]: The stale names, across every report of the type
    """
    referenced: set[str] = set()

    for report in reports_for_type:
        referenced |= CmdbReport.from_data(report).referenced_field_names()

    return referenced - _field_names(updated_type) - {key.value for key in CmdbObjectKey}


def clean_type_reports_after_update(
    request_user: CmdbUser,
    old_type: CmdbType,
    updated_type: CmdbType,
    force: bool = False,
) -> None:
    """
    Strips the fields an update removed from the CmdbType's reports - with ``force``, every field they reference
    that the type no longer declares

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        updated_type (CmdbType): The CmdbType as written
        force (bool): Also strip names the type does not declare whatever removed them. Defaults to False

    Raises:
        ReportsManagerUpdateError: If the bulk write of the cleaned reports fails
    """
    removed_names: set[str] = _field_names(old_type) - _field_names(updated_type)

    if not removed_names and not force:
        return

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)
    reports_for_type: list[dict[str, Any]] = objects_manager.get_many_from_other_collection(
        CmdbReport.COLLECTION, criteria={ReportKey.TYPE_ID.value: updated_type.public_id},
    )

    if force:
        removed_names |= undeclared_report_field_names(reports_for_type, updated_type)

    reports_manager.strip_removed_fields_from_reports(reports_for_type, removed_names, updated_type)


def get_objects_using_location_field(
    request_user: CmdbUser,
    target_type: CmdbType,
) -> list[int]:
    """
    Returns the public_ids of CmdbObjects that currently store a location value
    (an integer > 0) in the location-typed field of the given CmdbType

    Returns an empty list if the CmdbType has no location field. The result is unbounded - every
    matching public_id is returned, which for a large type is a large list

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        list[int]: public_ids of CmdbObjects that have a value in the location field
    """
    location_field: dict[str, Any] | None = get_location_field(target_type)

    if not location_field:
        return []

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    criteria: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID: target_type.get_public_id(),
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: location_field[FieldKey.NAME],
                CmdbObjectFieldKey.VALUE: {'$gt': 0},
            },
        },
    }

    # Only the public_ids are used, so the query projects them instead of loading whole documents -
    # this runs on every type-edit page load and inside both update guards
    matching_objects: list[dict[str, Any]] = objects_manager.find_objects(
        criteria,
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )

    return [obj[CmdbObjectKey.PUBLIC_ID] for obj in matching_objects]


def build_location_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the shared "is this Type's location placement in use" pre-check payload

    Resolves the CmdbObjects of the given CmdbType that currently store a location value and packs
    them into the {in_use, count, object_public_ids} shape returned by the location-field-usage GET
    route. That one answer pre-checks both location guards on update - removing the location field and
    turning 'selectable_as_parent' off - because both ask whether any object of the type is placed in
    the location tree

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use: bool, count: int, object_public_ids: list[int]}
    """
    object_public_ids: list[int] = get_objects_using_location_field(request_user, target_type)

    return {
        'in_use': bool(object_public_ids),
        'count': len(object_public_ids),
        'object_public_ids': object_public_ids,
    }


def get_port_usage_of_type(request_user: CmdbUser, target_type: CmdbType) -> dict[str, int]:
    """
    Counts the CmdbPorts that exist on the CmdbObjects of one CmdbType

    A port stores its owner CmdbObject, not its type, so the question is two steps: which objects
    belong to this type, and how many ports name one of them. Resolved that way round on purpose - the
    alternative, a `$lookup` from framework.ports into framework.objects, would pay a join on every
    type-edit page load, and storing a type_id on the port would duplicate a fact the owner already
    holds and go stale if an object ever changed type.

    Only the object public_ids are read, never whole documents. Both counts are returned because the
    refusal message names them; the caller that only needs "any" reads the port count

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, int]: {'port_count': ports in total, 'object_count': objects of the type carrying at
            least one port}. Both zero when the type has no objects or none of them has ports
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

    object_documents: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.TYPE_ID: target_type.get_public_id()},
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )
    object_ids: list[int] = [document[CmdbObjectKey.PUBLIC_ID] for document in object_documents]

    if not object_ids:
        return {UsesPortsUsageKey.PORT_COUNT.value: 0, UsesPortsUsageKey.OBJECT_COUNT.value: 0}

    owned_criteria: dict[str, Any] = {PortKey.OBJECT_ID.value: {'$in': object_ids}}

    port_count: int = ports_manager.count_documents(owned_criteria)
    owners_with_ports: list[Any] = ports_manager.get_distinct(PortKey.OBJECT_ID.value, owned_criteria)

    return {
        UsesPortsUsageKey.PORT_COUNT.value: port_count,
        UsesPortsUsageKey.OBJECT_COUNT.value: len(owners_with_ports),
    }


def build_uses_ports_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the "may 'uses_ports' be turned off" pre-check payload

    Counts only, never an id list - the equivalent location payload is unbounded for a large type,
    and the type builder only needs to know whether the flag may be cleared.
    `in_use: false` means it may

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use, port_count, object_count}
    """
    usage: dict[str, int] = get_port_usage_of_type(request_user, target_type)

    return {
        UsesPortsUsageKey.IN_USE.value: usage[UsesPortsUsageKey.PORT_COUNT.value] > 0,
        **usage,
    }


def uses_ports_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'uses_ports' off, if it may not

    A CmdbType may only stop using ports once no port of its objects is left: the frontend renders the
    ports panel only for a port-bearing type, so clearing the flag would leave those ports as rows
    nothing in the UI can reach - and the port create route would refuse to recreate them.

    Only the true -> false transition is guarded. Turning it ON is always allowed here (the
    license guard `enforce_uses_ports_license` governs that direction), and keeping it off is a no-op. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_uses_ports_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = bool(old_type.uses_ports) and not bool(new_type.uses_ports)

    if not turning_off:
        return None

    usage: dict[str, int] = get_port_usage_of_type(request_user, old_type)

    if not usage[UsesPortsUsageKey.PORT_COUNT.value]:
        return None

    return USES_PORTS_DISABLE_MESSAGE.format(
        port_count=usage[UsesPortsUsageKey.PORT_COUNT.value],
        object_count=usage[UsesPortsUsageKey.OBJECT_COUNT.value],
    )


def guard_uses_ports_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'uses_ports' off while ports of the Type still exist

    The route-level wrapper around `uses_ports_change_blocker`. 400 follows the codebase convention
    for business-rule rejections, like the location-field and selectable-as-parent guards beside it

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the flag may not be turned off
    """
    blocker: str | None = uses_ports_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def selectable_as_parent_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'selectable_as_parent' off, if it may not

    A CmdbType may only stop being selectable as a parent once no CmdbObject of that type is placed
    in the location tree; otherwise a placed object of a now-non-selectable type would remain in the
    tree (and could still act as a parent) while its type forbids it. Only the true -> false
    transition is guarded - keeping it off, or turning it on, is always allowed. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_selectable_as_parent_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = old_type.selectable_as_parent and not new_type.selectable_as_parent

    if not turning_off:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot disable 'selectable as parent': "
        f"{len(object_public_ids)} Object(s) of this Type are placed in the location tree. "
    )


def guard_selectable_as_parent_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'selectable_as_parent' off while objects of the type are placed

    The route-level wrapper around `selectable_as_parent_change_blocker`. 400 follows the codebase
    convention for business-rule rejections (the same as the location-field removal guard)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when 'selectable_as_parent' may not be turned off
    """
    blocker: str | None = selectable_as_parent_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def count_objects_of_type(objects_manager: ObjectsManager, type_id: int) -> int:
    """
    Counts every CmdbObject of a CmdbType - the one question the delete guard and its pre-check both ask

    Active and inactive objects alike, and unscoped by the object ACL: an ACL lives on the Type, so a
    scoped count of one Type is either the total or 0, and a 0 would offer a delete the guard refuses

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_id (int): public_id of the CmdbType

    Raises:
        ObjectsManagerGetError: When the count failed

    Returns:
        int: The number of CmdbObjects of the Type
    """
    return objects_manager.count_documents({CmdbObjectKey.TYPE_ID: type_id})


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Confirms a CmdbType can be safely deleted, aborting the request when it cannot

    Aborts with HTTP 404 when the CmdbType does not exist, and with HTTP 400 when at least one
    CmdbObject of this CmdbType still exists, at least one CmdbReport still references it, or at
    least one other CmdbType pulls fields from it through a reference section. 400 follows the
    codebase convention for business-rule rejections (CLAUDE.md) - the same convention the
    location-field removal guard uses.

    The reference-section check is the type-level half of
    `referenced_section_removal_blocker`: deleting the referenced type leaves the dependent's
    ref-section pointing at a type_id that no longer resolves, which loses the referenced block from
    every object view of that type just as deleting the single section does

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType being checked
        to_delete_type (dict[str, Any] | None): The CmdbType document to delete, or None
            when the lookup already returned no result
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    if not to_delete_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    # Only possible to delete types when there are no objects
    if count_objects_of_type(objects_manager, public_id) > 0:
        abort(400, "Delete not possible if Objects of this Type exist!")

    # Only possible to delete types when there are no reports using it
    reports_count = reports_manager.count_documents({ReportKey.TYPE_ID: public_id})

    if reports_count > 0:
        abort(400, "Delete not possible if Reports exist which are using this Type!")

    # Only possible to delete types no other type references in a ref-section. Self-references are
    # excluded: a type whose own ref-section points at itself goes away with it
    referencing_types: list[dict[str, Any]] = get_types_referencing_section(
        request_user, public_id, exclude_type_id=public_id,
    )

    if referencing_types:
        abort(400, REFERENCED_TYPE_DELETE_MESSAGE.format(
            dependents=describe_section_dependents(referencing_types),
        ))


def type_deletion_followup(
    request_user: CmdbUser,
    public_id: int,
    special_type: str | None = None,
) -> None:
    """
    Performs cleanup actions that must run after a CmdbType has been deleted

    Removes the deleted type's id from relations, CiExplorerProfiles, dynamic object
    groups and the 'types' arrays of all CmdbCategories, and strips it from every other
    CmdbType's field-level 'ref_types' arrays so no surviving type still offers the
    deleted type as a reference target. When the deleted type carried a SpecialType
    marker, the 'dg-ipam-interface' section template - the one document that type-level
    sweep cannot reach - is un-wired too, so newly added 'dg-ipam-interface' sections no
    longer offer it either

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType that was just deleted
        special_type (str | None): SpecialType marker of the deleted CmdbType, if any
    """
    relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)
    ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
        ManagerType.CI_EXPLORER_PROFILE,
        request_user
    )
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, request_user)

    # Delete this type_id from all relations parent and child ids
    relations_manager.remove_type_from_relations(public_id)

    # Delete this type_id from all CiExplorerProfiles
    ci_explorer_profile_manager.remove_type_from_profiles(public_id)

    # Delete the type from all dynamic groups
    object_groups_manager.remove_ids_from_groups(public_id, ObjectGroupMode.DYNAMIC)

    # Delete this type_id from the 'types' array of every CmdbCategory
    categories_manager.remove_type_from_categories(public_id)

    # Strip the deleted type id from every other CmdbType's field-level 'ref_types'
    updated_count: int = cleanup_type_references_from_all_types(types_manager, public_id)

    if updated_count:
        LOGGER.info(
            "Cleaned references to deleted CmdbType %s from %s sibling CmdbType(s)",
            public_id, updated_count,
        )

    # The type-level sweep above cannot reach the 'dg-ipam-interface' section template document, so a
    # deleted SpecialType is additionally un-wired there (template-only, no overlap with the sweep)
    if special_type:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user,
        )
        cleanup_special_type_template_references(
            section_templates_manager,
            special_type,
            public_id,
        )


def location_field_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not remove the CmdbType's location field, if it may not

    A CmdbType's location field may only be dropped once no CmdbObject of that type still stores a
    location value, otherwise those stored values would be silently orphaned. The reason is returned
    instead of raised so both write paths can use it: the route aborts with it
    (`guard_location_field_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the removal is refused, or None when the update is allowed
    """
    removing_location_field: bool = get_location_field(old_type) is not None and get_location_field(new_type) is None

    if not removing_location_field:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot remove the location field: "
        f"{len(object_public_ids)} Object(s) of this Type still have a location value. "
    )


def guard_location_field_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update removes the location field while CmdbObjects still hold a location value

    The route-level wrapper around `location_field_removal_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the location field may not be removed
    """
    blocker: str | None = location_field_removal_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)



def type_has_objects(request_user: CmdbUser, type_id: int) -> bool:
    """
    Whether at least one CmdbObject of the CmdbType exists

    One count, no documents loaded. Shared by the identifier guards below, which only refuse a change
    once there is stored data it could damage - a Type still being designed may be reshaped freely

    Args:
        request_user (CmdbUser): User performing the request
        type_id (int): public_id of the CmdbType

    Returns:
        bool: True when the Type has at least one Object
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    return objects_manager.count_documents({CmdbObjectKey.TYPE_ID: type_id}) > 0


def describe_identifier_swap(old_names: set[str], new_names: set[str]) -> tuple[list[str], list[str]] | None:
    """
    Reports the removed and added identifiers of an edit, but only when it looks like a rename

    A field and a multi-data-section are identified by their **name** and by nothing else - there is
    no stable id underneath - so a rename is indistinguishable from one removal plus one addition in
    the same write. That is precisely what this detects: identifiers disappearing *and* appearing
    together. A pure removal or a pure addition is not a rename and is not reported

    Args:
        old_names (set[str]): The identifiers the stored CmdbType declares
        new_names (set[str]): The identifiers the update would persist

    Returns:
        tuple[list[str], list[str]] | None: (removed, added), sorted, or None when the edit does not
            have the shape of a rename
    """
    removed: set[str] = old_names - new_names
    added: set[str] = new_names - old_names

    if not removed or not added:
        return None

    return sorted(removed), sorted(added)


def field_identifier_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not rename a field identifier, if it may not

    **A field's `name` is its identifier and is immutable once the Type has Objects.** Every
    CmdbObject stores its values keyed by that name, and the realignment that follows a Type update
    reads a rename as one removal plus one addition: the Object loses the value it held and gains an
    empty field. The same is true of a multi-data-section row. Nothing about the payload distinguishes
    a rename from a deliberate remove-plus-add, so the shape itself is refused and the caller is asked
    to perform the two as separate updates.

    This covers ordinary AND multi-data-section fields, because a Type declares every field in its
    flat `fields` list and its sections only reference them by name.

    Only applies once the Type has Objects: a Type still being designed carries no values to lose, and
    the sibling guards are conditioned the same way. The reason is returned rather than raised so both
    write paths can use it - the route aborts with it (`guard_field_identifier_change`), the type
    import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    swap = describe_identifier_swap(
        {field[FieldKey.NAME] for field in old_type.fields},
        {field[FieldKey.NAME] for field in new_type.fields},
    )

    if swap is None or not type_has_objects(request_user, old_type.public_id):
        return None

    removed, added = swap

    return FIELD_IDENTIFIER_IMMUTABLE_MESSAGE.format(
        removed=', '.join(removed), added=', '.join(added),
    )


def guard_field_identifier_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update would rename a field identifier while the CmdbType has Objects

    The route-level wrapper around `field_identifier_change_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when a field identifier would change
    """
    blocker: str | None = field_identifier_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def mds_section_identifier_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not rename a multi-data-section identifier, if it may not

    **A multi-data-section's `name` is the `section_id` every CmdbObject stores its rows under.** The
    MDS propagation matches sections on `(type, name)`, so a renamed section reads as a section the
    Type no longer declares - and every Object drops **all** of its rows for it, not just one value.
    That makes this the most destructive of the identifier renames, and it is refused in the same
    shape: identifiers disappearing and appearing in one write.

    Only applies once the Type has Objects, like its field counterpart

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    swap = describe_identifier_swap(old_type.get_mds_section_ids(), new_type.get_mds_section_ids())

    if swap is None or not type_has_objects(request_user, old_type.public_id):
        return None

    removed, added = swap

    return MDS_SECTION_IDENTIFIER_IMMUTABLE_MESSAGE.format(
        removed=', '.join(removed), added=', '.join(added),
    )


def guard_mds_section_identifier_change(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> None:
    """
    Aborts 400 when an update would rename a multi-data-section while the CmdbType has Objects

    The route-level wrapper around `mds_section_identifier_change_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when a multi-data-section identifier would change
    """
    blocker: str | None = mds_section_identifier_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def compute_removed_global_templates(
    old_type: CmdbType,
    incoming_template_ids: set[str],
) -> tuple[set[str], dict[str, tuple[list[str], str]]]:
    """
    Determines which global section templates an update drops, snapshotting each one's section info

    Compares the pre-update template set to the incoming payload's set and, for each removed
    template still present on old_type, records its section field names and section type while
    they are still available - the blind update wipes those sections afterwards

    Args:
        old_type (CmdbType): State of the CmdbType before the update
        incoming_template_ids (set[str]): global_template_ids carried by the update payload

    Returns:
        tuple[set[str], dict[str, tuple[list[str], str]]]: the removed template names, and a map of
            template name -> (section field names, section type) for each removed template
    """
    removed_template_ids: set[str] = set(old_type.global_template_ids or []) - incoming_template_ids

    removed_template_hints: dict[str, tuple[list[str], str]] = {}

    for template_name in removed_template_ids:
        section = old_type.get_section(template_name)

        if section is not None:
            removed_template_hints[template_name] = (section.get_fields(), section.type)

    return removed_template_ids, removed_template_hints


def build_types_overview_items(
    types: list[dict[str, Any]],
    user_lookup: dict[int, CmdbUser],
) -> list[dict[str, Any]]:
    """
    Builds the per-type response items for the types overview listing

    Each item bundles the CmdbType document with its resolved author/editor display block, so the
    overview can render author/editor names without a per-type user lookup (they are pre-resolved
    from a single bulk ``get_user_lookup``)

    Args:
        types (list[dict[str, Any]]): The CmdbType documents to bundle
        user_lookup (dict[int, CmdbUser]): Lookup of the relevant author / editor CmdbUsers

    Returns:
        list[dict[str, Any]]: One {type_data, user_data} item per type
    """
    response_items: list[dict[str, Any]] = []

    for type_data in types:
        types_user_data: dict[str, Any] = get_types_user_data(
            user_lookup,
            type_data.get(TypeSchemaKey.AUTHOR_ID),
            type_data.get(TypeSchemaKey.EDITOR_ID),
        )

        response_items.append({
            TypeOverviewKey.TYPE_DATA: type_data,
            TypeOverviewKey.USER_DATA: types_user_data,
        })

    return response_items


def strip_removed_global_templates(
    type_document: dict[str, Any],
    removed_templates: tuple[set[str], dict[str, tuple[list[str], str]]],
) -> dict[str, Any]:
    """
    Takes the global section templates an update drops out of the type document it is about to write

    The template's name leaves ``global_template_ids``, its section leaves ``render_meta.sections``, and the fields
    it contributed leave ``fields`` and the summary - in the document itself, so the one type write already carries
    the cleaned type and no second write of the type can fail after it. What the objects still hold of the template
    is dropped by the object alignment that follows, because the type no longer declares it

    Args:
        type_document (dict[str, Any]): The CmdbType document to write; not modified
        removed_templates (tuple): (removed template names, per-template (field names, section type)) as returned
            by compute_removed_global_templates

    Returns:
        dict[str, Any]: A new document without the removed templates (the same one when none is removed)
    """
    removed_template_ids, removed_template_hints = removed_templates

    if not removed_template_ids:
        return type_document

    removed_fields: set[str] = {
        field_name for field_names, _ in removed_template_hints.values() for field_name in field_names
    }
    cleaned: dict[str, Any] = deepcopy(type_document)
    render_meta: dict[str, Any] = cleaned.get(TypeSchemaKey.RENDER_META.value) or {}
    summary: dict[str, Any] = render_meta.get(TypeSchemaKey.SUMMARY.value) or {}

    cleaned[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] = [
        template_id for template_id in cleaned.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or []
        if template_id not in removed_template_ids
    ]
    cleaned[TypeSchemaKey.FIELDS.value] = [
        field for field in cleaned.get(TypeSchemaKey.FIELDS.value) or []
        if field.get(FieldKey.NAME.value) not in removed_fields
    ]

    if TypeSchemaKey.SECTIONS.value in render_meta:
        render_meta[TypeSchemaKey.SECTIONS.value] = [
            section for section in render_meta[TypeSchemaKey.SECTIONS.value]
            if section.get(SectionKey.NAME.value) not in removed_template_ids
        ]

    if TypeSchemaKey.FIELDS.value in summary:
        summary[TypeSchemaKey.FIELDS.value] = [
            field_name for field_name in summary[TypeSchemaKey.FIELDS.value] if field_name not in removed_fields
        ]

    return cleaned


def run_alignment_step(step: TypeAlignmentStep, action: Callable[[], Any]) -> None:
    """
    Runs one step of a type update's alignment, naming the step when it fails

    Args:
        step (TypeAlignmentStep): The step
        action (Callable[[], Any]): What the step does

    Raises:
        HTTPException: Unchanged - a step's own answer, such as the 400 for an object grown past the document
            size limit
        TypesManagerAlignmentError: Wrapping whatever else the step raised, with the step's name
    """
    try:
        action()
    except HTTPException:
        raise
    except Exception as err:
        LOGGER.error("[run_alignment_step] %s failed: %s. Type: %s", step.value, err, type(err).__name__,
                     exc_info=True)
        raise TypesManagerAlignmentError(err, step.value) from err


def apply_type_update_side_effects(
    request_user: CmdbUser,
    types_manager: TypesManager,
    old_type: CmdbType,
    updated_type: CmdbType,
) -> None:
    """
    Brings everything that follows a CmdbType in line with it, once the update is written

    The type is written WITH ``alignment_pending`` set; these steps run in order, each idempotent, and only when
    the last succeeds is the marker cleared:

    1. SpecialType ``ref_types`` wiring (re-applied every time)
    2. label / icon / selectable on the type's CmdbLocations
    3. the multi-data sections of its CmdbObjects
    4. the flat field set of its CmdbObjects
    5. its CmdbReports' fields
    6. the marker cleared

    A step decides what to do from what the update changed - unless the stored type still carried the marker:
    then an earlier save did not finish, what it changed is no longer known, and every step brings its data in line
    with the type as it is now. So a failed save is finished by the next save of the type, the same payload
    included. A failure stops the steps and is raised with the step's name; the marker stays

    Args:
        request_user (CmdbUser): User performing the request
        types_manager (TypesManager): db interface for CmdbTypes
        old_type (CmdbType): The CmdbType as stored before the update
        updated_type (CmdbType): The CmdbType as written

    Raises:
        TypesManagerAlignmentError: When a step failed - the type is written, its marker still set
    """
    force: bool = old_type.alignment_pending
    type_id: int = updated_type.public_id

    if updated_type.special_type:
        run_alignment_step(TypeAlignmentStep.SPECIAL_TYPE_WIRING, lambda: handle_special_types(
            types_manager, updated_type.special_type,
            ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES, request_user), type_id,
        ))

    run_alignment_step(TypeAlignmentStep.LOCATIONS,
                       lambda: apply_type_changes_to_locations(request_user, old_type, updated_type, force))
    run_alignment_step(TypeAlignmentStep.MULTI_DATA_SECTIONS, lambda: (
        align_type_mds(request_user, updated_type) if force
        else apply_type_changes_to_mds(request_user, old_type, CmdbType.to_json(updated_type))
    ))
    run_alignment_step(TypeAlignmentStep.OBJECT_FIELDS,
                       lambda: realign_type_object_fields(request_user, old_type, updated_type, force))
    run_alignment_step(TypeAlignmentStep.REPORTS,
                       lambda: clean_type_reports_after_update(request_user, old_type, updated_type, force))
    run_alignment_step(TypeAlignmentStep.ALIGNMENT_MARKER,
                       lambda: types_manager.update_type_field(type_id, TypeSchemaKey.ALIGNMENT_PENDING.value, False))
