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
Generating port names from a token syntax, and refusing the ones that would not work

A customer creating 48 ports does not type 48 names: they give a pattern such as ``Gi0/{n}`` or
``{prefix}-{slot}/{n:02}`` and a count, and this module turns that into the list. Every rule the
concept states about it lives here:

  - the four tokens ``{prefix}``, ``{slot}``, ``{n}`` and ``{n:02}`` - the last being ``{n}`` with a
    zero-padded width
  - a start index, so a second batch can continue where the first stopped
  - **two syntaxes for a patch panel**, front and rear, generated independently
  - collisions detected **within the batch** and **against the ports that already exist**

**Nothing here writes.** The preview route and the bulk creation of step 12 run the same functions, so
what a customer is shown cannot differ from what they get - the usual failure of a preview being a
second implementation.

An unknown token is REFUSED rather than left in place or dropped. Leaving ``{slt}`` in the output would
create 48 ports whose names all contain a literal brace; dropping it would silently produce 48
duplicates. Both are worse than telling the customer they made a typo
"""
from logging import Logger, getLogger
from typing import Any

import re

from cmdb.framework.port.name_syntax_constants import (
    MAX_PAD_WIDTH,
    PortNameSyntaxError,
    SyntaxToken,
    TOKEN_PATTERN,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    reading a syntax                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def find_tokens(syntax: str) -> list[str]:
    """
    Returns every ``{...}`` token a syntax contains, in the order they appear

    Args:
        syntax (str): The name syntax

    Returns:
        list[str]: The raw token bodies, without their braces
    """
    return TOKEN_PATTERN.findall(syntax)


def parse_pad_width(token: str) -> int | None:
    """
    Reads the zero-pad width out of a numbering token

    ``n`` is the bare counter and pads to nothing; ``n:02`` pads to two digits. The width is what makes
    a switch's ports sort as 01, 02 ... 10 rather than 1, 10, 11 ... 2, which is the whole reason the
    concept has the form at all

    Args:
        token (str): The token body, without braces

    Returns:
        int | None: The pad width, 0 for an unpadded counter, or None when the token is not a
            numbering token at all
    """
    if token == SyntaxToken.NUMBER:
        return 0

    prefix: str = f'{SyntaxToken.NUMBER.value}:'

    if not token.startswith(prefix):
        return None

    width: str = token[len(prefix):]

    if not width.isdigit():
        return None

    return int(width)


def is_known_token(token: str) -> bool:
    """
    Reports whether a token is one this module can render

    Args:
        token (str): The token body, without braces

    Returns:
        bool: True for {prefix}, {slot}, {n} and any {n:<digits>}
    """
    if token in (SyntaxToken.PREFIX, SyntaxToken.SLOT):
        return True

    return parse_pad_width(token) is not None


def syntax_blockers(syntax: Any, count: Any, start_index: Any) -> list[str]:
    """
    Every reason a syntax and its numbering would be refused, reported at once

    A caller fixes one form rather than discovering the rules one submission at a time - which matters
    more here than anywhere else in the feature, because this is the form a customer fills in before
    creating 48 ports

    Args:
        syntax (Any): The name syntax
        count (Any): How many names to generate
        start_index (Any): The value {n} takes for the first name

    Returns:
        list[str]: The reasons the request is refused; empty when it is usable
    """
    blockers: list[str] = []

    if not isinstance(syntax, str) or not syntax.strip():
        blockers.append(PortNameSyntaxError.EMPTY_SYNTAX.value)
    else:
        blockers.extend(
            PortNameSyntaxError.UNKNOWN_TOKEN.format(
                token=token,
                allowed=', '.join(f'{{{member.value}}}' for member in SyntaxToken),
            )
            for token in find_tokens(syntax) if not is_known_token(token)
        )
        blockers.extend(
            PortNameSyntaxError.PAD_WIDTH_TOO_LARGE.format(token=token, maximum=MAX_PAD_WIDTH)
            for token in find_tokens(syntax)
            if (parse_pad_width(token) or 0) > MAX_PAD_WIDTH
        )

    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        blockers.append(PortNameSyntaxError.INVALID_COUNT.format(value=count))

    if not isinstance(start_index, int) or isinstance(start_index, bool) or start_index < 0:
        blockers.append(PortNameSyntaxError.INVALID_START_INDEX.format(value=start_index))

    return blockers

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  generating the names                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def render_name(syntax: str, number: int, prefix: str = '', slot: str = '') -> str:
    """
    Renders one name from a syntax

    Every token is replaced, so nothing brace-shaped survives into a stored port name. A syntax with no
    numbering token renders the same string every time - which is legal here and caught by the
    duplicate check rather than by a rule of its own, because one such name is perfectly valid and only
    a batch of them is not

    Args:
        syntax (str): The name syntax
        number (int): The value {n} takes for this name
        prefix (str): The value {prefix} takes. Defaults to empty
        slot (str): The value {slot} takes. Defaults to empty

    Returns:
        str: The rendered name
    """
    def _replace(match: re.Match) -> str:
        token: str = match.group(1)

        if token == SyntaxToken.PREFIX:
            return prefix

        if token == SyntaxToken.SLOT:
            return slot

        width: int | None = parse_pad_width(token)

        if width is not None:
            return str(number).zfill(width)

        # Unreachable through the routes, which refuse an unknown token before rendering. Left as the
        # raw token rather than as an empty string so a caller that skipped the validation gets output
        # it can recognise instead of a silent duplicate
        return match.group(0)

    return TOKEN_PATTERN.sub(_replace, syntax)


def generate_names(
        syntax: str,
        count: int,
        start_index: int = 1,
        prefix: str = '',
        slot: str = '') -> list[str]:
    """
    Renders a whole batch of names

    The numbering runs from ``start_index``, so a second batch continues where the first stopped rather
    than colliding with it

    Args:
        syntax (str): The name syntax
        count (int): How many names to generate
        start_index (int): The value {n} takes for the first name. Defaults to 1
        prefix (str): The value {prefix} takes. Defaults to empty
        slot (str): The value {slot} takes. Defaults to empty

    Returns:
        list[str]: The generated names, in order
    """
    return [
        render_name(syntax, start_index + offset, prefix, slot)
        for offset in range(count)
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    collisions                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def duplicate_names(names: list[str]) -> list[str]:
    """
    Returns the names a batch produces more than once, in the order they first repeat

    A syntax with no numbering token, or one whose padding truncates nothing, generates the same name
    for every port. The unique index would refuse the second one mid-batch and leave a half-created
    device behind, so this is caught before anything is written

    Args:
        names (list[str]): The generated names

    Returns:
        list[str]: The duplicated names, each reported once
    """
    seen: set[str] = set()
    duplicated: list[str] = []

    for name in names:
        if name in seen and name not in duplicated:
            duplicated.append(name)

        seen.add(name)

    return duplicated


def colliding_names(names: list[str], existing_names: set[str]) -> list[str]:
    """
    Returns the generated names an existing port already carries

    The other half of the collision check. Creating them would be refused by the unique
    (object_id, side, name) index one at a time, so a customer adding a second batch to a switch has to
    learn which names clash BEFORE half the batch is written

    Args:
        names (list[str]): The generated names
        existing_names (set[str]): The names already taken on the face being created into

    Returns:
        list[str]: The colliding names, in the order they were generated, each reported once
    """
    reported: list[str] = []

    for name in names:
        if name in existing_names and name not in reported:
            reported.append(name)

    return reported
