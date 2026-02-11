**********
Changelogs
**********

Version 3.1.0
=============

| 

New Features
------------

| 

:ref:`Automations (OpenCelium Integration) <automations-anchor>`

-  Integration of **OpenCelium** directly into DataGerry
-  Embedded **OpenCelium Connection Editor** within the application
-  Creation and management of interfaces ("Automations") directly in DataGerry
-  Automation execution options:
  
  -  Time-based (Scheduler)
  -  Manual execution via button click

-  Logging functionality:
  
  -  Execution logs available after each automation run
  -  Storage of the last two logs for **Success**
  -  Storage of the last two logs for **Fail**

| 

:ref:`CI-Explorer Enhancements <ci-explorer-anchor>`

-  Visualization of relationships originating from the **Location Tree**
-  CI-Explorer can now be opened via the **Toolbox**
  
  -  Free selection of the object to be displayed when starting

-  Export functionality:
  
  -  CI-Explorer can be exported as a **PNG file**

-  Dynamic root handling:
  
  -  When changing the root object inside a Configuration Item, the currently displayed CI is automatically updated
  -  Attributes of the newly selected root object are displayed immediately

| 

 :ref:`Relations Configuration <n-m-relations-anchor>`

-  New **Preview Widget**
  
  -  Visual preview of how relation configurations will appear in the CI-Explorer
  -  Immediate feedback during configuration

| 


=======================================================================================================================

| 

Improvements
------------

| 

Location Tree
~~~~~~~~~~~~~

-  Improved visual representation of locations with long names
-  Added **search functionality**
-  Added **filter functionality**
-  Improved usability for complex hierarchical structures

| 

Technical Improvements
----------------------

-  Enhanced logging mechanisms for Automations
-  Improved usability when switching root objects
-  Optimized rendering performance in the CI-Explorer

| 

=======================================================================================================================

| 

Changes
-------

**Documentation**

-   Added Automation Documentation
-   Updated the documentation for the ci-explorer

**Frontend**

-   Upgrade Angular from v17 to v19
-   Bootstrap 5 adoption and angular 19
-   Missing copy Identifier added for controls and type configuration
-   Types not displaying in the category edit
-   Redesign Toast Message
-   Improve Diagnostic Ui
-   Implement Object selector for CI Explorer
-   Show Type Description in Object Type List page
-   Add a button to confirm adding report
-   Render preview in table format (with pagination)
-   Improve Clone Section template modal


**Backend**

-   SSL configuration for Webserver
-   Upgrade python from 3.9 to 3.12
-   Improve Object count API and public_id incrementation handling in the backend
-   Error message improvements

| 

=======================================================================================================================

| 

Bugfixes
--------

