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
Implementation of SafeDict

`SafeDict` is a ``dict`` subclass used to wrap template data for rendering. Any missing key or
attribute, and any ``None`` value, resolves to a `SafeNull` instead of raising `KeyError` /
`AttributeError`, so a template referencing an absent field degrades to a blank cell rather than
crashing the render. Nested dicts are re-wrapped as `SafeDict` and list elements are wrapped on
access, so the "safe" behaviour follows nested lookups.

Intentional behaviours (relied on by the render path, not bugs):
- ``get(key)`` / ``get(key, None)`` returns a `SafeNull`, not ``None`` — a missing value must
  still render as blank and absorb further access.
- list values are returned as plain lists, so out-of-range indexing is NOT absorbed (only missing
  keys/attributes and ``None`` are); tuples/sets are passed through unwrapped.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   SafeDict - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeDict(dict):
    """
    ``dict`` subclass whose missing keys/attributes and ``None`` values resolve to `SafeNull`
    """

    def __getitem__(self, key: Any) -> Any:
        """
        Returns the wrapped value for `key`, or a `SafeNull` when the key is absent

        Args:
            key (Any): The key to look up

        Returns:
            Any: The wrapped value, or a `SafeNull` if the key is missing
        """
        if key in self:
            return self._wrap(super().__getitem__(key))

        return SafeNull()


    def get(self, key: Any, default: Any = None) -> Any:
        """
        Returns the wrapped value for `key`, or the wrapped `default` when the key is absent

        A `default` of ``None`` (the implicit default) resolves to a `SafeNull`, so a missing
        lookup stays render-safe instead of returning ``None``.

        Args:
            key (Any): The key to look up
            default (Any): The value to fall back to when the key is missing (default None)

        Returns:
            Any: The wrapped value, or the wrapped default (a `SafeNull` when default is None)
        """
        if key in self:
            return self._wrap(super().__getitem__(key))

        return self._wrap(default)


    def __getattr__(self, name: str) -> Any:
        """
        Attribute-style access: returns the wrapped value for `name`, or a `SafeNull` if absent

        Dunder names raise `AttributeError` so copy/pickle protocol probes (which call
        ``getattr(obj, '__deepcopy__', None)`` and similar) are not handed a non-callable
        `SafeNull`, which would break those protocols.

        Args:
            name (str): The attribute name to look up

        Returns:
            Any: The wrapped value, or a `SafeNull` if the name is not a key

        Raises:
            AttributeError: If `name` is a dunder (``__...__``) name
        """
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)

        if name in self:
            return self._wrap(super().__getitem__(name))

        return SafeNull()


    def _wrap(self, value: Any) -> Any:
        """
        Wraps a value so that nested access stays safe

        ``None`` becomes a `SafeNull`, a plain ``dict`` becomes a `SafeDict`, and a ``list`` has
        each element wrapped; any other value is returned unchanged.

        Args:
            value (Any): The raw value to wrap

        Returns:
            Any: The wrapped value
        """
        if value is None:
            return SafeNull()

        if isinstance(value, dict) and not isinstance(value, SafeDict):
            return SafeDict(value)

        if isinstance(value, list):
            return [self._wrap(v) for v in value]

        return value
