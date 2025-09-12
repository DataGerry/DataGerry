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
import { ChangeDetectionStrategy, Component, Input, OnDestroy, OnInit, ViewEncapsulation } from '@angular/core';
import { ControlContainer, FormArray, FormControl, FormGroup, FormGroupDirective } from '@angular/forms';
import { Subscription } from 'rxjs';

interface SectionMeta {
  name: string;
  label: string;
  fields?: string[];
}

export interface SectionRow {
  form: FormGroup; 
  meta: SectionMeta;
}

@Component({
  selector: 'tr[cmdb-ai-section-selector]',
  templateUrl: './ai-section-selector.component.html',
  styleUrls: ['./ai-section-selector.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false,
  viewProviders: [{ provide: ControlContainer, useExisting: FormGroupDirective }],
  encapsulation: ViewEncapsulation.None,
  host: { '[formGroup]': 'row.form' }
})
export class AiSectionSelectorComponent implements OnInit, OnDestroy {
  @Input({ required: true }) row!: SectionRow;
  @Input({ required: true }) rowIndex!: number;

  /** Guards provided by parent */
  @Input() sectionUncheckDisabled = false;
  @Input() totalSelectedFields = 1;

  /** For labels */
  @Input({ required: true }) fieldLabel!: (fieldName: string) => string;
  @Input({ required: true }) fieldKind!: (fieldName: string) => string;

  /** Keep template tidy */
  fieldChecks(): FormArray<FormControl<boolean>> {
    return this.row.form.get('fieldChecks') as FormArray<FormControl<boolean>>;
  }

  /** Disable a field when:
   * - the section is OFF, or
   * - it's checked and the total selected fields would drop to 0 (global guard)
   */
  disableField(fi: number): boolean {
    const sectionOn = !!this.row.form.value.includeSection;
    const current = (this.row.form.value.fieldChecks as boolean[])[fi];
    if (!sectionOn) return true;
    if (!current) return false;
    return this.totalSelectedFields <= 1; // cannot uncheck the very last field globally
  }

  trackByIdx = (i: number) => i;

  private includeSub?: Subscription;

  ngOnInit(): void {
    const includeCtrl = this.row.form.get('includeSection') as FormControl<boolean> | null;
    if (!includeCtrl) return;
    this.includeSub = includeCtrl.valueChanges.subscribe((isOn: boolean) => {
      if (isOn) return;
      const fa = this.fieldChecks();
      if (!fa) return;
      fa.controls.forEach(ctrl => ctrl.setValue(false, { emitEvent: false }));
    });
  }

  ngOnDestroy(): void {
    this.includeSub?.unsubscribe();
  }


  get includeSectionCtrl(): FormControl<boolean> {
    return this.row.form.get('includeSection') as FormControl<boolean>;
  }
  
}
