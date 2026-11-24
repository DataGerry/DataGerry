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
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { ReportSentencePart } from '../filter-builder/report-filter-labels';

@Component({
    selector: 'app-report-sentence',
    standalone: true,
    template: `<p class="report-sentence">@for (part of parts(); track $index) {<span [class]="'report-sentence__' + part.kind">{{ part.text }}</span>}</p>`,
    styleUrls: ['./report-sentence.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ReportSentenceComponent {
    public readonly parts = input<ReportSentencePart[]>([]);
}
