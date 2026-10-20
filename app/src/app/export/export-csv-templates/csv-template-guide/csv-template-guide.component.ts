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
import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Collapsible reference for filling in an exported CSV template.
 */
@Component({
    selector: 'cmdb-csv-template-guide',
    standalone: true,
    templateUrl: './csv-template-guide.component.html',
    styleUrls: ['./csv-template-guide.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CsvTemplateGuideComponent {}
