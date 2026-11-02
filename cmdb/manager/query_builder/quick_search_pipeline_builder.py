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
Implementation of QuickSearchPipelineBuilder

The count the search bar shows while the user types: how many objects a term finds, split into active
and inactive. It must agree with what `GET|POST /search/` then lists for the same term, which is why a
term is matched by the same rules rather than by a copy of them: the same field and flags
(`SEARCH_VALUE_FIELD`, `SEARCH_REGEX_FLAGS`), the same fallback for a term that is not a usable pattern
(`as_executable_pattern`, the TEXT form's rule) and the same `build_text_term_stages` - the object's own
values, or those of a readable object it references
"""
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

from cmdb.manager.query_builder.pipeline_builder import PipelineBuilder

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS, SEARCH_VALUE_FIELD, QuickSearchCountKey
from cmdb.framework.search.search_pattern import as_executable_pattern
from cmdb.framework.search.search_reference_match import build_text_term_stages
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.builder import build_acl_pipeline

if TYPE_CHECKING:
    # Imported for type checking only - cmdb.manager imports the query builders, so a module-level
    # import would be circular; the manager is resolved inside build()
    from cmdb.manager import ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          QuickSearchPipelineBuilder - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class QuickSearchPipelineBuilder(PipelineBuilder):
    """
    Builds the quick-search count: the objects one term finds, counted as active, inactive and in total

    The pipeline answers one document ``{active, inactive, total}`` (``QuickSearchCountKey``, integers), or
    nothing when the term finds no object - the route answers the zeroed counts then. An object counts as active
    only when its ``active`` is exactly true - the same test the active-only filter applies - so one without the
    key counts as inactive

    Extends: PipelineBuilder
    """

    def __init__(self, pipeline: list[dict[str, Any]] | None = None) -> None:
        """
        Initializes the QuickSearchPipelineBuilder instance

        Args:
            pipeline (list[dict[str, Any]] | None): A predefined aggregation pipeline.
                                          Defaults to an empty list
        """
        super().__init__(pipeline=pipeline)


    def build(
            self,
            search_term: str,
            user: CmdbUser | None = None,
            permission: AccessControlPermission | None = None,
            active_flag: bool = False) -> list[dict[str, Any]]:
        # pylint: disable=arguments-differ
        """
        Builds the count pipeline for one search term

        The stages run in this order: the caller's ACL, the active-only filter when asked for, the term (a usable
        pattern as written, any other as an escaped literal - ``as_executable_pattern``, so ``*`` is counted rather
        than refused), and one ``$group`` summing each state, projected to the three counts. Building already
        queries: ``build_text_term_stages`` reads the objects the term finds, to match the objects referencing them

        Args:
            search_term (str): The term as typed
            user (CmdbUser | None): The user executing the search, used for access control
            permission (AccessControlPermission | None): The required permission level
            active_flag (bool, optional): If True, counts active objects only. Defaults to False

        Returns:
            list[dict[str, Any]]: The aggregation pipeline, ending in the ``{active, inactive, total}`` projection
        """
        # Imported lazily to avoid a circular import at module load (see the TYPE_CHECKING note above)
        # pylint: disable=import-outside-toplevel
        from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)

        value_condition: dict[str, Any] = self.regex_(
            SEARCH_VALUE_FIELD, as_executable_pattern(search_term), SEARCH_REGEX_FLAGS,
        )

        # Resolved once: the term's referenced objects are restricted by it as well as the hits
        acl_stages: list[dict[str, Any]] = build_acl_pipeline(user, permission) if user and permission else []

        self.pipeline = [*acl_stages]

        if active_flag:
            self.add_pipe(self.match_({CmdbObjectKey.ACTIVE.value: {'$eq': True}}))

        self.pipeline = [*self.pipeline, *build_text_term_stages(objects_manager, value_condition, acl_stages)]

        # One pass counts both states: active only when exactly true, everything else inactive
        is_active: dict[str, Any] = {'$eq': [f'${CmdbObjectKey.ACTIVE.value}', True]}
        self.add_pipe(self.group_(None, {
            QuickSearchCountKey.ACTIVE.value: {'$sum': {'$cond': [is_active, 1, 0]}},
            QuickSearchCountKey.INACTIVE.value: {'$sum': {'$cond': [is_active, 0, 1]}},
            QuickSearchCountKey.TOTAL.value: {'$sum': 1},
        }))
        self.add_pipe(self.project_({
            '_id': 0,
            QuickSearchCountKey.ACTIVE.value: 1,
            QuickSearchCountKey.INACTIVE.value: 1,
            QuickSearchCountKey.TOTAL.value: 1,
        }))

        return self.pipeline
