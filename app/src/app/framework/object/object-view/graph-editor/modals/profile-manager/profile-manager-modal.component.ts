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
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal, NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { FilterProfile } from '../../interfaces/graph.interfaces';
import { GraphProfileService } from '../../services/graph-profile.service';
import { ProfileDeleteModalComponent } from '../profile-delete/profile-delete-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { CI_EXPLORER_EDIT_RIGHT } from 'src/app/framework/models/ci-explorer.model';

@Component({
    selector: 'app-profile-manager-modal',
    templateUrl: './profile-manager-modal.component.html',
    styleUrls: ['./profile-manager-modal.component.scss'],
    standalone: false
})
export class ProfileManagerModalComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();
  private readonly permissionService = inject(PermissionService);

  /** The modal is opened from code, so it re-checks the right instead of trusting its caller. */
  readonly canEdit = this.permissionService.hasRight(CI_EXPLORER_EDIT_RIGHT)
    || this.permissionService.hasExtendedRight(CI_EXPLORER_EDIT_RIGHT);

  profileForm: FormGroup;
  profiles: FilterProfile[] = [];
  editMode = false;
  editingProfile: FilterProfile | null = null;

  typeOptions: { public_id: number; display_name: string }[] = [];
  relationOptions: { public_id: number; display_name: string }[] = [];

  constructor(
    private fb: FormBuilder,
    private activeModal: NgbActiveModal,
    private profileService: GraphProfileService,
    private loaderService: LoaderService,
    private toast: ToastService,
    private modalService: NgbModal,
    private fullscreenModalService: FullscreenModalService
  ) {
    this.profileForm = this.fb.group({
      name: ['', [Validators.required]],
      types_filter: [[]],
      relations_filter: [[]]
    });
  }

  ngOnInit(): void {
    this.loadProfiles();
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
  }


  /**
   *  Initializes the type and relation options for the profile form.
   * @param typeOptions 
   * @param relationOptions 
   */
  initializeOptions(typeOptions: any[], relationOptions: any[]): void {
    this.typeOptions = typeOptions;
    this.relationOptions = relationOptions;
  }


  /**
   * Loads all profiles from the GraphProfileService and updates the component state.
   */
  private loadProfiles(): void {
    this.loaderService.show();
    this.profileService.getProfiles()
      .pipe(
        finalize(() => this.loaderService.hide()),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: profiles => {
          this.profiles = profiles; // Now profiles is FilterProfile[]
        },
        error: (error) => this.toast.error(error?.error?.message)
      });
  }


  /**
   *  Starts editing a profile by setting the edit mode and populating the form with the profile data.
   * @param profile 
   */
  startEdit(profile: FilterProfile): void {
    this.editMode = true;
    this.editingProfile = profile;
    this.profileForm.patchValue(profile);
  }


  /**
   * Cancels the edit mode and resets the form to its initial state.
   */
  cancelEdit(): void {
    this.editMode = false;
    this.editingProfile = null;
    this.profileForm.reset({
      name: '',
      types_filter: [],
      relations_filter: []
    });
  }


  /**
   *  Saves the profile data from the form.
   * @returns 
   */
  saveProfile(): void {
    if (!this.canEdit) {
      return;
    }

    if (this.profileForm.invalid) {
      this.profileForm.markAllAsTouched();
      return;
    }

    let profileData = this.profileForm.value as FilterProfile;

    if (this.editMode && this.editingProfile?.public_id) {
      profileData = {
        ...profileData,
        public_id: this.editingProfile.public_id
      };
    }
    const operation = this.editMode
      ? this.profileService.updateProfile(this.editingProfile!.public_id!, profileData)
      : this.profileService.createProfile(profileData);

    this.loaderService.show();
    operation
      .pipe(
        finalize(() => this.loaderService.hide()),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: () => {
          this.toast.success(`Profile ${this.editMode ? 'updated' : 'created'} successfully!`);
          this.loadProfiles();
          this.cancelEdit();
        },
        error: (error) => this.toast.error(error?.error?.message)
      });
  }


  /**
   * Deletes a profile after user confirmation through a modal dialog.
   * @param profile 
   */
  deleteProfile(profile: FilterProfile): void {
    if (!this.canEdit) {
      return;
    }

    const modalRef: NgbModalRef = this.fullscreenModalService.open(this.modalService, ProfileDeleteModalComponent, {
      size: 'md',
      centered: false,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });
    modalRef.componentInstance.profile = profile;

    modalRef.result.then((result: number) => {
      if (result === 0) {
        return;
      }

      const isDeletingEditedProfile = this.editingProfile?.public_id === profile.public_id;

      this.loaderService.show();
      this.profileService.deleteProfile(profile.public_id!)
        .pipe(
          finalize(() => this.loaderService.hide()),
          takeUntil(this.destroy$)
        )
        .subscribe({
          next: () => {
            this.toast.success('Profile deleted successfully!');

            if (isDeletingEditedProfile) {
              this.cancelEdit();
            }

            this.loadProfiles();
          },
          error: (error) => this.toast.error(error?.error?.message)
        });
    }).catch(() => { });
  }


  /**
   * Returns the display names of types based on their public IDs.
   * @param typeIds 
   * @returns 
   */
  getTypeNames(typeIds: number[]): string[] {
    return typeIds.map(id => {
      const type = this.typeOptions.find(t => t.public_id === id);
      return type?.display_name || `Type #${id}`;
    });
  }


  /**
   * Returns the display names of relations based on their public IDs.
   * @param relationIds 
   * @returns 
   */
  getRelationNames(relationIds: number[]): string[] {
    return relationIds.map(id => {
      const relation = this.relationOptions.find(r => r.public_id === id);
      return relation?.display_name || `Relation #${id}`;
    });
  }


  /**
   * Applies the selected profile and closes the modal.
   * @param profile 
   */
  applyProfile(profile: FilterProfile): void {
    this.activeModal.close(profile);
  }


  /**
   * Closes the modal without applying any profile.
   */
  close(): void {
    this.activeModal.dismiss();
  }
}
