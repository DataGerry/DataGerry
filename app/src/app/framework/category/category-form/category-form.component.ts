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
import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { ReplaySubject, Subscription } from 'rxjs';

import { CategoryService, checkCategoryExistsValidator } from '../../services/category.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { CmdbMode } from '../../modes.enum';
import { CmdbCategory } from '../../models/cmdb-category';
import { CmdbType } from '../../models/cmdb-type';
import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { WizardComponent } from '@rg-software/angular-archwizard';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../../services/models/api-response';

/**
 * Font awesome classes are the only accepted icon values, so anything with
 * unexpected characters falls back to the default folder icon.
 */
const ICON_CLASS_PATTERN = /^[a-z0-9\s-]+$/i;
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-category-form',
    templateUrl: './category-form.component.html',
    styleUrls: ['./category-form.component.scss'],
    standalone: false
})
export class CategoryFormComponent implements OnInit, OnChanges, OnDestroy {

  /**
   * Modification mode for the form and validation.
   * Default is always: CREATE
   */
  @Input() public mode: CmdbMode = CmdbMode.Create;
  /**
   * Preset data from existing category.
   * Will be ignored if mode is CREATE.
   */
  @Input() public category: CmdbCategory;

  @Input() public unAssignedTypes: CmdbType[] = [];

  @Input()
  public set assignedTypes(value: CmdbType[]) {
    this.tempAssignedTypes = value;
  }

  /**
   * Event call if form is valid and submit button was pressed.
   * Data will be a category instance.
   */
  @Output() public submitEmitter: EventEmitter<CmdbCategory> = new EventEmitter<CmdbCategory>();

  /**
   * Event which will show the current validation status of the form.
   */
  @Output() public validationEmitter: EventEmitter<boolean> = new EventEmitter<boolean>();

  // Inner category holder for assignments
  private $category: CmdbCategory = new CmdbCategory();

  /**
   * Subscription if any value of the form has changed.
   * Triggers the validationEmitter output.
   */
  private valueChangeSubscription: Subscription = new Subscription();

   // Subscription for the complete category list
  private categoryServiceSubscription: Subscription = new Subscription();

  // Complete category list. Will be used to select the parent id.
  public categories: CmdbCategory[] = [];


  // Total number of categories
  public totalCategories: number = 0;

  // Total number of category pages
  public totalCategoriesPages: number = 0;

  public categoryForm: UntypedFormGroup;

  // Categories loading flag
  public categoriesLoading: boolean = false;

  public categoryParams: CollectionParameters = {
    filter: {}, limit: 10, sort: 'public_id', order: 1, page: 1
  };

  public subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  private tempAssignedTypes: CmdbType[] = [];

  public get assignedTypes(): CmdbType[] {
    return this.tempAssignedTypes;
  }

  // Current search term of the unassigned types list
  public typeSearch: string = '';

  // Unassigned types matching the current search term. Rendered instead of the master list.
  public filteredUnassignedTypes: CmdbType[] = [];

  public effect: DropEffect = 'move';
  public readonly fallBackIcon = 'far fa-folder-open';
  public readonly fallBackTypeIcon = 'far fa-clone';

  @ViewChild(WizardComponent) private wizard: WizardComponent;

  // Stable references, so the stepper input is not fed a new array on every change detection run.
  private readonly detailsStepInvalid: readonly number[] = [1];
  private readonly allStepsValid: readonly number[] = [];

/* --------------------------------------------------- LIFE CYLCLE -------------------------------------------------- */
    public constructor(private categoryService: CategoryService,
                       private toast: ToastService,
                       private route:ActivatedRoute,
                       private router: Router) {

        this.categoryForm = new UntypedFormGroup({
            name: new UntypedFormControl('', Validators.required),
            label: new UntypedFormControl(''),
            meta: new UntypedFormGroup({
                icon: new UntypedFormControl(null),
                order: new UntypedFormControl(null)
            }),
            parent: new UntypedFormControl(null),
            types: new UntypedFormArray([])
        });
    }


