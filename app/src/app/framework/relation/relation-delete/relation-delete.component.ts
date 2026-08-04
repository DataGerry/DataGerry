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
import { ActivatedRoute, Router } from '@angular/router';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, ValidatorFn, Validators } from '@angular/forms';

import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { PreviousRouteService } from '../../../services/previous-route.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { Location } from '@angular/common';

import { RelationService } from '../../services/relaion.service';
import { CmdbRelation } from '../../models/relation.model';
import { ObjectRelationService } from '../../services/object-relation.service';

/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-relation-delete-confirm-modal',
    styleUrls: ['./relation-delete-confirm-modal.component.scss'],
    template: `
    <dg-modal
        icon="fas fa-trash-can"
        eyebrow="Relation"
        title="Relation deletion"
        [subtitle]="typeLabel"
        (dismiss)="modal.dismiss('Cross click')">

        <p class="delete-lead">
            <strong>Are you sure you want to delete <span class="text-primary">{{typeLabel}}</span> relation?</strong>
        </p>

        <form id="deleteTypeModalForm" [formGroup]="deleteTypeModalForm" class="needs-validation" novalidate autocomplete="off">
            <div class="form-group">
                <label for="typeNameInput">Type the name: {{typeName}} <span class="required">*</span></label>
                <input
                    type="text"
                    formControlName="name"
                    class="form-control"
                    [ngClass]="{ 'is-valid': name.valid && (name.dirty || name.touched),
                                 'is-invalid': name.invalid && (name.dirty || name.touched)}"
                    id="typeNameInput"
                    required
                >
                <small id="typeNameInputHelp" class="form-text text-muted">
                    Type in the name of the relation to confirm the deletion.
                </small>
                @if (name.invalid && (name.dirty || name.touched)) {
                        <div class="invalid-feedback">
                    @if (name.errors.required) {
                        <div class="text-end">
                        Name is required
                    </div>
}
                    @if (name.errors.notequal) {
                        <div class="text-end">
                        Your answer is not equal!
                    </div>
                }
                </div>
            }
                <div class="clearfix"></div>
            </div>
        </form>

        <app-button
            dgModalFooter
            [bootstrapClass]="'btn-secondary'"
            label="Cancel"
            type="button"
            (clicked)="modal.dismiss('cancel')">
        </app-button>

        <app-button
            dgModalFooter
            [bootstrapClass]="'btn-danger'"
            label="Delete"
            type="button"
            icon="fas fa-trash-can"
            [disabled]="deleteTypeModalForm.invalid"
            (clicked)="modal.close('delete')">
        </app-button>
    </dg-modal>
    `,
    standalone: false
})
export class RelationDeleteConfirmModalComponent {
    @Input() typeID: number = 0;
    @Input() typeName: string = '';
    @Input() typeLabel: string = '';
    public deleteTypeModalForm: UntypedFormGroup;

    public get name() {
        return this.deleteTypeModalForm.get('name');
    }


    constructor(public modal: NgbActiveModal) {
        this.deleteTypeModalForm = new UntypedFormGroup({
            name: new UntypedFormControl('', [Validators.required, this.equalName()]),
        });
    }


    public equalName(): ValidatorFn {
        return (control: AbstractControl): { [key: string]: boolean } | null => {
            if (control.value !== this.typeName) {
                return { notequal: true };
            } else {
                return null;
            }
        };
    }
}


@Component({
    selector: 'cmdb-relation-delete',
    templateUrl: './relation-delete.component.html',
    styleUrls: ['./relation-delete.component.scss'],
    standalone: false
})
export class RelationDeleteComponent implements OnInit {
    public relationID: number;
    public relationInstance: CmdbRelation;
    public relationObjectsCounter: number;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private relationService: RelationService,
        private router: Router,
        private route: ActivatedRoute,
        public prevRoute: PreviousRouteService,
        private modalService: NgbModal,
        private toast: ToastService,
        private location: Location,
        private objectRelation: ObjectRelationService
    ) {
        this.route.params.subscribe((id) => {
            this.relationID = id.publicID;
        });
    }


    public ngOnInit(): void {
        this.loadRelationObjectCount();
        this.relationService.getRelation(this.relationID).subscribe((relationInstanceResp: CmdbRelation) => {
            this.relationInstance = relationInstanceResp;
        });
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /*
     * Fetches the count of related objects for a given relation.
     */
    loadRelationObjectCount(): void {
        const filter = { 'relation_id': Number(this.relationID) };
        const params = {
            filter,
            limit: 0,
            sort: '',
            order: 1,
            page: 1
        };

        this.objectRelation.getObjectRelations(params).subscribe({
            next: (response) => {
                this.relationObjectsCounter = Number(response?.count);
            },
            error: (error) => {
                this.toast.error(error?.error?.message)
            }
        })
    }


    /*
     * Opens the delete confirmation modal and handles deletion logic.
     * Prevents deletion if related objects exist.
     */
    public open(): void {
        if (this.relationObjectsCounter > 0) {
            this.toast.error('Deletion is only possible if there are no relation objects of this relation!')
            return;
        }
        try {
            const deleteModal = this.modalService.open(RelationDeleteConfirmModalComponent, {
                windowClass: 'dg-modal-window',
                backdropClass: 'dg-modal-window-backdrop'
            });
            deleteModal.componentInstance.typeID = this.relationID;
            deleteModal.componentInstance.typeName = this.relationInstance.relation_name;
            deleteModal.result.then(
                (result) => {
                    if (result === 'delete') {
                        this.relationService.deleteRelation(this.relationID).subscribe({
                            next: () => {
                                this.router.navigate(['/framework/relation/']);
                                this.toast.success(`Relation was successfully deleted: RelationID: ${this.relationID}`);
                            },
                            error: (error) => {
                                this.toast.error(error?.error?.message);
                            }
                        });
                    }
                },
                (reason) => {
                }
            );
        } catch (error) {
            this.toast.error(error?.error?.message);
        }
    }


    /**
     * Navigates back to the previous page in the browser's history.
     */
    goBack(): void {
        this.location.back();
    }
}