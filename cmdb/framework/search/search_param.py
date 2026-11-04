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
Implementation of SearchParam, one parsed criterion of an object search

A search request is a LIST of these, built by the Angular search bar: each tag the user adds becomes
one parameter, and `SearchPipelineBuilder.build` turns the list into the aggregation pipeline. Three
properties are worth knowing before changing anything here:

**The wire keys and the form names are a frontend contract.** `SearchParamKey` mirrors the Angular
`SearchBarTag` and `SearchFormType` mirrors the strings the search bar hardcodes, so narrowing either
rejects a payload the UI still sends.

**A parameter that cannot be read is refused, not dropped.** Logging a malformed entry and
continuing would return a shorter list the caller could not tell from a complete one - and a lost
*filter* parameter makes a search return MORE objects than the user asked to see, with a 200 and
nothing to notice. `from_request` raises `SearchParamError` instead, which the search route answers as
a 400 naming the parameter.

**`settings` is checked per form.** It is a JSON object for every form; a TYPE parameter's `types` and a CATEGORY
parameter's `categories` are lists of public_ids, and a CATEGORY parameter must name at least one - the builder
resolves the categories by id, so one without ids would filter by nothing and widen the result.

**`disjunction` decides how several TYPE parameters combine** - OR when true (they are collected into
one `$or`), AND when false (each becomes its own `$match`). It defaults to **True**, which is what
every request the frontend sends relies on: the search bar never sets the key on a type tag, and its
OR mode is expressed by appending a separate DISJUNCTION marker parameter that nothing reads. The
constructor and `from_request` default it the same way, so the same absent key cannot mean opposite
things depending on which one built the parameter
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.search.search_constants import (
    SEARCH_CATEGORY_IDS_REQUIRED_MESSAGE,
    SEARCH_PARAMETER_NOT_AN_OBJECT_MESSAGE,
    SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE,
    SEARCH_SETTING_IDS_INVALID_MESSAGE,
    SEARCH_SETTINGS_NOT_AN_OBJECT_MESSAGE,
    SearchFormType,
    SearchParamKey,
    SearchSettingKey,
)

