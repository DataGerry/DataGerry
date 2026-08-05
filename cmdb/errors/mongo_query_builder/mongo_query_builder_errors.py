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
Contains MongoDBQueryBuilder Error Classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class MongoDBQueryBuilderError(Exception):
    """
    Raised to catch all MongoDBQueryBuilder related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all MongoDBQueryBuilder related errors
        """
        super().__init__(err)

# ------------------------------------------- MongoDBQueryBuilder - ERRORS ------------------------------------------- #

class MongoQueryBuilderInitError(MongoDBQueryBuilderError):
    """
    Raised if MongoDBQueryBuilder could not be initialised
    """


class MongoQueryBuilderInvalidOperatorError(MongoDBQueryBuilderError):
    """
    Raised if a condition has an unsupported operator
    """


class MongoQueryBuilderBuildRuleError(MongoDBQueryBuilderError):
    """
    Raised if a rule could not be build
    """


class MongoQueryBuilderBuildRulesetError(MongoDBQueryBuilderError):
    """
    Raised if a ruleset could not be build
    """


class MongoQueryBuilderBuildError(MongoDBQueryBuilderError):
    """
    Raised if the build fails
    """
