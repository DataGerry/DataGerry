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
import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { UntypedFormArray, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { ReplaySubject, Subscription } from 'rxjs';

import { CategoryService, checkCategoryExistsValidator } from '../../services/category.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { CmdbMode } from '../../modes.enum';
import { CmdbCategory } from '../../models/cmdb-category';
import { CmdbType } from '../../models/cmdb-type';
import { DndDropEvent, DropEffect } from 'ngx-drag-drop';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { takeUntil } from 'rxjs/operators';
import { APIGetMultiResponse } from '../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
  selector: 'cmdb-category-form',
  templateUrl: './category-form.component.html',
  styleUrls: ['./category-form.component.scss']
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

  public effect: DropEffect = 'move';
  public readonly fallBackIcon = 'far fa-folder-open';

/* --------------------------------------------------- LIFE CYLCLE -------------------------------------------------- */
    public constructor(private categoryService: CategoryService,
                       private toast: ToastService,
                       private route:ActivatedRoute) {

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
                (err) => this.toast.error(err)).add(() => this.categoriesLoading = false);
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


    public clickRemoveAssignedType(item: CmdbType): void {
        const index: number = this.assignedTypes.indexOf(item);

        this.assignedTypes.splice(index, 1);
        this.unAssignedTypes.push(item);
        this.types.removeAt(index);
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
    }


    public onDragged(item: CmdbType, list: any[], effect: DropEffect, control: boolean = false) {
        if (effect === 'move') {
            const index = list.indexOf(item);
            list.splice(index, 1);

            if (control) {
                this.types.removeAt(index);
            }
        }
    }


    public onIconSelect(value: string): void {
        this.icon.setValue(value);
    }


    public onSubmit(): void {
        this.categoryForm.markAllAsTouched();

        if (this.categoryForm.valid) {
            this.$category = Object.assign(this.$category, this.categoryForm.getRawValue() as CmdbCategory);
            this.submitEmitter.emit(this.$category);
        }
    }

/* --------------------------------------------------- API SECTION -------------------------------------------------- */

    private loadCategoriesFromAPI() {
        this.categoriesLoading = true;

        this.categoryService.getCategories(this.categoryParams).pipe(takeUntil(this.subscriber))
        .subscribe((apiResponse: APIGetMultiResponse<CmdbCategory>) => {
            this.categories = this.categories.concat(apiResponse.results as Array<CmdbCategory>);
            this.categoriesLoading = false;
            },
            (err) => this.toast.error(err)).add(() => this.categoriesLoading = false);
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

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    public findAssignedTypeByIndex(idx: number): CmdbType | undefined {
        return this.assignedTypes[this.assignedTypes.findIndex(x => x.public_id === idx)];
    }
}
