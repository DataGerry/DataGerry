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
Implementation of SafeObject

`SafeObject` is the null-object stand-in for a *missing referenced object* during template
rendering — the fallback returned when a template resolves an object/report that does not exist
(e.g. ``{{ object(999).field }}``). It is wired in as the ``safe_fallback`` in `TemplateEngine`
and returned by `DefaultTemplateData._object_accessor`; `TemplateEngine.finalize` also renders a
`SafeObject` reaching the output as a blank cell.

Any attribute or item access on a `SafeObject` yields a `SafeNull`, and a call yields itself, so a
chain such as ``object(999).type.label`` degrades to a blank cell instead of raising. It is the
object-level twin of the value-level `SafeNull` and the dict-level `SafeDict`.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SafeObject - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeObject:
    """
    Null-object placeholder for a missing referenced object; all access resolves to `SafeNull`
    """

    def get(self, *args: Any, **kwargs: Any) -> SafeNull:  # pylint: disable=unused-argument
        """
        Absorbs a ``.get(...)`` call, ignoring the requested key and default

        Returns:
            SafeNull: A blank, access-absorbing null value
        """
        return SafeNull()


    def __getattr__(self, name: str) -> SafeNull:
        """
        Attribute access resolves to a `SafeNull`, except dunder names which raise normally

        Dunder names raise `AttributeError` so copy/pickle protocol probes (which call
        ``getattr(obj, '__deepcopy__', None)`` and similar) are not absorbed, which would break
        those protocols.

        Args:
            name (str): The attribute name being accessed

        Returns:
            SafeNull: A blank, access-absorbing null value

        Raises:
            AttributeError: If `name` is a dunder (``__...__``) name
        """
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)

        return SafeNull()


    def __getitem__(self, key: Any) -> SafeNull:
        return SafeNull()


    def __call__(self, *args: Any, **kwargs: Any) -> 'SafeObject':  # pylint: disable=unused-argument
        # Absorbs a call so invoking a missing object in a template returns a SafeObject instead
        # of raising TypeError.
        return self


    def __str__(self) -> str:
        return "\u00A0"


    def __repr__(self) -> str:
        return "\u00A0"


    def __html__(self) -> str:
        return "&nbsp;"


    def __bool__(self) -> bool:
        return False
