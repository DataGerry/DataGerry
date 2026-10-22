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
The three steps of ``PUT /types/<public_id>``, in the order the route runs them

* ``prepare_type_update_payload``: the payload alone, against the stored Type - licences, the reconciled global
  template copies, the normalisations, the structure rules and the ACL groups
* ``guard_type_update_changes``: the stored Type against the new one - every change refused while Objects (or other
  Types) depend on what it would change
* ``write_type_update``: the one write of the Type, the alignment marker set, then everything that follows the Type
  brought in line with it

Each step refuses with an HTTPException; nothing is written before ``write_type_update``
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from pymongo.results import UpdateResult

from cmdb.manager import GroupsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_acl_helper import abort_if_unknown_acl_groups
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper import (
    guard_field_identifier_change,
    guard_location_field_removal,
    guard_mds_section_identifier_change,
    guard_selectable_as_parent_change,
    guard_uses_ports_change,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    SPECIAL_TYPE_IMMUTABLE_MESSAGE,
    TYPE_GONE_BEFORE_UPDATE_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    apply_type_update_side_effects,
    enforce_rack_selectable_as_parent,
    enforce_special_type_license,
    enforce_uses_ports_license,
    normalize_ci_explorer_label,
    normalize_port_section_index,
    special_type_is_unchanged,
    strip_removed_global_templates,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    guard_referenced_section_removal,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_structure_helper import (
    drop_stale_type_references,
    guard_field_defaults,
    guard_field_patterns,
    guard_new_identifiers,
    guard_type_structure,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_template_helper import (
    reconcile_global_template_copies,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def prepare_type_update_payload(data: dict[str, Any], old_type: CmdbType, request_user: CmdbUser) -> list[str]:
    """
    Brings a Type update's payload into the shape it is stored in, and refuses one that may not be stored

    Runs before ``CmdbType.from_data``, so every normalisation reaches the instance that is written. In order:

    1. the IPAM licence for an IPAM SpecialType (stored or requested), a Rack kept selectable as a parent, and the
       IPAM licence for turning ``uses_ports`` on - only the requested value is gated, so an unlicensed instance can
       still turn it off
    2. each claimed global section template's copy is put back in line with the stored template, before any rule
       judges the payload; a claim naming no stored template is dropped and returned
    3. the port section index is validated (and reset without ports), the CI Explorer label nomination is cleared
       when its field leaves, and the stale names a stored Type carries are dropped
    4. the identifier, structure, pattern and default rules of the create - for identifiers and patterns only what
       the update adds or changes, a stored one passes
    5. a UserGroup the ``acl`` names must exist, unless the stored ``acl`` already names it

    Args:
        data (dict[str, Any]): The validated update payload, changed in place
        old_type (CmdbType): The stored Type
        request_user (CmdbUser): CmdbUser requesting the update

    Raises:
        HTTPException: 403 when a licence is missing; 400 when a rule refuses the payload

    Returns:
        list[str]: The global template claims that named no stored template
    """
    enforce_special_type_license(request_user, old_type.special_type, data.get(TypeSchemaKey.SPECIAL_TYPE))
    # Keyed on the STORED marker: the SpecialType of a Type never changes (guard_type_update_changes)
    enforce_rack_selectable_as_parent(old_type.special_type, data)
    enforce_uses_ports_license(request_user, data.get(TypeSchemaKey.USES_PORTS))

    dropped_claims: list[str] = reconcile_global_template_copies(data, request_user)

    normalize_port_section_index(data)
    normalize_ci_explorer_label(data, old_type)
    drop_stale_type_references(data, old_type)

    guard_new_identifiers(data, old_type)
    guard_type_structure(data)
    guard_field_patterns(data, old_type)
    guard_field_defaults(data)

    groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    abort_if_unknown_acl_groups(data, groups_manager, CmdbType.to_json(old_type).get(TypeSchemaKey.ACL.value))

    return dropped_claims


def guard_type_update_changes(
        request_user: CmdbUser,
        old_type: CmdbType,
        new_type: CmdbType,
        requested_special_type: str | None) -> None:
    """
    Refuses the changes a Type update may not make to the stored Type

    * the SpecialType never changes
    * a field name or a multi-data-section name is an identifier: every CmdbObject keys its values (its rows) by it,
      so neither is renamed while the Type has Objects
    * the location field stays while CmdbObjects hold a location value
    * a section another Type's reference section pulls from stays while that reference exists
    * ``selectable_as_parent`` stays on while CmdbObjects of the Type are placed in the tree, and ``uses_ports`` while
      Ports of its Objects exist

    Args:
        request_user (CmdbUser): CmdbUser requesting the update
        old_type (CmdbType): The stored Type
        new_type (CmdbType): The Type the update would write
        requested_special_type (str | None): The SpecialType the payload names

    Raises:
        HTTPException: 400 when a change is refused
        ObjectsManagerGetError: When a guard could not read the Objects it judges
    """
    if not special_type_is_unchanged(old_type.special_type, requested_special_type):
        abort(400, SPECIAL_TYPE_IMMUTABLE_MESSAGE)

    guard_field_identifier_change(request_user, old_type, new_type)
    guard_mds_section_identifier_change(request_user, old_type, new_type)
    guard_location_field_removal(request_user, old_type, new_type)
    guard_referenced_section_removal(request_user, old_type, new_type)
    guard_selectable_as_parent_change(request_user, old_type, new_type)
    guard_uses_ports_change(request_user, old_type, new_type)


def write_type_update(
        request_user: CmdbUser,
        types_manager: TypesManager,
        old_type: CmdbType,
        new_type: CmdbType,
        removed_templates: tuple[set[str], dict[str, tuple[list[str], str]]]) -> None:
    """
    Writes a Type update once, then brings everything that follows the Type in line with it

    The document written has the dropped global templates already taken out and ``alignment_pending`` set. The
    SpecialType wiring, the Locations, the Objects and the Reports are aligned afterwards, and only when all of that
    succeeded is the marker cleared - so a save that fails half-way shows on the Type, and its next save finishes the
    work. A full-document update that does not upsert: a Type deleted since it was read is not recreated

    Args:
        request_user (CmdbUser): CmdbUser requesting the update
        types_manager (TypesManager): Manager of the Types
        old_type (CmdbType): The stored Type before the update
        new_type (CmdbType): The Type the update writes
        removed_templates (tuple[set[str], dict[str, tuple[list[str], str]]]): The global templates the update drops,
            from ``compute_removed_global_templates``

    Raises:
        HTTPException: 404 when the Type no longer exists
        TypesManagerUpdateError: When the write failed
        TypesManagerAlignmentError: When a step after the write failed; the Type IS saved and carries the marker
    """
    public_id: int = new_type.get_public_id()
    type_document: dict[str, Any] = strip_removed_global_templates(CmdbType.to_json(new_type), removed_templates)
    type_document[TypeSchemaKey.ALIGNMENT_PENDING.value] = True
    written_type: CmdbType = CmdbType.from_data(type_document)

    update_result: UpdateResult = types_manager.update_type(public_id, type_document)

    if update_result.matched_count == 0:
        LOGGER.warning(
            "[write_type_update] Type with ID:%s disappeared between its read and its update", public_id
        )
        abort(404, TYPE_GONE_BEFORE_UPDATE_MESSAGE.format(public_id=public_id))

    # written_type IS what was just written, so it is used directly instead of reading it back
    apply_type_update_side_effects(request_user, types_manager, old_type, written_type)
