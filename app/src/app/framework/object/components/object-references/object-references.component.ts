/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { Location } from '@angular/common';

import { Subject, Subscription } from 'rxjs';

import { ObjectService } from '../../../services/object.service';

import { RenderResult } from '../../../models/cmdb-render';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

interface TypeRef {
    typeID: number;
    typeLabel: string;
    typeName: string;
    occurences: number;
    hidden: boolean;
}


@Component({
    selector: 'cmdb-object-references',
    templateUrl: './object-references.component.html',
    styleUrls: ['./object-references.component.scss'],
    standalone: false
})

export class ObjectReferencesComponent implements OnChanges {
    // The public id of the current object
    @Input() publicID: number;

    // The total number of references to this object
    totalReferences: number = 0;

    // Serves as event emitter for the references by type tabs
    clickSubject: Subject<number> = new Subject<number>();

    // List of referenced Types
    referencedTypes: Array<TypeRef> = [];
    referenceSubscription: Subscription;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */
    constructor(public objectService: ObjectService, private location: Location) {

    }


    /**
     * Load/reload objects from the api
     * @private
     */
    ngOnChanges(changes: SimpleChanges) {
        if (changes.publicID) {
            const params: CollectionParameters = {
                filter: undefined,
                limit: 0,
                sort: 'public_id',
                order: 1,
                page: 1
            };

            if (this.referenceSubscription) {
                this.referenceSubscription.unsubscribe();
            }

            this.referenceSubscription = this.objectService.getObjectReferences(this.publicID, params).subscribe(
                (apiResponse: APIGetMultiResponse<RenderResult>) => {
                    this.sortReferencesByType(apiResponse.results as Array<RenderResult>);
                }
            );
        }
    }


    ngOnDestroy() {
        if (this.referenceSubscription) {
            this.referenceSubscription.unsubscribe();
        }
    }

    /* -------------------------------------------------- EVENT HANDLER ------------------------------------------------- */

    /**
     * Hides the selected type from the tab list
     */
    onSelect(type) {
        type.hidden = !type.hidden;
    }


    /**
     * Resets the hidden Tabs
     */
    onReset() {
        this.referencedTypes.forEach((type) => {
            type.hidden = false;
        });
    }


    /**
     * Sends event to the clicked Tab to enable Lazy loading
     * @param event
     */
    onClick(event) {
        this.clickSubject.next(event);
    }

    /**
     * Navigates back to the previous page in the browser's history.
     */
    goBack(): void {
        this.location.back();
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Sorts References by Type
     * @param event
     */
    sortReferencesByType(event: Array<RenderResult>) {
        this.referencedTypes = [];
        let objectList: Array<RenderResult> = Array.from(event);
        this.totalReferences = objectList.length;

        while (objectList.length > 0) {
            const typeID = objectList[0].type_information.type_id;
            const typeLabel = objectList[0].type_information.type_label;
            const typeName = objectList[0].type_information.type_name;
            const occurences = objectList.filter(object => object.type_information.type_id === typeID).length;
            this.referencedTypes.push({ typeID, typeLabel, typeName, occurences, hidden: false });
            objectList = objectList.filter(object => object.type_information.type_id !== typeID);
            this.sortRefTabs();
        }
    }


    /**
     * Sorts the referenced types by occurence or alphabetical if occurences are the same
     */
    sortRefTabs() {
        this.referencedTypes = this.referencedTypes.sort((a, b) => {
            if (a.occurences > b.occurences) {
                return -1;
            } else if (a.occurences < b.occurences) {
                return 1;
            } else {
                if (a.typeLabel > b.typeLabel) {
                    return 1;
                } else if (a.typeLabel < b.typeLabel) {
                    return -1;
                }
            }

            return 0;
        });
    }
}
