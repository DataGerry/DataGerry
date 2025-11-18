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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import {
  FormControl,
  FormGroup,
  Validators
} from '@angular/forms';
import { TypeService } from '../../../services/type.service';
import { ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';
import { RelationBuilderStepComponent } from '../relation-builder-step.component';
import { CmdbRelation } from 'src/app/framework/models/relation.model';
import { LoaderService } from 'src/app/core/services/loader.service';
import { alphanumericValidator } from 'src/app/framework/type/type-builder/type-basic-step/alphanumeric-validator';
import { CmdbMode } from 'src/app/framework/modes.enum';

@Component({
    selector: 'cmdb-relation-basic-step',
    templateUrl: './relation-basic-step.component.html',
    styleUrls: ['./relation-basic-step.component.scss'],
    standalone: false
})
export class RelationBasicStepComponent
  extends RelationBuilderStepComponent
  implements OnInit, OnDestroy {
  @Input() public relationInstance!: CmdbRelation;
  @Input() public mode: CmdbMode;

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /** Main form with all fields, including parent/child icons by chosen names */
  public form: FormGroup;
  public CmdbMode = CmdbMode; 

  /** Separate mini-form for the parent icon */
  public parentIconForm: FormGroup;
  /** Separate mini-form for the child icon */
  public childIconForm: FormGroup;

  public isLoadingTypes = false;
  public availableTypes: any[] = [];
  public isLoading$ = this.loaderService?.isLoading$;

  constructor(private typeService: TypeService, private loaderService: LoaderService) {
    super();

    this.form = new FormGroup({
      relation_name: new FormControl('', {
        validators: [Validators.required, alphanumericValidator()],
        updateOn: 'blur'
      }),
      description: new FormControl(''),

      relation_name_parent: new FormControl('', Validators.required),
      relation_icon_parent: new FormControl('fas fa-link'),
      relation_color_parent: new FormControl(''),

      relation_name_child: new FormControl('', Validators.required),
      relation_icon_child: new FormControl('',),
      relation_color_child: new FormControl(''),

      parent_type_ids: new FormControl<number[]>([], Validators.required),
      child_type_ids: new FormControl<number[]>([], Validators.required)
    });

    // Create two sub–forms, each with a single control named "icon"
    this.parentIconForm = new FormGroup({
      icon: new FormControl('fas fa-link', Validators.required)
    });

    this.childIconForm = new FormGroup({
      icon: new FormControl('fas fa-link', Validators.required)
    });
  }

  // getters for main form
  get relation_name() {
    return this.form.get('relation_name');
  }
  get relation_name_parent() {
    return this.form.get('relation_name_parent');
  }
  get relation_icon_parent() {
    return this.form.get('relation_icon_parent');
  }
  get relation_color_parent() {
    return this.form.get('relation_color_parent');
  }
  get relation_name_child() {
    return this.form.get('relation_name_child');
  }
  get relation_icon_child() {
    return this.form.get('relation_icon_child');
  }
  get relation_color_child() {
    return this.form.get('relation_color_child');
  }
  get description() {
    return this.form.get('description');
  }

  ngOnInit(): void {
    this.loadTypes();
    this.initFormListeners();
    this.emitValidationState();

    // Sync existing relation data
    if (this.relationInstance) {
      this.patchFormValues();
    }

    this.syncIconForms();

  }

  private loadTypes(): void {
    this.loaderService?.show();
    this.isLoadingTypes = true;
    this.typeService
      .getTypes({
        filter: undefined,
        limit: 0,
        sort: 'public_id',
        order: 1,
        page: 1
      })
      .pipe(takeUntil(this.subscriber), finalize(() => this.loaderService?.hide()))
      .subscribe({
        next: resp => {
          this.availableTypes = resp.results || [];
          this.isLoadingTypes = false;
        },
        error: err => {
          // console.error('Failed to load types:', err);
          this.isLoadingTypes = false;
        }
      });
  }

  /**
 * Ensures the validation state is emitted immediately on page load.
 */
  private emitValidationState(): void {
    setTimeout(() => {
      this.validateChange.emit(this.form.valid);
      this.valid = this.form.valid;
    });
  }

  private initFormListeners(): void {
    // Whenever main form values change, push them to the model
    this.form.valueChanges
      .pipe(takeUntil(this.subscriber))
      .subscribe(changes => this.assign(changes));

    // Whenever main form validity changes, notify parent
    this.form.statusChanges
      .pipe(takeUntil(this.subscriber))
      .subscribe(() => {
        this.validateChange.emit(this.form.valid);
        this.valid = this.form.valid;
      });
  }

  private patchFormValues(): void {
    // Patch the main form from the relation instance
    this.form.patchValue(
      {
        relation_name: this.relationInstance.relation_name,
        description: this.relationInstance.description,

        relation_name_parent: this.relationInstance.relation_name_parent,
        relation_icon_parent: this.relationInstance.relation_icon_parent,
        relation_color_parent: this.relationInstance.relation_color_parent,

        relation_name_child: this.relationInstance.relation_name_child,
        relation_icon_child: this.relationInstance.relation_icon_child,
        relation_color_child: this.relationInstance.relation_color_child,

        parent_type_ids: this.relationInstance.parent_type_ids,
        child_type_ids: this.relationInstance.child_type_ids
      },
      { emitEvent: false }
    );

    // Also update the sub–forms for icons:
    this.parentIconForm.patchValue(
      {
        icon: this.relationInstance.relation_icon_parent
      },
      { emitEvent: false }
    );
    this.childIconForm.patchValue(
      {
        icon: this.relationInstance.relation_icon_child
      },
      { emitEvent: false }
    );
  }

  /**
   * Keep parentIconForm in sync with form.get('relation_icon_parent'),
   * and childIconForm in sync with form.get('relation_icon_child').
   */
  private syncIconForms(): void {
    this.parentIconForm
      .get('icon')
      .valueChanges.pipe(takeUntil(this.subscriber))
      .subscribe(newVal => {
        this.relation_icon_parent.setValue(newVal, { emitEvent: false });
        this.relationInstance.relation_icon_parent = newVal;
      });

    this.relation_icon_parent.valueChanges
      .pipe(takeUntil(this.subscriber))
      .subscribe(newVal => {
        this.parentIconForm.get('icon').setValue(newVal, { emitEvent: false });
      });

    this.childIconForm
      .get('icon')
      .valueChanges.pipe(takeUntil(this.subscriber))
      .subscribe(newVal => {
        this.relation_icon_child.setValue(newVal, { emitEvent: false });
        this.relationInstance.relation_icon_child = newVal;
      });

    this.relation_icon_child.valueChanges
      .pipe(takeUntil(this.subscriber))
      .subscribe(newVal => {
        this.childIconForm.get('icon').setValue(newVal, { emitEvent: false });
      });
  }

  /**
   * Write the main form changes back into the relationInstance model
   */
  public assign(changes: Partial<CmdbRelation>): void {
    this.relationInstance.relation_name = changes.relation_name;
    this.relationInstance.description = changes.description;

    this.relationInstance.relation_name_parent = changes.relation_name_parent;
    this.relationInstance.relation_icon_parent = changes.relation_icon_parent;
    this.relationInstance.relation_color_parent = changes.relation_color_parent;

    this.relationInstance.relation_name_child = changes.relation_name_child;
    this.relationInstance.relation_icon_child = changes.relation_icon_child;
    this.relationInstance.relation_color_child = changes.relation_color_child;

    this.relationInstance.parent_type_ids = changes.parent_type_ids;
    this.relationInstance.child_type_ids = changes.child_type_ids;
  }

  ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}