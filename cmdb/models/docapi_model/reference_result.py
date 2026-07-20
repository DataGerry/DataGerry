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
Implementation of ReferenceResult

`ReferenceResult` wraps a resolved reference-field object (the referenced object's data) so DocAPI
templates can safely read into it and filter by type. It is created by `ObjectTemplateData` for
``"ref"`` fields. Field access — via item (`ref['x']`), attribute (`ref.x`) or `get()` — resolves
through `SafeDict` so a missing key or nested lookup degrades to a blank instead of raising, and
`type(type_id)` returns the object's data only when it matches the given type (else an empty
`SafeDict`).
"""
import json
from typing import Any
from logging import Logger, getLogger

from cmdb.models.docapi_model.safe_dict import SafeDict
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ReferenceResult - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ReferenceResult:
    """
    Wrapper for a resolved reference field to allow safe access and type filtering in templates
    """

    def __init__(self, obj_data: dict | None) -> None:
        """
        Stores the resolved referenced-object data

        Args:
            obj_data (dict | None): The resolved reference object's data (None becomes an empty dict)
        """
        self.obj_data: dict = obj_data or {}


    @staticmethod
    def _wrap(value: Any) -> Any:
        """
        Wraps a looked-up value so nested access stays render-safe

        A dict becomes a `SafeDict`, a list has each element wrapped, and a missing value (``None``)
        becomes an empty `SafeDict`; any other value is returned unchanged.

        Args:
            value (Any): The raw looked-up value

        Returns:
            Any: The render-safe value
        """
        if isinstance(value, dict):
            return SafeDict(value)

        if isinstance(value, list):
            return [ReferenceResult._wrap(item) for item in value]

        if value is None:
            return SafeDict({})

        return value


    def type(self, type_id: int) -> SafeDict:
        """
        Returns the object's data when it is of the given type, else an empty `SafeDict`

        Enables template type-filtering such as ``{{ ref.type(5).label }}``.

        Args:
            type_id (int): The type id to match against the referenced object's ``type_id``

        Returns:
            SafeDict: The object's data as a `SafeDict` if the type matches, otherwise empty
        """
        if self.obj_data.get("type_id") == type_id:
            return SafeDict(self.obj_data)

        return SafeDict({})


    def get(self, key: Any, default: Any = None) -> Any:
        """
        Returns the render-safe value for `key`, or the wrapped `default` when the key is absent

        Mirrors `__getitem__`: a missing key with no default resolves to an empty `SafeDict` (not
        ``None``), so a chained lookup stays render-safe.

        Args:
            key (Any): The field name to look up
            default (Any): The value to fall back to when the key is missing (default None)

        Returns:
            Any: The render-safe value
        """
        return self._wrap(self.obj_data.get(key, default))


    def __getitem__(self, key: Any) -> Any:
        """Returns the render-safe value for `key`, or an empty `SafeDict` when the key is absent."""
        return self._wrap(self.obj_data.get(key))


    def __getattr__(self, name: str) -> Any:
        """
        Attribute-style field access, resolving to a render-safe value

        Dunder names (and the backing ``obj_data`` attribute) raise `AttributeError` so copy/pickle
        protocol probes are not absorbed and attribute resolution does not recurse.

        Args:
            name (str): The field name to look up

        Returns:
            Any: The render-safe value

        Raises:
            AttributeError: If `name` is a dunder name or the internal ``obj_data`` attribute
        """
        if name == "obj_data" or (name.startswith("__") and name.endswith("__")):
            raise AttributeError(name)

        return self._wrap(self.obj_data.get(name))


    def __repr__(self) -> str:
        """Returns a debug representation; non-JSON-serializable values are coerced via ``str``."""
        return f"ReferenceResult(obj_data={json.dumps(self.obj_data, indent=2, default=str)})"
