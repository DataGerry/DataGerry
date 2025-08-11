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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnInit, OnDestroy } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ReportCategoryService } from 'src/app/reporting/services/report-category.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { Observable, ReplaySubject, forkJoin, throwError } from 'rxjs';
import { catchError, finalize, takeUntil, tap } from 'rxjs/operators';
import { ReportService } from 'src/app/reporting/services/report.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { ActivatedRoute, Router } from '@angular/router';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'app-create-report',
    templateUrl: './create-report.component.html',
    styleUrls: ['./create-report.component.scss'],
    standalone: false
})
export class CreateReportComponent implements OnInit, OnDestroy {
    public createReportForm: FormGroup;
    public categories = [];
    public types = [];
    public fields = [];
    public typeLoading = false;
    private unsubscribe$ = new ReplaySubject<void>(1);
    public conditions: any = {};
    public filterBuilderValidation: boolean = true;
    public isEditMode = false;
    public reportId: number;
    public filterBuilderReady = false;

    public mdsModeOptions = [
        { label: 'inside the rows', value: 'ROWS' },
        { label: 'inside the columns', value: 'COLUMNS' }
    ];

    public isLoading$ = this.loaderService.isLoading$;


    /* --------------------------------------------------- LIFECYCLE METHODS -------------------------------------------------- */

    constructor(
        private fb: FormBuilder,
        private categoryService: ReportCategoryService,
        private typeService: TypeService,
        private reportService: ReportService,
        private toast: ToastService,
        private router: Router,
        private route: ActivatedRoute,
        private loaderService: LoaderService
    ) { }

    ngOnInit(): void {
        this.createReportForm = this.fb.group({
            name: ['', [Validators.required, Validators.minLength(3)]],
            category: [null, Validators.required],
            type: [null, Validators.required],
            fields: [[], Validators.required],
            mds_mode: ['ROWS', Validators.required]
        });

        // Load types and categories first
        forkJoin([
            this.loadTypes(),
            this.loadCategories()
        ]).subscribe(() => {
            // After types and categories are loaded, proceed to check if we are in edit mode
            this.route.paramMap.subscribe((params) => {
                const id = params.get('id');
                if (id) {
                    this.isEditMode = true;
                    this.reportId = +id;
                    this.loadReportData(this.reportId);
                }
            });

            // Subscribe to type change and load corresponding fields
            this.createReportForm.get('type').valueChanges
                .pipe(takeUntil(this.unsubscribe$))
                .subscribe((typeId) => {
                    this.loadFieldsForType(typeId);
                    // Clear selected fields when the type changes
                    this.createReportForm.get('fields').setValue([]);
                    this.conditions = {
                        condition: 'and',
                        rules: []
                    };
                    this.filterBuilderReady = false; // Reset filter builder to re-render with new fields
                    setTimeout(() => (this.filterBuilderReady = true), 0);
                });
        });
    }

    ngOnDestroy(): void {
        this.unsubscribe$?.next();
        this.unsubscribe$?.complete();
    }

    /* --------------------------------------------------- LOADING FROM API -------------------------------------------------- */

    /**
     * Loads the categories and updates the categories list.
     * Returns an observable for further actions if needed.
     * @returns An observable of the API response.
     */
    private loadCategories(): Observable<any> {
        const params = { limit: 0, page: 1, sort: 'public_id', order: 1 };
        return this.categoryService.getAllCategories(params).pipe(
            tap((response) => {
                this.categories = response.results;
            }),
            catchError((error) => {
                this.toast.error(error?.error?.message);
                return throwError(() => error);
            })
        );
    }

    /**
     * Loads the types with default parameters and updates the component state.
     * Sets the loading state and returns an observable for further actions.
     * @returns An observable of the API response.
     */
    private loadTypes(): Observable<any> {
        this.loaderService.show();
        this.typeLoading = true;
        const params = { limit: 0, page: 1, sort: 'public_id', order: 1 };
        return this.typeService.getTypes(params).pipe(
            finalize(() => this.loaderService.hide()),
            tap((response) => {
                this.types = response.results;
                this.typeLoading = false;
            }),
            catchError((error) => {
                this.typeLoading = false;
                this.toast.error(error?.error?.message);
                return throwError(() => error);
            })
        );
    }

    /**
     * Loads the fields for the specified type ID and updates the filter builder readiness.
     * Sets the fields array and filterBuilderReady flag based on the selected type.
     * @param typeId - The ID of the type to load fields for.
     */
    private loadFieldsForType(typeId: number): void {
        const selectedType = this.types.find((type) => type.public_id === typeId);
        if (selectedType && selectedType.fields && selectedType.fields.length > 0) {
            this.fields = selectedType.fields;
            this.filterBuilderReady = true;
        } else {
            this.fields = [];
            this.filterBuilderReady = false;
        }
    }

    /**
     * Loads report data for editing.
     * @param id - The ID of the report to load.
     */
    private loadReportData(id: number): void {
        this.loaderService.show();
        this.reportService.getReportById(id).pipe(takeUntil(this.unsubscribe$), finalize(() => this.loaderService.hide()))
        .subscribe({
            next: (report) => {        
                this.createReportForm.patchValue({
                    name: report.name,
                    category: report.report_category_id,
                    type: report.type_id,
                    fields: report.selected_fields,
                    mds_mode: report.mds_mode || 'ROWS'
                });

                // Load fields for the selected type
                this.loadFieldsForType(report.type_id);

                // Set conditions and make filter builder ready
                this.conditions = report.conditions;
                this.filterBuilderReady = true; // Ensure FilterBuilderComponent renders with conditions
            },
            error: (error) => {
                this.toast.error(error?.error?.message);
            }}            
        );
    }

    /* --------------------------------------------------- ACTION METHODS -------------------------------------------------- */

    /**
     * Updates the conditions based on changes from the filter builder component.
     * @param conditions - The new conditions to set.
     */
    onConditionsChange(conditions: any): void {
        // Receive conditions from FilterBuilderComponent
        this.conditions = conditions;
    }

    /**
     * Updates the validation status from the filter builder.
     * @param validation - The validation result to set.
     */
    onFilterBuilderValidation(validation: any): void {
        this.filterBuilderValidation = validation;
    }

    /**
     * Handles form submission, creating or updating a report based on the form data and current mode.
     */
    onSubmit(): void {
        if (this.createReportForm.valid || !this.filterBuilderValidation) {
            this.loaderService.show();
            const formValues = this.createReportForm.value;
            const reportData = {
                public_id: this.reportId,
                report_category_id: formValues.category,
                name: formValues.name,
                type_id: formValues.type,
                selected_fields: formValues.fields,
                conditions: this.conditions,
                report_query: {}, // Empty as required by backend
                predefined: false,
                mds_mode: formValues.mds_mode
            };

            if (this.isEditMode) {
                this.reportService.updateReport(this.reportId, reportData).pipe(finalize(() => this.loaderService.hide())).subscribe({
                    next: () => {
                        this.toast.success('Report updated successfully');
                        this.router.navigate(['/reports/overview']);
                    },
                    error: (error) => {
                        this.toast.error(error?.error?.message);
                    }
                });

            } else {
                delete reportData.public_id;
                this.reportService.createReport(reportData).pipe(finalize(() => this.loaderService.hide())).subscribe({
                    next: (response) => {
                        this.toast.success('Report created successfully');
                        this.router.navigate(['/reports/overview']);
                    },
                    error: (error) => {
                        this.toast.error(error?.error?.message);
                    }
                });
            }
        }
    }

    goBack(): void {
        this.router.navigate(['/reports/overview'])
    }
}
