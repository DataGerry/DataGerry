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
import { Component, Input, OnDestroy, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { UntypedFormControl } from '@angular/forms';

import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { ObjectService } from 'src/app/framework/services/object.service';

import { BaseSectionComponent } from '../base-section/base-section.component';
import { Column } from 'src/app/layout/table/table.types';
import { PreviewModalComponent } from 'src/app/framework/type/builder/modals/preview-modal/preview-modal.component';
import { CmdbMultiDataSection, CmdbType } from 'src/app/framework/models/cmdb-type';
import { MultiDataSectionEntry, MultiDataSectionFieldValue, MultiDataSectionSet } from 'src/app/framework/models/cmdb-object';
import { DeleteEntryModalComponent } from '../modals/delete-entry-modal.component';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-multi-data-section',
    templateUrl: './multi-data-section.component.html',
    styleUrls: ['./multi-data-section.component.scss'],
    standalone: false
})
export class MultiDataSectionComponent extends BaseSectionComponent implements OnInit, OnDestroy{
    @Input() public typeInstance: CmdbType;
    @Input() public renderResult: RenderResult;

    public modalSection: any = {};
    private modalRef: NgbModalRef;

    // Summary lines of the current referenced objects (For view mode)
    public currentObjectSummaryLines: any;

    // Dict of all summary lines of objects from  Type 'ref_types'
    public refTypesSummaries: any = {};

    // Helper to update values in table
    public updateRequired = false;

    // Columns of the MDS-table
    public multiDataColumns: Column[] = [];

    //Pagesize of elements
    public pageSizeLimit = 10;
    // Current page of table
    public currentPage = 1;

    // Current 10 values which should be displayed
    public currentMultiDataValues = [];

    // All Values of the MDS-Table
    public tableMultiDataValues = [];

    //Initial MultiDataSectionEntry which will track the values of the form
    formatedDataSection: MultiDataSectionEntry = {
        "section_id": "",
        "highest_id": 0,
        "values": []
    };

    //Control containing all the values which should be saved in the database
    mdsTableControl = new UntypedFormControl('');

    // Table Template: Type actions column
    @ViewChild('actionsTemplate', { static: true }) actionsTemplate: TemplateRef<any>;



/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    constructor(private modalService: NgbModal, private objectService: ObjectService) {
        super();
    }


    ngOnInit(): void {
        //Init 'refTypesSummaries'
        this.initRefTypesSummaryLines();

        //Init 'formatedDataSection' and fill Values if they exist
        this.initFormatedDataSection();

        //Init all controls + form + patchValues
        this.initFieldControlsAndForm();

        //Init the table
        this.initTableColumns();

        //Init the Section which will be passed to the popups to display the MDS
        this.initModalSectionData();
    }


    ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }
    }

