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
    selector: 'cmdb-docapi-page-margins-options',
    templateUrl: './docapi-page-margins-options.component.html',
    styleUrls: ['./docapi-page-margins-options.component.scss'],
    standalone: false
})
export class DocapiPageMarginsOptionsComponent {
    @Input() public marginsForm: UntypedFormGroup;

    public get previewTopPercent(): number {
        return this.convertMarginToPercent(this.marginsForm?.get('top')?.value, 297);
    }

    public get previewBottomPercent(): number {
        return this.convertMarginToPercent(this.marginsForm?.get('bottom')?.value, 297);
    }

    public get previewLeftPercent(): number {
        return this.convertMarginToPercent(this.marginsForm?.get('left')?.value, 210);
    }

    public get previewRightPercent(): number {
        return this.convertMarginToPercent(this.marginsForm?.get('right')?.value, 210);
    }

    private convertMarginToPercent(value: unknown, pageSizeMm: number): number {
        const parsed = Number(value);
        if (!Number.isFinite(parsed) || parsed < 0) {
            return 0;
        }

        const maxPreviewPercent = 40;
        return Math.min((parsed / pageSizeMm) * 100, maxPreviewPercent);
    }
}
