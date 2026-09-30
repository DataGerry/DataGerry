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

**The rule for callers.** Every aggregation stage in live code is built with its constructor here -
`Builder.match_(...)`, never `{'$match': ...}` - so a stage's shape is written down once. Two things are
deliberately outside the rule:

* the database updaters (`cmdb/database/updater/versions/`): shipped migrations are history, and editing
  one only adds risk to a module that must stay safe to re-run
* query operators (`$in`, `$and`, `$exists`, ...): mostly nested expressions no constructor fits. The
  operator constructors here are used where they fit, and `regex_` always, because it carries the
  options default

`tests/unit/test_builder_stage_tripwire.py` enforces the stage rule: a hand-written stage in a pipeline
position fails it.

Only constructors with real callers live here. Adding one back is a two-line change, so the file
stays a description of what DataGerry actually queries rather than a mirror of the MongoDB manual
"""
from abc import ABC, abstractmethod
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# Why a `$sort` stage could not be built
SORT_ORDER_INVALID_MSG: str = 'Order value must be 1 (ascending) or -1 (descending)'
SORT_ORDER_MISSING_MSG: str = 'A single sort field needs its order (1 or -1)'
SORT_ORDER_DUPLICATED_MSG: str = 'A sort specification carries its own orders; pass no separate order'
SORT_SPECIFICATION_EMPTY_MSG: str = 'A sort specification needs at least one field'

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
    def and_(expressions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Joins query clauses with a logical AND

        Args:
            expressions (list[dict[str, Any]]): The clauses that must all match

        Returns:
            dict[str, Any]: An `$and` expression
        """
        return {'$and': expressions}


    @staticmethod
    def or_(expressions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Joins query clauses with a logical OR

        Args:
            expressions (list[dict[str, Any]]): The clauses of which at least one must match

        Returns:
            dict[str, Any]: An `$or` expression
        """
        return {'$or': expressions}

# ---------------------------------------------------- COMPARISON ---------------------------------------------------- #

    @staticmethod
    def in_(field: str, values: list[Any]) -> dict[str, Any]:
        """
        Matches any of the values specified in an array

        Args:
            field (str): The document field to test
            values (list[Any]): The accepted values

        Returns:
            dict[str, Any]: An `$in` expression
        """
        return {field: {'$in': values}}

# ---------------------------------------------------- EVALUATION ---------------------------------------------------- #

    @staticmethod
    def regex_(field: str, regex: str, options: str = 'ims') -> dict[str, Any]:
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
            dict[str, Any]: A `$regex` expression carrying its `$options`
        """
        return {field: {'$regex': regex, '$options': options}}

# --------------------------------------------------- AGGREGATIONS --------------------------------------------------- #

    @staticmethod
    def match_(query: dict[str, Any]) -> dict[str, Any]:
        """
        Filters the document stream to the documents matching the query

        Args:
            query (dict[str, Any]): The filter the documents must satisfy

        Returns:
            dict[str, Any]: A `$match` stage
        """
        return {'$match': query}


    @staticmethod
    def count_(name: str) -> dict[str, Any]:
        """
        Counts the documents reaching this stage of the pipeline

        Args:
            name (str): Name of the output field holding the count

        Returns:
            dict[str, Any]: A `$count` stage
        """
        return {'$count': name}


    @staticmethod
    def skip_(value: int) -> dict[str, Any]:
        """
        Skips the given number of documents

        Args:
            value (int): How many documents to pass over

        Returns:
            dict[str, Any]: A `$skip` stage
        """
        return {'$skip': value}


    @staticmethod
    def limit_(value: int) -> dict[str, Any]:
        """
        Limits how many documents pass to the next stage

        Args:
            value (int): Maximum number of documents to forward

        Returns:
            dict[str, Any]: A `$limit` stage
        """
        return {'$limit': value}


    @staticmethod
    def facet_(stages: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """
        Runs several sub-pipelines over the same input documents

        Args:
            stages (dict[str, list[dict[str, Any]]]): Mapping of output field name to its sub-pipeline

        Returns:
            dict[str, Any]: A `$facet` stage
        """
        return {'$facet': stages}


    @staticmethod
    def group_(_id: Any, value: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Groups documents by an expression, optionally accumulating further fields

        Args:
            _id (Any): The grouping expression; None groups every document into one bucket
            value (dict[str, Any] | None): Additional accumulator fields to emit per group

        Returns:
            dict[str, Any]: A `$group` stage
        """
        return {'$group': {'_id': _id, **(value or {})}}


    @staticmethod
    def lookup_(from_collection: str,
                local_field: str,
                foreign_field: str,
                as_field: str,
                pipeline: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """
        Performs a left outer join to another collection in the same database

        With a `pipeline`, the joined documents run through it after the equality match - the way to
        cap or trim what each join loads while keeping the index-backed `localField` / `foreignField`
        match. Without one, the stage carries no `pipeline` key at all

        Args:
            from_collection (str): The collection to join with
            local_field (str): The field on the documents entering the stage
            foreign_field (str): The field on the joined collection to match against
            as_field (str): Name of the new array field the matches are added under
            pipeline (list[dict[str, Any]] | None): Stages run on the matched documents, or None for
                a plain equality join

        Returns:
            dict[str, Any]: A `$lookup` stage
        """
        stage: dict[str, Any] = {
            'from': from_collection,
            'localField': local_field,
            'foreignField': foreign_field,
            'as': as_field,
        }

        if pipeline is not None:
            stage['pipeline'] = pipeline

        return {'$lookup': stage}


    @staticmethod
    def correlated_lookup_(
        from_collection: str,
        let: dict[str, Any],
        pipeline: list[dict[str, Any]],
        as_field: str,
    ) -> dict[str, Any]:
        """
        Joins another collection through a sub-pipeline that can read the incoming document

        The pipeline form of `$lookup`: `let` binds values of the incoming document to variables
        (`$$name` inside the sub-pipeline), and the sub-pipeline decides what matches. Use it when a
        plain `localField` / `foreignField` equality is not the join - when only some of the local
        values take part, or the joined documents must also pass a filter of their own

        Args:
            from_collection (str): The collection to join with
            let (dict[str, Any]): Variable name -> expression over the incoming document
            pipeline (list[dict[str, Any]]): The stages run against the joined collection
            as_field (str): Name of the new array field the joined documents are added under

        Returns:
            dict[str, Any]: A `$lookup` stage
        """
        return {
            '$lookup': {
                'from': from_collection,
                'let': let,
                'pipeline': pipeline,
                'as': as_field,
            }
        }


    @staticmethod
    def unset_(fields: list[str]) -> dict[str, Any]:
        """
        Removes fields from the documents passing through, keeping everything else

        The opposite of an inclusion `$project`: what it names is removed, and a field nobody named is
        never dropped by accident

        Args:
            fields (list[str]): The field paths to remove

        Returns:
            dict[str, Any]: An `$unset` stage
        """
        return {'$unset': list(fields)}


    @staticmethod
    def graph_lookup_(
        from_collection: str,
        start_with: str,
        connect_from_field: str,
        connect_to_field: str,
        as_field: str,
    ) -> dict[str, Any]:
        """
        Recursively follows a parent/child edge and collects every reachable document

        The recursion starts from the `start_with` expression of each incoming document and keeps
        joining `connect_from_field` -> `connect_to_field` until no further match is found. Cycles
        are detected by MongoDB itself, so a malformed edge chain terminates instead of recursing
        forever

        Args:
            from_collection (str): The collection to search recursively
            start_with (str): Expression the recursion starts from (e.g. `'$parent'`)
            connect_from_field (str): Field of a visited document whose value is followed further
            connect_to_field (str): Field the followed value is matched against
            as_field (str): Name of the new array field the reachable documents are added under

        Returns:
            dict[str, Any]: A `$graphLookup` stage
        """
        return {
            '$graphLookup': {
                'from': from_collection,
                'startWith': start_with,
                'connectFromField': connect_from_field,
                'connectToField': connect_to_field,
                'as': as_field,
            }
        }


    @staticmethod
    def unwind_(path: str | dict[str, Any]) -> dict[str, Any]:
        """
        Outputs one document per element of an array field

        Args:
            path (str | dict[str, Any]): The array field path (`'$items'`), or the full option document when
                extra behaviour such as `preserveNullAndEmptyArrays` is needed

        Returns:
            dict[str, Any]: An `$unwind` stage
        """
        return {'$unwind': path}


    @staticmethod
    def project_(specification: dict[str, Any]) -> dict[str, Any]:
        """
        Passes the documents on with only the requested fields

        Args:
            specification (dict[str, Any]): The field inclusion / exclusion specification

        Returns:
            dict[str, Any]: A `$project` stage
        """
        return {'$project': specification}


    @staticmethod
    def sort_(sort: str | dict[str, int], order: int | None = None) -> dict[str, Any]:
        """
        Sorts the documents by one field, or by several in the given order

        One field is `sort_('name', 1)`. Several are an ordered specification,
        `sort_({'value': -1, 'public_id': 1})`: the first key sorts, each later one breaks the ties left
        by the keys before it, so the dict's order is the sort's order

        Args:
            sort (str | dict[str, int]): The field to sort on, or the ordered field -> order specification
            order (int | None): 1 for ascending, -1 for descending, for a single field. Must be None
                with a specification, which carries its orders itself

        Raises:
            ValueError: If an order is neither 1 nor -1, a single field comes without its order, a
                specification comes with a separate one, or the specification is empty

        Returns:
            dict[str, Any]: A `$sort` stage
        """
        if isinstance(sort, str):
            if order is None:
                raise ValueError(SORT_ORDER_MISSING_MSG)
            specification: dict[str, int] = {sort: order}
        else:
            if order is not None:
                raise ValueError(SORT_ORDER_DUPLICATED_MSG)
            specification = dict(sort)

        if not specification:
            raise ValueError(SORT_SPECIFICATION_EMPTY_MSG)

        if any(value not in (1, -1) for value in specification.values()):
            raise ValueError(SORT_ORDER_INVALID_MSG)

        return {'$sort': specification}


    @staticmethod
    def add_fields_(fields: dict[str, Any]) -> dict[str, Any]:
        """
        Adds computed fields to the documents passing through, keeping every existing one

        Args:
            fields (dict[str, Any]): New field name -> expression

        Returns:
            dict[str, Any]: An `$addFields` stage
        """
        return {'$addFields': fields}


    @staticmethod
    def set_(fields: dict[str, Any]) -> dict[str, Any]:
        """
        Sets fields on the documents passing through - the `$set` stage, MongoDB's alias of `$addFields`

        Kept as its own constructor rather than folded into `add_fields_`: a pipeline-style update
        (`update_many(filter, [ ... ])`) reads more naturally with `$set`, and the stage a caller wrote is
        the stage it gets

        Args:
            fields (dict[str, Any]): Field name -> expression

        Returns:
            dict[str, Any]: A `$set` stage
        """
        return {'$set': fields}


    @staticmethod
    def replace_root_(new_root: Any) -> dict[str, Any]:
        """
        Replaces each document with the embedded document an expression names

        Args:
            new_root (Any): The expression of the new document (e.g. `'$type_objects'`)

        Returns:
            dict[str, Any]: A `$replaceRoot` stage
        """
        return {'$replaceRoot': {'newRoot': new_root}}
