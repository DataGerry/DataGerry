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
Implementation of ResponseFailedMessage
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                             ResponseFailedMessage - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ResponseFailedMessage:
    """Message wrapper for failed objects (serialized to JSON via its ``__dict__``)"""

    def __init__(self, error_message: Any, status: int, public_id: int | None = None,
                 obj: dict | None = None) -> None:
        """
        Initialises the ResponseFailedMessage

        Args:
            error_message (Any): The failure reason (an exception or string); coerced to str so it
                serializes as readable text rather than an empty object
            status (int): The HTTP-like status code describing the failure
            public_id (int | None): The public_id that failed, if known
            obj (dict | None): The object dict that failed
        """
        self.status: int = status
        self.public_id: int | None = public_id
        self.error_message: str = str(error_message)
        self.obj = obj
