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
import { distinctUntilChanged, debounceTime, finalize } from 'rxjs/operators';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { ConnectorsService } from '../../services/connectors.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { Connector } from '../../models/connector.model';
import { Invoker } from '../../models/invoker.model';
import { environment } from 'src/environments/environment';


@Component({
  selector: 'app-connector-form',
  templateUrl: './connector-form.component.html',
  styleUrls: ['./connector-form.component.scss'],
  standalone: false
})
export class ConnectorFormComponent implements OnInit, OnDestroy {
  public isLoading$ = this.loaderService.isLoading$;

  mode: 'create' | 'edit' | 'internal' = 'create';
  id?: number;
  isCloudMode = environment.cloudMode;

  invokers: Invoker[] = [];
  form!: FormGroup;

  testing = false;
  isValidCredentials = false;
  inlineLoading = false;

  // flag to control rendering
  credentialsReady = false;
  selectedInvoker: Invoker | null = null;

  // Master password functionality
  showMasterPassword = false;
  masterPasswordVerified = false;
  credentialsBlurred = false;
  verifyingPassword = false;
  showPassword = false;
  showDataGerryPassword = false;
  originalInvokerName: string | null = null;

  // Internal connector state
  internalConnectorExists = false;

  private destroy$ = new Subject<void>();
  private initializing = false;

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private svc: ConnectorsService,
    private toast: ToastService,
    private loaderService: LoaderService
  ) { }


  ngOnInit(): void {
    // Use state mode if provided, otherwise use route data
    this.mode = history.state?.mode || (this.route.snapshot.data['mode'] || 'create') as any;
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

    // Reset connection test status when form values change
    this.form.valueChanges
      .pipe(
        distinctUntilChanged(),
        debounceTime(300),
        takeUntil(this.destroy$)
      )
      .subscribe(() => {
        // Reset connection test status when form is modified (except during initialization)
        if (!this.initializing && this.isValidCredentials) {
          this.isValidCredentials = false;
        }
      });

    if (this.mode === 'edit') {
      this.id = +this.route.snapshot.paramMap.get('id')!;

      // Check if connector was passed via state 
      const connector = history.state?.connector;
      if (connector) {
        this.patchForEdit(connector);
      }
    } else if (this.mode === 'internal') {
      this.checkInternalConnectorExists();
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


  patchForEdit(c: Connector) {
    this.credentialsReady = false;
    this.initializing = true;

    this.originalInvokerName = c.invoker?.name ?? null;
    this.form.get(['invoker', 'name'])!.setValue(this.originalInvokerName, { emitEvent: false });
    this.selectedInvoker = this.findInvokerByName(this.originalInvokerName);

    this.form.patchValue({
      title: c.title,
      description: c.description ?? '',
      sslCert: c.sslCert,
      timeout: c.timeout
    }, { emitEvent: false });

    this.rebuildCredentials(this.selectedInvoker);
    this.requestDataGroup.patchValue(c.requestData ?? {}, { emitEvent: false });
    this.requestDataGroup.updateValueAndValidity({ emitEvent: false });

    const missing = this.areCredentialsMissing(this.requestDataGroup.getRawValue());
    this.showMasterPassword = missing;
    this.credentialsBlurred = missing;
    this.credentialsReady = true;

    this.initializing = false;
  }


  private patchForInternal(c: Connector | any, connectorExists: boolean = false): void {

    this.credentialsReady = false;
    this.initializing = true;

    try {
      //  Set invoker without emitting and resolve selectedInvoker
      this.originalInvokerName = c?.invoker?.name ?? null;
      this.form.get(['invoker', 'name'])!.setValue(this.originalInvokerName, { emitEvent: false });
      this.selectedInvoker = this.findInvokerByName(this.originalInvokerName);

      // Ensure selectedInvoker has the DATAGerry hint in internal mode
      if (this.mode === 'internal' && (!this.selectedInvoker || !this.selectedInvoker.hint)) {
        this.selectedInvoker = this.getDataGerryInvoker();
      }

      //  Patch basic fields (no emission)
      this.form.patchValue({
        title: c?.title ?? 'DataGerryInternal',
        description: c?.description ?? 'Internal DATAGerry connector for automations',
        sslCert: false,
        timeout: 1000
      }, { emitEvent: false });

      //  Build fixed internal credential fields synchronously
      this.buildDataGerryCredentials();
      this.form.updateValueAndValidity({ emitEvent: false });

      if (connectorExists) {
        // Fetch actual existing internal connector (for ID + possibly real requestData)
        this.loaderService.show();
        this.svc.getInternalConnector({})
          .pipe(
            finalize(() => this.loaderService.hide()),
            takeUntil(this.destroy$)
          )
          .subscribe({
            next: (actual) => {
              this.id = actual?.connectorId;

              // Patch requestData if backend provided it
              const rd = actual?.requestData ?? null;
              if (rd) {
                this.requestDataGroup.patchValue(rd, { emitEvent: false });
                this.requestDataGroup.updateValueAndValidity({ emitEvent: false });
              }

              // Check if we have request data values - if values are empty, show master password
              const hasRequestData = rd && Object.keys(rd).length > 0;
              const hasEmptyValues = hasRequestData && Object.values(rd).every(value => !value || value.toString().trim() === '');

              // Show master password if we have empty values OR no request data
              const shouldShowMasterPassword = !hasRequestData || hasEmptyValues;
              this.showMasterPassword = shouldShowMasterPassword;
              this.credentialsBlurred = shouldShowMasterPassword;
              this.masterPasswordVerified = !shouldShowMasterPassword;

              // Disable fixed fields in internal mode (after patching)
              this.form.get('title')?.disable({ emitEvent: false });
              this.form.get('description')?.disable({ emitEvent: false });
              this.form.get('invoker')?.disable({ emitEvent: false });
              this.form.get('sslCert')?.disable({ emitEvent: false });
              this.form.get('timeout')?.disable({ emitEvent: false });

              this.credentialsReady = true;
            },
            error: (error) => {
              this.toast.error(error?.error?.message);

              // Without secrets, require master password
              this.showMasterPassword = true;
              this.credentialsBlurred = true;

              // Disable fixed fields in internal mode
              this.form.get('title')?.disable({ emitEvent: false });
              this.form.get('description')?.disable({ emitEvent: false });
              this.form.get('invoker')?.disable({ emitEvent: false });
              this.form.get('sslCert')?.disable({ emitEvent: false });
              this.form.get('timeout')?.disable({ emitEvent: false });

              this.credentialsReady = true;
            }
          });
      } else {
        //  Internal connector does not exist – allow creation, no overlay
        this.showMasterPassword = false;
        this.credentialsBlurred = false;

        // Disable fixed fields in internal mode (they’re predefined)
        this.form.get('title')?.disable({ emitEvent: false });
        this.form.get('description')?.disable({ emitEvent: false });
        this.form.get('invoker')?.disable({ emitEvent: false });
        this.form.get('sslCert')?.disable({ emitEvent: false });
        this.form.get('timeout')?.disable({ emitEvent: false });

        this.credentialsReady = true;
      }
    } finally {
      this.initializing = false;
    }
  }


  private enableFormForInternalCreation(): void {
    // When in internal mode without connector data, pre-fill with default internal connector data
    const internalConnectorData = {
      title: 'DataGerryInternal',
      description: 'Internal DATAGerry connector for automations',
      invoker: { name: environment.cloudMode ? 'DataGerryCloud' : 'DataGerry', hint: "This interface provides a basic auth. Read here the api documentation https://docs.datagerry.com/latest/api/rest/" },
      sslCert: false,
      timeout: 1000
    };

    this.form.patchValue(internalConnectorData);

    // Set the selected invoker for internal mode to ensure hint is displayed
    this.selectedInvoker = this.getDataGerryInvoker();

    // Disable fixed fields in internal mode (they're predefined)
    this.form.get('title')?.disable({ emitEvent: false });
    this.form.get('description')?.disable({ emitEvent: false });
    this.form.get('invoker')?.disable({ emitEvent: false });
    this.form.get('sslCert')?.disable({ emitEvent: false });
    this.form.get('timeout')?.disable({ emitEvent: false });

    // Build hardcoded credential fields for DataGerry invoker
    setTimeout(() => {
      this.buildDataGerryCredentials();
      this.credentialsReady = true;
    }, 0);
  }


  private handleInvokerChange(name: string | null): void {
    // Skip invoker change handling in internal mode 
    if (this.mode === 'internal') {
      return;
    }

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


  private areCredentialsMissing(requestData: any): boolean {
    if (!requestData) {
      return true;
    }

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


  private checkInternalConnectorExists(): void {
    this.loaderService.show();

    this.svc.checkConnectorExists('DataGerryInternal')
      .pipe(
        finalize(() => this.loaderService.hide()),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: (exists: boolean) => {
          this.internalConnectorExists = exists;

          if (exists) {
            // Connector exists - show update button and load connector data
            this.loaderService.show();
            this.svc.getInternalConnector({})
              .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntil(this.destroy$)
              )
              .subscribe({
                next: (connector) => {
                  this.patchForInternal(connector, true);
                },
                error: (error) => {
                  this.toast.error(error?.error?.message);
                  this.router.navigate(['/automations/connectors']);
                }
              });
          } else {
            // Connector doesn't exist - show create button
            this.enableFormForInternalCreation();
          }
        },
        error: (err) => {
          this.toast.error('Failed to check if internal connector exists');
          this.router.navigate(['/automations/connectors']);
        }
      });
  }


  private buildDataGerryCredentials(): void {
    const newGroup = this.fb.group({});

    // URL: set from environment in cloud mode, otherwise empty string
    const urlValue = environment.cloudMode
      ? `${environment.protocol}://${environment.apiUrl}:${environment.apiPort}`
      : '';

    newGroup.addControl('url', new FormControl(urlValue, Validators.required));
    newGroup.addControl('username', new FormControl('', Validators.required));
    newGroup.addControl('password', new FormControl('', Validators.required));

    if (environment.cloudMode) {
      newGroup.addControl('x-api-key', new FormControl('', Validators.required));
    }

    this.form.setControl('requestData', newGroup);
  }


  getDisplayedRequestDataControlNames(): string[] {
    const allControls = this.getRequestDataControlNames();

    // Filter out URL field in internal mode when cloudMode is enabled
    if (this.mode === 'internal' && environment.cloudMode) {
      return allControls.filter(controlName => controlName !== 'url');
    }

    return allControls;
  }


  // Master password verification
  verifyMasterPassword(): void {
    const masterPassword = this.form.get('masterPassword')?.value;
    if (!masterPassword) {
      this.toast.warning('Please enter the master password');
      return;
    }

    this.verifyingPassword = true;
    this.loaderService.show();

    let verification$;

    if (this.mode === 'internal') {
      // For internal connectors, use getInternalConnector with password
      verification$ = this.svc.getInternalConnector({ password: masterPassword });
    } else {
      // For regular connectors, use checkMasterPassword
      if (!this.id) {
        this.toast.error('Something went wrong');
        this.loaderService.hide();
        this.verifyingPassword = false;
        return;
      }
      verification$ = this.svc.checkMasterPassword(masterPassword, this.id);
    }

    verification$.pipe(
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


  // Action methods
  private toPayload(): Connector {
    // Use getRawValue() to get all form values including disabled fields
    const v = this.form.getRawValue();

    // Handle internal mode where invoker might be disabled
    let invokerName = v.invoker?.name;
    if (!invokerName && this.mode === 'internal') {
      invokerName = 'DataGerry';
    }

    return {
      connectorId: this.id,
      title: v.title,
      description: v.description,
      invoker: { name: invokerName },
      sslCert: v.sslCert,
      timeout: v.timeout,
      requestData: this.mode === 'internal' && environment.cloudMode
        ? { ...v.requestData, url: this.getInternalUrlFromEnvironment() }
        : v.requestData
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
          this.testing = false;
        }),
        takeUntil(this.destroy$))
      .subscribe({
        next: (ok: boolean) => {
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
    let req$;

    if (this.mode === 'internal') {
      // For internal mode, use the internal-specific endpoints
      req$ = this.id
        ? this.svc.updateInternalConnector(payload)
        : this.svc.createInternalConnector(payload);
    } else {
      req$ = this.mode === 'create'
        ? this.svc.createConnector(payload)
        : this.svc.updateConnector(this.id!, payload);
    }

    this.loaderService.show();

    req$.pipe(finalize(() => this.loaderService.hide()),
      takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.toast.success(
            this.mode === 'create' || this.mode === 'internal'
              ? 'Connector created successfully'
              : 'Connector updated successfully'
          );
          this.router.navigate(['/automations/connectors']);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }


  cancel(): void {
    this.router.navigate(['../'], { relativeTo: this.route });
  }


  private getInternalUrlFromEnvironment(): string {
    if (environment.cloudMode) {
      return `${environment.protocol}://${environment.apiUrl}`;
    }

    return this.requestDataGroup?.get('url')?.value ?? '';
  }


  get saveButtonLabel(): string {
    if (this.mode === 'internal') {
      return this.internalConnectorExists ? 'Update' : 'Create';
    }
    return this.mode === 'create' ? 'Create' : 'Update';
  }


  // Toggle password visibility
  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }


  toggleDataGerryPasswordVisibility(): void {
    this.showDataGerryPassword = !this.showDataGerryPassword;
  }


  private getDataGerryInvoker(): Invoker {
    return {
      name: 'DataGerry',
      hint: "This interface provides a basic auth. Read here the api documentation https://docs.datagerry.com/latest/api/rest/",
      requiredData: {}
    };
  }
}