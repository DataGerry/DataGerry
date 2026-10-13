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
Object-ACL filtering for the CI Explorer graph

The ACL is applied to **every** source - object relations, dg_location, IPAM, and the focal object
itself - not only to the one a caller enters through. Without that, a user who can open the CI
Explorer learns the label, type and neighbourhood of objects they are not allowed to read anywhere
else in the product.

An ACL lives on the **CmdbType**, not on the CmdbObject, so the question is per type rather than per object.
It is asked twice, from the same rule:

* **once before any source reads** - ``load_denied_type_ids``, one projected query on ``framework.types``. The
  focal object is refused on it straight away, and every source keeps denied neighbours out of its own Mongo
  read (``type_scope.NeighbourTypeScope``), so they spend none of the ``item_limit`` budget. Were they read and
  dropped afterwards, a capped graph would come back emptier than an uncapped one - fewer nodes than the cap
  while readable neighbours exist, and, by trying caps, a count of what the caller may not see
* **once over the types actually loaded** - ``collect_denied_type_ids``, a pure pass with no query, as the
  safety net that keeps a type whose ACL changed between the two reads out of the payload

Two rules govern what comes out:

**A denied neighbour is omitted silently.** No placeholder node, no count, no slot of the cap - nothing in the
payload that distinguishes "there is a neighbour you may not see" from "there is no neighbour". A placeholder,
or a cap spent on it, would leak exactly what the ACL hides: that the object exists.

**A denied focal object is a 404, identical to a missing one.** Same reasoning - a 403 would confirm
the object exists. ``build_ci_explorer_graph`` raises ``CiExplorerTargetNotFoundError`` for both, so
the route needs no new branch and the frontend no new state.

An object whose ``type_id`` resolves to no CmdbType at all passes the filter. That matches
``acl/builder.py``, whose ``type_id: {'$nin': [...]}`` exclusion lets an orphan through for the same
reason: a filter that denies on absence would hide data no ACL was ever configured to protect. Such
an object is dropped a step later anyway, by ``resolve_composable``, because it has no type to draw
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import TypesManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.builder import DENIED_TYPES_PROJECTION, build_denied_types_criteria
from cmdb.security.acl.helpers import has_type_document_access
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: The CI Explorer is a read surface, so READ is the only permission any of its nodes is checked for
CI_EXPLORER_PERMISSION: AccessControlPermission = AccessControlPermission.READ

TYPE_ID_KEY: str = 'type_id'


def load_denied_type_ids(
        types_manager: TypesManager,
        user: CmdbUser | None,
        permission: AccessControlPermission = CI_EXPLORER_PERMISSION) -> frozenset[int]:
    """
    Reads, once per request, the CmdbTypes the requesting user may NOT read

    One projected query on ``framework.types`` - the same rule ``collect_denied_type_ids`` applies to the documents
    it is handed (``build_denied_types_criteria`` and ``has_type_document_access`` read an ACL alike). Known before
    any source reads, it lets each source keep unreadable neighbours out of its own read, so they spend none of the
    ``item_limit`` budget, and a hidden focal object is refused before anything else is read

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        user (CmdbUser | None): The CmdbUser the request was made for, or None to skip the check
        permission (AccessControlPermission): The permission the user's group must hold. Defaults to READ

    Returns:
        frozenset[int]: public_ids of the CmdbTypes the user may not read; empty without a user
    """
    if user is None:
        return frozenset()

    denied_types = types_manager.find(
        criteria=build_denied_types_criteria(int(user.group_id), permission),
        projection=DENIED_TYPES_PROJECTION,
    )

    return frozenset(
        denied_type[TypeSchemaKey.PUBLIC_ID.value]
        for denied_type in denied_types
        if denied_type.get(TypeSchemaKey.PUBLIC_ID.value) is not None
    )


def collect_denied_type_ids(
        types_by_id: dict[int, dict[str, Any]],
        user: CmdbUser | None,
        permission: AccessControlPermission = CI_EXPLORER_PERMISSION) -> set[int]:
    """
    Resolves which of the in-scope CmdbTypes the requesting user may NOT read

    Pure: it reads the type documents the graph has already loaded and issues no query of its own.
    ``user`` of None disables access control entirely, matching ``acl/helpers.verify_access`` - the
    convention every manager in this codebase follows for an internal caller with no user to check

    Args:
        types_by_id (dict[int, dict[str, Any]]): The CmdbType documents of every object in scope,
            keyed by public_id
        user (CmdbUser | None): The CmdbUser the request was made for, or None to skip the check
        permission (AccessControlPermission): The permission the user's group must hold. Defaults
            to READ, which is the only permission the graph needs

    Returns:
        set[int]: public_ids of the CmdbTypes whose objects must not appear in the response; empty
            when nothing is denied, which is the common case
    """
    if user is None:
        return set()

    denied_type_ids: set[int] = {
        type_id for type_id, type_document in types_by_id.items()
        if not has_type_document_access(type_document, user, permission)
    }

    if denied_type_ids:
        LOGGER.debug(
            "[ci_explorer] ACL denies user %s read access to %s of the %s CmdbType(s) in scope",
            user.public_id, len(denied_type_ids), len(types_by_id),
        )

    return denied_type_ids


def is_denied(document: dict[str, Any], denied_type_ids: set[int] | frozenset[int]) -> bool:
    """
    Whether one object document belongs to a CmdbType the requesting user may not read

    Args:
        document (dict[str, Any]): A CmdbObject document
        denied_type_ids (set[int] | frozenset[int]): The denied CmdbType public_ids - from
            ``load_denied_type_ids`` or ``collect_denied_type_ids``

    Returns:
        bool: True when the object must not appear in the response
    """
    return document.get(TYPE_ID_KEY) in denied_type_ids


def filter_accessible_objects(
        documents: list[dict[str, Any]],
        denied_type_ids: set[int]) -> list[dict[str, Any]]:
    """
    Drops every object of a denied CmdbType, keeping the order of the rest

    Applied before the enrichment pass rather than after it, so a denied object costs no summary or
    dg_location lookup and never reaches the composers. With nothing denied the input list is
    returned unchanged

    Args:
        documents (list[dict[str, Any]]): Every CmdbObject in scope - root, relation, location, IPAM
        denied_type_ids (set[int]): The denied CmdbType public_ids from ``collect_denied_type_ids``

    Returns:
        list[dict[str, Any]]: The documents the requesting user may read
    """
    if not denied_type_ids:
        return documents

    return [document for document in documents if not is_denied(document, denied_type_ids)]
