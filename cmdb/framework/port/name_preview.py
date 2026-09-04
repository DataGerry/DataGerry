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
What a batch of ports WOULD be called, per face, with every collision already found

The preview a customer sees before creating 48 ports, and - by construction - the same computation
step 12 uses to create them. A preview that is a second implementation is a preview that eventually
lies; sharing the function is what stops that.

A standard device has one face. A **patch panel has two**, named by two independent syntaxes, and the
preview additionally states which front name will be paired with which rear name. That pairing is
positional: the first front port pairs with the first rear port. It is shown only so a customer can
check it - **the stored pairing is the INTERNAL connection step 12 creates, never the names**, which
the concept forbids deriving it from.

Pure: the existing port names are handed in by the caller, which does the reading
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.port_model import PortSide

from cmdb.framework.port.name_syntax import colliding_names, duplicate_names, generate_names
from cmdb.framework.port.name_syntax_constants import PortCollisionKey, PortPreviewKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def build_face(
        side: str,
        syntax: str,
        count: int,
        existing_names: set[str],
        start_index: int = 1,
        prefix: str = '',
        slot: str = '') -> dict[str, Any]:
    """
    Builds the preview of one face: its names and everything that would stop them being written

    Both kinds of collision are reported together - names the batch repeats among themselves, and names
    an existing port already holds - because a customer fixing a syntax wants to see all of it at once
    rather than one refusal per attempt

    Args:
        side (str): The PortSide value the face's ports will carry
        syntax (str): The name syntax for this face
        count (int): How many ports the face gets
        existing_names (set[str]): The names already taken on this face of the target CmdbObject
        start_index (int): The value {n} takes for the first name. Defaults to 1
        prefix (str): The value {prefix} takes. Defaults to empty
        slot (str): The value {slot} takes. Defaults to empty

    Returns:
        dict[str, Any]: The face's side, its generated names, and its collisions
    """
    names: list[str] = generate_names(syntax, count, start_index, prefix, slot)

    return {
        PortPreviewKey.SIDE.value: side,
        PortPreviewKey.NAMES.value: names,
        PortPreviewKey.COLLISIONS.value: {
            PortCollisionKey.DUPLICATES.value: duplicate_names(names),
            PortCollisionKey.EXISTING.value: colliding_names(names, existing_names),
        },
    }


def build_standard_preview(
        syntax: str,
        count: int,
        existing_names: set[str],
        start_index: int = 1,
        prefix: str = '',
        slot: str = '') -> dict[str, Any]:
    """
    Builds the preview of a standard network device: one face of plain ports

    Args:
        syntax (str): The name syntax
        count (int): How many ports to create
        existing_names (set[str]): The names already taken on the object's SINGLE face
        start_index (int): The value {n} takes for the first name. Defaults to 1
        prefix (str): The value {prefix} takes. Defaults to empty
        slot (str): The value {slot} takes. Defaults to empty

    Returns:
        dict[str, Any]: One face and the total port count
    """
    face: dict[str, Any] = build_face(
        PortSide.SINGLE.value, syntax, count, existing_names, start_index, prefix, slot,
    )

    return {
        PortPreviewKey.FACES.value: [face],
        PortPreviewKey.TOTAL.value: len(face[PortPreviewKey.NAMES.value]),
    }


#pylint: disable=R0913, R0917
def build_panel_preview(
        front_syntax: str,
        rear_syntax: str,
        count: int,
        existing_front_names: set[str],
        existing_rear_names: set[str],
        start_index: int = 1,
        prefix: str = '',
        slot: str = '') -> dict[str, Any]:
    """
    Builds the preview of a patch panel: two faces of equal size, plus the pairing

    ONE count for both faces, which is how the concept's "equal numbers, every element paired" rule is
    made unbreakable - there is no way to ask for 24 front and 18 rear, so the validator never has to
    refuse it.

    The two faces are checked for collisions SEPARATELY, because a port name is unique within a face:
    a panel's front 1 and rear 1 are two different ports and must not be reported as a clash

    Args:
        front_syntax (str): The name syntax for the front face
        rear_syntax (str): The name syntax for the rear face
        count (int): How many pairs the panel has - the port count of EACH face
        existing_front_names (set[str]): The names already taken on the front face
        existing_rear_names (set[str]): The names already taken on the rear face
        start_index (int): The value {n} takes for the first name of both faces. Defaults to 1
        prefix (str): The value {prefix} takes. Defaults to empty
        slot (str): The value {slot} takes. Defaults to empty

    Returns:
        dict[str, Any]: Both faces, the positional pairing, and the total port count
    """
    front: dict[str, Any] = build_face(
        PortSide.FRONT.value, front_syntax, count, existing_front_names, start_index, prefix, slot,
    )
    rear: dict[str, Any] = build_face(
        PortSide.REAR.value, rear_syntax, count, existing_rear_names, start_index, prefix, slot,
    )

    return {
        PortPreviewKey.FACES.value: [front, rear],
        # Shown so the customer can check the pairing before anything is written. The STORED pairing is
        # the INTERNAL connection step 12 creates - never these names
        PortPreviewKey.PAIRS.value: [
            {PortPreviewKey.FRONT.value: front_name, PortPreviewKey.REAR.value: rear_name}
            for front_name, rear_name in zip(
                front[PortPreviewKey.NAMES.value], rear[PortPreviewKey.NAMES.value], strict=True,
            )
        ],
        PortPreviewKey.TOTAL.value: (
            len(front[PortPreviewKey.NAMES.value]) + len(rear[PortPreviewKey.NAMES.value])
        ),
    }


def preview_has_collisions(preview: dict[str, Any]) -> bool:
    """
    Reports whether a preview found anything that would stop the batch being created

    The single question the creation route asks before writing, so it cannot disagree with what the
    preview showed

    Args:
        preview (dict[str, Any]): A preview built by one of the builders above

    Returns:
        bool: True when any face has a duplicate or an existing-name collision
    """
    return any(
        face[PortPreviewKey.COLLISIONS.value][PortCollisionKey.DUPLICATES.value]
        or face[PortPreviewKey.COLLISIONS.value][PortCollisionKey.EXISTING.value]
        for face in preview.get(PortPreviewKey.FACES.value, [])
    )
