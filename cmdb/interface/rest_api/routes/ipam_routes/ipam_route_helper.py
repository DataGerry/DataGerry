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
Shared request readers for the IPAM route modules

Every paginated IPAM view reads the same `page` / `page_size` / `search` triple off the query string
with the same defaults and the same truncation, and every IPAM write route reads the same JSON object
body, so the parsing lives here instead of being repeated per route. These helpers only normalise what
arrives on the wire - the values are still validated by the framework-layer builders that consume them.

The body readers below the query-string ones serve the `/ipam/validate/*` pre-checks, which take a
JSON body instead of a query string. They share one rule that is the whole reason they exist: a
field the caller **omitted** and a field the caller **sent as something unusable** are different
requests and get different answers. On a pre-check route that distinction decides correctness - an
unreadable `exclude_subnet_id` read as "nothing to exclude" makes the validator compare a subnet
against itself and answer "invalid" for an edit that is perfectly valid - so an unusable value is
refused with a 400 and only an absent one reads as None.

`read_ipam_managers` is the one exception to "request readers": every IPAM view needs the same two
managers and resolved them in the same two lines per route, so the pair is assembled here as well
"""
from typing import Any

from flask import abort, request

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.utils import coerce_whole_number

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamPagination,
    IpamSearch,
    IpamValidationRequestKey,
)
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_constants import (
    INVALID_OBJECT_ID_MESSAGE,
    REQUIRED_OBJECT_ID_MESSAGE,
    REQUIRED_STRING_MESSAGE,
    VALIDATION_ROW_INDEX_MESSAGE,
    VALIDATION_ROW_NOT_AN_OBJECT_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Page number served when the client sends none, an unparsable one, or an explicit 0
DEFAULT_PAGE: int = 1


def read_pagination_params() -> tuple[int, int]:
    """
    Reads the `page` / `page_size` pair off the current request's query string

    A missing, unparsable or zero value falls back to the default; the builders clamp the result
    into the valid range afterwards, so no bounds are enforced here

    Returns:
        tuple[int, int]: The requested page number and page size
    """
    page: int = request.args.get(IpamOverviewKey.PAGE, default=DEFAULT_PAGE, type=int) or DEFAULT_PAGE
    page_size: int = (
        request.args.get(IpamOverviewKey.PAGE_SIZE, default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
        or IpamPagination.DEFAULT_PAGE_SIZE
    )

    return page, page_size


def read_string_param(key: str) -> str:
    """
    Reads one string filter off the current request's query string

    The `default='' ... or ''` pair matters and is why this is a helper rather than an inline call:
    Flask returns None both when the parameter is absent and when it arrives with an empty value, so
    without the trailing `or ''` an `?sort=` with nothing after it reaches a builder as None instead
    of as "no sort requested".

    Nothing is validated here. Whether the value is a usable one depends on type or schema context
    the route does not have, so the framework-layer builder that consumes it decides - see the module
    docstring of `ipam_subnet_routes`

    Args:
        key (str): The query-parameter name to read

    Returns:
        str: The raw value, empty when the parameter is absent or empty
    """
    return request.args.get(key, default='', type=str) or ''


def read_search_param() -> str:
    """
    Reads the `search` filter off the current request's query string

    Truncated at `IpamSearch.MAX_QUERY_LENGTH` here so an oversized query never reaches a builder;
    queries shorter than `IpamSearch.MIN_QUERY_LENGTH` are ignored by the builders themselves

    Returns:
        str: The raw search query, truncated to the maximum length; empty when none was sent
    """
    raw_search: str = request.args.get(IpamOverviewKey.SEARCH, default='', type=str) or ''

    return raw_search[:IpamSearch.MAX_QUERY_LENGTH]


def read_json_object_body() -> dict[str, Any]:
    """
    Reads the current request's body as a JSON object

    A body that is absent, unparseable, or parses to something other than an object is rejected here.
    Without this guard `request.get_json(silent=True) or {}` turns all three cases into an empty dict,
    and the caller is told a required field is missing rather than that its body never arrived

    Raises:
        HTTPException: 400 when the body is not a JSON object

    Returns:
        dict[str, Any]: The decoded body
    """
    payload: Any = request.get_json(silent=True)

    if not isinstance(payload, dict):
        abort(400, "Request body must be a JSON object!")

    return payload


def read_required_string(payload: dict[str, Any], field: str) -> str:
    """
    Reads a body field that has to carry a non-empty string

    The guard in front of every candidate a pre-check route validates: an absent field, a null, a
    number and an empty string are all the same refusal, because none of them is something the
    validator can parse a CIDR out of

    Args:
        payload (dict[str, Any]): The decoded request body
        field (str): The body key to read

    Raises:
        HTTPException: 400 when the field is absent, not a string, or empty

    Returns:
        str: The field's value
    """
    value: Any = payload.get(field)

    if not isinstance(value, str) or not value:
        abort(400, REQUIRED_STRING_MESSAGE.format(field=field))

    return value


def read_required_object_id(payload: dict[str, Any], field: str) -> int:
    """
    Reads a body field that has to carry an object id

    Args:
        payload (dict[str, Any]): The decoded request body
        field (str): The body key to read

    Raises:
        HTTPException: 400 when the field is absent or is not a whole number

    Returns:
        int: The id as a number
    """
    object_id: int | None = coerce_whole_number(payload.get(field))

    if object_id is None:
        abort(400, REQUIRED_OBJECT_ID_MESSAGE.format(field=field))

    return object_id


def read_optional_object_id(payload: dict[str, Any], field: str) -> int | None:
    """
    Reads a body field that may carry an object id, refusing an unusable one

    **Absent is not the same as unusable, and that distinction is the point.** Omitting the field (or
    sending null) means "none" - no parent supernet chosen, nothing to exclude - and is answered with
    None. A field that IS present but holds something that is not a whole number is refused with a
    400 rather than being read as "none", because on a pre-check route reading it as "none" does not
    fail, it answers the caller's question **wrongly**: an unreadable `exclude_subnet_id` stops the
    candidate being excluded from its own sibling check, so editing a subnet without touching its
    range comes back as an overlap with itself.

    `coerce_whole_number` is what decides usability, so a JSON boolean is refused (it is an int
    subclass in Python, and `True` would otherwise pass as the id 1) and a fractional float is
    refused rather than truncated

    Args:
        payload (dict[str, Any]): The decoded request body
        field (str): The body key to read

    Raises:
        HTTPException: 400 when the field is present but is not a whole number

    Returns:
        int | None: The id as a number, or None when the field was not sent
    """
    raw: Any = payload.get(field)

    if raw is None:
        return None

    object_id: int | None = coerce_whole_number(raw)

    if object_id is None:
        abort(400, INVALID_OBJECT_ID_MESSAGE.format(field=field, value=raw))

    return object_id


def parse_interface_rows_payload(
        raw_rows: list[Any]) -> list[tuple[int, int | None, str | None, str | None]]:
    """
    Normalises the `/validate/interface` row list into the tuple shape the batch validator expects

    Each entry must be a dict carrying a whole-number `row_index`; a missing or unreadable one fails
    the whole request, because the response echoes the index back so the frontend can attach each
    error to the row that caused it and a guessed index would attach it to the wrong row.

    The other three fields are optional per row and follow save-time semantics rather than being
    refused: a missing `subnet_id` or `ip_address` leaves the row in the cross-row duplicate check but
    skips the per-row database check, so a half-typed row produces no noise, and a missing
    `interface_type` skips the type-family check the way a legacy row does. Note the asymmetry with
    the ids read by `read_optional_object_id`: here an unusable value is deliberately tolerated as
    "not filled in yet", because the caller is a form being typed into

    Args:
        raw_rows (list[Any]): The `rows` field straight off the decoded body

    Raises:
        HTTPException: 400 when an entry is not an object, or carries no readable `row_index`

    Returns:
        list[tuple[int, int | None, str | None, str | None]]: One
            (row_index, subnet_ref, ip_address, interface_type) tuple per row, in input order
    """
    rows: list[tuple[int, int | None, str | None, str | None]] = []

    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            abort(400, VALIDATION_ROW_NOT_AN_OBJECT_MESSAGE.format(index=index))

        row_index: int | None = coerce_whole_number(raw.get(IpamValidationRequestKey.ROW_INDEX.value))

        if row_index is None:
            abort(400, VALIDATION_ROW_INDEX_MESSAGE.format(
                index=index, field=IpamValidationRequestKey.ROW_INDEX.value,
            ))

        subnet_ref: int | None = coerce_whole_number(raw.get(IpamValidationRequestKey.SUBNET_ID.value))

        ip_raw: Any = raw.get(IpamValidationRequestKey.IP_ADDRESS.value)
        ip_address: str | None = ip_raw if isinstance(ip_raw, str) and ip_raw else None

        type_raw: Any = raw.get(IpamValidationRequestKey.INTERFACE_TYPE.value)
        interface_type: str | None = type_raw if isinstance(type_raw, str) and type_raw else None

        rows.append((row_index, subnet_ref, ip_address, interface_type))

    return rows


def read_ipam_managers(request_user: CmdbUser) -> tuple[ObjectsManager, TypesManager]:
    """
    Resolves the two managers every IPAM view needs

    Each IPAM payload is built from CmdbObjects plus the CmdbTypes that give them their labels and
    their SUBNET / SUPERNET markers, so every route resolved the identical pair in the identical two
    lines. Returned as a tuple rather than assembled into an object because that is exactly how the
    framework-layer builders take them - `(objects_manager, types_manager)`, in that order, as their
    first two positional arguments

    Args:
        request_user (CmdbUser): The user the managers are resolved for (selects the database in
            cloud mode)

    Returns:
        tuple[ObjectsManager, TypesManager]: The objects manager and the types manager
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    return objects_manager, types_manager
