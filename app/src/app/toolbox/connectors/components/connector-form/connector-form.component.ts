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

import { Component, OnInit, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  Validators
} from '@angular/forms';
import { map, distinctUntilChanged, debounceTime, finalize } from 'rxjs/operators';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { ConnectorsService } from '../../services/connectors.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Connector } from '../../models/connector.model';
import { Invoker } from '../../models/invoker.model';


@Component({
  selector: 'app-connector-form',
  templateUrl: './connector-form.component.html',
  styleUrls: ['./connector-form.component.scss']
})
export class ConnectorFormComponent implements OnInit, OnDestroy {
  mode: 'create' | 'edit' = 'create';
  id?: number;

  invokers: Invoker[] = [];
  form!: FormGroup;

  testing = false;
  isValidCredentials = false;
  inlineLoading = false;

  // Add flag to control rendering
  credentialsReady = false;
  selectedInvoker: Invoker | null = null;

  // Master password functionality
  showMasterPassword = false;
  masterPasswordVerified = false;
  credentialsBlurred = false;
  verifyingPassword = false;
  showPassword = false;
  originalInvokerName: string | null = null;

  public isLoading$ = this.loaderService.isLoading$;

  private destroy$ = new Subject<void>();

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private svc: ConnectorsService,
    private toast: ToastService,
    private loaderService: LoaderService
  ) { }

  ngOnInit(): void {
    this.mode = (this.route.snapshot.data['mode'] || 'create') as any;
    this.invokers = this.route.snapshot.data['invokers'] || [];
    this.buildForm();

    // Listen to invoker changes with proper timing
    this.form.get(['invoker', 'name'])!.valueChanges
      .pipe(
        distinctUntilChanged(),
        debounceTime(50), // Small debounce to ensure DOM stability
        takeUntil(this.destroy$)
      )
      .subscribe((name: string | null) => {
        this.handleInvokerChange(name);
      });

    if (this.mode === 'edit') {
      this.id = +this.route.snapshot.paramMap.get('id')!;
      
      // Check if connector was passed via state 
      const connector = history.state?.connector;
      if (connector) {
        this.patchForEdit(connector);
      } 
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private buildForm(): void {
    this.form = this.fb.group({
      title: ['', Validators.required],
      description: [''],
      invoker: this.fb.group({
        name: [null, Validators.required]
      }),
      sslCert: [false],
      timeout: [1000, [Validators.required, Validators.min(0)]],
      requestData: this.fb.group({}),
      masterPassword: ['']
    });
  }

  private handleInvokerChange(name: string | null): void {
    // First, hide the controls
    this.credentialsReady = false;
    this.isValidCredentials = false;

    // Find the invoker
    this.selectedInvoker = this.findInvokerByName(name);

    // Handle master password logic for invoker switching
    if (this.mode === 'edit' && this.originalInvokerName) {
      const isOriginalInvoker = name === this.originalInvokerName;
      
      if (isOriginalInvoker) {
        // Switching back to original invoker
        // Check if we have loaded credentials or if we need master password
        const currentRequestData = this.requestDataGroup?.value;
        const credentialsMissing = this.areCredentialsMissing(currentRequestData);
        
        if (credentialsMissing && !this.masterPasswordVerified) {
          // Show master password for original invoker with missing credentials
          this.showMasterPassword = true;
          this.credentialsBlurred = true;
        } else {
          // Either credentials are loaded or master password was verified
          this.showMasterPassword = false;
          this.credentialsBlurred = false;
        }
      } else {
        // Switching to a different invoker - no master password needed
        this.showMasterPassword = false;
        this.credentialsBlurred = false;
      }
    }

    // Use setTimeout to ensure DOM has updated
    setTimeout(() => {
      this.rebuildCredentials(this.selectedInvoker);
      // Only show controls after they're built
      this.credentialsReady = true;
    }, 0);
  }

  private rebuildCredentials(inv?: Invoker | null): void {
    const newGroup = this.fb.group({});

    if (inv?.requiredData) {
      Object.keys(inv.requiredData).forEach((key) => {
        const defaultVal = inv.requiredData[key] ?? '';
        newGroup.addControl(
          key,
          new FormControl(defaultVal, Validators.required)
        );
      });
    }

    // Replace the entire group
    this.form.setControl('requestData', newGroup);
  }

  private findInvokerByName(name?: string | null): Invoker | null {
    if (!name) return null;
    return this.invokers.find(i => i.name === name) || null;
  }

  // Template helper methods
  get requestDataGroup(): FormGroup {
    return this.form.get('requestData') as FormGroup;
  }

  getRequestDataControlNames(): string[] {
    return Object.keys(this.requestDataGroup?.controls ?? {});
  }

  getRequestControl(name: string): FormControl {
    return this.requestDataGroup?.get(name) as FormControl;
  }

  trackByName = (_: number, name: string) => name;

  hasErr(path: string, err: string): boolean {
    const c = this.form.get(path);
    return !!c && c.touched && c.hasError(err);
  }

  private patchForEdit(c: Connector): void {
    // Set the invoker first and wait for controls to be ready
    this.credentialsReady = false;

    // Store the original invoker name
    this.originalInvokerName = c.invoker?.name || null;

    // Find and set the selected invoker
    this.selectedInvoker = this.findInvokerByName(c.invoker?.name);

    // Patch basic fields
    this.form.patchValue({
      title: c.title,
      description: c.description || '',
      invoker: { name: c.invoker?.name },
      sslCert: c.sslCert,
      timeout: c.timeout
    });

    // Check if requestData is missing or has empty values
    const credentialsMissing = !c.requestData || this.areCredentialsMissing(c.requestData);
    
    // Always build credentials so they're visible (but blurred if needed)
    setTimeout(() => {
      this.rebuildCredentials(this.selectedInvoker);

      if (c.requestData && !credentialsMissing) {
        this.requestDataGroup.patchValue(c.requestData);
      }

      // Set flags after building credentials
      this.showMasterPassword = credentialsMissing;
      this.credentialsBlurred = credentialsMissing;
      this.credentialsReady = true;
    }, 0);
  }

  private areCredentialsMissing(requestData: any): boolean {
    if (!requestData) return true;

    // If no invoker is selected, we can't determine required fields
    if (!this.selectedInvoker) {
      return true;
    }

    // Get the required fields from the selected invoker's configuration
    const requiredFields = Object.keys(this.selectedInvoker.requiredData || {});
    
    // If no required fields are defined, assume credentials are complete
    if (requiredFields.length === 0) {
      return false;
    }

    // Check if any required field is missing or empty
    for (const field of requiredFields) {
      const value = requestData[field];
      // Check if field exists and has a non-empty value
      if (!value || value.toString().trim() === '') {
        return true;
      }
    }

    return false;
  }

  // Master password verification
  verifyMasterPassword(): void {
    const masterPassword = this.form.get('masterPassword')?.value;
    if (!masterPassword) {
      this.toast.warning('Please enter the master password');
      return;
    }

    if (!this.id) {
      this.toast.error('Connector ID is missing');
      return;
    }

    this.verifyingPassword = true;
    this.loaderService.show();

    this.svc.checkMasterPassword(masterPassword, this.id)
      .pipe(
        finalize(() => {
          this.loaderService.hide();
          this.verifyingPassword = false;
        }),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: (connector: Connector) => {
          // Password is correct, populate the form with connector data
          this.masterPasswordVerified = true;
          this.showMasterPassword = false;
          this.credentialsBlurred = false;
          
          // Patch the form with the actual credential values
          if (connector.requestData) {
            this.requestDataGroup.patchValue(connector.requestData);
          }
          
          this.credentialsReady = true;
          this.toast.success('Credentials loaded successfully');
        },
        error: (err) => {
          // Handle 403 error specifically for incorrect password
          if (err.status === 403) {
            this.toast.error('Incorrect master password');
          } else {
            this.toast.error(err?.error?.message);
          }
        }
      });
  }

  // Toggle password visibility
  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  // Action methods
  private toPayload(): Connector {
    const v = this.form.value;
    return {
      connectorId: this.id,
      title: v.title,
      description: v.description,
      invoker: { name: v.invoker.name },
      sslCert: v.sslCert,
      timeout: v.timeout,
      requestData: v.requestData
    };
  }

  test(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.toast.warning('Please fill in all required fields');
      return;
    }

    this.loaderService.show();
    this.testing = true;
    this.isValidCredentials = false;

    const payload = this.toPayload();

    this.svc.checkConnector(payload)
      .pipe(
        finalize(() => {
          this.loaderService.hide();
        }),
        takeUntil(this.destroy$))
      .subscribe({
        next: (ok: boolean) => {
          this.testing = false;
          this.isValidCredentials = !!ok;

          if (ok) {
            this.toast.success('Connection test successful');
          } else {
            this.toast.error('Connection test failed');
          }
        },
        error: (err) => {
          this.isValidCredentials = false;
          this.toast.error(err?.error?.message);
        }
      });
  }

  save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.toast.warning('Please fill in all required fields');
      return;
    }

    if (!this.isValidCredentials) {
      this.toast.warning('Please test the connection before saving');
      return;
    }

    const payload = this.toPayload();
    const req$ = this.mode === 'create'
      ? this.svc.createConnector(payload)
      : this.svc.updateConnector(this.id!, payload);

    this.loaderService.show();

    req$.pipe(finalize(() => this.loaderService.hide()),
      takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.toast.success(
            this.mode === 'create'
              ? 'Connector created successfully'
              : 'Connector updated successfully'
          );
          this.router.navigate(['/connectors']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  cancel(): void {
    this.router.navigate(['../'], { relativeTo: this.route });
  }
}
