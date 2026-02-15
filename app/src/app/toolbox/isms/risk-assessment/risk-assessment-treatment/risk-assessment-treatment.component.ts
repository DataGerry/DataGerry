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
import {
  Component, Input, OnInit, OnChanges, SimpleChanges,
  ViewChild
} from '@angular/core';
import { FormGroup } from '@angular/forms';
import { RaCmAssignmentInlineComponent } from './ control-measure-assignment-inline/ra-cm-assignment-inline.component';

@Component({
    selector: 'app-risk-assessment-treatment',
    templateUrl: './risk-assessment-treatment.component.html',
    styleUrls: ['./risk-assessment-treatment.component.scss'],
    standalone: false
})
export class RiskAssessmentTreatmentComponent implements OnInit, OnChanges {

  @ViewChild('cmInline', { static:false })
  readonly cmInline!: RaCmAssignmentInlineComponent;
  


  /* ─────────── inputs from parent RA component ─────────── */
  @Input({ required:true }) parentForm!: FormGroup;
  @Input() allPersons:            any[] = [];
  @Input() allPersonGroups:       any[] = [];
  @Input() implementationStates:  any[] = [];
  @Input() riskAssessmentId?: number;

  /* NEW: full list of control / measures comes from RA-Add component */
  @Input() allControlMeasures:    { public_id:number; title:string }[] = [];

  /** hide add / edit / delete when not in create-mode */
  @Input() createMode = true;

  

  /* ─────────── responsible-person helper list ─────────── */
  responsiblePersonOptions: any[] = [];

  /* ─────────── tiny helpers kept from your original code ─────────── */
  riskTreatmentOptions = [
    { label:'Avoid',          value:'AVOID' },
    { label:'Accept',         value:'ACCEPT' },
    { label:'Reduce',         value:'REDUCE' },
    { label:'Transfer/Share', value:'TRANSFER_SHARE' }
  ];
  priorityOptions = [
    { label:'Low', value:1 }, { label:'Medium', value:2 },
    { label:'High', value:3 }, { label:'Very High', value:4 }
  ];

  /* ─────────────────── life-cycle ─────────────────── */
  ngOnInit(): void { this.buildRespOptions(); }

  ngOnChanges(ch: SimpleChanges): void {
    if (ch['allPersons'] || ch['allPersonGroups']) { this.buildRespOptions(); }
  }

  /* ─────────────────── helpers unchanged ─────────────────── */
  private buildRespOptions(): void {
    this.responsiblePersonOptions = [
      ...this.allPersonGroups.map(pg => ({
        public_id: pg?.public_id, display_name: pg?.name,
        group:'Person groups', type:'PERSON_GROUP'
      })),
      ...this.allPersons.map(p => ({
        public_id: p?.public_id, display_name: p?.display_name,
        group:'Persons', type:'PERSON'
      }))
    ];
  }

  onOwnerSelected(item:any):void{
    if (item){
      this.parentForm?.patchValue(
        { responsible_persons_id_ref_type:item?.type },
        { emitEvent:false }
      );
    }
  }

  onPrioritySelected(item:any):void{
    if (item){
      this.parentForm.patchValue(
        { priority:item.value },
        { emitEvent:false }
      );
    }
  }


  buildAssignmentsPayload() {
    return this.cmInline?.buildAssignmentsPayload();
  }


  /** called by the parent once the initial CMA list has been downloaded */
public markInlineSnapshot(): void {
  this.cmInline?.markSnapshot();
}


 setInlineToEditMode(): void {
    if (!this.cmInline) { return; }
    //  this.cmInline.createMode = false;        // switch off “create” mode
     this.cmInline?.refreshSnapshot();         // take a pristine snapshot
   }


  /** Called by parent to recalc “availableControlMeasures” inside inline */
  public updateInlineAvailableCMs(currentId?: number): void {
    this.cmInline?.updateAvailableControlMeasures(currentId);
  }

}