/* ------------------------------------------------- REFERENCE SETUP ------------------------------------------------ */

    /**
     * Retrives all objects of the 'ref_types' and initialises the 'this.refTypesSummaries'
     */
    initRefTypesSummaryLines(): void {
        let refTypes: number[] = this.getRefTypes();

        if (refTypes) {
            const params: CollectionParameters = {
                filter: [{ $match: { type_id: { $in: refTypes }}}],
                limit: 0,
                sort: 'public_id',
                order: 1,
                page: 1
            };

            this.objectService.getObjects(params).subscribe((apiResponse: APIGetMultiResponse<RenderResult>) => {
                this.setRefTypesSummaries(apiResponse.results);
                if(this.mode == CmdbMode.View || this.mode == CmdbMode.Edit) {
                    this.initTableValuesFromFormatedDataSection();
                }
            });
        } else {
            if(this.mode == CmdbMode.View || this.mode == CmdbMode.Edit) {
                this.initTableValuesFromFormatedDataSection();
            }
        }
    }


    /**
     * Retrieves all 'ref_types' of the objects Type
     * @returns (Array): All 'ref_types' of the objects Type
     */
    getRefTypes(): number[] {
        let refTypes: number[] = []
        let refTypesSource: CmdbType | RenderResult = this.typeInstance ? this.typeInstance : this.renderResult;

        for (let field of refTypesSource.fields) {
            if (field.type == 'ref' && field.ref_types) {
                refTypes = [...refTypes, ... field.ref_types];
            }
        }

        return refTypes;
    }


    /**
     * Sets the attribute 'this.refTypesSummaries'
     * 
     * @param objectList (RenderResult[]): Array of objects for 'ref_types'
     */
    setRefTypesSummaries(objectList: RenderResult[]): void {
        for (let refObject of objectList) {
            const refObjectID = refObject.object_information.object_id;
            const refObjectLabel = refObject.type_information.type_label;
            const refObjectSummaryLine = refObject.summary_line;

            if(refObjectSummaryLine) {
                this.refTypesSummaries[refObjectID] = `${refObjectLabel} #${refObjectID} - ${refObjectSummaryLine}`;
            } else {
                this.refTypesSummaries[refObjectID] = `${refObjectLabel} #${refObjectID}`;
            }
        }
    }


    /**
     * Retrieves all objectIDs which are referenced in the MultiDataSections of the current object
     * 
     * @param multiDataSections All MDS of the current object
     * @returns (number[]): All referenced objectIDs
     */
    getAllReferencedObjectIdsInMDS(multiDataSections: any): number[] {
        let refIDs: number[] = []

        for(let section of multiDataSections) {
            for (let value of section.values) {
                for (let dataSet of value.data) {
                    if (this.isRefField(dataSet.name) && dataSet.value) {
                        refIDs.push(dataSet.value);
                    }
                }
            }
        }

        return refIDs;
    }


    /**
     * Checks if the type of the Field with the fieldName is of type 'ref
     * @param fieldName (string): name of the Field
     * @returns (boolean): True if type of Field is 'ref', else False
     */
    isRefField(fieldName: string): boolean {
        if (this.mode == CmdbMode.View) {
            for (let aField of this.renderResult.fields) {
                if (aField.name == fieldName) {
                    return aField.type == 'ref';
                }
            }
        }

        return false;
    }

