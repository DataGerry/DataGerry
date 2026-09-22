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
Structural assertions over the assembled URL map

These do not call a route; they read `app.url_map` once the whole application has been built, which
is the only place the API's shape is visible as a whole. A rule about how paths are registered can be
stated here and nowhere else - a per-route test cannot see a duplicate, because each half of one
works perfectly.

**A path is registered once.** A handler carrying two `@blueprint.route` decorators that differ only
by a trailing slash answers both forms, and every later change has to remember both: a method added
to one, a decorator reordered on one, a rename applied to one. Such pairs are easy to miss by hand -
which is why the rule is pinned here instead of being re-checked.

**Which form survives is decided by the callers, not by a preference.** The importer's five kept the
trailing slash because the frontend's `ImportService` called them that way; the media-file read
dropped it because `file.service.ts` calls it without. What the rule forbids is registering both.
The behavioural half of that last one - the surviving form answering and the dropped form not - is in
`framework/test_functional_media_file_route.py`, next to the upload helper it needs.
"""
# -------------------------------------------------------------------------------------------------------------------- #

# The item path whose duplicate registration was the last one in the map. The frontend calls it
# without a trailing slash (`file.service.ts::getFileElement`), so that is the form that survived
MEDIA_FILE_ITEM_RULE: str = '/media_file/<string:filename>'

def _rules(rest_api) -> set[str]:
    """Every rule in the assembled URL map, as its path pattern."""
    return {rule.rule for rule in rest_api.application.url_map.iter_rules()}


def test_no_path_is_registered_in_both_slash_forms(rest_api) -> None:
    """
    The whole map, in one assertion: no rule has a twin differing only by a trailing slash

    The root rule `/` is excluded - it has no no-slash form to collide with.
    """
    rules = _rules(rest_api)

    twins = sorted(rule for rule in rules if rule.endswith('/') and rule != '/' and rule[:-1] in rules)

    assert twins == []


def test_the_map_is_not_empty(rest_api) -> None:
    """Guards the assertion above: an empty map would satisfy it vacuously."""
    assert len(_rules(rest_api)) > 200


def test_the_media_file_read_is_registered_without_a_trailing_slash(rest_api) -> None:
    """The surviving form of the collapsed pair, pinned as the frontend's own spelling."""
    assert MEDIA_FILE_ITEM_RULE in _rules(rest_api)
