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
This module contains the classes of all ISMS report errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsReportError(Exception):
    """
    Raised to catch all ISMS report related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all ISMS report related errors

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# ---------------------------------------------- ISMS REPORT - ERRORS ------------------------------------------------ #

class RiskMatrixReportError(IsmsReportError):
    """
    Raised when the risk-matrix report could not be built

    The route answers 400: every read behind the report belongs to the ISMS configuration, so a
    failure here is about the stored data rather than about the request - and the caller learns that
    the report failed instead of receiving three empty matrices that look like an answer
    """
