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
Unit tests for build_relation_tabs_pipeline

Pins the MongoDB aggregation that turns an object's relations into tab descriptors: the object filter,
the parent/child role fan-out, the (relation_id, role) grouping + count, the join to the relation
definition and the role-oriented label / icon / color projection. This locks the pipeline shape so a
later optimisation is safe.
"""
from cmdb.models.relation_model import CmdbRelation
from cmdb.manager.object_relations_manager import build_relation_tabs_pipeline
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 42


def _stage(pipeline: list[dict], op: str) -> dict:
    """Returns the body of the first stage using the given operator."""
    return next(stage[op] for stage in pipeline if op in stage)


class TestRelationTabsPipeline:
    """The pipeline matches, fans out roles, groups+counts, joins the definition and projects tabs."""

    def test_stage_order(self) -> None:
        """The pipeline runs match -> addFields -> unwind -> group -> lookup -> unwind -> project -> sort."""
        pipeline = build_relation_tabs_pipeline(OBJECT_ID)

        assert [next(iter(stage)) for stage in pipeline] == [
            '$match', '$addFields', '$unwind', '$group', '$lookup', '$unwind', '$project', '$sort'
        ]

    def test_match_targets_object_on_either_side(self) -> None:
        """The match selects relations where the object is the parent or the child."""
        match = _stage(build_relation_tabs_pipeline(OBJECT_ID), '$match')

        assert match == {'$or': [{'relation_parent_id': OBJECT_ID}, {'relation_child_id': OBJECT_ID}]}

    def test_group_keys_and_count(self) -> None:
        """Grouping is by (relation_id, role) with an instance count."""
        group = _stage(build_relation_tabs_pipeline(OBJECT_ID), '$group')

        assert group['_id'] == {'relation_id': '$relation_id', 'role': '$roles'}
        assert group['count'] == {'$sum': 1}

    def test_lookup_joins_relation_definition(self) -> None:
        """The lookup joins the CmdbRelation definition on public_id."""
        lookup = _stage(build_relation_tabs_pipeline(OBJECT_ID), '$lookup')

        assert lookup['from'] == CmdbRelation.COLLECTION
        assert lookup['localField'] == '_id.relation_id'
        assert lookup['foreignField'] == 'public_id'

    def test_projection_is_role_oriented(self) -> None:
        """label/icon/color are chosen per role (parent vs child definition fields)."""
        projection = _stage(build_relation_tabs_pipeline(OBJECT_ID), '$project')

        assert set(projection) >= {'relation_id', 'role', 'label', 'icon', 'color', 'count'}
        assert projection['_id'] == 0
        # label picks relation_name_parent when role==parent, else relation_name_child
        label_cond = projection['label']['$cond']
        assert label_cond[0] == {'$eq': ['$_id.role', 'parent']}
        assert label_cond[1] == '$definition.relation_name_parent'
        assert label_cond[2] == '$definition.relation_name_child'
        assert projection['color']['$cond'][1] == '$definition.relation_color_parent'

    def test_sort_parent_before_child(self) -> None:
        """Results are ordered by relation, parent tab before child tab."""
        sort = _stage(build_relation_tabs_pipeline(OBJECT_ID), '$sort')

        assert sort == {'relation_id': 1, 'role': -1}
