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
import {
  Component, Input, ViewChild, TemplateRef,
  OnInit, OnChanges, SimpleChanges, inject,
  ChangeDetectionStrategy
} from '@angular/core';
import {
  FormArray, FormGroup, Validators, NonNullableFormBuilder
} from '@angular/forms';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { Column, Sort } from 'src/app/layout/table/table.types';
import { ControlMeasureAssignment } from '../../../models/control‑measure‑assignment.model';


/* ───────── helper types ───────── */
type CmItem = { public_id: number; title: string; identifier: string };
type RespType = 'PERSON' | 'PERSON_GROUP';
interface RespItem {
  public_id: number;
  display_name: string;
  group: string;
  type: RespType;
}

@Component({
    selector: 'ra-cm-assignment-inline',
    templateUrl: './ra-cm-assignment-inline.component.html',
    styleUrls: ['./ra-cm-assignment-inline.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class RaCmAssignmentInlineComponent implements OnInit, OnChanges {

  /* ───────── inbound data ───────── */
  @Input({ required: true }) parentForm!: FormGroup;
  /** When `false`, component runs in *edit / view* context */
  @Input() createMode = true;
  /** Full CM list */
  @Input() allControlMeasures: CmItem[] = [];
  /** Implementation-state list */
  @Input() implementationStates: { public_id: number; value: string }[] = [];
  /** Person / group master data */
  @Input() allPersons: any[] = [];
  @Input() allPersonGroups: any[] = [];
  @Input() riskAssessmentId?: number;


  /* ───────── template refs ───────── */
  @ViewChild('modalTpl', { static: true }) modalTpl!: TemplateRef<any>;
  @ViewChild('cmActionsTpl', { static: true }) cmActionsTpl!: TemplateRef<any>;

  /* ───────── DI ───────── */
  private readonly fb = inject(NonNullableFormBuilder);
  private readonly modal = inject(NgbModal);

  /* ───────── lookup maps ───────── */
  private readonly cmMap = new Map<number, CmItem>();
  private readonly stsMap = new Map<number, string>();

  /* ───────── dropdown helpers ───────── */
  readonly priorityOptions = [
    { label: 'Low', value: 1 }, { label: 'Medium', value: 2 },
    { label: 'High', value: 3 }, { label: 'Very High', value: 4 }
  ];
  responsibleOptions: RespItem[] = [];
  availableControlMeasures: CmItem[] = [];

  /* ───────── modal bookkeeping ───────── */
  private modalRef!: NgbModalRef;
  modalForm!: FormGroup;
  editIndex: number | null | undefined;
  modalMode: 'add' | 'edit' | 'view' = 'add';

  /* ───────── change-tracking (edit-mode) ───────── */
  private originalSnapshot: ControlMeasureAssignment[] = [];

  /* ───────── table helpers ───────── */
  columns!: Column[];
  page = 1;
  pageSize = 5;


  /* ═════════════════════════ lifecycle ═════════════════════════ */
  ngOnInit(): void {
    this.buildMaps();
    this.buildResponsibleOptions();
    this.initColumns();
    this.ensureCmArrayExists();

    /* keep pristine copy for diff-calculation (edit / view only) */
    if (!this.createMode) {
      this.originalSnapshot = structuredClone(this.cmArray?.value) as ControlMeasureAssignment[];
    }

    this.modalForm = this.buildModalForm();           // create once
    this.updateAvailableControlMeasures();

  }


  ngOnChanges(ch: SimpleChanges): void {
    if (ch['allControlMeasures'] && !ch['allControlMeasures'].firstChange) {
      this.buildMaps();
      this.updateAvailableControlMeasures();
    }
  }

  /* ═════════════════════ build-helpers ═════════════════════ */
  private buildMaps(): void {
    this.cmMap?.clear();
    this.allControlMeasures?.forEach(cm => this.cmMap?.set(cm?.public_id, cm));
    this.stsMap?.clear();
    this.implementationStates?.forEach(s => this.stsMap?.set(s?.public_id, s?.value));
  }


  private buildResponsibleOptions(): void {
    const groups: RespItem[] = this.allPersonGroups?.map(pg => ({
      public_id: pg?.public_id, display_name: pg?.name,
      group: 'Groups', type: 'PERSON_GROUP'
    }));
    const persons: RespItem[] = this.allPersons?.map(p => ({
      public_id: p?.public_id, display_name: p?.display_name,
      group: 'Persons', type: 'PERSON'
    }));
    this.responsibleOptions = [...groups, ...persons];
  }


  private getRespType(id: number): RespType {
    return this.responsibleOptions?.find(r => r?.public_id === id)?.type ?? 'PERSON';
  }


  private initColumns(): void {
    this.columns = [
      { display: 'Identifier', name: 'ident', data: 'identifier', sortable: true },
      { display: 'Control Name', name: 'title', data: 'title', sortable: true },
      // { display:'Responsible', name:'resp',  data:'responsibleLabel'               },
      { display: 'Status', name: 'stat', data: 'statusLabel' },
      {
        display: 'Actions', name: 'act', data: 'dummy',
        template: this.cmActionsTpl, fixed: true,
        style: { width: '95px', 'text-align': 'center' }
      }
    ];
  }


  /* ═════════════════════ form-array helpers ═════════════════════ */
  private get cmArray(): FormArray {
    return this.parentForm?.get('control_measure_assignments') as FormArray;
  }


  private ensureCmArrayExists(): void {
    if (!this.parentForm?.get('control_measure_assignments')) {
      this.parentForm?.addControl('control_measure_assignments', this.fb?.array([]));
    }
  }

  /* ═════════════════════ table rows ═════════════════════ */
  get rowsLength(): number { return this.cmArray.length; }
  // get tableRows():any[]{
  //   return this.cmArray.controls.map(ctrl=>{
  //     const v  = ctrl.value as ControlMeasureAssignment;
  //     const cm = this.cmMap.get(v.control_measure_id);
  //     return {
  //       ...v,
  //       identifier      : cm?.identifier ?? `#${v.control_measure_id}`,
  //       title           : cm?.title ?? '',
  //       responsibleLabel: this.responsibleOptions.find(r=>r.public_id===v.responsible_for_implementation_id)?.display_name ?? '',
  //       statusLabel     : this.stsMap.get(v.implementation_status) ?? v.implementation_status
  //     };
  //   });
  // }

  get tableRows(): any[] {
    const allRows = this.cmArray.controls.map(ctrl => {
      const v = ctrl?.value as ControlMeasureAssignment;
      const cm = this.cmMap?.get(v?.control_measure_id);
      return {
        ...v,
        identifier: cm?.identifier ?? `#${v.control_measure_id}`,
        title: cm?.title ?? '',
        responsibleLabel: this.responsibleOptions?.find(r => r?.public_id === v?.responsible_for_implementation_id)?.display_name ?? '',
        statusLabel: this.stsMap.get(v?.implementation_status) ?? v?.implementation_status
      };
    });

    // Slice for pagination
    const startIndex = (this.page - 1) * this.pageSize;
    const endIndex = startIndex + this.pageSize;
    return allRows.slice(startIndex, endIndex);
  }

  onPageChange(p: number) { this.page = p; }
  onSort(_: Sort) { }

  /* ═════════════════════ modal-helpers ═════════════════════ */
  private buildModalForm(seed?: Partial<ControlMeasureAssignment>): FormGroup {
    return this.fb.group({
      control_measure_id: [seed?.control_measure_id ?? null, Validators.required],
      planned_implementation_date: seed?.planned_implementation_date ?? null,
      implementation_status: [seed?.implementation_status ?? null, Validators.required],
      finished_implementation_date: seed?.finished_implementation_date ?? null,
      priority: seed?.priority ?? null,
      responsible_for_implementation_id_ref_type: [seed?.responsible_for_implementation_id_ref_type ?? 'PERSON'],
      responsible_for_implementation_id: [seed?.responsible_for_implementation_id ?? null]
    });
  }


  // public updateAvailableControlMeasures(currentId?: number): void {
  //   const used = new Set<number>();
  //   const controls = this.cmArray.value;

  //   for (let i = 0; i < controls.length; i++) {
  //     used.add(controls[i].control_measure_id);
  //   }

  //   if (currentId != null) {
  //     used.delete(currentId);
  //   }

  //   const filtered: CmItem[] = [];
  //   for (const cm of this.allControlMeasures) {
  //     if (!used.has(cm.public_id)) {
  //       filtered.push(cm);
  //     }
  //   }

  //   filtered.sort((a, b) => a.title.localeCompare(b.title));
  //   this.availableControlMeasures = filtered;
  // }

  public updateAvailableControlMeasures(currentId?: number): void {
    const used = new Set<number>();
    const controls = this.cmArray?.value;
  
    for (let i = 0; i < controls.length; i++) {
      used.add(controls[i]?.control_measure_id);
    }
  
    if (currentId != null) {
      used?.delete(currentId);
    }
  
    const temp: (CmItem & { displayTitle: string })[] = [];
  
    for (const cm of this.allControlMeasures) {
      if (!used?.has(cm?.public_id)) {
        temp.push({
          ...cm,
          displayTitle: `${cm?.identifier} - ${cm?.title}`
        });
      }
    }
  
    // Sort by title
    temp.sort((a, b) => a?.title?.localeCompare(b?.title));
  
    this.availableControlMeasures = temp;
  }
  /* -------- open modal ------- */
  // openModal(idx?:number, mode:'add'|'edit'|'view'='add'):void{
  //   this.modalMode = mode;
  //   this.editIndex = idx ?? null;

  //   const seed = idx!=null ? { ...this.cmArray.at(idx).getRawValue() } : undefined;
  //   this.modalForm.reset();
  //   this.modalForm.patchValue(seed ?? {});
  //   (mode==='view') ? this.modalForm.disable() : this.modalForm.enable();

  //   this.updateAvailableControlMeasures(seed?.control_measure_id);

  //   queueMicrotask(()=>{
  //     this.modalRef = this.modal.open(this.modalTpl,
  //       { size:'lg', centered:true, backdrop:'static', windowClass:'dg-modal' });
  //   });
  // }

  openModal(idx?: number, mode: 'add' | 'edit' | 'view' = 'add'): void {
    this.modalMode = mode;
    this.editIndex = idx ?? null;
    const seed = idx != null ? { ...this.cmArray?.at(idx)?.getRawValue() } : undefined;
    this.modalForm?.reset();
    this.modalForm?.patchValue(seed ?? {});
    mode === 'view' ? this.modalForm?.disable() : this.modalForm?.enable();
  
    // Defer both data update and modal rendering
    setTimeout(() => {
      this.updateAvailableControlMeasures(seed?.control_measure_id);
      this.modalRef = this.modal?.open(this.modalTpl, {
        size: 'lg',
        centered: true,
        backdrop: 'static',
        windowClass: 'dg-modal'
      });
    }, 0);
  }

  /* -------- save ------- */
  saveAssignment(): void {
    if (this.modalForm?.invalid) { return; }

    const val = this.modalForm?.getRawValue();
    val.responsible_for_implementation_id_ref_type =
      this.getRespType(val?.responsible_for_implementation_id);

    if (this.riskAssessmentId) {
      (val as any).risk_assessment_id = this.riskAssessmentId;
    }

    /* prevent duplicates */
    const dup = this.cmArray?.controls?.find((c, i) =>
      c?.value?.control_measure_id === val?.control_measure_id && i !== this.editIndex);
    if (dup) { return; }

    if (this.editIndex != null) {
      this.cmArray?.at(this.editIndex)?.patchValue(val);
    } else {
      /* remove public_id */
      delete (val as any)?.public_id;
      this.cmArray?.push(this.fb?.group(val));
    }
    this.closeModal();
    this.updateAvailableControlMeasures();
  }

  /* -------- close ------- */
  closeModal(): void {
    this.modalRef?.close();
    this.modalMode = 'add';
    this.editIndex = undefined;
    this.modalForm.enable();
  }

  /* -------- row actions ------- */
  onEditRow(r: any) { this.openModal(this.rowIndex(r), 'edit'); }
  onViewRow(r: any) { this.openModal(this.rowIndex(r), 'view'); }
  deleteRow(r: any) {
    const idx = this.rowIndex(r);
    if (idx !== -1) { this.cmArray.removeAt(idx); this.updateAvailableControlMeasures(); }
  }
  private rowIndex(r: any): number {
    return this.cmArray?.controls?.findIndex(c => c?.value?.control_measure_id === r?.control_measure_id);
  }

  /* ═════════════════════ PUBLIC: build payload ═════════════════════ */
  /** Call this from the parent *once* just before saving RA */
  buildAssignmentsPayload(): {
    created: any[],
    updated: any[],
    deleted: number[]
  } {
    const current = this.cmArray?.value as ControlMeasureAssignment[];

    /* helper maps */
    const origById = new Map<number, ControlMeasureAssignment>(
      this.originalSnapshot?.filter(o => o?.public_id != null)
        .map(o => [o.public_id!, o]));
    const curById = new Map<number, ControlMeasureAssignment>(
      current.filter(c => c?.public_id != null).map(c => [c?.public_id!, c]));

    /* created */
    const created = current?.filter(c => c?.public_id == null)
      .map(c => ({ ...c })); // keep shape – NO public_id

    /* updated */
    const updated: ControlMeasureAssignment[] = [];
    curById?.forEach((cur, id) => {
      const orig = origById.get(id);
      if (orig && JSON.stringify(orig) !== JSON.stringify(cur)) {
        updated.push(cur);
      }
    });

    /* deleted */
    const deleted: number[] = [];
    origById?.forEach((_v, id) => {
      if (!curById?.has(id)) { deleted?.push(id); }
    });

    return { created, updated, deleted };
  }

  public markSnapshot(): void {
    this.originalSnapshot = structuredClone(
      this.cmArray?.value
    ) as ControlMeasureAssignment[];
  }

  public refreshSnapshot(): void {
    this.originalSnapshot = structuredClone(this.cmArray?.value) as ControlMeasureAssignment[];
  }
}
