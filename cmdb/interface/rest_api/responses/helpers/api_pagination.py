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
Implementation of APIPagination
"""
from typing import Any
from urllib import parse
# -------------------------------------------------------------------------------------------------------------------- #

class APIPagination:
    """
    Pagination data for rest api calls.
    Reference to RFC 5988 and should be used as a cursor.
    """

    def __init__(self, current: str, first, prev=None, next_=None, last=None) -> None:
        self.current: str = current
        self.first = first
        self.prev = prev
        self.next = next_
        self.last = last


    @staticmethod
    def __update_query(query: str, key: str, value: Any) -> str:
        """
        Update any query string parameter

        Args:
            query: query string
            key: key which will be changes
            value: new value of the parameter

        Returns:
            encoded string url
        """
        url_dict = dict(parse.parse_qsl(query))
        url_dict.update(**{key: value})
        return parse.urlencode(url_dict)


    @staticmethod
    def __set_page(query: str, page: int) -> str:
        """
        Set the query page parameter

        Args:
            query: query string
            page: page value

        Returns:
            encoded string url with updated page value
        """
        return APIPagination.__update_query(query, 'page', page)


    @staticmethod
    def __first_url(parsed_url: parse.ParseResult, first_page: int = 1) -> parse.ParseResult:
        """Set the page parameter of a url to the first page"""
        query = parsed_url.query
        new_query = APIPagination.__set_page(query, first_page)
        return parsed_url._replace(query=new_query)


    @staticmethod
    def __last_url(parsed_url: parse.ParseResult, total_pages: int) -> parse.ParseResult:
        """Set the page parameter of a url to the last page"""
        query = parsed_url.query
        new_query = APIPagination.__set_page(query, total_pages)
        return parsed_url._replace(query=new_query)


    @staticmethod
    def __pre_url(parsed_url: parse.ParseResult, page: int):
        """Set the page parameter of a url to the previous page"""
        query = parsed_url.query
        if page == 1:
            new_query = APIPagination.__set_page(query, page)
        else:
            new_query = APIPagination.__set_page(query, page - 1)
        return parsed_url._replace(query=new_query)


    @staticmethod
    def __next_url(parsed_url: parse.ParseResult, page: int, total_pages: int):
        """Set the page parameter of a url to the last page"""
        query = parsed_url.query
        if page == total_pages:
            new_query = APIPagination.__set_page(query, page)
        else:
            new_query = APIPagination.__set_page(query, page + 1)
        return parsed_url._replace(query=new_query)


    @classmethod
    def create(cls, url: str, page: int, total_pages: int):
        """
        Create a APIPagination from the url and the pager data

        Args:
            url: Full url path
            page: current page number
            total_pages: Total number of pages

        Returns:
            Instance of a APIPagination
        """
        parsed_url: parse.ParseResult = parse.urlparse(url)
        first_url = parse.urlunparse(cls.__first_url(parsed_url))
        last_url = parse.urlunparse(cls.__last_url(parsed_url, total_pages))
        prev_url = parse.urlunparse(cls.__pre_url(parsed_url, page))
        next_url = parse.urlunparse(cls.__next_url(parsed_url, page, total_pages))
        return cls(current=url, first=first_url, prev=prev_url, next_=next_url, last=last_url)


    def to_dict(self) -> dict[str, Any | None]:
        """
        Converts the attributes of the IsmsVulnerability into a json compatible dict

        Returns:
            dict[str, Any | None]: Json compatible dict of the IsmsVulnerability attributes
        """
        return {
            'current': self.current,
            'first': self.first,
            'prev': self.prev,
            'next': self.next,
            'last': self.last
        }
