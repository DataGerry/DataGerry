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
This module contains the classes of all ChatGPT related errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ChatGptError(Exception):
    """
    Raised to catch all ChatGPT related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all ChatGPT related errors

        Args:
            err (str | Exception): The message, or the exception this one wraps
        """
        super().__init__(err)

# ------------------------------------------------- ChatGpt - ERRORS ------------------------------------------------- #

class ChatGptNotConfiguredError(ChatGptError):
    """
    Error if no usable ChatGPT API key is configured for the current mode

    Carries the message the REST layer hands to the client, so the "how do I fix this" text is
    decided where the two modes are told apart and not repeated in the route. Distinct from every
    other failure of this feature on purpose: an unconfigured integration is an installation state
    an admin resolves, not an outage and not a bug, and the route maps it to its own status
    """
