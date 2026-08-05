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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { CmdbMode } from '../../../modes.enum';
import { RenderResult } from '../../../models/cmdb-render';
import { CmdbType } from '../../../models/cmdb-type';

@Component({
    selector: 'cmdb-object-bulk-change-preview',
    templateUrl: './object-bulk-change-preview.component.html',
    styleUrls: ['./object-bulk-change-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.Default,
    standalone: false
})
export class ObjectBulkChangePreviewComponent {

    /**
     * Render form mode.
     */
    public readonly mode: CmdbMode = CmdbMode.Simple;

    /**
     * Initial Page number
     */
    public p: number = 1;

    /**
     * Changed data.
     */
    @Input() public changeForm: UntypedFormGroup;

    /**
     * Object types of bulk change.
     */
    @Input() public type: CmdbType;

    /**
     * Activation state
     * @private
     */
    private objectState: boolean;

    @Input()
    public set activeState(value: boolean) {
        this.objectState = value;
    }


    public get activeState(): boolean {
        return this.objectState;
    }


    /**
     * List of original results.
     */
    public originals: Array<RenderResult> = [];

    /**
     * List of results.
     */
    public results: Array<RenderResult> = [];

    @Input('results')
    public set Results(renderResults: Array<RenderResult>) {
        this.results = renderResults;
        this.originals = JSON.parse(JSON.stringify(renderResults));
        this.onChangePage(this.paginateItems(this.results, 1, 10));
    }


    /**
     * List of paginated items.
     */
    public displayedItems: Array<RenderResult> = [];

    /**
     * Get a field from the type definition
     * @param name
     */
    public getField(name: string): any {
        const f = this.type.fields.find(field => field.name === name);
        f.value = this.changeForm.get(name).value;
        return f;
    }


    /**
     * Get the original displayed item.
     * @param index
     * @param name
     */
    public getOriginal(index: number, name: string): any {
        return this.displayedItems[index].fields.find(field => field.name === name);
    }


    /**
     * Set the displayed items on a new set.
     * @param items
     */
    public onChangePage(items: Array<RenderResult>) {
        this.displayedItems = items;
    }


    /**
     * Get changed value
     * @param name
     */
    public getChangedValue(name: string): any {
        return this.changeForm.get(name).value;
    }


    /**
     * Track when item was changed trigger.
     * @param index
     * @param item
     */
    public track(index, item) {
        return item.value.value;
    }


    /**
    * Paginates the given array of items based on the page number and page size.
    * @param items The array of items to paginate.
    * @param pageNumber The current page number.
    * @param pageSize The number of items per page.
    * @returns The paginated array of items for the given page.
    */
    private paginateItems(items: RenderResult[], pageNumber: number, pageSize: number): RenderResult[] {
        const startIndex = (pageNumber - 1) * pageSize;
        const endIndex = Math.min(startIndex + pageSize, items.length);
        return items.slice(startIndex, endIndex);
    }
}