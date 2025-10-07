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
      this.loadForEdit(this.id);
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
      requestData: this.fb.group({})
    });
  }

  private handleInvokerChange(name: string | null): void {
    // First, hide the controls
    this.credentialsReady = false;
    this.isValidCredentials = false;

    // Find the invoker
    this.selectedInvoker = this.findInvokerByName(name);

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

  // Edit mode methods
  private loadForEdit(id: number): void {
    this.loaderService.show();
    this.svc.getConnectors()
      .pipe(
        map((list: Connector[]) => list?.find(c => c.connectorId === id)),
        finalize(() => this.loaderService.hide()),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: (c) => {
          this.inlineLoading = false;
          if (!c) {
            this.toast.error('Connector not found');
            this.router.navigate(['../'], { relativeTo: this.route });
            return;
          }
          this.patchForEdit(c);
        },
        error: (err) => {
          this.inlineLoading = false;
          this.router.navigate(['../'], { relativeTo: this.route });
          this.toast.error(err?.error?.message);
        }
      });
  }

  private patchForEdit(c: Connector): void {
    // Set the invoker first and wait for controls to be ready
    this.credentialsReady = false;

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

    // Build and patch credentials after a tick
    setTimeout(() => {
      this.rebuildCredentials(this.selectedInvoker);

      if (c.requestData) {
        this.requestDataGroup.patchValue(c.requestData);
      }

      this.credentialsReady = true;
    }, 0);
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
