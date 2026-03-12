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
import { Component, Input, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { DEFAULT_PAGE_MARGINS, PageMargins, parseMarginValue } from '../../utils/page-margins.util';

@Component({
    selector: 'cmdb-docapi-page-margins-modal',
    templateUrl: './docapi-page-margins-modal.component.html',
    styleUrls: ['./docapi-page-margins-modal.component.scss'],
    standalone: false
})
export class DocapiPageMarginsModalComponent implements OnInit {
    @Input() public initialMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };

    public readonly form = new UntypedFormGroup({
        top: new UntypedFormControl(''),
        bottom: new UntypedFormControl(''),
        left: new UntypedFormControl(''),
        right: new UntypedFormControl('')
    });
    public validationError = '';

    constructor(public readonly activeModal: NgbActiveModal) { }


    public ngOnInit(): void {
        this.form.patchValue({
            top: this.initialMargins.top.toString(),
            bottom: this.initialMargins.bottom.toString(),
            left: this.initialMargins.left.toString(),
            right: this.initialMargins.right.toString()
        });
    }


    public get previewTopPercent(): number {
        return this.convertMarginToPercent(this.form.get('top')?.value, 297);
    }


    public get previewBottomPercent(): number {
        return this.convertMarginToPercent(this.form.get('bottom')?.value, 297);
    }


    public get previewLeftPercent(): number {
        return this.convertMarginToPercent(this.form.get('left')?.value, 210);
    }


    public get previewRightPercent(): number {
        return this.convertMarginToPercent(this.form.get('right')?.value, 210);
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }


    public apply(): void {
        const top = parseMarginValue(this.form.get('top')?.value);
        const bottom = parseMarginValue(this.form.get('bottom')?.value);
        const left = parseMarginValue(this.form.get('left')?.value);
        const right = parseMarginValue(this.form.get('right')?.value);

        if (top === null || bottom === null || left === null || right === null) {
            this.validationError = 'Please enter valid margin values (numbers >= 0).';
            return;
        }

        this.validationError = '';
        this.activeModal.close({ top, bottom, left, right } as PageMargins);
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
