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
import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormControl, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { NgSelectComponent } from '@ng-select/ng-select';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { LocationService } from '../../../services/location.service';

import { RenderFieldComponent } from '../components.fields';
import { ObjectPreviewModalComponent } from '../../../object/modals/object-preview-modal/object-preview-modal.component';
import { RenderResult } from '../../../models/cmdb-render';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './location.component.html',
    styleUrls: ['./location.component.scss'],
    standalone: false
})
export class LocationComponent extends RenderFieldComponent implements OnInit, OnDestroy {
  // fallback objectID for modal preview
  public objectID: number;
  private modalRef: NgbModalRef;
  private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();
  public protect: boolean = false;

  public currentObjectID: number;
  public objectLocation: RenderResult;
  private hasChildren: boolean = false; 

  public locationsList: Array<RenderResult> = [];
  public ownLocation;

  public locationTree = new FormControl('', Validators.required);
  public locationForObjectExists = new FormControl('', Validators.required);
  
  @ViewChild('locationSelect') locationSelect: NgSelectComponent;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public constructor(private locationService: LocationService,
                        private modalService: NgbModal,
                        private route: ActivatedRoute) {
        super();
    }

    public ngOnInit(): void {
        if(this.mode != this.MODES.Bulk){
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
            this.getLocations();
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
     * Get all locations which are selectable as parent
     */
    private getLocations(){
        const params: CollectionParameters = {
            filter: [{ $match: { name: { $ne: null } } }],
            limit: 0,
            sort: 'public_id',
            order: 1,
            page: 1
        };

        this.locationService.getLocations(params).pipe(takeUntil(this.unsubscribe))
            .subscribe((apiResponse: APIGetMultiResponse<RenderResult>) => {
                this.setLocationExists('false');
                let locations = this.extractOwnLocation(apiResponse.results);
                let ownChildren = [];

                if(this.ownLocation){
                    ownChildren = this.locationService.extractAllChildren(this.ownLocation['public_id'],locations);
                }

                this.setValidLocations(ownChildren,locations);

                if(this.mode == this.MODES.Edit && this.hasChildren){
                    this.locationSelect.clearable = false;
                }
        });
    }


    private getChildren(){
        if(this.currentObjectID){
            this.locationService.getChildren(this.currentObjectID).pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (children: RenderResult[]) => {
                            if(children.length > 0){
                    this.hasChildren = true;
                } 
            },
            error: (error) => {
                if (error.status != 404) {
                    // console.error("Error:", error);
                }
            }
            
            }
        );
        }
    }


    private getParent() {
        if (this.currentObjectID) {
            this.locationService.getParent(this.currentObjectID).pipe(takeUntil(this.unsubscribe))
                .subscribe({
                    next: (locationObject: RenderResult) => {
                        if (locationObject) {
                            this.objectLocation = locationObject;
                            var public_id = this.objectLocation['public_id'];
                            this.parentFormGroup.patchValue({ 'dg_location': public_id });
                            this.setLocationExists('true');
                        }
                    },
                    error: (error) => {
                        if (error.status != 404) {
                            // console.error("Error:", error);
                        }
                    }
                }
                );
        }
    }

/* ------------------------------------------------- HELPER SECTION ------------------------------------------------- */

    /**
     * Removes the location of the current object and filters unselectable locations
     * 
     * @param locations all locations from backend
     * @returns all selectable locations without the location of the current object
     */
    private extractOwnLocation(locations){
        let selectableLocations = [];

        for(let location of locations){
            if(location['object_id'] == this.currentObjectID){
                this.ownLocation = location;
                this.setTreeName(this.ownLocation['name']);
                this.setLocationExists('true');
                continue;
            }

            if(location['type_selectable']){
                selectableLocations.push(location);
            }
        }

        return selectableLocations;
    }


    /**
     * Removes child locations of current object location to prevent loops
     * 
     * @param children 
     * @param locations 
     */
    private setValidLocations(children, locations){
        let validLocations = [];
        let childIDs: number[] = [];

        for(let child of children){
            childIDs.push(Number(child['public_id']));
        }

        for(let location of locations){
            //add location to selection when it is not a child of current object
            if(!childIDs.includes(location['public_id'])){
                validLocations.push(location);
            }
        }

        this.locationsList = validLocations;
    }


    /**
     * Removes the selected location when unselecting
     * 
     * @param event 
     */
    public locationChanged(event){
        if(event == undefined){
            this.data.value = null;
        }
    }


    public searchRef(term: string, item: any) {
        term = term.toLocaleLowerCase();
        const value = item.object_information.object_id + item.type_information.type_label + item.summary_line;

        return value.toLocaleLowerCase().indexOf(term) > -1 || value.toLocaleLowerCase().includes(term);
    }


    public showReferencePreview() {
        this.modalRef = this.modalService.open(ObjectPreviewModalComponent, { size: 'lg' });
        this.modalRef.componentInstance.renderResult = this.objectLocation;
    }


    public onTreeNameChanged(currentName){
        this.locationTree.setValue(currentName);
        this.parentFormGroup.value['locationTreeName'] = currentName;
        this.parentFormGroup.markAsDirty();

        this.locationService.locationTreeName = currentName;
    }


    private setLocationExists(val: string){
        this.locationForObjectExists.setValue(val);
        this.parentFormGroup.value['locationForObjectExists'] = val;
    }


    private setTreeName(val: string){
        this.locationTree.setValue(val);
        this.parentFormGroup.value['locationTreeName'] = val;
    }


    private registerForEventChanges() {
        this.parentFormGroup.valueChanges.subscribe( (event) => {
        this.parentFormGroup.value['locationTreeName'] = this.locationTree.value;
        this.parentFormGroup.value['locationForObjectExists'] = this.locationForObjectExists.value;
        });
    }


    groupByFn = (item) => item.type_label;

    groupValueFn = (_: string, children: any[]) => ({
        name: children[0].type_label
    })
}
