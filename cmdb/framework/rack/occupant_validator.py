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
Which fields each kind of Rack row may carry

The SHAPE rules, as opposed to the geometry rules in mount_validator: one document holds a mounted
CmdbObject, a reservation and a blocker, so something has to say which fields belong to which kind.

  - **MOUNT** names a CmdbObject and carries none of the reservation fields
  - **RESERVATION** names no object. Its ``start_date`` and ``end_date`` are both optional, and its
    ``color`` is optional; a date range that is given in full must not end before it starts
  - **BLOCKER** names no object and carries no reservation fields either - it is a fact about the rack,
    not a plan

The dates are **purely descriptive**. Nothing here or anywhere else reads the clock: a reservation
occupies its slots until somebody deletes or unassigns it, whatever its dates say. That keeps the
overlap check pure, keeps the dry-run route from disagreeing with the write moments later, and means a
reservation can never quietly stop holding space the user still believes is held.

Pure and free of Flask: every function reports its reasons and the routes decide whether to abort. Both
the write path and the dry-run ``/validate`` route go through the same cores, so neither can accept a row
the other refuses
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.utils import coerce_datetime, is_hex_color

from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey, RackMountKind

from cmdb.framework.rack.rack_constants import RackOccupantError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The fields that belong to a RESERVATION alone, in the order they are reported
RESERVATION_KEYS: tuple[RackMountKey, ...] = (
    RackMountKey.START_DATE,
    RackMountKey.END_DATE,
    RackMountKey.COLOR,
)

# The date fields, in the order they are reported
DATE_KEYS: tuple[RackMountKey, ...] = (RackMountKey.START_DATE, RackMountKey.END_DATE)

# -------------------------------------------------------------------------------------------------------------------- #

def coerce_kind(raw_kind: Any) -> str | None:
    """
    Reads the kind out of a request, defaulting to MOUNT

    An absent kind means MOUNT: that keeps every existing client working unchanged, and it is what a row
    written before the kinds existed reads as. An unrecognised value is NOT defaulted - it returns None
    so the caller can refuse it, because guessing MOUNT for a misspelled 'RESERVATON' would silently
    create the wrong kind of row

    Args:
        raw_kind (Any): The raw kind value from the request

    Returns:
        str | None: The RackMountKind value, or None when the value is not a known kind
    """
    if raw_kind is None:
        return RackMountKind.MOUNT.value

    if isinstance(raw_kind, str) and raw_kind in {member.value for member in RackMountKind}:
        return raw_kind

    return None


def read_stored_kind(mount: dict[str, Any]) -> str:
    """
    Reads a stored row's kind, defaulting to MOUNT

    Every row written since the kinds existed carries one; a row written before them is a mount, which is
    exactly what the default says. A drifted value defaults the same way rather than propagating - a row
    must stay editable and drawable even if its kind did not survive whatever wrote it

    Args:
        mount (dict[str, Any]): The stored row

    Returns:
        str: The row's RackMountKind value
    """
    kind: Any = mount.get(RackMountKey.KIND.value)

    return coerce_kind(kind) or RackMountKind.MOUNT.value


def unknown_kind_blocker(raw_kind: Any) -> str | None:
    """
    Judges whether a request names a kind that exists

    Args:
        raw_kind (Any): The raw kind value from the request

    Returns:
        str | None: The reason the kind is unusable, or None when it is fine
    """
    if coerce_kind(raw_kind) is not None:
        return None

    return RackOccupantError.UNKNOWN_KIND.format(
        kind=raw_kind,
        allowed=', '.join(member.value for member in RackMountKind),
    )


def field_blockers(kind: str, payload: dict[str, Any]) -> list[str]:
    """
    Judges the fields a request carries against the kind of row it is creating or changing

    Reports every reason at once rather than the first, so a caller fixes one payload rather than
    discovering the rules one request at a time. Only keys the payload actually carries are judged, which
    is what lets the same core back a PATCH that names a single field

    Args:
        kind (str): The RackMountKind value of the row
        payload (dict[str, Any]): The request body

    Returns:
        list[str]: The reasons the request is refused; empty when its shape is valid
    """
    blockers: list[str] = []

    if RackMountKind.is_occupant(kind) and payload.get(RackMountKey.OBJECT_ID.value) is not None:
        blockers.append(RackOccupantError.OBJECT_ID_ON_OCCUPANT.format(kind=kind))

    if kind != RackMountKind.RESERVATION.value:
        blockers.extend(
            RackOccupantError.RESERVATION_FIELD_ON_OTHER_KIND.format(field=key.value, kind=kind)
            for key in RESERVATION_KEYS
            if payload.get(key.value) is not None
        )

    blockers.extend(date_value_blockers(payload))

    color: Any = payload.get(RackMountKey.COLOR.value)

    if color is not None and not is_hex_color(color):
        blockers.append(RackOccupantError.INVALID_COLOR.format(value=color))

    label: Any = payload.get(RackMountKey.LABEL.value)

    if label is not None and not isinstance(label, str):
        blockers.append(RackOccupantError.INVALID_LABEL.value)

    return blockers


