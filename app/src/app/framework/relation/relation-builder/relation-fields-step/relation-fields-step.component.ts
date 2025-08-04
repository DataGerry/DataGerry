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
import { Component, DoCheck, Input, KeyValueDiffer, KeyValueDiffers, OnDestroy, OnInit } from '@angular/core';
import { ReplaySubject } from 'rxjs';

import { CmdbRelation } from '../../../models/relation.model';
import { RelationBuilderStepComponent } from '../relation-builder-step.component';
import { CmdbMode } from 'src/app/framework/modes.enum';

@Component({
  selector: 'cmdb-relation-fields-step',
  templateUrl: './relation-fields-step.component.html',
  styleUrls: ['./relation-fields-step.component.scss']
})
export class RelationFieldsStepComponent extends RelationBuilderStepComponent implements OnInit, DoCheck, OnDestroy {

  @Input() public relationInstance!: CmdbRelation;
  @Input() public mode: CmdbMode;

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  private relationInstanceDiffer: KeyValueDiffer<string, any>;

  public builderValid: boolean = true;
  public CmdbMode = CmdbMode;
  public initialFieldsPresent: boolean = false;

  constructor(
    private differs: KeyValueDiffers,
  ) {
    super();
  }

  public ngOnInit(): void {
    if (this.relationInstance) {
      this.initialFieldsPresent = this.relationInstance.fields.length > 0;
      this.relationInstanceDiffer = this.differs.find(this.relationInstance).create();
    }

  }

  public ngDoCheck(): void {
    if (this.relationInstanceDiffer && this.relationInstance) {
      const changes = this.relationInstanceDiffer.diff(this.relationInstance);
      if (changes) {
        this.valid = this.status;
        this.validateChange.emit(this.valid);
      }
    }
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }

  /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public get status(): boolean {
    const sections = this.relationInstance?.sections || [];
    const allSectionsValid = sections.every(section => section.fields?.length > 0);
    return this.builderValid && (sections.length === 0 || allSectionsValid);
  }
  

  public onBuilderValidChange(status: boolean): void {
    this.builderValid = status;
    this.valid = this.status;
    this.validateChange.emit(this.valid);
  }
}