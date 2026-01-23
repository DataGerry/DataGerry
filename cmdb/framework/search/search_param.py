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
Implementation of SearchParam
"""
import logging
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SearchParam - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchParam:
    """
    A class representing a search parameter for database queries
    """

    POSSIBLE_FORM_TYPES = [
        'text',
        'regex',
        'type',
        'category',
        'disjunction',
        'publicID',
    ]

    def __init__(self, search_text: str, search_form: str, settings: dict = None, disjunction: bool = False):
        """
        Initialises the SearchParam

        Args:
            search_text (str): The user input used for searching in the database
            search_form (str): The kind of search parameter, must be one of the POSSIBLE_FORM_TYPES
            settings (dict | None): Settings specific to the search form
            disjunction (bool): If True, indicates the search should be treated as a
                                          disjunction (OR operation). Defaults to False.

        Raises:
            ValueError: If the provided search_form is not in POSSIBLE_FORM_TYPES.
        """
        self.search_text = search_text

        if search_form not in self.POSSIBLE_FORM_TYPES:
            raise ValueError(f'{search_form} is not a possible param type')

        self.search_form = search_form
        self.settings: dict = settings or {}
        self.disjunction: bool = disjunction


    def __repr__(self):
        """
        Returns a string representation of the SearchParam instance

        Returns:
            str: String showing the search text and form type
        """
        return f'[SearchParam] {self.search_text} - {self.search_form}'


    @classmethod
    def from_request(cls, request) -> list['SearchParam']:
        """
        Creates a list of SearchParam instances from an HTTP request

        Args:
            request (iterable): 
                An iterable (such as a list of dictionaries) containing search parameters

        Returns:
            list[SearchParam]: 
                A list of SearchParam instances built from the request

        Notes:
            If an error occurs while parsing a parameter, the error is logged and the parameter is skipped
        """
        param_list: list['SearchParam'] = []

        for param in request:
            try:
                param_list.append(cls(
                        param['searchText'],
                        param['searchForm'],
                        param.get('settings', None),
                        param.get('disjunction', True)
                    )
                )
            except Exception as err:
                LOGGER.error("[from_request] Exception: %s, Type: %s", err, type(err))
                continue

        return param_list
