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
Reading a preview request and turning the framework's refusals into HTTP ones

Deliberately the ONLY place a preview request body is interpreted, because step 12 will create ports
from the same body: the request is read here, the names are built in cmdb.framework.port.name_preview,
and the creation route will call both. Splitting the reading from the building is what lets the
creation reuse it without also reusing a Flask response
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_model import PortKey, PortSide

from cmdb.framework.port.name_preview import build_panel_preview, build_standard_preview
from cmdb.framework.port.name_syntax import syntax_blockers
from cmdb.framework.port.name_syntax_constants import (
    SYNTAX_ABORT_PREFIX,
    PortDeviceKind,
)

from cmdb.interface.rest_api.routes.port_routes.port_preview_constants import (
    PREVIEW_MISSING_REAR_SYNTAX_MESSAGE,
    PREVIEW_UNKNOWN_DEVICE_KIND_MESSAGE,
    PortPreviewRequestKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The value {n} starts at when a request names none. 1 rather than 0, because a port called '0' is not
# what anybody means by "the first port"
DEFAULT_START_INDEX: int = 1

# -------------------------------------------------------------------------------------------------------------------- #

def get_device_kind_or_abort(payload: dict[str, Any]) -> str:
    """
    Reads the device kind from a preview request, aborting 400 on a missing or unknown value

    Deliberately without a default: it is the assistant's first question, the customer always answered
    it, and guessing STANDARD for a typo would silently preview the wrong device - a panel's two faces
    would collapse into one

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the kind is absent or not a PortDeviceKind value

    Returns:
        str: The requested PortDeviceKind value
    """
    raw: Any = payload.get(PortPreviewRequestKey.DEVICE_KIND.value)

    if not isinstance(raw, str) or not PortDeviceKind.is_valid(raw):
        abort(400, PREVIEW_UNKNOWN_DEVICE_KIND_MESSAGE.format(
            device_kind=raw,
            allowed=', '.join(member.value for member in PortDeviceKind),
        ))

    return raw


def enforce_syntax_usable(syntax: Any, count: Any, start_index: Any) -> None:
    """
    Aborts 400 with every reason a syntax and its numbering would be refused, in one message

    Args:
        syntax (Any): The name syntax
        count (Any): How many ports to create
        start_index (Any): The value {n} takes for the first name

    Raises:
        HTTPException: 400 when the syntax, the count or the start index is unusable
    """
    blockers: list[str] = syntax_blockers(syntax, count, start_index)

    if blockers:
        abort(400, f'{SYNTAX_ABORT_PREFIX}: {" | ".join(blockers)}')


def existing_names_by_side(ports_manager: PortsManager, object_id: int) -> dict[str, set[str]]:
    """
    Reads the port names an object already carries, grouped by face

    ONE read for every face rather than one per face: a port name is unique within its face, so the
    grouping is what stops a panel's existing front 1 being reported as a collision for its rear 1

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject

    Returns:
        dict[str, set[str]]: The taken names keyed by PortSide value, empty sets for unused faces
    """
    taken: dict[str, set[str]] = {side.value: set() for side in PortSide}

    for port in ports_manager.get_ports_of_object(object_id):
        side: Any = port.get(PortKey.SIDE.value) or PortSide.SINGLE.value
        name: Any = port.get(PortKey.NAME.value)

        if side in taken and isinstance(name, str):
            taken[side].add(name)

    return taken


def build_preview_or_abort(
        ports_manager: PortsManager,
        object_id: int,
        payload: dict[str, Any]) -> dict[str, Any]:
    """
    Reads a preview request and builds the preview, refusing an unusable one

    The whole request interpretation in one place, so step 12's creation can call it and then create
    from exactly what the customer was shown

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject the ports would be created on
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the device kind, a syntax or the numbering is unusable

    Returns:
        dict[str, Any]: The preview document
    """
    device_kind: str = get_device_kind_or_abort(payload)

    syntax: Any = payload.get(PortPreviewRequestKey.SYNTAX.value)
    count: Any = payload.get(PortPreviewRequestKey.COUNT.value)
    start_index: Any = payload.get(PortPreviewRequestKey.START_INDEX.value, DEFAULT_START_INDEX)
    prefix: str = str(payload.get(PortPreviewRequestKey.PREFIX.value) or '')
    slot: str = str(payload.get(PortPreviewRequestKey.SLOT.value) or '')

    enforce_syntax_usable(syntax, count, start_index)

    taken: dict[str, set[str]] = existing_names_by_side(ports_manager, object_id)

    if device_kind == PortDeviceKind.STANDARD:
        return build_standard_preview(
            syntax, count, taken[PortSide.SINGLE.value], start_index, prefix, slot,
        )

    rear_syntax: Any = payload.get(PortPreviewRequestKey.REAR_SYNTAX.value)

    if not isinstance(rear_syntax, str) or not rear_syntax.strip():
        abort(400, PREVIEW_MISSING_REAR_SYNTAX_MESSAGE)

    enforce_syntax_usable(rear_syntax, count, start_index)

    return build_panel_preview(
        syntax, rear_syntax, count,
        taken[PortSide.FRONT.value], taken[PortSide.REAR.value],
        start_index, prefix, slot,
    )
