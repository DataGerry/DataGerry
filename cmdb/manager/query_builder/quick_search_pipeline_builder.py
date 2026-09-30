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
term is matched by the same `build_text_term_stages` - the object's own values, or those of a readable
object it references - rather than by a copy of the rule
"""
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

from cmdb.manager.query_builder.pipeline_builder import PipelineBuilder

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
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
    A specialized pipeline builder for quick search queries

    This class constructs a MongoDB aggregation pipeline based on a search term,
    user permissions, and an active flag filter

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
        Builds an aggregation pipeline based on the given search term and optional filters

        Args:
            search_term (str): The term to search for
            user (CmdbUser | None): The user executing the search, used for access control
            permission (AccessControlPermission | None): The required permission level
            active_flag (bool, optional): If True, filters results to only active items. Defaults to False

        Returns:
            list[dict[str, Any]]: The constructed aggregation pipeline
        """
        # Imported lazily to avoid a circular import at module load (see the TYPE_CHECKING note above)
        # pylint: disable=import-outside-toplevel
        from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)

        value_condition: dict[str, Any] = self.regex_('fields.value', f'{search_term}', 'ims')

        # Resolved once: the term's referenced objects are restricted by it as well as the hits
        acl_stages: list[dict[str, Any]] = build_acl_pipeline(user, permission) if user and permission else []

        self.pipeline = [*acl_stages]

        if active_flag:
            self.add_pipe(self.match_({CmdbObjectKey.ACTIVE.value: {'$eq': True}}))

        self.pipeline = [*self.pipeline, *build_text_term_stages(objects_manager, value_condition, acl_stages)]

        # Aggregation pipeline for counting and categorizing results
        self.add_pipe(self.group_({'active': '$active'}, {'count': {'$sum': 1}}))
        self.add_pipe(self.group_(0, {
            'levels': {'$push': {'_id': '$_id.active', 'count': '$count'}},
            'total': {'$sum': '$count'},
        }))
        self.add_pipe(self.unwind_('$levels'))
        self.add_pipe(self.sort_('levels._id', -1))
        self.add_pipe(self.group_(0, {'levels': {'$push': {'count': "$levels.count"}}, "total": {'$avg': '$total'}}))
        self.add_pipe(self.project_({
            'total': "$total",
            'active': {'$arrayElemAt': ["$levels", 0]},
            'inactive': {'$arrayElemAt': ["$levels", 1]}
        }))
        self.add_pipe(self.project_({
            '_id': 0,
            'active': {'$cond': [{'$ifNull': ["$active", False]}, '$active.count', 0]},
            'inactive': {'$cond': [{'$ifNull': ['$inactive', False]}, '$inactive.count', 0]},
            'total': '$total'
        }))

        return self.pipeline
