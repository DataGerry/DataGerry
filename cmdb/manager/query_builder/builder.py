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
Implementation of Builder

The shared vocabulary every query builder is assembled from: small constructors that each return one
MongoDB query operator or aggregation stage as a plain dict. They hold no state, so they are
staticmethods and can be called either on the class (`Builder.match_(...)`) or through a subclass
instance (`self.match_(...)`).

The MongoDB operator names (`'$match'`, `'$and'`, ...) are deliberately kept as bare literals here.
They are the database's own wire vocabulary, not DataGerry document keys - unlike the field and
schema keys of a stored document, which belong in their `*Key` enums (`FieldKey`, `CmdbObjectKey`,
`TypeSchemaKey`, ...) and must never be written as literals. This module is the boundary between
those two worlds: operators in, schema keys out.

Only constructors with real callers live here. Adding one back is a two-line change, so the file
stays a description of what DataGerry actually queries rather than a mirror of the MongoDB manual
"""
from abc import ABC, abstractmethod
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    Builder - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

class Builder(ABC):
    """
    Abstract base class for building query-like structures

    Defines the two operations every builder must provide - reporting its length and resetting
    itself - and supplies the stateless operator/stage constructors its subclasses share. Being an
    ABC, a subclass that forgets either abstract method fails at construction rather than at the
    call that needed it
    """

    @abstractmethod
    def __len__(self) -> int:
        """
        Returns the number of elements in the builder

        Returns:
            int: Number of query elements or pipeline stages held
        """


    @abstractmethod
    def clear(self) -> None:
        """
        Clears the builder's data, resetting it to its empty state
        """

# ------------------------------------------- LOGICAL QUERY OPERATORS ------------------------------------------------ #

    @staticmethod
    def and_(expressions: list[dict]) -> dict:
        """
        Joins query clauses with a logical AND

        Args:
            expressions (list[dict]): The clauses that must all match

        Returns:
            dict: An `$and` expression
        """
        return {'$and': expressions}


    @staticmethod
    def or_(expressions: list[dict]) -> dict:
        """
        Joins query clauses with a logical OR

        Args:
            expressions (list[dict]): The clauses of which at least one must match

        Returns:
            dict: An `$or` expression
        """
        return {'$or': expressions}

# ---------------------------------------------------- COMPARISON ---------------------------------------------------- #

    @staticmethod
    def in_(field: str, values: list[Any]) -> dict:
        """
        Matches any of the values specified in an array

        Args:
            field (str): The document field to test
            values (list[Any]): The accepted values

        Returns:
            dict: An `$in` expression
        """
        return {field: {'$in': values}}

# ---------------------------------------------------- EVALUATION ---------------------------------------------------- #

    @staticmethod
    def regex_(field: str, regex: str, options: str = 'ims') -> dict:
        """
        Matches a field against a regular expression

        The default options are case-insensitive (`i`), multi-line (`m`) and dot-matches-newline
        (`s`) - the combination a user-entered search term needs. The `x` (extended) flag is
        deliberately NOT part of the default: it makes the engine ignore unescaped whitespace in the
        pattern and treat `#` as a comment, so a search for `Data Center` would silently match
        nothing at all

        Args:
            field (str): The document field to match against
            regex (str): The regular expression, usually a raw user-entered search term
            options (str): MongoDB regex option flags. Defaults to `'ims'`

        Returns:
            dict: A `$regex` expression carrying its `$options`
        """
        return {field: {'$regex': regex, '$options': options}}

# --------------------------------------------------- AGGREGATIONS --------------------------------------------------- #

    @staticmethod
    def match_(query: dict) -> dict:
        """
        Filters the document stream to the documents matching the query

        Args:
            query (dict): The filter the documents must satisfy

        Returns:
            dict: A `$match` stage
        """
        return {'$match': query}


    @staticmethod
    def count_(name: str) -> dict:
        """
        Counts the documents reaching this stage of the pipeline

        Args:
            name (str): Name of the output field holding the count

        Returns:
            dict: A `$count` stage
        """
        return {'$count': name}


    @staticmethod
    def skip_(value: int) -> dict:
        """
        Skips the given number of documents

        Args:
            value (int): How many documents to pass over

        Returns:
            dict: A `$skip` stage
        """
        return {'$skip': value}


    @staticmethod
    def limit_(value: int) -> dict:
        """
        Limits how many documents pass to the next stage

        Args:
            value (int): Maximum number of documents to forward

        Returns:
            dict: A `$limit` stage
        """
        return {'$limit': value}


    @staticmethod
    def facet_(stages: dict) -> dict:
        """
        Runs several sub-pipelines over the same input documents

        Args:
            stages (dict): Mapping of output field name to its sub-pipeline

        Returns:
            dict: A `$facet` stage
        """
        return {'$facet': stages}


    @staticmethod
    def group_(_id: Any, value: dict | None = None) -> dict:
        """
        Groups documents by an expression, optionally accumulating further fields

        Args:
            _id (Any): The grouping expression; None groups every document into one bucket
            value (dict | None): Additional accumulator fields to emit per group

        Returns:
            dict: A `$group` stage
        """
        return {'$group': {'_id': _id, **(value or {})}}


    @staticmethod
    def lookup_(from_collection: str, local_field: str, foreign_field: str, as_field: str) -> dict:
        """
        Performs a left outer join to another collection in the same database

        Args:
            from_collection (str): The collection to join with
            local_field (str): The field on the documents entering the stage
            foreign_field (str): The field on the joined collection to match against
            as_field (str): Name of the new array field the matches are added under

        Returns:
            dict: A `$lookup` stage
        """
        return {
            '$lookup': {
                'from': from_collection,
                'localField': local_field,
                'foreignField': foreign_field,
                'as': as_field,
            }
        }


    @staticmethod
    def unwind_(path: str | dict) -> dict:
        """
        Outputs one document per element of an array field

        Args:
            path (str | dict): The array field path (`'$items'`), or the full option document when
                extra behaviour such as `preserveNullAndEmptyArrays` is needed

        Returns:
            dict: An `$unwind` stage
        """
        return {'$unwind': path}


    @staticmethod
    def project_(specification: dict) -> dict:
        """
        Passes the documents on with only the requested fields

        Args:
            specification (dict): The field inclusion / exclusion specification

        Returns:
            dict: A `$project` stage
        """
        return {'$project': specification}


    @staticmethod
    def sort_(sort: str, order: int) -> dict:
        """
        Sorts the documents by one field

        Args:
            sort (str): The field to sort on
            order (int): 1 for ascending, -1 for descending

        Raises:
            ValueError: If order is neither 1 nor -1

        Returns:
            dict: A `$sort` stage
        """
        if order not in (1, -1):
            raise ValueError('Order value must be 1 (ascending) or -1 (descending)')

        return {'$sort': {sort: order}}
