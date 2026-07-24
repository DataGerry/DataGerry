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
Implementation of ImportFailedMessage
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ImportFailedMessage:
    """
    Report entry for a single rejected/failed imported object

    Serializes (via ``__dict__``) to ``{failed_object, errors}``: the object exactly as the user
    provided it, plus every reason it could not be imported.
    """

    def __init__(self, failed_object: dict, errors: list[str]) -> None:
        """
        Initialises the ImportFailedMessage

        Args:
            failed_object (dict): The object as provided by the user (a JSON entry, or a CSV row
                transformed to a JSON object)
            errors (list[str]): The reasons the object was rejected or failed to import
        """
        self.failed_object: dict = failed_object
        self.errors: list[str] = errors
