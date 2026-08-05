/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

@Component({
    selector: 'cmdb-docapi-page-header-options',
    templateUrl: './docapi-page-header-options.component.html',
    styleUrls: ['./docapi-page-header-options.component.scss'],
    standalone: false
})
export class DocapiPageHeaderOptionsComponent {
    @Input() public headerForm: UntypedFormGroup;
    @Input() public editorConfig: Record<string, unknown> = {};
    @Input() public activatedControlName = 'header_activated';
    @Input() public activationToggleId = 'sectionActivatedInput';
    @Input() public contentControlName = 'header_content';
    @Input() public activationLabel = 'Activate header';
    @Input() public contentLabel = 'Header Content';
    @Input() public contentHelpText = 'Design the content that appears in the document header.';
    @Input() public paginationHint = '';
}
