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
What the caller may do with each Type an answer carries - ``allowed_operations`` on every Type of it - and the ``acl``
each Type answers with

The access engine decides (``access_engine.allowed_operation_values``): ``view``, ``create``, ``edit``, ``delete`` as
allowed, read once per request whatever the number of Types. A client shows or hides its actions by this list instead
of reading the Type's ``acl`` itself. The ``acl`` an answer carries is the one the access rules decide
(``access_engine.synthesised_acl_values``), never the stored block, which decides nothing - so a client still reading
it sees the truth
"""
from collections.abc import Iterable
from typing import Any

from cmdb.framework.access_engine import ALLOWED_OPERATIONS_KEY, allowed_operation_values, synthesised_acl_values
from cmdb.models.category_model.category_constants import CategoryNodeKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #


def with_allowed_operations(type_documents: Iterable[dict[str, Any]], user: CmdbUser) -> None:
    """
    Adds the caller's allowed operations to each Type document - one engine call for all of them

    A document without an integer ``public_id`` (a projection leaving it out) is left as it is

    Args:
        type_documents (Iterable[dict[str, Any]]): The Type documents of the answer, changed in place
        user (CmdbUser): The caller

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the caller's grants could not be read
    """
    documents: list[dict[str, Any]] = [document for document in type_documents
                                       if isinstance(document.get(TypeSchemaKey.PUBLIC_ID.value), int)]
    allowed: dict[int, list[str]] = allowed_operation_values(
        user, [document[TypeSchemaKey.PUBLIC_ID.value] for document in documents])

    for document in documents:
        document[ALLOWED_OPERATIONS_KEY] = allowed[document[TypeSchemaKey.PUBLIC_ID.value]]


def with_synthesised_acl(type_documents: Iterable[dict[str, Any]], user: CmdbUser) -> None:
    """
    Replaces each Type document's ``acl`` with the block the access rules decide - one read for all of them

    A document without an ``acl`` (a projection leaving it out) or without an integer ``public_id`` is left as it is

    Args:
        type_documents (Iterable[dict[str, Any]]): The Type documents of the answer, changed in place
        user (CmdbUser): The caller - it names the tenant

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the access rules could not be read
    """
    documents: list[dict[str, Any]] = [document for document in type_documents
                                       if TypeSchemaKey.ACL.value in document
                                       and isinstance(document.get(TypeSchemaKey.PUBLIC_ID.value), int)]

    if not documents:
        return

    blocks: dict[int, dict[str, Any]] = synthesised_acl_values(
        user, [document[TypeSchemaKey.PUBLIC_ID.value] for document in documents])

    for document in documents:
        document[TypeSchemaKey.ACL.value] = blocks[document[TypeSchemaKey.PUBLIC_ID.value]]


def tree_types(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Every Type document of a category tree's nodes, at any depth

    Args:
        nodes (Iterable[dict[str, Any]]): The tree's root nodes as answered (``CategoryTree.to_json``)

    Returns:
        list[dict[str, Any]]: The Type documents, in tree order
    """
    found: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = list(nodes)

    while pending:
        node: dict[str, Any] = pending.pop(0)
        found.extend(node.get(CategoryNodeKey.TYPES.value) or [])
        pending.extend(node.get(CategoryNodeKey.CHILDREN.value) or [])

    return found
