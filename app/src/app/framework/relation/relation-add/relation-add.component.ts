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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { v4 as uuidv4 } from 'uuid';
import { Component } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { CmdbRelation } from '../../models/relation.model';
import { RelationService } from '../../services/relaion.service';


@Component({
    selector: 'cmdb-relation-add',
    templateUrl: './relation-add.component.html',
    styleUrls: ['./relation-add.component.scss'],
    standalone: false
})
export class RelationAddComponent {
  public relationInstance: CmdbRelation;

  constructor(
    private route: ActivatedRoute,
    private relationService: RelationService,
  ) {
    this.relationInstance = new CmdbRelation();
    
    this.route.queryParams.subscribe((query) => {
      if (query.copy !== undefined) {
        this.relationService.getRelation(query.copy).subscribe((copyRelation: CmdbRelation) => {
          // Remove ID and author details to create a fresh copy
          delete copyRelation.public_id;

          this.relationInstance = this.setNewIDs(copyRelation);
        });
      }
    });
  }

  
  /**
   * Generates new unique IDs for copied sections and fields
   * @param relation - The relation instance to update
   */
  private setNewIDs(relation: CmdbRelation): CmdbRelation {
    for (let sectionIndex in relation.sections) {
      let section = relation.sections[sectionIndex];

      // Generate a new section ID
        section.name = this.generateNewID(section.name);

        for (let fieldIndex in section.fields) {
          let field = section.fields[fieldIndex];

          // Assign a new unique ID to each field
          const newFieldID = this.generateNewID(field.type);
          field.name = newFieldID;
          section.fields[fieldIndex] = newFieldID;
        
      }
    }
    return relation;
  }


  /**
   * Generates a unique ID for sections and fields
   */
  private generateNewID(name: string): string {
    if (name.startsWith('section-')) {
      name = 'section';
    }
    return `${name}-${uuidv4()}`;
  }
}
