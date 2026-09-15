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
Refusal messages of the IPAM REST routes

The route-surface counterpart of ``models/special_type_model/ipam_constants.py``: that module owns what
the IPAM *domain* is made of (field names, address families, pagination and search limits, the export
column rows), this one owns what the HTTP layer *says* when it refuses a request. The split follows
``cmdb_objects/objects_constants.py``, whose docstring states the same rule - a document's own keys
belong to the model, a query parameter and a refusal message belong to the REST surface.

The subnet and the validation routes read their messages from here. ``ipam_route_helper.py`` still
inlines the one it raises for a non-object body; it belongs here too.

Members with a ``{...}`` placeholder are filled via ``format()``
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SUBNET_INVALID_FAMILY_MESSAGE',
    'SUBNET_SECTOR_START_REQUIRED_MESSAGE',
    'REQUIRED_STRING_MESSAGE',
    'REQUIRED_OBJECT_ID_MESSAGE',
    'INVALID_OBJECT_ID_MESSAGE',
    'VALIDATION_ROWS_NOT_A_LIST_MESSAGE',
    'VALIDATION_ROW_NOT_AN_OBJECT_MESSAGE',
    'VALIDATION_ROW_INDEX_MESSAGE',
]

# Refusal (HTTP 400) when the subnet-options route is given a `type` that is not an address family.
# Names the allowed tokens because the same parameter means something entirely different one route
# over (a CmdbType public_id list on the overview), so "invalid" alone would leave the caller guessing
# which of the two meanings it got wrong. The comparison behind it is case-sensitive, hence the
# echo of what was actually sent
SUBNET_INVALID_FAMILY_MESSAGE: str = (
    "'{family}' is not a valid address family; allowed values: {allowed}!"
)

# Refusal (HTTP 400) when the sector drill-down is called without the sector it should drill into.
# Required rather than defaulted: a sector is identified by the `ip_start` the overview's
# ip_distribution emitted for that cell, and guessing one would silently return a different sector's
# page than the one the user clicked
SUBNET_SECTOR_START_REQUIRED_MESSAGE: str = (
    "The '{parameter}' query parameter is required - it identifies the sector to list!"
)


# Refusal (HTTP 400) for a body field that has to carry a non-empty string
REQUIRED_STRING_MESSAGE: str = "'{field}' is required and must be a non-empty string!"

# Refusal (HTTP 400) for a body field that has to carry an object id
REQUIRED_OBJECT_ID_MESSAGE: str = "'{field}' is required and must be a whole number!"

# Refusal (HTTP 400) for an OPTIONAL id field that was sent, but not as a usable id. Distinguished from
# REQUIRED_OBJECT_ID_MESSAGE because omitting the field is legal and means something specific - on the
# validation routes an absent `exclude_*_id` means "nothing to exclude". Silently reading an unusable
# value as absent would answer the caller's question with the wrong answer instead of refusing it
INVALID_OBJECT_ID_MESSAGE: str = (
    "'{field}' was sent as {value!r}, which is not a whole number - omit it entirely to mean 'none'!"
)

# Refusal (HTTP 400) when the interface pre-check is not given a list of rows to check
VALIDATION_ROWS_NOT_A_LIST_MESSAGE: str = (
    "'{field}' is required and must be a list of {{row_index, subnet_id, ip_address, interface_type}}!"
)

# Refusal (HTTP 400) for one unusable entry of that list. Positional, because the entry has no id of
# its own to name it by - and its own `row_index` is exactly what is missing or unreadable here
VALIDATION_ROW_NOT_AN_OBJECT_MESSAGE: str = "rows[{index}] must be an object!"

# Refusal (HTTP 400) when a row carries no readable position. Required rather than defaulted: the
# response echoes the index back so the frontend can attach each error to the row that caused it, and a
# guessed index would attach it to the wrong row
VALIDATION_ROW_INDEX_MESSAGE: str = (
    "rows[{index}].{field} is required and must be a whole number!"
)
