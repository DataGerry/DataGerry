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
Reading a wrapped error's cause chain

Every layer of DataGerry wraps the error it caught into its own (`raise XxxError(err) from err`), so what
a route catches is the outermost of several: a manager error around a BaseManager error around a
database error around the driver's. `find_cause` answers whether a given kind of error is anywhere in
that chain - a duplicate key, say - without the route having to know how many layers there are
"""
from typing import TypeVar
# -------------------------------------------------------------------------------------------------------------------- #

ErrorT = TypeVar('ErrorT', bound=BaseException)


def find_cause(err: BaseException, error_class: type[ErrorT]) -> ErrorT | None:
    """
    Finds the first error of a class in an error's cause chain, the error itself included

    Follows ``__cause__`` - what ``raise ... from err`` sets - from the outermost error inwards, and
    stops at the first instance of ``error_class``. A chain that loops back on itself ends there
    instead of looping forever

    Args:
        err (BaseException): The error that was caught
        error_class (type[ErrorT]): The kind of error to look for; its subclasses count

    Returns:
        ErrorT | None: The first matching error, None when the chain holds none
    """
    seen: set[int] = set()
    current: BaseException | None = err

    while current is not None and id(current) not in seen:
        if isinstance(current, error_class):
            return current

        seen.add(id(current))
        current = current.__cause__

    return None