    public ngOnInit(): void {
        if (CmdbMode.Create === this.mode) {
            this.name.setAsyncValidators(checkCategoryExistsValidator(this.categoryService));
        } else if (CmdbMode.Edit === this.mode) {
            this.name.disable({ onlySelf: true });
            // onlySelf skips the parent update, so the group would keep the required
            // identifier's INVALID status and the wizard could never leave step one.
            this.categoryForm.updateValueAndValidity();
        }

        this.valueChangeSubscription = this.categoryForm.statusChanges.subscribe(() => {
            this.validationEmitter.emit(this.categoryForm.valid);
        });

        this.categoriesLoading = true;

        if(this.mode == CmdbMode.Edit){
            const publicID: number = Number(this.route.snapshot?.params['publicID']);

            if(publicID){
                this.categoryParams['filter'] = {'public_id':{'$ne': publicID}};
            }
        }

        this.categoryService.getCategories(this.categoryParams).pipe(takeUntil(this.subscriber))
            .subscribe((apiResponse: APIGetMultiResponse<CmdbCategory>) => {
                this.categories = apiResponse.results as Array<CmdbCategory>;

                this.totalCategories = apiResponse.total;
                this.totalCategoriesPages = apiResponse.pager.total_pages;
                this.categoriesLoading = false;
                },
                (error) => this.toast.error(error?.error?.message)).add(() => this.categoriesLoading = false);
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes.category !== undefined &&
            changes.category.currentValue !== undefined &&
            (changes.category.previousValue !== changes.category.currentValue)) {
                this.$category = this.category;
                this.categoryForm.patchValue(this.$category);

                for (const type of this.$category.types) {
                    this.types.push(new UntypedFormControl(type));
                }
        }

        // TODO fix wrong order!!!
        if (changes.assignedTypes !== undefined &&
            changes.assignedTypes.currentValue !== undefined &&
            this.$category.types &&
            (changes.assignedTypes.previousValue !== changes.assignedTypes.currentValue)) {
                const buffer: CmdbType[] = [];

                for (const type of this.$category.types) {
                    const assignedType = this.findAssignedTypeByIndex(type);
                    if (assignedType) {
                    buffer.push(assignedType);
                    }
                }

                this.assignedTypes = buffer;
        }

