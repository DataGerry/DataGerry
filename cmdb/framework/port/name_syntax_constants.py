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
Tokens, limits, response keys and refusal messages of the port name syntax and its preview

The preview's RESPONSE keys live here rather than in the route package because the framework builds
that document - step 12 creates ports from the same structure - and a builder naming its own keys with
bare strings is how two readers end up disagreeing about them. The preview's REQUEST keys stay in the
route layer, which is the only thing that reads a body
"""
import re

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SyntaxToken(BaseStrEnum):
    """
    The tokens a port name syntax may contain

    The concept names exactly these. NUMBER additionally accepts a zero-pad width written after a
    colon - ``{n:02}`` - which is what makes a switch's ports sort as 01, 02 ... 10 rather than
    1, 10, 11 ... 2.

      - PREFIX / SLOT - free values the caller supplies once for the whole batch
      - NUMBER        - the per-port counter, running from the batch's start index
    """
    PREFIX = 'prefix'
    SLOT = 'slot'
    NUMBER = 'n'


# Matches one ``{...}`` token and captures its body. Deliberately permissive about what is INSIDE the
# braces: an unknown token has to be recognised as a token before it can be refused by name, and a
# pattern that only matched the valid ones would let '{slt}' through as literal text
TOKEN_PATTERN: re.Pattern = re.compile(r'\{([^{}]*)\}')

# The widest zero-padding a numbering token may ask for. Not a product rule - a guard against
# '{n:99999999}' turning a 48-port batch into megabytes of zeroes
MAX_PAD_WIDTH: int = 10


class PortNameSyntaxError(BaseStrEnum):
    """
    Messages reported when a name syntax or its numbering is refused

    Members with a `{...}` placeholder are filled via `format()`. Every one is a business-rule
    rejection surfaced as an HTTP 400 by the preview and the bulk-create routes
    """
    EMPTY_SYNTAX = 'A name syntax is required - it is what the port names are generated from!'
    UNKNOWN_TOKEN = "'{{{token}}}' is not a known syntax token. Allowed: {allowed}"
    PAD_WIDTH_TOO_LARGE = "The padding of '{{{token}}}' is too wide - at most {maximum} digits!"
    INVALID_COUNT = 'The number of ports to create must be a whole number of at least 1, but was {value}!'
    INVALID_START_INDEX = 'The start index must be a whole number of at least 0, but was {value}!'
    DUPLICATE_NAMES = 'This syntax generates the same name more than once: {names}. Add {{n}} to it!'
    COLLIDING_NAMES = 'These names are already taken on the {side} side of this CmdbObject: {names}'
    UNEQUAL_PANEL_COUNTS = (
        'A patch panel needs the same number of front and rear ports, but got {front} and {rear}!'
    )


# Prefix of the aggregated 400 the preview and creation routes build from the reasons above
SYNTAX_ABORT_PREFIX: str = 'Port name syntax validation failed'


class PortDeviceKind(BaseStrEnum):
    """
    What is being created, which is the creation assistant's FIRST question

    The concept is explicit that this choice **replaces any "port side" field**: nothing asks the user
    which face a port is on, because that follows from the kind.

      - STANDARD    - n plain ports, all PortSide.SINGLE, no internal connections
      - PATCH_PANEL - equal numbers of FRONT and REAR ports, paired in step 12 by an automatically
        created INTERNAL connection. The pairing IS that connection and is never derived from the
        names
    """
    STANDARD = 'STANDARD'
    PATCH_PANEL = 'PATCH_PANEL'


class PortPreviewKey(BaseStrEnum):
    """
    Keys of a preview document

    FACES holds one entry per face - one for a standard device, two for a panel. PAIRS is present for a
    panel only and states which front name will be joined to which rear name
    """
    SIDE = 'side'
    NAMES = 'names'
    COLLISIONS = 'collisions'
    FACES = 'faces'
    PAIRS = 'pairs'
    TOTAL = 'total'
    FRONT = 'front'
    REAR = 'rear'


class PortCollisionKey(BaseStrEnum):
    """
    Keys of a face's collision report

    Two distinct problems, reported apart because the fix differs: DUPLICATES means the syntax itself
    produces one name several times (add {n}), EXISTING means the object already has ports with those
    names (change the prefix, or start the numbering higher)
    """
    DUPLICATES = 'duplicates'
    EXISTING = 'existing'
