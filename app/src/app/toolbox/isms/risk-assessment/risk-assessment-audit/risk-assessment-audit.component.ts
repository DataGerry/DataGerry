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
import { Component, Input, SimpleChanges } from '@angular/core';
import { FormGroup } from '@angular/forms';

@Component({
    selector: 'app-risk-assessment-audit',
    templateUrl: './risk-assessment-audit.component.html',
    styleUrls: ['./risk-assessment-audit.component.scss'],
    standalone: false
})
export class RiskAssessmentAuditComponent {
  @Input() parentForm!: FormGroup;
  @Input() allPersons: any[] = [];
  @Input() allPersonGroups: any[] = [];

  auditorOptions: any[] = [];

  public personRefTypes = [
    { label: 'Person', value: 'PERSON' },
    { label: 'Person Group', value: 'PERSON_GROUP' }
  ];

    ngOnChanges(ch: SimpleChanges): void {
      if (ch['allPersons'] || ch['allPersonGroups']) {
        this.auditorOptions = [
          ...this.allPersonGroups.map(pg => ({
            public_id   : pg.public_id,
            display_name: pg.name,
            group       : 'Person groups',
            type        : 'PERSON_GROUP'
          })),
          ...this.allPersons.map(p => ({
            public_id   : p.public_id,
            display_name: p.display_name,
            group       : 'Persons',
            type        : 'PERSON'
          }))
        ];
      }
    }
  
    
    onAuditorSelected(item: any): void {
      if (!item) return;
    
      this.parentForm.patchValue({
        auditor_id_ref_type : item.type   // PERSON / PERSON_GROUP
      }, { emitEvent: false });
      
    }
}