-   [**DAT-2338**] Reference Resolve issue
-   [**DAT-2337**] Fix the UI issue if credentials fail; then show the credentials again
-   [**DAT-2323**] Improve the request (Connection Update + Scheduler Update)
-   [**DAT-2322**] Fix connectionID issue in update request (connection)
-   [**DAT-2321**] Update the route for connection update
-   [**DAT-2314**] ProtectionGoal not deletable
-   [**DAT-2166**] Change the order of the columns
-   [**DAT-2135**] Editing a Webhook throws an error
-   [**DAT-2126**] Objects missing in „Referenced By“ tab of object
-   [**DAT-2118**] Improve GitHub workflows due to failing tests online
-   [**DAT-2050**] Type creation: name uniqueness needs to be checked
-   [**DAT-2005**] Preview modal is not responsive
-   [**DAT-1987**] Wrong navigation after returning from Risk Assessment to Risk
-   [**DAT-1986**] Object summary not displayed when adding new Risk Assessment from object
-   [**DAT-1984**] Improve link and breadcrumbs of Persons component
-   [**DAT-1983**] Unclean action when deleting sections fails
-   [**DAT-1981**] Permission for Add Relation button
-   [**DAT-1980**] External link issue while adding a link without fields
-   [**DAT-1979**] External links issues
-   [**DAT-1977**] Fix external links icon not visible
-   [**DAT-1976**] Update type: Checkbox intermittently sent as unchecked to backend for Location control
-   [**DAT-1975**] Optimise object limit logics for on-premises version
-   [**DAT-1972**] Restrict Connect page from Cloud
-   [**DAT-1971**] Webhook search not working
-   [**DAT-1970**] Search is not working in the objects list
-   [**DAT-1967**] File count in File Explorer always returns 0
-   [**DAT-1964**] public_id notation issue
-   [**DAT-1957**] Fix parent category dropdown integration and visibility
-   [**DAT-1956**] Improve webhooks breadcrumbs
-   [**DAT-1955**] Fix issues in Explorer display and functionality
-   [**DAT-1954**] Change the documentation link
-   [**DAT-1952**] Wrong error message for external API when reaching CI limit
-   [**DAT-1944**] Improve object selection dropdown layout for long type names (while adding a relation)
-   [**DAT-1844**] Upon clicking on Filter button in object type list getting error in console
-   [**DAT-1824**] Password fields in MultiDataSections are shown in cleartext
-   [**DAT-1538**] Invalid URL in MLHttpRequest with reverse proxy: (http://):4000/rest/
-   [**DAT-1390**] Error occurs while saving a type after editing
-   [**DAT-1236**] Console error when opening a type with a number field in its section
-   [**DAT-1155**] Fix field ordering issue when adding new object with MDS


| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Version 3.0.0
=============

| 

New Features
------------

| 

:ref:`Reporting System <reports-anchor>`

-  Introduced a new **Reporting** module accessible via :menuselection:`Toolbox --> Reporting`
-  Enables creation, management, and execution of custom reports on CMDB object data
-  Users can define reports per object type (CmdbType) with:

   -  Custom report name and user-defined category
   -  Field selection for fine-grained control over report content
   -  Optional filter logic using nested AND/OR conditions
   -  Multi-value field rendering options: per row or per column

-  Added a separate interface to manage report categories
-  Reports can be executed directly in the UI and downloaded as **CSV**
-  Report results are tailored for flexible documentation, audit support, or export use cases

| 

:ref:`Webhooks <webhooks-anchor>`

-  Introduced support for **Webhooks** to enable real-time integrations with external systems
-  Accessible via :menuselection:`Toolbox --> Webhooks`
-  Webhooks can be configured with:

   -  A custom name and description
   -  The target URL to which event data should be sent
   -  Trigger types (create, update, delete) to define when the webhook should fire

-  Supports **POST** requests with JSON payloads for seamless integration with APIs
-  Webhook execution logs are available for debugging and monitoring delivery status
-  Designed for automation, event-driven workflows, and external system synchronization

| 

 :ref:`n:m (many-to-many) Relations <nm-relations-anchor>` between :ref:`Types <types-anchor>`

  - Added the ability to configure n:m reference fields, allowing :ref:`Objects <objects-anchor>` to be linked to
    multiple other :ref:`Objects <objects-anchor>` and vice versa
  - Enables advanced modeling scenarios such as associating multiple users with multiple systems, or linking services
    across multiple infrastructures
  - Includes support for bidirectional navigation and optional display of related data in both linked
    :ref:`Types <types-anchor>`

| 

Release of the ISMS (Information Security Management System) module
-------------------------------------------------------------------

  - Introduced a comprehensive module for managing information security risks based on ISO 27001 concepts
  - Provides full configurability of core :ref:`ISMS <isms-anchor>` elements including:
    
    - Protection goals
    - :ref:`Risk Classes <isms-risk-class-anchor>` and matrices
    - :ref:`Likelihoods <isms-likelihood-anchor>`, :ref:`Impacts <isms-impact-anchor>` and
      :ref:`Impact Categories <isms-impact-categories-anchor>`
    - :ref:`Threats <isms-threat-anchor>` and :ref:`Vulnerabilities <isms-vulnerability-anchor>`
    - :ref:`Controls and measures <isms-controls-anchor>`

  - Added support for modeling and assessing :ref:`Risks <isms-risk-anchor>`
  - :ref:`Risk Assessments <isms-risk-assessments-anchor>` can be assigned to specific :ref:`Risks <isms-risk-anchor>`,
    :ref:`Objects <objects-anchor>` or :ref:`ObjectGroups <object-groups-anchor>` and include lifecycle data such as
    implementation status and treatment options
  - Allows linking of controls to risks and tracking of implementation progress
  - Statement of Applicability (SOA) functionality for managing control applicability and implementation
  - Includes built-in reporting features for overviews like risk matrices, treatment plans, SOA, and detailed assessments
  - Introduced the concept of **Persons** and **Person Groups** for mapping real-world responsibilities within assessments

| 

=======================================================================================================================

| 

Backward incompatible changes
-----------------------------

-   We are replacing the existing exportD service with OpenCelium, an integration platform that enables seamless
    communication between applications via APIs. OpenCelium will allow us to deliver data flexibly and in real time via
    webhooks, improving data flow and integration capabilities across our ecosystem
-   Another part of this change is the removal of RabbitMQ which will no longer be a dependency when installing
    DataGerry

| 

=======================================================================================================================

| 

Changes
-------

**Documentation**

-   New design and structure of the DataGerry documentation
-   API routes are now being documented using the OpenAPI format, beginning with this release. This is an ongoing
    process and will be expanded in future updates

**Frontend**

-   Tests were added to various frontend components (ongoing process)
-   Design changes for the detailed view of :ref:`Objects <objects-anchor>`
-   Improved and optimized validation workflows when creating and editing :ref:`Types <types-anchor>`
-   Object links between two :ref:`Objects <objects-anchor>` are now limited to once
-   Enforced uniqueness of the **Email** field when creating or updating users to prevent duplicate entries
-   Refactored several components and workflows in Angular frontend to optimize speed and resource usage
    (onging process)
-   Added a "Back" button in the "Referenced by"-tab of :ref:`Object <objects-anchor>` detailed views
-   The special control **Reference** has now its required fields highlighted
-   Improved visual feedback for invalid fields and sections when creating/editing a :ref:`Type <types-anchor>`
-   A new basic control type has been added to the :ref:`Types <types-anchor>` creation/edit form: the Numeric Field,
    which strictly accepts numeric input values
-   :ref:`Types <types-anchor>` cannot be deleted if :ref:`Reports <reports-anchor>` exist which are using it
-   A spinner has been added while the Frontned is waiting for API responses from the Backend
-   The "Enter"-Key can now be used on the login page to trigger the "Login" button
-   Login credentials are now preserved on an incorrect login attempt
-   Added a toggle button to hide/show the password on the login page
-   Added a default value field for basic control **Checkbox**

**Backend**

-   New backend startup routine checks if all required collections are exisiting in the database
-   Improved error message texts for backend responses to be more informative (ongoing process)
-   Several APi routes were improved with proper error handling and extended error messages (ongoing process)
-   Refactored several workflows and classes in Backend to optimize speed and resource usage (ongoing process)

| 

=======================================================================================================================

| 

Bugfixes
--------

-   [**DAT-568**] Fixed a bug where the creation date of :ref:`Objects <objects-anchor>` overwritten by the edit date
    when editing an :ref:`Object <objects-anchor>`
-   [**DAT-859**] Fixed a bug where duplicate identifiers were saved for :ref:`Type <types-anchor>` controls
-   [**DAT-860**] Fixed a bug where duplicate identifiers were saved for :ref:`Type <types-anchor>` sections
-   [**DAT-883**] Fixed a bug where invalid characters could be entered in the name property when a
    :ref:`Type <types-anchor>` is created
-   [**DAT-898**] Fixed a bug where incorrect section names were applied when setting multiple section names to "Empty"
    while creating a :ref:`Type <types-anchor>`
-   [**DAT-967**] Fixed a bug where the list of documents sometiems was not updated when a document was deleted
    in the :ref:`File Explorer <file-explorer-anchor>`
-   [**DAT-968**] Fixed a bug where the Frontend crashed when saving a new
    :ref:`Section Template <section-templates-anchor>`
-   [**DAT-979**] Fixed an issue where options from a removed reference type selection remained visible in the summary
    section
-   [**DAT-983**] Fixed an issue when Rapidly Clicking Delete Button in :ref:`File Explorer <file-explorer-anchor>`
    crashed the frontend
-   [**DAT-984**] Fixed an issue where the file upload count was not correctly displayed in the
    :ref:`File Explorer <file-explorer-anchor>`
-   [**DAT-985**] Fixed an issue where the uploaded files were not displayed in the
    :ref:`File Explorer <file-explorer-anchor>`
-   [**DAT-989**] Fixed a bug where adding a :ref:`Multi Data Sections <mds-anchor>` to a :ref:`Type <types-anchor>`
    with three existing sections caused one section to be incorrectly converted into a
    :ref:`Multi Data Sections <mds-anchor>`
-   [**DAT-992**] Fixed an intermittent issue where performing a clean action on a :ref:`Type <types-anchor>` could
    cause the application to crash
-   [**DAT-1007**] Fixed an issue where accessing **Settings -> Database Properties** could result in an error with
    an unclear error message
-   [**DAT-1019**] Fixed an issue where fields in the :ref:`Type <types-anchor>` creation form lost its index when
    the identifier was empty
-   [**DAT-1022**] Fixed an issue where the special control **Reference** could only be dragged once and the got locked
-   [**DAT-1036**] Fixed a bug where identifiers were incorrectly validated against labels, causing uniqueness errors
    when both fields had identical values
-   [**DAT-1040**] Fixed a bug where sometimes deleting **UserGroups** caused an error
-   [**DAT-1042**] Fixed a bug where newly added :ref:`Types <types-anchor>` where not displayed in the sidebar until
    the page was refreshed manually
-   [**DAT-1063**] Fixed a bug where an incorrect path was used when clicking the back button in the **View Logs Page**
-   [**DAT-1077**] Fixed a bug where in section templates, updating the label of an existing section does not reflect
    the change. This issue also occured while creating a new section label
-   [**DAT-1139**] Fixed a bug where the "Unclean" action of :ref:`Types <types-anchor>` resulted in an error under
    certain circumstances
-   [**DAT-1179**] Fixed a bug where under certain circumstances the creation of :ref:`Locations <locations-anchor>`
    failed
-   [**DAT-1188**] Fixed a bug where under certain circumstances a new :ref:`Type <types-anchor>` could not be created(
    "Save" - button stayed disabled) when a Reference special control was dragged into a section
-   [**DAT-1204**] Fixed a bug which occured during imports from CSV files
-   [**DAT-1274**] Fixed a bug that, under certain conditions, caused the application to crash when opening the
    ObjectLogs
-   [**DAT-1281**] Fixed a bug that caused the application to crash if a :ref:`Type <types-anchor>` ,which contains a
    :ref:`Locations <locations-anchor>`, was viewed
-   [**DAT-1407**] Fixed :ref:`Object <objects-anchor>` exporters mapping public_id to object_id
-   [**DAT-1545**] Fixed an issue with incorrectly referenced type summary fields when specific input patterns are used
-   [**DAT-1625**] Fixed an issue where hidden fields of :ref:`Multi Data Sections <mds-anchor>` were not saved upon
    editing an :ref:`Objects <objects-anchor>`
-   [**DAT-1655**] Fixed an issue where the special control **Reference** label was not saved correctly inside of
    :ref:`Section Templates <section-templates-anchor>`
-   [**DAT-1831**] Fixed a bug where incorrect data was shown inside of reference sections of
    :ref:`Objects <objects-anchor>`

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Version 2.2.0
=============

| 

New Features
------------

| 

Multi Data Sections (MDS)

-  Added a new section type named **MultiDataSection**
-  The **MultiDataSection** is filled with fields like a normal
   **Section** but it can store multiple value sets of the fields
-  The values are displayed in a table where they can also be modified
-  At the current state of development there are some restrictions to
   MultiDataSections of which some are intended and some will be
   implemented in later releases

   -  Objects with MDS can only be exported and imported in JSON format
   -  MDS entries can not be used in the DocAPI
   -  MDS entries does not interact with exportd
   -  MultiDataSections in objects are not displayed in bulk changes
   -  MDS fields can not be used as summary fields in the type
      configuration

| 

Bugfixes
--------

-  Fixed a wrongfully thrown error when generating a PDF from DocAPI
   although the PDF was generated correctly
-  Fixed an issue where some special characters were not rendered
   correctly in the DocAPI
-  Fixed an issue where german special characters were not imported
   correctly from a CSV file
-  Fixed an issue where sometimes references were missing when importing
   from a CSV file
-  Fixed an issue where the value of rows for textarea controls was not
   saved in the backend
-  Fixed an issue in object view-mode where the “External Links”-Button
   would throw an error instead of opening
-  Fixed an issue in object view-mode where the “Documents”-Button would
   throw an error instead of opening
-  Fixed a bug where the “Attachments” in object view-mode showed a
   wrong counter
-  Fixed a bug which raised an error when editing a PDF template
-  Fixed an issue where changes to the label for the Special Control
   “Reference” were not saved
-  Fixed an occurring error when adding a new DocAPI document. also
   fixed an issue where sometimes the template content section was not
   working as desired
-  Fixed an occurring error when selecting the file format when
   importing objects
-  Fixed an occurring error when importing objects
-  Fixed an issue where the identifier of sections and fields was not
   saved in the type configuration
-  Fixed a falsely displayed error message in DocAPI when creating a new
   template
-  Fixed an issue in DocAPI where it was possible to proceed to the next
   step without all required fields having valid values
-  Fixed a bug where it was possible to save a type configuration with
   an invalid section state
-  Fixed a bug where the configuration of selected columns in tables
   were not saved
-  Fixed a bug where a click on the password field in tables triggered a
   redirection instead of showing the password

| 

Changes
-------

RHEL 8

-  DATAGERRY is no longer compatible with **RHEL8**. The build package
   of version 2.2.0 and following will use **RHEL9**

| 

General

-  Dates in date fields can now be copy pasted via keyboard, see the
   hint below date fields for more details on the format
-  The “Cancel” button in object edit-mode page navigates back to the
   objects overview table instead of the objects corresponding view-mode
   page
-  The “ATTACHMENTS” modal view in the object overview now has a
   “Cancel”-Button to close it instead of only be able to press the “x”
   in the top right corner to close it
-  The “About”-Section of DATAGERRY was slightly reworked
-  Changed the displayed message in backend when DATAGERRY informs the
   user that an update needs to be executed to update the objects/types
   schema due to a previous misleading message
-  Added additional backend console logs for RabbitMQ connection
   exceptions

| 

Frontend Changes

-  Several package bumps to fix security issues
-  Angular has been updated from Version 15 to Version 17
-  Several modules have been refactored

| 

Angular Package Bumps

-  **@angular/animations** to **17.3.1** (from 15.2.4)
-  **@angular/cdk** to **17.3.1** (from 15.2.4)
-  **@angular/common** to **17.3.1** (from 15.2.4)
-  **@angular/compiler** to **17.3.1** (from 15.2.4)
-  **@angular/core** to **17.3.1** (from 15.2.4)
-  **@angular/forms** to **17.3.1** (from 15.2.4)
-  **@angular/localize** to **17.3.1** (from 15.2.4)
-  **@angular/material** to **17.3.1** (from 15.2.4)
-  **@angular/platform-browser** to **17.3.1** (from 15.2.4)
-  **@angular/platform-browser-dynamic** to **17.3.1** (from 15.2.4)
-  **@angular/router** to **17.3.1** (from 15.2.4)
-  **@fortawesome/angular-fontawesome** to **0.14.1** (from 0.12.1)
-  **@fortawesome/fontawesome-free** to **6.5.1** (from 6.4.2)
-  **@fortawesome/fontawesome-svg-core** to **6.5.1** (from 6.4.2)
-  **@fortawesome/free-brands-svg-icons** to **6.5.1** (from 6.4.2)
-  **@fortawesome/free-regular-svg-icons** to **6.5.1** (from 6.4.2)
-  **@fortawesome/free-solid-svg-icons** to **6.5.1** (from 6.4.2)
-  **@ng-bootstrap/ng-bootstrap** to **16.0.0** (from 14.2.0)
-  **@ng-select/ng-select** to **12.0.7** (from 10.0.4)
-  **angularx-qrcode** to **17.0.0** (from 15.0.1)
-  **chart.js** to **4.4.2** (from 2.9.4)
-  **chartjs-plugin-datalabels** to **2.2.0** (from 0.7.0)
-  **core-js** to **3.36.1** (from 3.33.2)
-  **moment-timezone** to **0.5.45** (from 0.5.43)
-  **ngx-drag-drop** to **17.0.0** (from 15.1.0)
-  **ngx-filesaver** to **17.0.0** (from 11.0.0)
-  **ngx-icon-picker** to **1.11.2** (from 1.10.0)
-  **ngx-indexed-db** to **16.0.0** (from 12.0.0)
-  **node-sass** to **9.0.0** (from 8.0.0)
-  **rxjs** to **7.8.1** (from 6.6.7)
-  **semver** to **7.6.0** (from 7.5.4)
-  **tinymce** to **7.0.0** (from 6.7.2)
-  **zone.js** to **014.4** (from 0.14.2)

| 

Backend Changes

-  Several package bumps to fix security issues

| 

Python Package Bumps

-  **alabaster** to **0.7.16** (from 0.7.13)
-  **astroid** to **3.1.0** (from 3.0.1)
-  **Authlib** to **1.3.0** (from 1.2.1)
-  **Babel** to **2.14.0** (from 2.13.1)
-  **certifi** to **2024.2.2** (from 2023.7.22)
-  **coverage** to **7.4.3** (from 7.3.2)
-  **cryptography** to **42.0.5** (from 41.0.5)
-  **flake8** to **7.0.0** (from 6.1.0)
-  **Flask** to **3.0.2** (from 3.0.0)
-  **idna** to **3.6** (from 3.4)
-  **isort** to **5.13.2** (from 5.12.0)
-  **Jinja2** to **3.1.3** (from 3.1.2)
-  **MarkupSafe** to **2.1.5** (from 2.1.3)
-  **packaging** to **24.0** (from 23.2)
-  **Pillow** to **10.2.0** (from 10.1.0)
-  **pluggy** to **1.4.0** (from 1.3.0)
-  **pyasn1** to **0.5.1** (from 0.5.0)
-  **pycairo** to **1.26.0** (from 1.25.1)
-  **pycrptodome** to **3.20.0** (from 3.19.0)
-  **pyflakes** to **3.2.0** (from 3.1.0)
-  **Pygments** to **2.17.2** (from 2.16.1)
-  **pyinstaller** to **6.5.0** (from 6.1.0)
-  **pyinstaller-hooks-contrib** to **2024.3** (from 2023.10)
-  **pylint** to **3.1.0** (from 3.0.2)
-  **pymongo** to **4.6.2** (from 4.6.0)
-  **pyOpenSSL** to **24.1.0** (from 23.3.0)
-  **pytest** to **8.1.1** (from 7.4.3)
-  **pytest-metadata** to **3.1.1** (from 3.0.0)
-  **python-dateutil** to **2.9.0.post0** (from 2.8.2)
-  **reportlab** to **4.0.9** (from 4.0.7)
-  **sphinxcontrib-applehelp** to **1.0.8** (from 1.0.7)
-  **sphinxcontrib-devhelp** to **1.0.6** (from 1.0.5)
-  **sphinxcontrib-htmlhelp** to **2.0.5** (from 2.0.4)
-  **sphinxcontrib-qthelp** to **1.0.7** (from 1.0.6)
-  **sphinxcontrib-serializinghtml** to **1.1.10** (from 1.1.9)
-  **urllib** to **2.2.1** (from 2.0.7)
-  **xhtml2pdf** to **0.2.15** (from 0.2.13)

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Version 2.1.0
=============

| 

New Features
------------

| 

Section Templates

-  Added a new tab under **Framework => Section Templates** where
   sections can be prebuild and then used in the type configurations via
   drag and drop
-  There are three different types of section templates: Standard,
   Global and Predefined
-  Added new rights for section templates

| 

Locations

-  A “Toggle”-Button was added to the location tab in the sidebar. Now
   it is possible to use the complete sidebar to display locations
-  Added a filter field to search for specific locations

| 

deb-Package

-  Starting with version 2.1.0 DATAGERRY will provide a deb-package for
   installations on debian systems

| 

Bugfixes
--------

-  Object Links are now deleted when one of the objects is deleted
-  In type configurations the field “Reference type selections” for the
   special control “Reference” is now a required field. When this field
   was not set, no objects were displayed for selection in object
   configurations
-  The overview of selection fields now display correctly the
   select-option label instead of the select-option-value
-  Fixed various errors when opening object logs
-  The “Cleanup”-Button is now usable in object logs
-  Fixed an error occurring when pressing the “Edit”-Button in the
   categories overview
-  Fixed an error occurring when closing the “Add Link” popup in the
   object overview
-  Fixed an issue where the values of fields (except name and label) of
   controls in type config were not saved in the database
-  Fixed a bug where subcategories were not accessible when the parent
   category got deleted
-  Fixed “Copy to clipboard” action for select fields taking the option
   value instead of the option label
-  Fixed a bug causing an application crash when adding an object link
   in the “Add link” popup but not providing a value
-  Fixed a bug where the status message popups in the top right corner
   could not be closed
-  Fixed an issue where sometimes the “Root”-Location was not
   automatically created in the database
-  Fixed an issue with basic auth where it didn’t work as intended
-  Fixed a bug where an error wa shown although a type was successfully
   exported
-  Fixed all tabs of object logs (Settings => Object Logs) where wrong
   data was loaded or not loaded at all
-  Fixed all tabs of object logs (Settings => Object Logs) where various
   errors occurred
-  Fixed the “Cleanup”-Button for all object logs (Settings => Object
   Logs) which should now work

| 

Changes
-------

DATAGerry Assistant

-  Created types are now placed in categories instead of being added
   plain
-  Added predefined section templates to several types which can be
   created via the assistant

| 

General

-  When an object is deleted, all corresponding object links will be
   removed. Additionally the object reference will be removed from all
   other objects referencing the deleted object
-  Removed the info box in the type overview
-  Moved the status message boxes in the top right corner down to not
   overlap the buttons like Settings, Logout etc.
-  Fields and section identifiers are now getting an UUID instead of a
   random number
-  In the object list table an object’s **View Mode** can now be
   accessed by clicking once into the row and the **Edit Mode** can be
   accessed by double clicking the row of the object
-  When cloning a type, the sections and fields will receive new IDs if
   required (global section templates won’t get new IDs)

| 

Frontend Changes

-  Several package bumps to fix security issues
-  Several package bumps in preparation to upgrade the codebase to
   Angular 16 since Angular 15 is about to reach EoL for security
   support

| 

Angular Package Bumps

-  **@fortawesome/fontawesome-free** to **6.4.2** (from 6.4.0)
-  **@fortawesome/fontawesome-svg-core** to **6.4.2** (from 6.4.0)
-  **@fortawesome/free-brands-svg-icons** to **6.4.2** (from 6.4.0)
-  **@fortawesome/free-regular-svg-icons** to **6.4.2** (from 6.4.0)
-  **@fortawesome/free-solid-svg-icons** to **6.4.2** (from 6.4.0)
-  **@popperjs/core** to **2.11.8** (from 2.11.6)
-  **@tinymce/tinymce-angular** to **7.0.0** (from 4.2.4)
-  **@types/chart.js** to **2.9.40** (from 2.9.37)
-  **@types/file-saver** to **2.0.7** (from 2.0.5)
-  **angular-archwizard** to **7.0.0** (from 6.1.0)
-  **core-js** to **3.33.2** (from 3.29.1)
-  **jquery** to **3.7.1** (from 3.6.4)
-  **ngx-drag-drop** to **15.1.0** (from 2.0.0)
-  **ngx-indexed-db** to **12.0.0** (from 11.0.2)
-  **primeicons** to **6.0.1** (from 5.0.0)
-  **semver** to **7.5.4** (from 5.7.1)
-  **tinymce** to **6.7.2** (from 5.10.7)
-  **tslib** to **2.6.2** (from 2.5.0)
-  **zone.js** to **0.14.2** (from 0.11.4)
-  **@babel/traverse** to **7.23.3** (from 7.21.3)
-  **@types/bootstrap** to **5.2.9** (from 4.6.2)
-  **@types/jasmine** to **5.1.2** (from 3.6.0)
-  **@types/jasminewd2** to **2.0.13** (from 2.0.10)
-  **@types/jquery** to **3.5.27** (from 3.5.16)
-  **@types/node** to **20.9.0** (from 12.20.55)
-  Added **uuid 9.0.1**
-  Added **@types/uuid 9.0.7**
-  **codelyzer** to **6.0.2** (from 6.0.0)
-  **jasmine-core** to **5.1.1** (from 3.99.1)
-  **jasmine-spec-reporter** to **7.0.0** (from 5.0.0)
-  **karma-coverage-istanbul-reporter** to **3.0.3** (from 3.0.2)
-  **karma-jasmine** to **5.1.0** (from 4.0.2)
-  **karma-jasmine-html-reporter** to **2.1.0** (from 1.7.0)
-  **ts-node** to **10.9.1** (from 8.3.0)
-  **tslint** to **6.1.3** (from 6.1.0)
-  **typescript** to **5.2.2** (from 4.8.4)

| 

Backend Changes

-  The version of MongoDB for development is increased to 6.0 due the
   upcoming End of Life for MongoDB 4.4 and 5.0. There are currently
   noissues with MongoDB 4.4 and 5.0 and they should be compatible with
   the newest Version of DATAGERRY
-  Several package bumps to fix security issues

| 

Python Package Bumps

-  **altgraph** to **0.17.4** (from 0.17.3)
-  **astroid** to **3.0.1** (from 2.15.5)
-  **Babel** to **2.13.1** (from 2.12.1)
-  **blinker** to **1.7.0** (from 1.6.2)
-  **Cerberus** to **1.3.5** (from 1.3.4)
-  **cffi** to **1.16.0** (from 1.15.1)
-  **chardet** to **5.2.0** (from 5.1.0)
-  **click** to **8.1.7** (from 8.1.3)
-  **coverage** to **7.3.2** (from 7.2.7)
-  **cryptography** to **41.0.5** (from 41.0.1)
-  **flake8** to **6.1.0** (from 6.0.0)
-  **Flask** to **3.0.0** (from 2.3.2)
-  **gunicorn** to **21.2.0** (from 20.1.0)
-  **packaging** to **23.2** (from 23.1)
-  **Pillow** to **10.1.0** (from 10.0.0)
-  **pluggy** to **1.3.0** (from 1.2.0)
-  **pycodestyle** to **2.11.1** (from 2.10.0)
-  **pycryptodome** to **3.19.0** (from 3.18.0)
-  **pyflakes** to **3.1.0** (from 3.0.1)
-  **Pygments** to **2.16.1** (from 2.15.1)
-  **pyinstaller** to **6.1.0** (from 5.13.0)
-  **pyinstaller-hooks-contrib** to **2023.10** (from 2023.4)
-  **pylint** to **3.0.2** (from 2.17.4)
-  **pymongo** to **4.6.0** (from 3.11.2)
-  **pyOpenSSL** to **23.3.0** (from 23.2.0)
-  **pyparsing** to **3.1.1** (from 3.1.0)
-  **pytest** to **7.4.3** (from 7.4.0)
-  **pytest-html** to **4.1.1** (from 3.2.0)
-  **pytz** to **2023.3.post1** (from 2023.3)
-  **reportlab** to **4.0.7** (from 3.6.13)
-  **Sphinx** to **7.2.6** (from 7.0.1)
-  **sphinxcontrib-applehelp** to **1.0.7** (from 1.0.4)
-  **sphinxcontrib-devhelp** to **1.0.5** (from 1.0.2)
-  **sphinxcontrib-htmlhelp** to **2.0.1** (from 2.0.4)
-  **sphinxcontrib-qthelp** to **1.0.6** (from 1.0.3)
-  **sphinxcontrib-serializinghtml** to **1.1.9** (from 1.1.5)
-  **urllib3** to **2.0.7** (from 2.0.3)
-  **Werkzeug** to **3.0.1** (from 2.3.6)
-  **xhtml2pdf** to **0.2.13** (from 0.2.11)

| 

=======================================================================================================================

| 

Version 2.0.0
=============

| 

=======================================================================================================================

| 

New Features
------------

| 

Locations

-  The sidebar now contains a new Tab “Locations” where locations are
   displayed in a tree structure
-  Added new Special Control “Location” for types which enables types to
   be assigned to locations

| 

Assistant

-  Reworked initial assistant
-  It is now possible to select branches and profiles and DATAGERRY will
   automatically create the corresponding types for a quick start
-  Added a link to the assistant in the toolbox (**Toolbox =>
   Assistant**) so that it is possible to start it manually

| 

Bugfixes
--------

-  Fixed a bug displaying popup boxes behind the gray overlay background
-  Fixed an error where the progress bar of a toast was not
   animated(Popup confirmations in the top right corner)
-  Fixed a bug where saving a column config the input field would get an
   invalid red border. The red border now correctly only appear if the
   input field is empty when clicking the save button
-  Fixed a display bug in Exportd list where the column name was “Name”
   instead of “Label”
-  Fixed an error where Links between objects where not displayed in the
   object overview
-  Fixed a bug where the filter in the sidebar did not hide
   “Uncategorised” Types if the filter-input did not match
-  Fixed an occurring error when pressing the “Show Tabs” button in the
   object overview when the object didn’t have any references
-  Fixed a bug where object counters where not correctly updated when
   switching between “Only Active Objects” and “All Objects”-Mode
-  Fixed a display bug where other elements overlapped the sidebar when
   in cropped view
-  Fixed an error when copying dates to clipboard resulting in output to
   be [object Object]
-  Fixed bugs with the “Save” and “Cancel” button when creating new
   categories not working as intended
-  Fixed an error occurring when closing popups via the “x” in the top
   right corner at several places in DATAGERRY
-  Fixed stacking counters when interacting with bulk changes
-  Fixed an error appearing when pressing to often and to fast
   references in object overviews
-  Fixed a bug falsely displaying an error when objects are exported
-  Fixed a bug where multiple clicks were required to change the order
   of a table column
-  Fixed a visual bug where the scroll bar on text area fields was to
   small to be selected
-  Fixed a visual bug for the type overview on the dashboard
-  Fixed a visual bug hiding the filter field in the sidebar when
   cropping browser to mobile view mode
-  Fixed several occurrences where parts of the application were not
   reloaded after changes took place
-  Fixed a bug which cleared the table when clicking “Default configs”
   in object list
-  Fixed a bug where the sidebar was not reloaded after deleting a type
   and still showing the deleted type

| 

Changes
-------

-  Rework of the Feedback-Form (**Toolbox => Feedback**)
-  When creating or editing a type it is no longer possible to proceed
   to the next step (or press the “Save”-button) if this step has
   invalid fields
-  Added an “x” to be able to clear the filter input in the sidebar
-  Types are now only deletable if no object instances exist of this
   type
-  Dropped support for python 3.6, 3.7 and 3.8

| 

Frontend Changes

-  Bumped Angular packages to 15.2.4
-  Bumped Angular package dependencies to fit Angular 15.2.4

| 

Backend Changes

-  Bumped Python to Version 3.9.16
-  Tests are run against MongoDB 4.4, 5.0 and 6.0 with Python 3.9
   (Dropped tests for Python 3.7, 3.8 and MongoDB 4.2)
-  Added location logics to backend
-  Deleting an object with also delete the corresponding location

| 

Python Package Bumps

-  **alabaster** to **0.7.13** (from 0.7.12)
-  **altgraph** to **0.17.3** (from 0.17)
-  **astroid** to **2.15.5** (from 2.5.1)
-  **attrs** to **23.1.0** (from 20.3.0)
-  **Authlib** to **1.2.1** (from 0.15.3)
-  **Babel** to **2.12.1** (from 2.8.0)
-  **blinker** to **1.6.2** (from 1.4.0)
-  **Cerberus** to **1.3.4** (from 1.3.2)
-  **certifi** to **2023.7.22** (from 2020.6.20)
-  **cffi** to **1.15.1** (from 1.14.3)
-  **chardet** to **5.1.0** (from 3.0.4)
-  **click** to **8.1.3** (from 7.1.2)
-  **coverage** to **7.2.7** (from 5.5)
-  **cryptography** to **41.0.1** (from 3.4.7)
-  **docutils** to **0.20.1** (from 0.16)
-  **et-xmlfile** to **1.1.0** (from 1.0.1)
-  **flake8** to **6.0.0** (from 3.8.4)
-  **Flask** to **2.3.2** (from 1.1.2)
-  **Flask-Cors** to **4.0.0** (from 3.0.9)
-  **gunicorn** to **20.1.0** (from 20.0.4)
-  **idna** to **3.4** (from 2.10)
-  **imagesize** to **1.4.1** (from 1.2.0)
-  **iniconfig** to **2.0.0** (from 1.1.1)
-  **isort** to **5.12.0** (from 5.5.3)
-  **itsdangerous** to **2.1.2** (from 1.1.0)
-  **Jinja2** to **3.1.2** (from 2.11.2)
-  **lazy-object-proxy** to **1.9.0** (from 1.4.3)
-  **ldap3** to **2.9.1** (from 2.8.1)
-  **MarkupSafe** to **2.1.3** (from 1.1.1)
-  **mccabe** to **0.7.0** (from 0.6.1)
-  **openpyxl** to **3.1.2** (from 3.0.5)
-  **packaging** to **23.1** (from 20.4)
-  **Pillow** to **10.0.0** (from 8.1.2)
-  **pluggy** to **1.2.0** (from 0.13.1)
-  **py** to **1.11.0** (from 1.10.0)
-  **pyasn1** to **0.5.0** (from 0.4.8)
-  **pycodestyle** to **2.10.0** (from 2.6.0)
-  **pycparser** to **2.21** (from 2.20)
-  **pycryptodome** to **3.18.0** (from 3.10.1)
-  **pyflakes** to **3.0.1** (from 2.2.0)
-  **Pygments** to **2.15.1** (from 2.7.1)
-  **pyinstaller** to **5.1.3.0** (from 4.0)
-  **pyinstaller-hooks-contrib** to **2023.4** (from 2020.8)
-  **pylint** to **2.17.4** (from 2.7.2)
-  **PyMySQL** to **1.1.0** (from 0.10.1)
-  **pyOpenSSL** to **23.2.0** (from 19.0.0)
-  **pyparsing** to **3.1.0** (from 2.4.7)
-  **PyPDF2** to **3.0.1** (from 1.26.0)
-  **pytest** to **7.4.0** (from 6.2.2)
-  **pytest-cov** to **4.1.0** (from 2.11.1)
-  **pytest-html** to **3.2.0** (from 3.1.1)
-  **pytest-metadata** to **3.0.0** (from 1.11.0)
-  **python-dateutil** to **2.8.2** (from 2.8.1)
-  **pytz** to **2023.3** (from 2020.1)
-  **reportlab** to **3.6.13** (from 3.5.50)
-  **requests** to **2.31.0** (from 2.24.0)
-  **six** to **1.16.0** (from 1.15.0)
-  **snowballstemmer** to **2.2.0** (from 2.0.0)
-  **Sphinx** to **7.0.1** (from 3.2.1)
-  **sphinxcontrib-applehelp** to **1.0.4** (from 1.0.2)
-  **sphinxcontrib-htmlhelp** to **2.0.1** (from 1.0.3)
-  **sphinxcontrib-httpdomain** to **1.8.1** (from 1.7.0)
-  **sphinxcontrib-serializinghtml** to **1.1.5** (from 1.1.4)
-  **toml** to **0.10.2** (from 0.10.1)
-  **urllib3** to **2.0.3** (from 1.25.10)
-  **Werkzeug** to **2.3.6** (from 1.0.1)
-  **wrapt** to **1.15.0** (from 1.12.1)
-  **xhtml2pdf** to **0.2.11** (from 0.2.4)
