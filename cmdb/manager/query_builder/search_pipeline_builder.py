# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of SearchPipelineBuilder

Turns the search bar's parameters into the aggregation that answers `GET|POST /rest/search/`. The
**stage order is the contract**, because each stage narrows the stream the next one sees:

1. the reference stages (`SearchReferencesPipelineBuilder`), which make a referenced object's fields
   searchable as if they were the object's own - they must come first, since every filter below
   matches against `fields.value`;
2. `active`, when the caller asked for active objects only;
3. one `$match` per TEXT / REGEX parameter;
4. the TYPE parameters - collected into one `$or` when they are disjunctive (the default), otherwise
   one `$match` each, which is AND;
5. the CATEGORY parameters, resolved into the type ids of the matching categories;
6. the PUBLIC_ID parameters;
7. **the ACL stages last** (`build_acl_pipeline`) - they must be part of the pipeline BEFORE the
   caller appends its `$facet`, or the page and the counts would be taken from unfiltered documents.

`SearcherFramework` appends that `$facet` and runs the result; it also reads the `$regex` values back
out of the pipeline (`get_regex_pipes_values`) to highlight the matching fields of each hit.

**A TEXT parameter is matched as a regular expression, not as literal text.** The Angular search bar
escapes the term before sending it (`search-bar.component.ts`), so the UI behaves literally - but an
API client posting `searchForm: "text"` gets regex semantics: `C++` matches `CCC`, `Data (EU)` does
not match itself, and `*` fails the query. Aligning the two ends needs the frontend to stop escaping
at the same time (escaping here would double-escape what it already escaped), so it is recorded as
discussion-backlog #222 rather than changed here.
"""
from logging import Logger, getLogger
from typing import Any, TYPE_CHECKING

from cmdb.manager.query_builder.pipeline_builder import PipelineBuilder
from cmdb.manager.query_builder.search_references_pipeline_builder import SearchReferencesPipelineBuilder

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.framework.search.search_param import SearchParam
from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS, SearchFormType
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.builder import build_acl_pipeline

if TYPE_CHECKING:
    # Imported for type checking only - importing at module level would create a circular import
    # (cmdb.manager -> query_builder -> this module -> cmdb.manager), which is why this builder is
    # exported from the query_builder package while resolving its managers lazily inside build()
    from cmdb.manager import CategoriesManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The field every search parameter matches against: the flattened field values of an object, with a
# referenced object's own fields folded in by the reference stages
SEARCH_VALUE_FIELD: str = 'fields.value'

# The pipeline key holding a regex, read back out of a built pipeline to highlight the hits
REGEX_OPERATOR: str = '$regex'

# -------------------------------------------------------------------------------------------------------------------- #
#                                             SearchPipelineBuilder - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchPipelineBuilder(PipelineBuilder):
    """
    A query builder for search-specific database aggregation pipelines

    This class constructs a pipeline for performing search queries, allowing dynamic modification
    of pipeline stages

    Inherits from:
        PipelineBuilder: The base class for building aggregation query pipelines
    """

    def __init__(self, pipeline: list[dict] | None = None):
        """
        Initializes the SearchPipelineBuilder

        Args:
            pipeline (list[dict] | None): An ALREADY BUILT search pipeline to work on - what
                `SearcherFramework` hands in so it can read the search patterns back out and append
                its facet. `build()` does not extend it: it assembles a complete pipeline of its own
                (see that method). Defaults to an empty pipeline
        """
        super().__init__(pipeline=pipeline)


    def get_regex_pipes_values(self) -> list[str]:
        """
        Extracts every `$regex` value the pipeline carries, at any depth

        These are the patterns the search matched with, and the search result highlights each hit's
        fields against them - so a pattern missed here silently costs the highlighting of one search
        parameter. Walks dicts and lists all the way down, because a `$match` may nest its
        expressions under `$or` / `$and` several levels deep

        Returns:
            list[str]: The regex values, in the order the stages carry them
        """
        return [value for pipe in self.pipeline for value in _extract_values(REGEX_OPERATOR, pipe)]


    def build(self,
              params: list[SearchParam],
              user: CmdbUser | None = None,
              permission: AccessControlPermission | None = None,
              active_flag: bool = False) -> list[dict]:
        # A search pipeline is inherently branchy (text / type / category / publicID / permission stages)
        # pylint: disable=arguments-differ
        """
        Builds the search aggregation out of the search bar's parameters

        Assembles a COMPLETE pipeline in the documented stage order - any stages this builder was
        constructed with are not part of it. That is why `SearcherFramework`, which is handed a
        pipeline that is already built, never calls this method.

        Args:
            params (list[SearchParam]): The search parameters, as the search bar sent them
            user (CmdbUser | None): The user the search runs for; required for the ACL stages.
                                    Defaults to None
            permission (AccessControlPermission | None): The permission the ACL stages check.
                                    Defaults to None
            active_flag (bool): Whether to restrict the search to active objects. Defaults to False

        Returns:
            list[dict]: The aggregation stages, ACL filtering included when a user and a permission
                were given
        """
        # Imported lazily to avoid a circular import at module load (see the TYPE_CHECKING note above)
        # pylint: disable=import-outside-toplevel
        from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, user)

        # The reference stages open the pipeline: every filter below matches against fields.value,
        # which is what they fold a referenced object's own fields into
        self.pipeline = SearchReferencesPipelineBuilder().build()

        if active_flag:
            self.add_pipe(self.match_({CmdbObjectKey.ACTIVE.value: {'$eq': True}}))

        self._add_text_stages(params)
        self._add_type_stages(params)
        self._add_category_stages(params, categories_manager)
        self._add_public_id_stages(params)

        # LAST: the ACL filter has to be in the pipeline before the caller appends its facet
        if user and permission:
            self.pipeline = [*self.pipeline, *build_acl_pipeline(user, permission)]

        return self.pipeline


    def _add_text_stages(self, params: list[SearchParam]) -> None:
        """
        Adds one regex `$match` per TEXT or REGEX parameter

        The two forms are matched identically - see the module docstring for why a TEXT term is a
        regular expression here and what that means for a client that does not escape it

        Args:
            params (list[SearchParam]): The search parameters to read the text forms from
        """
        for param in _params_of(params, SearchFormType.TEXT, SearchFormType.REGEX):
            self.add_pipe(self.match_(
                self.regex_(SEARCH_VALUE_FIELD, param.search_text, SEARCH_REGEX_FLAGS)
            ))


    def _add_type_stages(self, params: list[SearchParam]) -> None:
        """
        Adds the TYPE parameters, either as one `$or` or as one `$match` each

        `disjunction` decides which, and it defaults to True: several type tags widen a search rather
        than narrowing it to nothing, which is what the search bar's payload relies on. A parameter
        carrying no type ids contributes no stage at all

        Args:
            params (list[SearchParam]): The search parameters to read the type forms from
        """
        disjunction_query: list[dict] = []

        for param in _params_of(params, SearchFormType.TYPE):
            type_ids = param.settings.get('types', []) if param.settings else []

            if not type_ids:
                continue

            type_id_in = self.in_(CmdbObjectKey.TYPE_ID.value, type_ids)

            if param.disjunction:
                disjunction_query.append(type_id_in)
            else:
                self.add_pipe(self.match_(type_id_in))

        if disjunction_query:
            self.add_pipe(self.match_(self.or_(disjunction_query)))


    def _add_category_stages(self, params: list[SearchParam], categories_manager: 'CategoriesManager') -> None:
        """
        Adds a type-id `$match` for every type of every matching category

        The categories are resolved by their LABEL, matched against the parameter's search text - the
        type ids the parameter also carries under `settings['categories']` are not used, which is
        recorded rather than changed here. All category parameters are resolved in ONE query: a
        search carrying several category tags used to cost a query per tag

        Args:
            params (list[SearchParam]): The search parameters to read the category forms from
            categories_manager (CategoriesManager): Manager used to resolve the category labels
        """
        label_patterns = [
            self.regex_('label', param.search_text, SEARCH_REGEX_FLAGS)
            for param in _params_of(params, SearchFormType.CATEGORY)
            if param.settings and param.settings.get('categories')
        ]

        if not label_patterns:
            return

        criteria = label_patterns[0] if len(label_patterns) == 1 else self.or_(label_patterns)

        for category in categories_manager.get_categories_by(**criteria):
            self.add_pipe(self.match_(self.in_(CmdbObjectKey.TYPE_ID.value, category.types)))


    def _add_public_id_stages(self, params: list[SearchParam]) -> None:
        """
        Adds a `public_id` `$match` per PUBLIC_ID parameter

        The text is read as an integer, which `SearchParam` guarantees is possible: it refuses a
        PUBLIC_ID parameter whose text is not a whole number

        Args:
            params (list[SearchParam]): The search parameters to read the public_id forms from
        """
        for param in _params_of(params, SearchFormType.PUBLIC_ID):
            self.add_pipe(self.match_({CmdbObjectKey.PUBLIC_ID.value: int(param.search_text)}))


def _params_of(params: list[SearchParam], *forms: SearchFormType) -> list[SearchParam]:
    """
    Filters the search parameters down to the given forms

    Read through `SearchFormType` rather than the form strings: `SearchParam` validates against that
    enum, so a form spelled by hand here could accept a value the parameter class rejects - or miss
    one it accepts

    Args:
        params (list[SearchParam]): Every parameter the request carried
        *forms (SearchFormType): The forms to keep

    Returns:
        list[SearchParam]: The matching parameters, in the order they were sent
    """
    wanted = {form.value for form in forms}

    return [param for param in params if param.search_form in wanted]


def _extract_values(key: str, node: Any) -> list[Any]:
    """
    Collects every value stored under the given key, at any depth of dicts and lists

    Used to read the `$regex` patterns back out of a built pipeline. Recurses through lists as well
    as dicts, and through lists nested in lists - a `$match` nests its expressions under `$or` /
    `$and`, and those are lists of dicts

    Args:
        key (str): The key to collect the values of
        node (Any): The pipeline, a stage, or any value inside one

    Returns:
        list[Any]: The collected values, in document order
    """
    if isinstance(node, dict):
        values: list[Any] = []

        for node_key, node_value in node.items():
            if node_key == key:
                values.append(node_value)

            values.extend(_extract_values(key, node_value))

        return values

    if isinstance(node, list):
        return [value for entry in node for value in _extract_values(key, entry)]

    return []
