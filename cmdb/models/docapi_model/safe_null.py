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
Implementation of SafeNull

`SafeNull` is the null-object `SafeDict` yields for missing values during template rendering. It
absorbs any access — indexing, attribute lookup, `.get(...)`, `.type(...)` and calls — by
returning itself, so a chain like ``data.missing.also_missing[0].whatever()`` never raises inside
a template. When finally stringified it renders as a non-breaking space (a blank cell) rather than
the literal text "None".
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   SafeNull - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeNull:
    """
    Null-object that absorbs any access and renders as blank

    Any attribute access, indexing or call on a `SafeNull` returns the same `SafeNull`, so nested
    lookups in a template degrade gracefully instead of raising. Stringification yields a
    non-breaking space (``U+00A0`` / ``&nbsp;``) and the instance is falsy.
    """

    def type(self, *args: Any, **kwargs: Any) -> 'SafeNull':  # pylint: disable=unused-argument
        """
        Absorbs a ``.type(...)`` call (e.g. a template field literally named ``type``)

        Returns:
            SafeNull: This same instance
        """
        return self


    def get(self, *args: Any, **kwargs: Any) -> 'SafeNull':  # pylint: disable=unused-argument
        """
        Absorbs a ``.get(...)`` call, ignoring the requested key and default

        Returns:
            SafeNull: This same instance
        """
        return self


    def __getitem__(self, key: Any) -> 'SafeNull':
        return self


    def __getattr__(self, name: str) -> 'SafeNull':
        # Dunder probes (e.g. copy/pickle looking up __deepcopy__ / __getstate__ via getattr)
        # must fail normally with AttributeError so those protocols fall back to their default
        # machinery; absorbing them into a (callable) SafeNull would silently corrupt copies.
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)

        return self


    def __call__(self, *args: Any, **kwargs: Any) -> 'SafeNull':  # pylint: disable=unused-argument
        # Absorbs a call so a missing method invocation in a template (e.g. value.foo()) returns
        # a SafeNull instead of raising TypeError.
        return self


    def __str__(self) -> str:
        return "\u00A0"


    def __repr__(self) -> str:
        return "\u00A0"


    def __bool__(self) -> bool:
        return False


    def __html__(self) -> str:
        return "&nbsp;"
