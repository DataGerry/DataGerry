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

import { Component } from '@angular/core';
import { FormGroup, FormControl, ValidatorFn } from '@angular/forms';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-profile-info-modal',
    templateUrl: './profile-info-modal.component.html',
    styleUrls: ['./profile-info-modal.component.scss'],
    standalone: false
})
  export class ProfileInfoModalComponent {
    public selectedBranches :any;
    public profileForm: FormGroup;

    public activeProfiles: Set<string>;


    constructor(public activeModal: NgbActiveModal){
      this.profileForm = new FormGroup({
        },
        this.oneCheckedRequired()
      );
    }


    /**
     * Validator which checks if at least one checkbox is selected
     * 
     * @returns Error or null
     */
    public oneCheckedRequired(): ValidatorFn {
      return function validate(formGroup: FormGroup) {
        let checked = false;

        Object.keys(formGroup.controls).forEach(key => {
          const control = formGroup.controls[key];
    
          if (control.value === true) {
            checked = true;
          }
        });

        if(!checked){
          return { requireOnetoBeChecked: true };
        }
        
        return null;
      };
    }

    /**
     * Creates distict Set of profiles for selected branches
     * 
     * @param selectedBranches The selected branches
     */
    public setProfiles(selectedBranches){
      let tmpActiveProfiles: Set<string> = new Set();

      for (let branchName of Object.keys(selectedBranches)){
        //if branch was selected
        if(selectedBranches[branchName]){
          let tmpBranchProfiles = this.branchProfiles[branchName];

          for(let profile of tmpBranchProfiles){
            tmpActiveProfiles.add(profile);
          }
        }
      }

      this.addControlsForProfiles(tmpActiveProfiles);
      this.activeProfiles = tmpActiveProfiles;
    }


    /**
     * Adds controls to formgroup for each profile
     * 
     * @param tmpActiveProfiles list of profiles 
     */
    private addControlsForProfiles(tmpActiveProfiles){
      for(let profileName of tmpActiveProfiles){
        this.profileForm.addControl(profileName, new FormControl(true));
      }
    }

    /**
     * List of profiles for each branch
     */
    private branchProfiles = {
      'telecommunications-branch': [
          'user-management-profile', 
          'location-profile',
          'ipam-profile',
          'server-management-profile',
          'network-infrastructure-profile'
      ],
      'helpdesk-branch': [
          'user-management-profile',
          'location-profile',
          'client-management-profile',
          'ipam-profile',
          'server-management-profile',
          'network-infrastructure-profile'
      ],
      'service-provider-branch': [
          'user-management-profile',
          'location-profile',
      ],
      'healthcare-branch': [
          'user-management-profile',
          'location-profile',
          'client-management-profile'
    ]
    }

    /**
     * List of names for each Profile
     */
    public branchProfileNames = {
      'user-management-profile': 'User management',
      'location-profile': 'Location',
      'client-management-profile': 'Client management',
      'ipam-profile': 'IPAM',
      'server-management-profile': 'Server management',
      'network-infrastructure-profile': 'Network infrastructure'
    }

  }
