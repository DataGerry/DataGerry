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
Implementation of TypeIterationParameters

Adds the ``active`` flag and the two category filters to the collection pager. Everything about the
pager itself - the coercion, the validation and the JSON parsing - is inherited; this class only
converts its own parameters and hands the rest to ``CollectionParameters.from_data``

``acl`` names the permission the caller is asking about: ``?acl=CREATE`` answers "the types my group
may create an object of" rather than the ones it may read. It **replaces** READ rather than adding to
it, which is exact parity with the ``getAclFilter`` the Angular app posts today, and several
permissions mean **all** of them. An absent parameter means READ; an empty or unrecognised one is
refused, because an empty ``$all`` matches nothing and would silently hide every ACL-carrying type.

``category`` and ``uncategorized`` are the server-side replacement for the ``$lookup`` pipelines the
Angular app would otherwise post as ``?filter=`` to ask "types in category N" and "types in no
category". They are mutually exclusive - asking for both is a contradiction rather than an
empty result, so it is refused here, where a ValueError becomes an HTTP 400.

Note ``to_dict`` here is currently DEAD: ``GetMultiResponse`` calls ``CollectionParameters.to_dict``
explicitly, so ``active`` never reaches the response envelope. Nothing in the frontend reads it, so the
envelope is left alone; the method is kept because it is the correct serializer for this class and the
only thing missing is a caller
"""
from typing import Any, Self

from cmdb.interface.rest_api.responses.response_parameters.collection_parameters import CollectionParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import str_to_bool
# -------------------------------------------------------------------------------------------------------------------- #


class TypeIterationParameters(CollectionParameters):
    """
    Represents parameters for type iteration, extending collection parameters

    Adds an ``active`` flag to the collection pager, used to restrict a type listing to active types
    """

    def __init__(
            self,
            query_string: str,
            active: bool = True,
            category: int | None = None,
            uncategorized: bool = False,
            acl: list[AccessControlPermission] | None = None,
            **kwargs: Any) -> None:
        """
        Initialize the TypeIterationParameters

        Args:
            query_string (str): The query string for the iteration
            active (bool): Indicates whether only active types are requested. Defaults to True
            category (int | None): public_id of the CmdbCategory the types must belong to, or None
                for no category restriction. Defaults to None
            uncategorized (bool): Whether only types belonging to no CmdbCategory at all are
                requested. Defaults to False
            acl (list[AccessControlPermission] | None): Every permission the requesting user's group
                must hold on a CmdbType for it to be listed. Defaults to None, meaning READ

            **kwargs (Any): Additional keyword arguments passed to the parent class constructor

        Raises:
            ValueError: When a pager value is invalid (see CollectionParameters), or when both
                category filters are given at once
        """
        if category is not None and uncategorized:
            raise ValueError(
                f"'{ParameterKey.CATEGORY.value}' and '{ParameterKey.UNCATEGORIZED.value}' "
                "cannot be combined - a type is either in the given category or in none at all!"
            )

        self.active: bool = active
        self.category: int | None = category
        self.uncategorized: bool = uncategorized
        self.acl: list[AccessControlPermission] = acl or [AccessControlPermission.READ]
        super().__init__(query_string=query_string, **kwargs)


    @classmethod
    def from_data(cls, query_string: str, **optional: Any) -> Self:
        """
        Create a TypeIterationParameters instance from HTTP request parameters

        Converts ``active``, ``category`` and ``uncategorized`` (which all arrive as strings) and
        delegates everything else - the wire ``filter`` mapping, the JSON parsing and the pager
        validation - to the parent

        Args:
            query_string (str): The query string for the iteration
            **optional (Any): Additional optional parameters passed from the HTTP request

        Raises:
            JSONDecodeError: When ``filter`` or ``projection`` is not valid JSON
            ValueError: When a pager value is invalid (see CollectionParameters), when ``category``
                is not an integer, when ``acl`` is empty or names an unknown permission, or when both
                category filters are given at once

        Returns:
            Self: An instance of the calling class with the parsed parameters
        """
        optional[ParameterKey.ACTIVE.value] = str_to_bool(
            optional.pop(ParameterKey.ACTIVE.value, True),
        )

        optional[ParameterKey.UNCATEGORIZED.value] = str_to_bool(
            optional.pop(ParameterKey.UNCATEGORIZED.value, False),
        )

        optional[ParameterKey.CATEGORY.value] = cls._coerce_category(
            optional.pop(ParameterKey.CATEGORY.value, None),
        )

        optional[ParameterKey.ACL.value] = cls._coerce_acl(
            optional.pop(ParameterKey.ACL.value, None),
        )

        return super().from_data(query_string, **optional)


    @staticmethod
    def _coerce_acl(acl: Any) -> list[AccessControlPermission] | None:
        """
        Coerces the ``acl`` query value to the permissions a listed CmdbType must grant

        The value is **one comma-separated string**, not a repeated key: ``parse_parameters`` builds
        its arguments with ``request.args.to_dict()``, which keeps only the first value of a repeated
        key - so ``?acl=READ&acl=CREATE`` would silently narrow to READ.

        Matching is exact and case-sensitive: a stored ACL holds the permission's upper-case value, so
        ``?acl=read`` would match no group entry at all and hide every ACL-carrying type. Refusing it
        is the only answer that does not look like a working query

        Args:
            acl (Any): The raw ``acl`` value - a comma-separated string when it came from the query
                parser, or an already-parsed list from an internal caller

        Raises:
            ValueError: When the value is present but empty, or names something that is not an
                AccessControlPermission; the ``parse_parameters`` decorator turns that into an
                HTTP 400

        Returns:
            list[AccessControlPermission] | None: The permissions to require, or None for the default
        """
        if acl is None:
            return None

        empty_value_error = ValueError(
            f"'{ParameterKey.ACL.value}' must name at least one permission, "
            f"one of: {', '.join(entry.value for entry in AccessControlPermission)}!"
        )

        # An internal caller may hand the permissions over already parsed
        if isinstance(acl, list):
            if not acl:
                raise empty_value_error

            return acl

        names: list[str] = [entry.strip() for entry in str(acl).split(',')]

        if not all(names):
            raise empty_value_error

        try:
            return [AccessControlPermission(name) for name in names]
        except ValueError as err:
            raise ValueError(
                f"'{ParameterKey.ACL.value}' must only contain "
                f"{', '.join(entry.value for entry in AccessControlPermission)}!"
            ) from err


    @staticmethod
    def _coerce_category(category: Any) -> int | None:
        """
        Coerces the ``category`` query value to a CmdbCategory public_id

        An absent or empty value means "no category restriction"; the empty string is accepted
        because that is what an Angular ``HttpParams`` entry looks like when its source is cleared

        Args:
            category (Any): The raw ``category`` value, a string when it came from the query parser

        Raises:
            ValueError: When the value is present but not an integer; the ``parse_parameters``
                decorator turns that into an HTTP 400

        Returns:
            int | None: The category public_id to filter on, or None
        """
        if category is None or category == '':
            return None

        return int(category)


    @staticmethod
    def to_dict(parameters: "TypeIterationParameters") -> dict[str, Any]:
        """
        Convert TypeIterationParameters to a dictionary

        Args:
            parameters (TypeIterationParameters): The TypeIterationParameters to be converted

        Returns:
            dict[str, Any]: The collection pager plus the ``active`` flag, the category filters and
                the requested permissions
        """
        return {
            **CollectionParameters.to_dict(parameters),
            ParameterKey.ACTIVE.value: parameters.active,
            ParameterKey.CATEGORY.value: parameters.category,
            ParameterKey.UNCATEGORIZED.value: parameters.uncategorized,
            ParameterKey.ACL.value: [entry.value for entry in parameters.acl],
        }