def date_value_blockers(payload: dict[str, Any]) -> list[str]:
    """
    Judges whether the dates a request carries are usable timestamps

    A date is refused rather than dropped: a client sending '01.09.2026' and getting a reservation with
    no dates at all would have no way to notice

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        list[str]: One reason per unusable date; empty when both are fine or absent
    """
    return [
        RackOccupantError.INVALID_DATE.format(value=payload[key.value], field=key.value)
        for key in DATE_KEYS
        if payload.get(key.value) is not None and coerce_datetime(payload[key.value]) is None
    ]


def date_order_blocker(start_date: Any, end_date: Any) -> str | None:
    """
    Judges a reservation's date range once both ends are known

    Applies to the row as it would END UP, not to the request alone, so a PATCH that moves only the end
    date is judged against the start date already stored. A range with only one end is not a range and
    is always allowed - both dates are optional by decision

    Args:
        start_date (Any): The row's effective start date
        end_date (Any): The row's effective end date

    Returns:
        str | None: The reason the range is refused, or None when it is fine
    """
    start: Any = coerce_datetime(start_date)
    end: Any = coerce_datetime(end_date)

    if start is None or end is None:
        return None

    # A naive and an aware datetime cannot be compared; the stored values are UTC, so an incoming naive
    # one is read as UTC too rather than making the comparison fail
    if (start.tzinfo is None) != (end.tzinfo is None):
        start = start.replace(tzinfo=None)
        end = end.replace(tzinfo=None)

    if end < start:
        return RackOccupantError.END_BEFORE_START.value

    return None


def area_blocker(kind: str, area: Any) -> str | None:
    """
    Judges whether a kind may sit in the area it was given

    An occupant holds a U range, and only the main areas have one - the side lists are plain ordered
    lists with no geometry, so a blocker there would block nothing and a reservation would reserve
    nothing. UNASSIGNED stays allowed: that is where a rack shrink puts an occupant that no longer fits,
    and it reads as the "still needs re-placing" list

    Args:
        kind (str): The RackMountKind value of the row
        area (Any): The row's RackArea value

    Returns:
        str | None: The reason the area is refused, or None when it is fine
    """
    if not RackMountKind.is_occupant(kind):
        return None

    if area not in {member.value for member in RackArea.get_side_areas()}:
        return None

    return RackOccupantError.OCCUPANT_IN_SIDE_AREA.format(
        kind=kind,
        allowed=', '.join(sorted(member.value for member in RackArea.get_main_areas())),
    )


def kind_change_blocker(stored_kind: Any, raw_kind: Any) -> str | None:
    """
    Refuses changing what an existing row is

    A reservation is never converted into a mount in place (it may cover space for several future
    devices, so there is nothing to convert), and a mount is not turned into a blocker. Naming the same
    kind again is not a change and is allowed, so a client that echoes the whole row back can PATCH it

    Args:
        stored_kind (Any): The kind the row currently has
        raw_kind (Any): The kind the request names, if any

    Returns:
        str | None: The reason the change is refused, or None when nothing changes
    """
    if raw_kind is None or raw_kind == stored_kind:
        return None

    return RackOccupantError.KIND_IS_IMMUTABLE.value


def shape_blockers(kind: str, payload: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """
    Every shape reason a row would be refused, in one call

    The aggregate the routes use: the per-field rules judge what the REQUEST carries, while the date
    order and the area judge what the row would BECOME - which is the same thing on a create and
    deliberately different on a PATCH

    Args:
        kind (str): The RackMountKind value of the row
        payload (dict[str, Any]): The request body
        candidate (dict[str, Any]): The row as it would be persisted

    Returns:
        list[str]: The reasons the row is refused; empty when its shape is valid
    """
    blockers: list[str] = field_blockers(kind, payload)

    order_blocker: str | None = date_order_blocker(
        candidate.get(RackMountKey.START_DATE.value), candidate.get(RackMountKey.END_DATE.value),
    )

    if order_blocker:
        blockers.append(order_blocker)

    area_reason: str | None = area_blocker(kind, candidate.get(RackMountKey.AREA.value))

    if area_reason:
        blockers.append(area_reason)

    return blockers
