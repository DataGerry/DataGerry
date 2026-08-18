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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, DestroyRef, inject } from '@angular/core';
import { FormGroup, FormControl, ValidatorFn } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Profile that is only offered when the IPAM premium feature is licensed. */
const IPAM_PROFILE = 'ipam-profile';

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

    private readonly premiumFeatureService = inject(PremiumFeatureService);
    private readonly destroyRef = inject(DestroyRef);

    /** All profiles derived from the selected branches, before premium gating is applied. */
    private allProfiles: Set<string> = new Set();


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

      this.allProfiles = tmpActiveProfiles;

      // Only Show IPAM in the profile selection if the premium feature is unlocked
      this.premiumFeatureService.isAvailable$(LicenseFeature.Ipam)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((ipamAvailable) => this.applyProfileGate(ipamAvailable));
    }


    /**
     * Rebuilds the visible profiles and their form controls, dropping the IPAM profile when the
     * feature is not licensed so it is neither shown nor submitted to the profile creation call.
     *
     * @param ipamAvailable Whether the IPAM premium feature is currently unlocked
     */
    private applyProfileGate(ipamAvailable: boolean){
      const visibleProfiles: Set<string> = new Set();

      for(const profile of this.allProfiles){
        if(profile === IPAM_PROFILE && !ipamAvailable){
          continue;
        }

        visibleProfiles.add(profile);
      }

      this.syncControls(visibleProfiles);
      this.activeProfiles = visibleProfiles;
    }


    /**
     * Reconciles the form controls with the visible profiles, preserving existing selections while
     * adding controls for newly available profiles and removing those that are no longer offered.
     *
     * @param visibleProfiles Profiles that should have a control
     */
    private syncControls(visibleProfiles: Set<string>){
      for(const controlName of Object.keys(this.profileForm.controls)){
        if(!visibleProfiles.has(controlName)){
          this.profileForm.removeControl(controlName);
        }
      }

      for(const profileName of visibleProfiles){
        if(!this.profileForm.contains(profileName)){
          this.profileForm.addControl(profileName, new FormControl(true));
        }
      }
    }

    /**
     * List of profiles for each branch
     */
    private branchProfiles = {
      'telecommunications-branch': [
          'user-management-profile', 
          'location-profile',
          'rack-profile',
          'ipam-profile',
          'server-management-profile',
          'network-infrastructure-profile'
      ],
      'helpdesk-branch': [
          'user-management-profile',
          'location-profile',
          'rack-profile',
          'client-management-profile',
          'ipam-profile',
          'server-management-profile',
          'network-infrastructure-profile'
      ],
      'service-provider-branch': [
          'user-management-profile',
          'location-profile',
          'rack-profile'
      ],
      'healthcare-branch': [
          'user-management-profile',
          'location-profile',
          'rack-profile',
          'client-management-profile'
    ]
    }

    /**
     * List of names for each Profile
     */
    public branchProfileNames = {
      'user-management-profile': 'User management',
      'location-profile': 'Location',
      'rack-profile': 'Rack View (New Feature)',
      'client-management-profile': 'Client management',
      'ipam-profile': 'IPAM (New Feature)',
      'server-management-profile': 'Server management',
      'network-infrastructure-profile': 'Network infrastructure'
    }

  }
