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
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  ViewEncapsulation
} from '@angular/core';
import {
  ControlContainer,
  FormArray,
  FormControl,
  FormGroup,
  FormGroupDirective
} from '@angular/forms';
import { CdkDragDrop } from '@angular/cdk/drag-drop';
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
  viewProviders: [{ provide: ControlContainer, useExisting: FormGroupDirective }],
  encapsulation: ViewEncapsulation.None,
  host: { '[formGroup]': 'row.form' }
})
export class AiSectionSelectorComponent implements OnInit, OnDestroy {
  @Input({ required: true }) row!: SectionRow;
  @Input({ required: true }) rowIndex!: number;

  /** guards from parent */
  @Input() sectionUncheckDisabled = false;
  @Input() totalSelectedFields = 1;

  /** label helpers */
  @Input({ required: true }) fieldLabel!: (fieldName: string) => string;
  @Input({ required: true }) fieldKind!: (fieldName: string) => string;

  /** selected sets (to reflect state for Summary & CI) */
  @Input() summarySelected!: Set<string>;
  @Input() ciExplorerLabel: string | null = null;

  /** outputs to parent */
  @Output() selectAll = new EventEmitter<boolean>();
  @Output() dropFieldReorder = new EventEmitter<CdkDragDrop<string[]>>();
  @Output() summaryToggle = new EventEmitter<{ fieldName: string; checked: boolean }>();
  @Output() pickCiExplorer = new EventEmitter<string>();

  /** UI state */
  editMode = false;
  collapsed = true;

  private includeSub?: Subscription;

  // trackBy for visible list
  trackByIdx = (i: number) => i;

  ngOnInit(): void {
    const includeCtrl = this.row.form.get('includeSection') as FormControl<boolean> | null;
    if (!includeCtrl) return;
    this.includeSub = includeCtrl.valueChanges.subscribe((isOn: boolean) => {
      if (isOn) return;
      // turning section off → uncheck all fields silently
      const fa = this.fieldChecks();
      if (!fa) return;
      fa.controls.forEach(ctrl => ctrl.setValue(false, { emitEvent: false }));
    });
  }
  ngOnDestroy(): void {
    this.includeSub?.unsubscribe();
  }

  /** form shortcuts */
  fieldChecks(): FormArray<FormControl<boolean>> {
    return this.row.form.get('fieldChecks') as FormArray<FormControl<boolean>>;
  }
  fieldLabels(): FormArray<FormControl<string>> {
    return this.row.form.get('fieldLabels') as FormArray<FormControl<string>>;
  }
  get includeSectionCtrl(): FormControl<boolean> {
    return this.row.form.get('includeSection') as FormControl<boolean>;
  }
  get sectionLabelCtrl(): FormControl<string> {
    return this.row.form.get('sectionLabel') as FormControl<string>;
  }
  get filterCtrl(): FormControl<string> {
    return this.row.form.get('filter') as FormControl<string>;
  }

  /** disable a field control? (global guard) */
  disableField(fi: number): boolean {
    const sectionOn = !!this.row.form.value.includeSection;
    const current = (this.row.form.value.fieldChecks as boolean[])[fi];
    if (!sectionOn) return true;
    if (!current) return false;
    return this.totalSelectedFields <= 1;
  }

  /** list of visible indexes after local filter */
  visibleFieldIndexes(): number[] {
    const query = (this.filterCtrl.value || '').toLowerCase().trim();
    const names = this.row.meta.fields || [];
    if (!query) return names.map((_, i) => i);
    return names
      .map((fname, i) => ({ i, label: this.fieldLabel(fname), kind: this.fieldKind(fname) }))
      .filter(x =>
        x.label.toLowerCase().includes(query) ||
        x.kind.toLowerCase().includes(query) ||
        (this.row.meta.fields![x.i] || '').toLowerCase().includes(query)
      )
      .map(x => x.i);
  }

  /** DnD from template */
  onDropFields(event: CdkDragDrop<string[]>) {
    this.dropFieldReorder.emit(event);
  }

  toggleEditMode() { this.editMode = !this.editMode; }
  toggleCollapse() { this.collapsed = !this.collapsed; }

  /** pretty counters */
  selectedCount(): number {
    const arr = (this.row.form.value.fieldChecks as boolean[]) || [];
    return arr.filter(Boolean).length;
  }
  totalCount(): number {
    return this.row.meta.fields?.length || 0;
  }


  resetFieldLabel(idx: number): void {
    const fname = this.row.meta.fields![idx];
    const original = this.fieldLabel(fname); // from cache (parent)
    this.fieldLabels().at(idx).setValue(original);
  }

  /** helpers to reflect Summary/CI selection */
  isSummaryChecked(fname: string): boolean {
    return this.summarySelected?.has?.(fname) ?? false;
  }
  isCiChecked(fname: string): boolean {
    return this.ciExplorerLabel === fname;
  }

  get sectionActive(): boolean {
    return this.includeSectionCtrl.value;
  }
}
