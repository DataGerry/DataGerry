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
Implementation of RegexConverter, the `regex` URL converter registered by `init_rest_api`

Lets a route constrain a parameter with a regular expression:
`@blueprint.route('/probe/<regex("[0-9]{4}"):year>')`. No route declares one today - it is
registered for routes that need a pattern the built-in converters cannot express.

Until 2026-09-14 it could not be used at all. Werkzeug builds a converter as
`converter(url_map, *args, **kwargs)`, passing the arguments written in the rule, but `__init__`
accepted `url_map` alone - so declaring any `<regex(...)>` parameter raised `TypeError: __init__()
takes 2 positional arguments but 3 were given` while the URL map was being built. It also discarded
the pattern instead of assigning `self.regex`, which is the attribute `BaseConverter` matches with,
so even constructed it would have behaved as the default string converter
"""
from logging import Logger, getLogger
from werkzeug.routing import BaseConverter
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: What the parameter matches when the rule names no pattern - the default string converter's rule,
#: i.e. any single path segment
DEFAULT_REGEX: str = '[^/]{1,}'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                RegexConverter - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RegexConverter(BaseConverter):
    """
    RegexConverter extends BaseConverter to allow regex-based URL matching

    Extends: BaseConverter
    """

    def __init__(self, url_map, *items: str) -> None:
        """
        Initialises the converter with the pattern written in the URL rule

        Args:
            url_map (Map): The Werkzeug URL map the rule belongs to, passed straight to the base class
            *items (str): The arguments of the `<regex(...)>` declaration. The first is the pattern;
                Werkzeug hands them over positionally, which is why this has to accept varargs.
                Omitting them falls back to DEFAULT_REGEX rather than failing to build the rule
        """
        super().__init__(url_map)

        self.regex = items[0] if items else DEFAULT_REGEX