        if (changes.unAssignedTypes !== undefined) {
            this.applyTypeFilter();
        }
    }


    public ngOnDestroy(): void {
        this.valueChangeSubscription?.unsubscribe();
        this.categoryServiceSubscription?.unsubscribe();
        this.submitEmitter?.unsubscribe();
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- EVENT HANDLERS ------------------------------------------------- */

    /**
     * Load more groups until end of list is reached
     */
    public onScrollToEnd() {
        if (this.categoryParams.page < this.totalCategoriesPages) {
            this.categoryParams.page += 1;
            this.loadCategoriesFromAPI();
        }
    }


    public onTypeSearchInput(event: Event): void {
        this.typeSearch = (event.target as HTMLInputElement).value;
        this.applyTypeFilter();
    }


    public clearTypeSearch(): void {
        this.typeSearch = '';
        this.applyTypeFilter();
    }


    /**
     * Click alternative to dragging a type into the category.
     */
    public clickAssignType(item: CmdbType): void {
        const index: number = this.unAssignedTypes.indexOf(item);

        if (index === -1) {
            return;
        }

        this.unAssignedTypes.splice(index, 1);
        this.assignedTypes.push(item);
        this.types.push(new UntypedFormControl(item.public_id));
        this.types.markAsDirty();
        this.applyTypeFilter();
    }


    public clickRemoveAssignedType(item: CmdbType): void {
        const index: number = this.assignedTypes.indexOf(item);

        this.assignedTypes.splice(index, 1);
        this.unAssignedTypes.push(item);
        this.types.removeAt(index);
        this.types.markAsDirty();
        this.applyTypeFilter();
    }


    /**
     * Drop target for types dragged back out of the category. The order of the
     * unassigned pool carries no meaning, so the type is appended.
     */
    public onDropToSource(event: DndDropEvent): void {
        this.unAssignedTypes.push(event.data);
        this.types.markAsDirty();
        this.applyTypeFilter();
    }


    public onDrop(event: DndDropEvent, list?: any[], control: boolean = false) {
        let index = event.index;

        if (typeof index === 'undefined') {
            index = list.length;
        }

        list.splice(index, 0, event.data);

        if (control) {
            this.types.insert(index, new UntypedFormControl(event.data.public_id));
        }

        this.types.markAsDirty();
        this.applyTypeFilter();
    }


    public onDragged(item: CmdbType, list: any[], effect: DropEffect, control: boolean = false) {
        if (effect === 'move') {
            const index = list.indexOf(item);
            list.splice(index, 1);

            if (control) {
                this.types.removeAt(index);
            }

            this.applyTypeFilter();
        }
    }


    public onIconSelect(value: string): void {
        this.icon.setValue(value);
    }


    public onCancel(): void {
        this.router.navigate(['/', 'framework', 'category']);
    }


    public onSubmit(): void {
        this.categoryForm.markAllAsTouched();

        if (!this.categoryForm.valid) {
            return;
        }

        // Enter on the details step continues the wizard instead of saving halfway through.
        if (!this.isOnLastStep) {
            this.wizard.navigation.goToStep(this.wizard, this.wizard.currentStepIndex + 1);
            return;
        }

        this.$category = Object.assign(this.$category, this.categoryForm.getRawValue() as CmdbCategory);
        this.submitEmitter.emit(this.$category);
    }

/* --------------------------------------------------- API SECTION -------------------------------------------------- */

    private loadCategoriesFromAPI() {
        this.categoriesLoading = true;

        this.categoryService.getCategories(this.categoryParams).pipe(takeUntil(this.subscriber))
        .subscribe((apiResponse: APIGetMultiResponse<CmdbCategory>) => {
            this.categories = this.categories.concat(apiResponse.results as Array<CmdbCategory>);
            this.categoriesLoading = false;
            },
            (error) => this.toast.error(error?.error?.message)).add(() => this.categoriesLoading = false);
    }

/* -------------------------------------------------- FORM CONTROL -------------------------------------------------- */

    public get name(): UntypedFormControl {
        return this.categoryForm.get('name') as UntypedFormControl;
    }


    public get label(): UntypedFormControl {
        return this.categoryForm.get('label') as UntypedFormControl;
    }


    public get meta(): UntypedFormGroup {
        return this.categoryForm.get('meta') as UntypedFormGroup;
    }


    public get icon(): UntypedFormControl {
        return this.meta.get('icon') as UntypedFormControl;
    }


    public get parent(): UntypedFormControl {
        return this.categoryForm.get('parent') as UntypedFormControl;
    }


    public get types(): UntypedFormArray {
        return this.categoryForm.get('types') as UntypedFormArray;
    }

/* ---------------------------------------------- TEMPLATE ACCESSORS ------------------------------------------------ */

    public get isEditMode(): boolean {
        return this.mode === CmdbMode.Edit;
    }


    /**
     * Gate for leaving the details step. Reads the group, not the name control,
     * because the identifier is disabled - and therefore never valid - in edit mode.
     */
    public get isDetailsValid(): boolean {
        return this.categoryForm.valid;
    }


    public get invalidSteps(): readonly number[] {
        return this.name.invalid && (this.name.dirty || this.name.touched)
            ? this.detailsStepInvalid
            : this.allStepsValid;
    }


    public get pageTitle(): string {
        if (this.isEditMode) {
            return `Edit category: ${this.category?.label ?? ''}`.trim();
        }

        if (this.mode === CmdbMode.View) {
            return `Category: ${this.category?.label ?? ''}`.trim();
        }

        return 'Add a new category';
    }


    public get saveBlockedHint(): string {
        return this.name.errors?.categoryExists
            ? 'That identifier is already in use.'
            : 'An identifier is required before saving.';
    }


    public get iconPreview(): string {
        return this.safeIcon(this.icon?.value, this.fallBackIcon);
    }


    public get hasUnassignedTypes(): boolean {
        return this.unAssignedTypes?.length > 0;
    }


    public get isTypeSearchActive(): boolean {
        return this.typeSearch.trim().length > 0;
    }


    public typeIcon(type: CmdbType): string {
        return this.safeIcon(type?.render_meta?.icon, this.fallBackTypeIcon);
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public findAssignedTypeByIndex(idx: number): CmdbType | undefined {
        return this.assignedTypes[this.assignedTypes.findIndex(x => x.public_id === idx)];
    }


    /**
     * Recalculates the rendered source list. Called whenever the search term or
     * the master list of unassigned types changes.
     */
    private applyTypeFilter(): void {
        const source: CmdbType[] = this.unAssignedTypes ?? [];
        const term: string = this.typeSearch.trim().toLowerCase();

        this.filteredUnassignedTypes = term
            ? source.filter((type: CmdbType) => this.matchesSearchTerm(type, term))
            : source;
    }


    private matchesSearchTerm(type: CmdbType, term: string): boolean {
        return `${type?.label ?? ''} ${type?.name ?? ''} ${type?.public_id ?? ''}`.toLowerCase().includes(term);
    }


    private get isOnLastStep(): boolean {
        return !this.wizard || this.wizard.currentStepIndex >= this.wizard.wizardSteps.length - 1;
    }


    private safeIcon(value: string, fallback: string): string {
        return value && ICON_CLASS_PATTERN.test(value) ? value : fallback;
    }
}
