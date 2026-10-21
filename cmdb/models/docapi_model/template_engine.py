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
Implementation of the TemplateEngine

`TemplateEngine` renders a DocAPI document template (a Jinja2 string stored in the database) with
object / report data, producing the HTML that is then converted to PDF.

**The template is untrusted.** A ``template_data`` string is author-supplied through the DocAPI
template write routes and rendered later for any caller who may read the object - a wider audience
than its author. It is therefore rendered in a **`SandboxedEnvironment`**: Jinja's sandbox refuses
access to the Python attributes a template expression would otherwise walk to reach the interpreter
(the ``__init__`` / ``__globals__`` / ``os`` server-side-template-injection chain), so a template
cannot run code in the backend process. The sandbox is the trust boundary - the rights on the write
routes are not.

Rendering is also made crash-tolerant so a missing field never aborts a document:

- ``undefined=ChainableUndefined`` lets undefined variables chain without raising;
- the data is wrapped via `safe_wrap` (`SafeDict` / `SafeNull`) so missing keys/attributes resolve
  to a blank `SafeNull`;
- the ``object(id)`` / ``root`` / ``report(id)`` globals fall back to a `SafeObject` when the id is
  unknown;
- `_finalize` renders ``None`` / empty string / `SafeNull` / `SafeObject` as a non-breaking space;
- ``autoescape`` is enabled, so interpolated field values are HTML-escaped (the `SafeNull` /
  `SafeObject` ``__html__`` hooks supply their blank markup) - the template markup itself is authored
  HTML and is not escaped. This is what keeps a field value carrying HTML / script from becoming
  markup in the produced document.
"""
from logging import Logger, getLogger
from typing import Any

from jinja2 import ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from cmdb.models.docapi_model.safe_null import SafeNull
from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.docapi_model.safe_wrap import safe_wrap

LOGGER: Logger = getLogger(__name__)

NBSP: str = " "

# What a template that fails to render answers, so the document stays non-empty without echoing the
# raw template source (a blocked sandbox expression, or malformed Jinja) back into the document
RENDER_FAILED_PLACEHOLDER: str = NBSP


def build_docapi_environment() -> SandboxedEnvironment:
    """
    Builds the one Jinja2 environment a DocAPI template is rendered in

    Every DocAPI render goes through this factory - there is no other Jinja2 environment in the code -
    so the security properties are declared in one place: the sandbox that refuses the SSTI attribute
    chain, autoescaping, and chainable undefined. The globals and the data are added by the caller

    Returns:
        SandboxedEnvironment: The sandboxed, autoescaping environment, before globals are attached
    """
    return SandboxedEnvironment(autoescape=True, undefined=ChainableUndefined)


class TemplateEngine:
    """
    Renders DocAPI document templates with a sandboxed Jinja2, degrading missing data to blank cells
    """

    @staticmethod
    def _finalize(value: Any) -> Any:
        """
        Jinja2 ``finalize`` hook: renders absent / null values as a non-breaking space

        Args:
            value (Any): The value Jinja2 is about to output

        Returns:
            Any: A non-breaking space for ``None`` / empty string / `SafeNull` / `SafeObject`,
                otherwise the value unchanged
        """
        if value is None or isinstance(value, (SafeNull, SafeObject)):
            return NBSP

        if isinstance(value, str) and value == "":
            return NBSP

        return value


    @staticmethod
    def render_template_string(template_string: str, template_data: dict[str, Any]) -> str:
        """
        Renders a DocAPI Jinja2 template string with the given data, in the sandbox

        Builds the sandboxed environment (`build_docapi_environment`), wraps the data so missing
        lookups stay render-safe, exposes the ``object`` / ``root`` / ``report`` globals with
        `SafeObject` fallbacks, and renders. A template that cannot be rendered - malformed Jinja, or
        an expression the sandbox refuses - is logged and answered with a neutral placeholder, so the
        document stays non-empty and the raw template source (the author's own expression included) is
        never echoed into it.

        Args:
            template_string (str): The Jinja2 template string to render
            template_data (dict[str, Any]): The data to insert into the template

        Returns:
            str: The rendered template, or `RENDER_FAILED_PLACEHOLDER` when rendering failed
        """
        environment = build_docapi_environment()
        environment.finalize = TemplateEngine._finalize

        safe_template_data = safe_wrap(template_data)
        safe_fallback = SafeObject()

        environment.globals["object"] = lambda public_id: (
            safe_template_data.get("objects", {}).get(public_id, safe_fallback)
        )
        environment.globals["root"] = safe_template_data.get("root", safe_fallback)
        environment.globals["report"] = lambda public_id: (
            safe_template_data.get("reports", {}).get(public_id, safe_fallback)
        )

        try:
            template = environment.from_string(template_string)

            return template.render(safe_template_data)
        except Exception as err:
            # A malformed template or an expression the sandbox refused. Never return the raw template:
            # for a blocked payload that would place the author's expression in the document
            LOGGER.error("Template rendering failed: %s", err)

            return RENDER_FAILED_PLACEHOLDER