/* -------------------------------------------------- INITIAL SETUP ------------------------------------------------- */

    /**
     * Initialises the MultiDataSectionEntry which will be submited
     */
    initFormatedDataSection(): void {
        if (this.mode == CmdbMode.View || this.mode == CmdbMode.Edit) {
            //Set the already existing values
            for (let aSection of this.renderResult.multi_data_sections) {
                if (aSection.section_id == this.section.name) {
                    this.formatedDataSection.section_id = aSection.section_id;
                    this.formatedDataSection.highest_id = aSection.highest_id;
                    this.formatedDataSection.values = aSection.values;
                }
            }
        } else {
            // In CmdbMode.Create just the section_id
            this.formatedDataSection.section_id = this.section.name;
        }
    }


    /**
     * Adds all FieldControls for the Form-Popups and initialises the form 
     */
    initFieldControlsAndForm(): void {
        //add the controls for all fields of the MDS
        for(let aField of this.fields){
            if (this.section.fields.includes(aField.name)) {
                const fieldControl = new UntypedFormControl('');
                this.form.addControl(aField.name, fieldControl);
            }
        }

        //add the mds-Control
        this.form.addControl("dg-mds-"+this.section.name, this.mdsTableControl);
        this.mdsTableControl.patchValue(this.formatedDataSection);
    }


    /**
     * Sets all columns of MDS-table
     */
    initTableColumns(): void {
        for(let aField of this.fields){
            if (this.section.fields.includes(aField.name) && !this.isHiddenField(aField.name)) {
                let fieldColumn: Column = {
                    display: aField.label,
                    name: aField.name,
                    data: aField.name,
                    searchable: false,
                    sortable: false,
                    fixed: true,
                    cssClasses: ['text-center'],
                };
    
                this.multiDataColumns.push(fieldColumn);
            }
        }

        // Only show the 'Actions'-column in Create- or Edit-Mode
        if (this.mode == CmdbMode.Create || this.mode == CmdbMode.Edit) {
            let actionsColumn: Column = {
                display: 'Actions',
                name: 'actions',
                data: 'actions',
                searchable: false,
                sortable: false,
                fixed: true,
                template: this.actionsTemplate,
                style: { width: '130px' },
                cssClasses: ['text-center']
            };
    
            this.multiDataColumns.push(actionsColumn);
        }
    }


    /**
     * Checks if a Field is a hidden field
     * @param fieldName (string): identifier of the Field which should be checked
     * @returns (boolean): True if it is a hidden field, else False
     */
    isHiddenField(fieldName: string): boolean {
        return (this.section as CmdbMultiDataSection).hidden_fields?.includes(fieldName);
    }


    /**
     * Initialises the 'modalSection' property which will be passed to modal popups
     */
    private initModalSectionData(): void {
        this.modalSection['type'] = this.section.type;
        this.modalSection['name'] = this.section.name;
        this.modalSection['label'] = this.section.label;
        this.modalSection['fields'] = [];

        for (let aSectionFieldName of this.section.fields){
            for(let aField of this.fields) {
                if (aField.name == aSectionFieldName) {
                    this.modalSection['fields'].push(aField);
                    continue;
                }
            }
        }
    }


    /**
     * Sets the values of the formatedDataSection as values for the table
     */
    initTableValuesFromFormatedDataSection(): void {

        for (let aValue of this.formatedDataSection.values) {
            let initialTableData = {}

            initialTableData['dg-multiDataRowIndex'] = aValue.multi_data_id;

            if (this.mode == CmdbMode.View || this.mode == CmdbMode.Edit) {
                for (let aDataSet of aValue.data) {
                    let tmpDict = {};
                    tmpDict[aDataSet.name] = aDataSet.value;

                    initialTableData[aDataSet.name] = this.formatFieldValue(aDataSet.name, tmpDict);

                }
            } else {
                for (let aDataSet of aValue.data) {
                    initialTableData[aDataSet.name] = aDataSet.value;
                }
            }

            this.tableMultiDataValues.push(initialTableData);
        }
        this.setValuesForPagination();
    }


    /**
     * Decides if the add button should be showed above the table
     * @returns (boolean): True if the add button should be showed about the table, else False
     */
    showAddButton(): boolean {
        return this.mode == CmdbMode.Create || this.mode == CmdbMode.Edit;
    }


    /**
     * Only shows the pagination if there are more than 10 entries in the MDS table
     * @returns Boolean if there are more than 10 entries in the MDS table
     */
    showPagination(): boolean {
        return this.tableMultiDataValues.length > 10;
    }


    calculateCurrentPage(action: string = ""): void {
        if (action == "create") {
            let maxPageSize = Math.ceil(this.tableMultiDataValues.length / 10);
            
            if( this.currentPage < maxPageSize) {
                this.currentPage = maxPageSize;
                this.setValuesForPagination();
            }
        }

        if (action == "delete") {
            let maxPageSize = Math.floor(this.tableMultiDataValues.length / 10);

            if (this.currentPage > maxPageSize) {
                this.currentPage = maxPageSize;
                this.setValuesForPagination();
            } 
        }
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                   EVENT HANDLING                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Opens empty popup form to create a now table row
     */
    public onAddRowClicked(): void{
        this.resetModalValues();
        this.modalRef = this.modalService.open(PreviewModalComponent, { scrollable: true, size: 'lg' });
        this.modalRef.componentInstance.sections = [this.modalSection];
        this.modalRef.componentInstance.saveValues = true;

        this.modalRef.result.then((values: any) => {
            if (values){
                this.addNewValuesToControl(values);

                values = this.formatNewValuesForTable(values);
                values['dg-multiDataRowIndex'] = this.getCurrentHighestMultiDataID();

                this.tableMultiDataValues.push(values);
                this.setValuesForPagination();
                this.incrementCurrentMultiDataID();
                this.calculateCurrentPage("create");

                this.form.markAsDirty();
            }
        });
    }


    /**
     * Opens popup to show preview of all values of the MultiDataSet
     * 
     * @param rowIndex (number): multiDataID of MultiDataSet
     */
    public onRowPreview(rowIndex: number): void {
        this.modalRef = this.modalService.open(PreviewModalComponent, { scrollable: true, size: 'lg' });
        this.modalRef.componentInstance.activateViewMode = true;
        this.modalRef.componentInstance.sections = [this.getModalSectionWithRowData(rowIndex)];
    }


    /**
     * Opens popup to edit edit current values of the MultiDataSet
     * 
     * @param rowIndex (number): MultiDataID of MultiDataSet
     */
    public onRowEdit(rowIndex: number): void {
        this.modalRef = this.modalService.open(PreviewModalComponent, { scrollable: true, size: 'lg' });
        this.modalRef.componentInstance.editValues = true;
        this.modalRef.componentInstance.sections = [this.getModalSectionWithRowData(rowIndex)];

        this.modalRef.result.then((values: any) => {
            if (values){
                this.updateNewValues(values, rowIndex);
                this.form.markAsDirty();
            }
        });
    }


    /**
     * Opens popup to confim deletion of a MultiDataSet
     * 
     * @param rowIndex (number): MultiDataID of MultiDataSet
     */
    public onRowDelete(rowIndex: number): void {
        this.modalRef = this.modalService.open(DeleteEntryModalComponent);

        this.modalRef.result.then((deleteConfirm: boolean) => {
            if(deleteConfirm){
                this.removeDataSet(rowIndex);
                this.calculateCurrentPage("delete");
                this.form.markAsDirty();
            }
        });
    }


    /**
     * Called when the page is changed and emits the new page
     * @param newPage (number): the new page
     */
    public onPageChange(newPage: number) {
        this.currentPage = newPage;
        this.setValuesForPagination();
    }

/* ------------------------------------------- ADD NEW TABLE ENTRY HELPER ------------------------------------------- */

    /**
     * Resets all values of property 'modalSection' so the 'create'-popup is empty
     */
    resetModalValues(): void {
        for (let aField of this.modalSection.fields) {
            if("value" in aField){
                delete aField["value"];
            }
        }
    }


    /**
     * Adds the new values to control
     * 
     * @param newValues the new values
     */
    private addNewValuesToControl(newValues: any){
        let newDataSet: MultiDataSectionSet = {
            "multi_data_id": this.getCurrentHighestMultiDataID(),
            "data": []
        }

        for (let fieldID in newValues) {
            let dataElement: MultiDataSectionFieldValue = {
                "name": fieldID,
                "value": newValues[fieldID]
            }

            newDataSet.data.push(dataElement);
        }

        this.formatedDataSection.values.push(newDataSet);
        this.mdsTableControl.patchValue(this.formatedDataSection);
    }


    /**
     * Formats the new values for table by replacing some values with the corresponding labels or summary lines
     * 
     * @param newValues the new values
     * @return the formatted values
     */
    private formatNewValuesForTable(newValues: any) {
        for (let fieldID in newValues) {
            let formattedValue = this.formatFieldValue(fieldID, newValues);
            newValues[fieldID] = formattedValue;
        }

        return newValues;
    }


    /**
     * Sets the values according to pagination
     */
    setValuesForPagination() {
        //Case: there are less then 10 elements
        if(this.tableMultiDataValues.length < this.pageSizeLimit) {
            this.currentMultiDataValues = this.tableMultiDataValues;
        } else { //Case: there are more then 10 elements
            if(this.currentPage == 1) {
                //Just take the first 10 elements
                this.currentMultiDataValues = this.tableMultiDataValues.slice(0, this.pageSizeLimit);
            } else {
                // calculate the 10 elements of the page (example for page 2)
                let pageLowerLimit = (this.currentPage -1) * this.pageSizeLimit; //E: (2-1) * 10 = 10
                let pageUpperLimit = this.currentPage * this.pageSizeLimit; //E: 2 * 10 = 20

                // If the pageUpperlimit is more than the total number of elements, then set it to total number of elements
                if (pageUpperLimit > this.tableMultiDataValues.length) {
                    pageUpperLimit = this.tableMultiDataValues.length;
                }

                this.currentMultiDataValues = this.tableMultiDataValues.slice(pageLowerLimit, pageUpperLimit);
            }
        }
    }


    /**
     * 
     * @param fieldID 
     * @param newValues 
     * @returns 
     */
    private formatFieldValue(fieldID: string, newValues:any){
        let fieldType = this.getTypeOfField(fieldID);

        switch (fieldType) {
            // case "date": {
            //     console.log("Formatting date for field:", fieldID);
            //     if(newValues[fieldID]) {
            //         const newDate = new Date(newValues[fieldID]["$date"]);

            //         const year = newDate.getFullYear();
            //         const month = (newDate.getMonth() + 1).toString().padStart(2, '0');
            //         const day = newDate.getDate().toString().padStart(2, '0');

            //         return `${year}-${month}-${day}`;
            //     }
            //     break;
            // }

            case "date": {
                if (newValues[fieldID]) {
                    let date: Date;
                    
                    // Handle MongoDB date format
                    if (newValues[fieldID].$date) {
                        date = new Date(newValues[fieldID].$date);
                    }
                    // Handle string dates
                    else if (typeof newValues[fieldID] === 'string') {
                        date = new Date(newValues[fieldID]);
                    }
                    // Handle Date objects
                    else if (newValues[fieldID] instanceof Date) {
                        date = newValues[fieldID];
                    }
                    else {
                        return newValues[fieldID];
                    }
    
                    // Validate date and format
                    if (!isNaN(date.getTime())) {
                        const year = date.getFullYear();
                        const month = String(date.getMonth() + 1).padStart(2, '0');
                        const day = String(date.getDate()).padStart(2, '0');
                        return `${year}-${month}-${day}`;
                    }
                }
                break;
            }
            case "select": {
                if (newValues[fieldID]) {
                    return this.getOptionLabel(fieldID, newValues[fieldID]);
                }
                break;
            }
            case "radio": {
                if (newValues[fieldID]) {
                    return this.getOptionLabel(fieldID, newValues[fieldID]);
                }
                break;
            }
            case "ref": {
                if (newValues[fieldID] && this.refTypesSummaries) {
                    return this.refTypesSummaries[newValues[fieldID]];
                }
                break;
            }
        }

        return  newValues[fieldID];
    }


    /**
     * Retrives the field_type of the field with the given fieldName
     * 
     * @param fieldName (string): name of the field
     * @returns (string): type of the field
     */
    private getTypeOfField(fieldName: string): string {
        let fieldType = "text";

        for (let aField of this.getAllFieldsOfType()) {
            if (aField["name"] == fieldName) {
                fieldType = aField["type"];
                break;
            }
        }

        return fieldType;
    }


    /**
     * Retrives all fields of the objects Type
     * 
     * @returns all fields of the objects Type
     */
    private getAllFieldsOfType() {
        let typeFields: any;

        if(this.typeInstance) {
            typeFields = this.typeInstance.fields;
        }
        else {
            typeFields = this.renderResult.fields;
        }

        return typeFields;
    }


    /**
     * Retrives the option label for an option value
     * 
     * @param fieldName name of the field
     * @param value the option value of the field
     * @returns 
     */
    private getOptionLabel(fieldName: string, value: string) {
        let fieldOptions = this.getField(fieldName)["options"];

        for (let option of fieldOptions) {
            if ( option["name"] == value) {
                return option["label"];
            }
        }

        return undefined;
    }


    /**
     * Retrives field information for a field with the given fieldName
     * 
     * @param fieldName name of the target field
     * @returns Dict with the field information
     */
    private getField(fieldName: string) {
        let targetField = {};

        for (let aField of this.getAllFieldsOfType()) {
            if (aField["name"] == fieldName) {
                targetField = aField;
                break;
            }
        }

        return targetField;
    }


    /**
     * Retrieves the current highest ID for a MultiDataSet
     * 
     * @returns (number): the current highest ID for a MultiDataSet
     */
    getCurrentHighestMultiDataID(): number {
        return this.formatedDataSection.highest_id;
    }


    /**
     * Incrementy the current highest ID for MultiDataSets
     */
    incrementCurrentMultiDataID(): void {
        this.formatedDataSection.highest_id += 1;
    }

/* ------------------------------------------- VIEW/EDIT TABLE ROW HELPER ------------------------------------------- */

    /**
     * Retrieves the modalSection filled with row data
     * @param multiDataID multiDataID of the row 
     * @returns modalSection with row data
     */
    getModalSectionWithRowData(multiDataID: number){
        let modalSectionWithValues = {...this.modalSection};

        let dataSet = this.getDataSet(multiDataID);

        for (let entry of dataSet){
            for(let aField of modalSectionWithValues.fields){
                if (entry.name == aField.name) {
                    aField['value'] = entry.value;
                    break;
                }
            }
        }

        return modalSectionWithValues;
    }


    /**
     * Retrieves the data of a table row from the formatedDataSection
     * 
     * @param multiDataID (number): multiDataID of the target row
     * @returns dict with the data of the row
     */
    getDataSet(multiDataID: number) {
        return  this.formatedDataSection.values.filter((dataSet) => dataSet.multi_data_id == multiDataID)[0].data;
    }


    /**
     * Updates the new values 
     * @param newValues 
     * @param multiDataID 
     */
    private updateNewValues(newValues: any, multiDataID: number) {
        // Update the formatedDataSection
        for (let aDataSet of this.formatedDataSection.values) {
            if (aDataSet.multi_data_id == multiDataID){
                for(let aField of aDataSet.data){
                    aField.value = newValues[aField.name];
                }
                break;
            } 
        }

        // Update the form control values
        this.mdsTableControl.patchValue(this.formatedDataSection);

        // Update the tableMultiDataValues
        for(let tableMultiDataEntry of this.tableMultiDataValues) {
            if (tableMultiDataEntry['dg-multiDataRowIndex'] == multiDataID) {
                for (let key in newValues) {
                    let tmpDict = {};
                    tmpDict[key] = newValues[key];
                    tableMultiDataEntry[key] = this.formatFieldValue(key, tmpDict);
                }
            }
        }
        this.setValuesForPagination();



        this.updateRequired = true;
        setTimeout(() => {
            this.updateRequired = false
        }, 0);
    }

/* --------------------------------------------- DELETE TABLE ROW HELPER -------------------------------------------- */

    /**
     * Removes a MultiDataSet with the given multiDataID from the table, formattedDataSection and table control
     * 
     * @param multiDataID (number): multiDataID of MultiDataSet
     */
    removeDataSet(multiDataID: number): void {
        // Remove dataSet from table values
        this.tableMultiDataValues = this.tableMultiDataValues.filter((rowData) => rowData['dg-multiDataRowIndex'] != multiDataID);
        this.setValuesForPagination();

        //Remove dataSet from formatedDataSection and table control
        this.formatedDataSection.values = this.formatedDataSection.values.filter(
            (dataSet) => dataSet.multi_data_id != multiDataID
          );

        this.mdsTableControl.patchValue(this.formatedDataSection);
    }
}
