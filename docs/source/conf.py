# pylint: disable=invalid-name
#
# Configuration file for the Sphinx documentation builder.
#
# Layout, theme and conventions follow the OpenCelium documentation
# (docs.opencelium.io) so that both becon products read the same way.
# http://www.sphinx-doc.org/en/master/config

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath('../../'))

# -- Project information -----------------------------------------------------

project = 'DataGerry'
author = 'becon GmbH'
copyright = f'{datetime.now().year}, becon GmbH'

version = 'latest'
release = 'latest'

html_title = 'DataGerry documentation'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.intersphinx',
    'sphinx_rtd_theme',
    'sphinx_copybutton',
    'sphinx_new_tab_link',
    'sphinx_reredirects',
]

master_doc = 'index'
source_suffix = '.rst'
language = 'en'
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
pygments_style = 'sphinx'

# |year| resolves to the year the docs are built, so copyright notices in the
# content do not have to be touched every January.
#
# The edition badges mark what only exists in one way of running DataGerry.
# Use them in headings and tables; the full comparison lives in
# start/editions.
rst_epilog = """
.. |year| replace:: {year}

.. role:: badge-cloud
   :class: badge badge-cloud
.. role:: badge-selfhosted
   :class: badge badge-selfhosted
.. role:: badge-licensed
   :class: badge badge-licensed

.. |cloud| replace:: :badge-cloud:`Cloud`
.. |selfhosted| replace:: :badge-selfhosted:`Self-hosted`
.. |licensed| replace:: :badge-licensed:`Licensed feature`
""".format(year=datetime.now().year)

# -- Options for HTML output -------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'collapse_navigation': False,
    'navigation_depth': 3,
}
html_logo = '_static/img/datagerry_logo.svg'
html_favicon = '_static/img/datagerry_favicon.png'

html_static_path = ['_static']
html_extra_path = ['api_docs']

html_css_files = [
    'css/custom.css',
]

# -- Extension configuration -------------------------------------------------

todo_include_todos = False
copybutton_prompt_text = r'\$ |# '
copybutton_prompt_is_regexp = True

# -- Redirects from the pre-3.3 page layout -------------------------------------
#
# The old pages are linked from the application, the Service Portal and search
# engines. sphinx-reredirects writes a small HTML page for each old docname that
# forwards to its new home; targets are relative to the old page. The template
# keeps the forwarding page free of JavaScript and links the target visibly.

redirect_html_template_file = '_redirect.html'

redirects = {
    'getting_started/welcome': '../start/introduction.html',
    'getting_started/cloud_vs_on_premises': '../start/editions.html',
    'getting_started/service_portal': '../cloud/subscriptions.html',
    'getting_started/dg_installation': '../operations/install.html',
    'getting_started/updates': '../operations/updating.html',
    'getting_started/administration': '../operations/configuration.html',
    'getting_started/license': '../about/license.html',
    'usage/cmdb_concepts': '../concepts/data-model.html',
    'usage/datagerry_assistant': '../guides/assistant.html',
    'usage/section_templates': '../guides/section-templates.html',
    'usage/multi_data_sections': '../guides/multi-data-sections.html',
    'usage/n_m_relations': '../guides/relations.html',
    'usage/ci_explorer': '../guides/ci-explorer.html',
    'usage/ipam': '../guides/ipam.html',
    'usage/locations': '../guides/locations.html',
    'usage/reports': '../guides/reports.html',
    'usage/document_generator': '../guides/generate-documents.html',
    'usage/isms': '../concepts/isms.html',
    'usage/automations': '../guides/automations.html',
    'usage/webhooks': '../guides/webhooks.html',
    'usage/imports': '../guides/import-data.html',
    'usage/exports': '../guides/export-data.html',
    'usage/file_explorer': '../guides/file-explorer.html',
    'usage/license_management': '../guides/license-management.html',
    'management/user': '../guides/users-and-groups.html',
    'management/user_group': '../guides/users-and-groups.html',
    'management/authentication': '../guides/authentication.html',
    'management/access_control_list': '../guides/access-control.html',
    'media/media': '../about/contact.html',
    'sources/packages': '../reference/downloads.html',
    'sources/docker': '../reference/downloads.html',
    'sources/changelog': '../reference/changelog.html',
    'rest_api/overview': '../reference/rest-api.html',
}

# pylint: enable=invalid-name
