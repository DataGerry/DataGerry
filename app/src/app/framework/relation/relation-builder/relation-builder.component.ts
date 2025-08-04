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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { finalize, Observable, ReplaySubject, Subscription } from 'rxjs';

import { ToastService } from '../../../layout/toast/toast.service';

import { CmdbMode } from '../../modes.enum';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbRelation } from '../../models/relation.model';
import { RelationService } from '../../services/relaion.service';
import { ValidationService } from '../../type/services/validation.service';

@Component({
  selector: 'cmdb-relation-builder',
  templateUrl: './relation-builder.component.html',
  styleUrls: ['./relation-builder.component.scss']
})
export class RelationBuilderComponent implements OnInit, OnDestroy {
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  private subscriptions = new Subscription();

  @Input() public relationInstance: CmdbRelation;
  @Input() public mode: CmdbMode = CmdbMode.Create;
  @Input() public stepIndex: number = 0;
  public modes = CmdbMode;

  public relations: CmdbRelation[] = [];

  public types: any[] = []; 
  public isSectionHighlighted: boolean = false;
  public isFieldHighlighted: boolean = false;
  public disableFields: boolean = false;
  public isSectionWithoutFields: boolean = false;

  public basicValid: boolean = true;
  public contentValid: boolean = true;
  public metaValid: boolean = true;
  public accessValid: boolean = true;

  public isValid$: Observable<boolean>;
  public isSectionValid$: Observable<boolean>;

  public isLoading$ = this.loaderService.isLoading$;
  public readonly isEditMode = this.route.snapshot.routeConfig?.path?.startsWith('edit') ?? false;

  constructor(
    private router: Router,
    private relationService: RelationService,
    private toast: ToastService,
    private validationService: ValidationService,
    private loaderService: LoaderService,
    private route: ActivatedRoute
  ) { 
    if(this.isEditMode){
      this.mode = CmdbMode.Edit
    }

  }

  ngOnInit(): void {

    // Setup validation state subscriptions
    this.validationService.isSectionHighlighted$.subscribe((highlighted) => {
      setTimeout(() => this.isSectionHighlighted = highlighted);
    });

    this.validationService.isFieldHighlighted$.subscribe((highlighted) => {
      setTimeout(() => this.isFieldHighlighted = highlighted);
    });

    this.validationService.disableFields$.subscribe((disable) => {
      setTimeout(() => this.disableFields = disable);
    });

    this.validationService.isSectionWithoutField$.subscribe((disabledSection) => {
      setTimeout(() => this.isSectionWithoutFields = disabledSection);
    });

    this.isValid$ = this.validationService.getIsValid();
    this.isSectionValid$ = this.validationService.overallSectionValidity();


    // If creating new
    if (this.mode === CmdbMode.Create) {
      this.relationInstance = new CmdbRelation();
    }
  }

  ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
    this.subscriptions?.unsubscribe();
  }



  private formatSections(sections: any[]): any[] {
    return sections.map(section => ({
      type: section.type,
      name: section.name,
      label: section.label,
      fields: section.fields.map(field => field.name)
    }));
  }


  saveRelation(): void {
    if (!this.basicValid || !this.contentValid || this.isSectionHighlighted || this.isFieldHighlighted || this.disableFields || !this.isSectionWithoutFields) {
      this.toast.error('Mandatory fields are missing. Please complete all required fields.');
      return;
  }



    const formattedInstance: CmdbRelation = {
      ...this.relationInstance,
      relation_name: this.relationInstance.relation_name,

      parent_type_ids: this.relationInstance.parent_type_ids,
      child_type_ids: this.relationInstance.child_type_ids,

      description: this.relationInstance.description || '',
      sections: this.formatSections(this.relationInstance.sections),
      fields: this.relationInstance.fields || []
    };

    if (this.mode === CmdbMode.Create) {
      this.loaderService.show();
      this.relationService.postRelation(formattedInstance)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (createdRelation: CmdbRelation) => {
            this.toast.success(`Relation created with ID: ${createdRelation.public_id}`);
            this.router.navigate(['/framework/relation'], { queryParams: { created: createdRelation.public_id } });
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    } else {
      this.loaderService.show();
      this.relationService.putRelation(formattedInstance)
        .pipe(finalize(() => this.loaderService.hide()))
        .subscribe({
          next: (updated: CmdbRelation) => {
            this.toast.success(`Relation updated (ID: ${updated.public_id})`);
            this.router.navigate(['/framework/relation'], { queryParams: { edited: updated.public_id } });
          },
          error: (err) => {
            this.toast.error(err?.error?.message);
          }
        });
    }
  }
}