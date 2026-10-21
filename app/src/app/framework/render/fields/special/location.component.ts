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
import { FormControl, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { LocationService } from '../../../services/location.service';

import { RenderFieldComponent } from '../components.fields';
import { ObjectPreviewModalComponent } from '../../../object/modals/object-preview-modal/object-preview-modal.component';
import { RenderResult } from '../../../models/cmdb-render';
import { LocationSelection } from 'src/app/core/components/location-tree-select/location-tree-select.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './location.component.html',
    styleUrls: ['./location.component.scss'],
    standalone: false
})
export class LocationComponent extends RenderFieldComponent implements OnInit, OnDestroy {
    // fallback objectID for modal preview
    public objectID: number;
    public protect: boolean = false;

    public currentObjectID: number;
    public objectLocation: RenderResult;
    public hasChildren: boolean = false;

    /** Renders the tree-select trigger for a preselected parent without a second lookup. */
    public objectLocationDisplay: { name: string; icon: string } | null = null;

    public locationTree = new FormControl('', Validators.required);
    public locationForObjectExists = new FormControl('', Validators.required);
    public clearable = true;

    private modalRef: NgbModalRef;
    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public constructor(private locationService: LocationService,
                        private modalService: NgbModal,
                        private route: ActivatedRoute) {
        super();
    }


    public ngOnInit(): void {
        if (this.mode != this.MODES.Bulk) {
            this.registerForEventChanges();
            this.setTreeName('');
            this.setLocationExists('false');

            // Only read the route publicID as object ID in view/edit flows.
            if (this.mode === this.MODES.View || this.mode === this.MODES.Edit) {
                this.currentObjectID = Number(this.route.snapshot.params.publicID);
            }

            if (!this.currentObjectID) {
                this.currentObjectID = this.objectID;
            }

            this.getParent();
            this.getChildren();
            this.getOwnLocation();
        }
    }


    public ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }

        this.unsubscribe?.next();
        this.unsubscribe?.complete();

        this.locationService.locationTreeName = "";
    }

/* ---------------------------------------------------- API CALLS --------------------------------------------------- */

    /**
     * Loads the currently selected parent location so its id populates the form control and its
     * name/icon can render on the tree-select trigger and in view mode.
     */
    private getParent(): void {
        if (!this.currentObjectID) {
            return;
        }

        this.locationService.getParent(this.currentObjectID).pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (locationObject: RenderResult) => {
                    if (locationObject) {
                        this.objectLocation = locationObject;
                        const publicId = this.objectLocation['public_id'];
                        this.parentFormGroup.patchValue({ 'dg_location': publicId });
                        this.objectLocationDisplay = {
                            name: this.objectLocation['name'],
                            icon: this.objectLocation['type_icon']
                        };
                        this.setLocationExists('true');
                    }
                },
                error: (error) => {
                    if (error.status != 404) {
                        // A missing placement (404) simply means no parent is set yet.
                    }
                }
            });
    }


    /**
     * Determines whether this object is itself a parent of other locations. When it is, its
     * placement may not be cleared (removing it would orphan its children).
     */
    private getChildren(): void {
        if (!this.currentObjectID) {
            return;
        }

        this.locationService.getChildren(this.currentObjectID).pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (children: RenderResult[]) => {
                    if (children.length > 0) {
                        this.hasChildren = true;

                        if (this.mode == this.MODES.Edit) {
                            this.clearable = false;
                        }
                    }
                },
                error: (error) => {
                    if (error.status != 404) {
                        // No children found (404) is expected for leaf objects.
                    }
                }
            });
    }


    /**
     * Loads the object's own location entry to prefill the "Label in location tree" input in edit
     * flows (its name is the label shown for this object in the tree).
     */
    private getOwnLocation(): void {
        if (!this.currentObjectID) {
            return;
        }

        this.locationService.getLocationForObject<RenderResult>(this.currentObjectID).pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (ownLocation: RenderResult) => {
                    if (ownLocation) {
                        this.setTreeName(ownLocation['name']);
                        this.setLocationExists('true');
                    }
                },
                error: (error) => {
                    if (error.status != 404) {
                        // Object has no own location entry yet (404) - nothing to prefill.
                    }
                }
            });
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /**
     * Reacts to a parent chosen (or cleared) in the tree-select and keeps the existence flag in sync.
     *
     * @param selection the picked location, or null when the value was cleared
     */
    public onLocationSelected(selection: LocationSelection | null): void {
        this.setLocationExists(selection ? 'true' : 'false');

        if (!selection) {
            this.data.value = null;
        }
    }


    public onTreeNameChanged(currentName: string): void {
        this.locationTree.setValue(currentName);
        this.parentFormGroup.value['locationTreeName'] = currentName;
        this.parentFormGroup.markAsDirty();

        this.locationService.locationTreeName = currentName;
    }


    public showReferencePreview(): void {
        this.modalRef = this.modalService.open(ObjectPreviewModalComponent, {
            size: 'xl',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.renderResult = this.objectLocation;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private setLocationExists(val: string): void {
        this.locationForObjectExists.setValue(val);
        this.parentFormGroup.value['locationForObjectExists'] = val;
    }


    private setTreeName(val: string): void {
        this.locationTree.setValue(val);
        this.parentFormGroup.value['locationTreeName'] = val;
    }


    private registerForEventChanges(): void {
        this.parentFormGroup.valueChanges.pipe(takeUntil(this.unsubscribe)).subscribe(() => {
            this.parentFormGroup.value['locationTreeName'] = this.locationTree.value;
            this.parentFormGroup.value['locationForObjectExists'] = this.locationForObjectExists.value;
        });
    }
}