from cmdb.errors.framework_search import SearchParamError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: The settings key holding a form's id list - the forms whose settings name objects to filter by
ID_SETTING_OF_FORM: dict[str, str] = {
    SearchFormType.TYPE.value: SearchSettingKey.TYPES.value,
    SearchFormType.CATEGORY.value: SearchSettingKey.CATEGORIES.value,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SearchParam - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchParam:
    """
    A class representing a search parameter for database queries
    """

    #: The accepted form names, as the frontend spells them. Read from SearchFormType so the two
    #: cannot drift; see that enum for which of them drive a pipeline stage
    POSSIBLE_FORM_TYPES: list[str] = [form_type.value for form_type in SearchFormType]

    def __init__(
            self,
            search_text: Any,
            search_form: str,
            settings: dict[str, Any] | None = None,
            disjunction: bool = True) -> None:
        """
        Initialises the SearchParam

        Args:
            search_text (Any): The user input searched for. A string for every form except
                               PUBLIC_ID, whose text is read as an integer by the pipeline builder
            search_form (str): The kind of search parameter, one of POSSIBLE_FORM_TYPES
            settings (dict | None): Settings specific to the form - the type ids of a TYPE parameter,
                                    the categories of a CATEGORY one. None becomes {}
            disjunction (bool): Whether several TYPE parameters combine with OR. Defaults to True,
                                matching what the frontend's payload relies on

        Raises:
            SearchParamError: If the search_form is not one of POSSIBLE_FORM_TYPES, a PUBLIC_ID
                              parameter carries text that is not a whole number, or the settings do not
                              fit the form (``check_settings``)
        """
        if search_form not in self.POSSIBLE_FORM_TYPES:
            raise SearchParamError(f"'{search_form}' is not a possible search form type!")

        if search_form == SearchFormType.PUBLIC_ID and not self._is_whole_number(search_text):
            raise SearchParamError(
                f"A '{SearchFormType.PUBLIC_ID.value}' search needs a whole number, got: {search_text}"
            )

        check_settings(search_form, settings)

        self.search_text = search_text
        self.search_form: str = search_form
        self.settings: dict[str, Any] = settings or {}
        self.disjunction: bool = disjunction


    def __repr__(self) -> str:
        """
        Returns a string representation of the SearchParam instance

        Returns:
            str: String showing the search text and form type
        """
        return f'[SearchParam] {self.search_text} - {self.search_form}'


    @staticmethod
    def _is_whole_number(value: Any) -> bool:
        """
        Reports whether a search text can be read as a public_id

        The check lives here rather than in the pipeline builder, which coerces with a bare int() two
        layers away - where the failure becomes a generic 400 that names no parameter

        Args:
            value (Any): The search text to check

        Returns:
            bool: True when the value is an integer or a string of digits
        """
        if isinstance(value, bool):
            return False

        if isinstance(value, int):
            return True

        return isinstance(value, str) and value.strip().lstrip('-').isdigit()


    @classmethod
    def from_request(cls, raw_params: list[dict[str, Any]]) -> list['SearchParam']:
        """
        Builds the list of SearchParams a search request carries

        Every entry has to be readable: one that is not refuses the whole request rather than being
        skipped, because a dropped filter parameter widens the result set and nothing in the response
        would say so

        Args:
            raw_params (list[dict[str, Any]]): The parameters as the frontend sent them - the decoded JSON, so
                any shape a client can send

        Raises:
            SearchParamError: If the parameters are not a list (an empty object is read as no parameters), an entry
                is not an object, or an entry is missing a required key or carries an unusable value

        Returns:
            list[SearchParam]: One SearchParam per entry, in the order they were sent
        """
        param_list: list['SearchParam'] = []

        if raw_params == {}:
            # `?query={}` is the historical spelling of an unfiltered search
            return param_list

        if not isinstance(raw_params, list):
            raise SearchParamError(SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE.format(kind=type(raw_params).__name__))

        for position, param in enumerate(raw_params):
            if not isinstance(param, dict):
                raise SearchParamError(
                    SEARCH_PARAMETER_NOT_AN_OBJECT_MESSAGE.format(position=position, kind=type(param).__name__)
                )

            try:
                param_list.append(cls(
                    param[SearchParamKey.SEARCH_TEXT.value],
                    param[SearchParamKey.SEARCH_FORM.value],
                    param.get(SearchParamKey.SETTINGS.value),
                    param.get(SearchParamKey.DISJUNCTION.value, True),
                ))
            except SearchParamError as err:
                LOGGER.error("[from_request] Unusable search parameter at %s: %s", position, err)
                raise
            except KeyError as err:
                LOGGER.error("[from_request] Search parameter at %s is missing %s", position, err)
                raise SearchParamError(
                    f"The search parameter at position {position} is missing the key {err}!"
                ) from err

        return param_list


def is_public_id_list(value: Any) -> bool:
    """
    Reports whether a settings value is a list of public_ids

    Args:
        value (Any): The value of an id key in a parameter's settings

    Returns:
        bool: True for a list whose every entry is an int (a bool is no id)
    """
    return isinstance(value, list) and all(
        isinstance(entry, int) and not isinstance(entry, bool) for entry in value
    )


def check_settings(search_form: str, settings: Any) -> None:
    """
    Refuses settings that do not fit the parameter's form

    None and an object are accepted for every form. TYPE's ``types`` and CATEGORY's ``categories`` must be lists of
    public_ids when present, and a CATEGORY parameter must name at least one category - it is resolved by id

    Args:
        search_form (str): The parameter's form, already checked
        settings (Any): The parameter's settings as sent

    Raises:
        SearchParamError: Naming the form (and the key) whose settings are unusable
    """
    if settings is not None and not isinstance(settings, dict):
        raise SearchParamError(SEARCH_SETTINGS_NOT_AN_OBJECT_MESSAGE.format(form=search_form))

    present: dict[str, Any] = settings or {}

    id_key: str | None = ID_SETTING_OF_FORM.get(search_form)

    if id_key and id_key in present and not is_public_id_list(present[id_key]):
        raise SearchParamError(SEARCH_SETTING_IDS_INVALID_MESSAGE.format(key=id_key, form=search_form))

    if search_form == SearchFormType.CATEGORY and not present.get(SearchSettingKey.CATEGORIES.value):
        raise SearchParamError(
            SEARCH_CATEGORY_IDS_REQUIRED_MESSAGE.format(form=search_form, key=SearchSettingKey.CATEGORIES.value)
        )
