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
Deriving a REQUEST schema from a document schema

Every schema under ``cmdb.class_schema`` describes a stored DOCUMENT: it is the contract a document in
the collection satisfies, and a stored document validating against its own schema is a property the
model tests assert. A request body is a different contract - it must not carry the keys the server
owns - and the two used to be the same dict, so ``APIBlueprint.validate`` admitted a client-chosen
``public_id`` on every write route that validated a document schema.

``build_write_schema`` derives the request contract from the document one, so a field's type stays
declared in exactly one place. What it removes is ``public_id``: the validator runs with
``purge_unknown=True``, so an undeclared key is DROPPED rather than rejected, and a payload id can no
longer reach the route at all. The pattern itself is not new - ``get_cmdb_port_connection_write_schema``
hand-rolled it first, for the same reason and with a wider set of server-owned keys.

Where a client-supplied id is contract rather than accident - ``POST /objects/`` honours a free one,
and the object importer imports under the id its file names - the document schema is used as-is and the
route keeps its own verification.
"""
from typing import Any
from collections.abc import Iterable
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_write_schema',
]


def build_write_schema(
        document_schema: dict[str, Any],
        server_owned: Iterable[str] | None = None,
    ) -> dict[str, Any]:
    """
    Derives a request-body schema from a document schema by dropping the server-owned keys

    Every other rule is carried over unchanged, so a write route keeps validating exactly what it
    validated before - minus the keys a client has no business sending

    The default set is the identity alone (``CmdbDAO.PUBLIC_ID_KEY``). The audit fields are
    server-stamped too, but several routes still round-trip them through the body, so widening the set
    is a change of its own. ``CmdbDAO`` is imported inside the function, not at module level: the
    class_schema package is importable on its own only because nothing here reaches into cmdb.models
    while a model package is still initialising (see the package docstring)

    Args:
        document_schema (dict[str, Any]): The model's document schema (its ``SCHEMA``)
        server_owned (Iterable[str] | None): Keys to drop; None selects the identity key

    Returns:
        dict[str, Any]: The request schema, a new dict; the document schema is not modified
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.cmdb_dao import CmdbDAO

    owned: set[str] = set(server_owned) if server_owned is not None else {CmdbDAO.PUBLIC_ID_KEY}

    return {key: rules for key, rules in document_schema.items() if key not in owned}
