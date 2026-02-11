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
import { Component, OnDestroy, OnInit } from '@angular/core';

import { ReplaySubject, takeUntil } from 'rxjs';

import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { ObjectService } from '../../../services/object.service';

import { RenderFieldComponent } from '../components.fields';
import { RenderResult } from '../../../models/cmdb-render';
import { ObjectPreviewModalComponent } from '../../../object/modals/object-preview-modal/object-preview-modal.component';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { CmdbMode } from '../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './ref.component.html',
    styleUrls: ['./ref.component.scss'],
    standalone: false
})
export class RefComponent extends RenderFieldComponent implements OnInit, OnDestroy {

    private modalRef: NgbModalRef;
    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();
    public objectList: Array<RenderResult> = [];
    public refObject: RenderResult;
    public protect: boolean = false;
    private mdsInteraction: boolean;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private objectService: ObjectService, private modalService: NgbModal) {
        super();
    }


    public ngOnInit(): void {
        this.mdsInteraction = false;

                //This is for MDS sections
        if(this.mode == CmdbMode.View) {
            if(this.data.value && !this.data?.reference){
                this.objectService.getObjectMdsReference(this.data.value).subscribe({
                    next: (result) => {
                        this.data.reference = result;
                        this.mdsInteraction = true;
                    },
                    error: (error) => {
                        // console.error(error);
                    }
                });
            }
        }

        this.data.default = parseInt(this.data.default, 10);

        if (this.mode === CmdbMode.Edit || this.mode === CmdbMode.Create || this.mode === CmdbMode.Bulk) {
            if (this.data.ref_types) {
                if (!Array.isArray(this.data.ref_types)) {
                    this.data.ref_types = [this.data.ref_types];
                }

                const params: CollectionParameters = {
                    filter: [{ $match: { type_id: { $in: this.data.ref_types } } }],
                    limit: 0,
                    sort: 'public_id',
                    order: 1,
                    page: 1
                };

                this.objectService.getObjects(params).pipe(takeUntil(this.unsubscribe))
                .subscribe((apiResponse: APIGetMultiResponse<RenderResult>) => {
                    this.objectList = apiResponse.results;
                });
            }
        }

        //TODO: this is for MDS sections and it should be Edit-Mode instead of Create-Mode
        if(this.mode == CmdbMode.Create) {
            if(this.data.value && !this.data?.reference){
                this.objectService.getObject(this.data.value, false).pipe(takeUntil(this.unsubscribe))
                .subscribe({
                    next: (refObject: RenderResult) => {
                        this.refObject = refObject;
                        this.mdsInteraction = true;
                    },
                    error: (error) => {
                        // console.error(error);
                    }
                });
            }
        }


        if (this.data.reference && this.data.reference.object_id !== '' && this.data.reference.object_id !== 0) {
            if (typeof this.data.reference === 'string' || this.mode === CmdbMode.Create || this.mode === CmdbMode.Bulk) {
                this.protect = true;
            } else {
                this.objectService.getObject(this.data.reference?.object_id, false).pipe(takeUntil(this.unsubscribe))
                .subscribe({
                    next: (refObject: RenderResult) => {
                        this.refObject = refObject;
                    },
                    error: (error) => {
                        // console.error(error);
                    }
                });
            }
        }
    }


    public ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }

        if (this.mdsInteraction) {
            this.data.reference = undefined;
        }

        this.unsubscribe?.next();
        this.unsubscribe?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    groupByFn = (item) => item.type_information.type_label;


    groupValueFn = (_: string, children: any[]) => ({
        name: children[0].type_information.type_label,
        total: children.length
    })


    public searchRef(term: string, item: any) {
        term = term.toLocaleLowerCase();
        const value = item.object_information.object_id + item.type_information.type_label + item.summary_line;
        return value.toLocaleLowerCase().indexOf(term) > -1 || value.toLocaleLowerCase().includes(term);
    }


    public showReferencePreview() {
        this.modalRef = this.modalService.open(ObjectPreviewModalComponent, { size: 'lg' });
        this.modalRef.componentInstance.renderResult = this.refObject;
    }
}
