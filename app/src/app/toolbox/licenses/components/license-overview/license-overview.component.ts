import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';
import { LicenseService } from '../../services/license.service';
import { License, LicenseInfoResponse, UsageItem } from '../../models/license.model';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

export enum SubscriptionType {
  Admin = 'admin',
  SalesManager = 'sales_manager',
  DuoCustomer = 'duo_customer',
  UnlimitedCustomer = 'unlimited_customer',
  Professional = 'professional',
  Enterprise = 'enterprise',
  EnterprisePlus = 'enterprise_plus',
  Starter_API = 'starter_api',
  Professional_API = 'professional_api',
  Enterprise_API = 'enterprise_api',
  EnterprisePlus_API = 'enterprise_plus_api',
  Free = 'free',
}

@Component({
  selector: 'app-license-overview',
  templateUrl: './license-overview.component.html',
  styleUrls: ['./license-overview.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseOverviewComponent implements OnInit, OnDestroy {
  loading = false;
  license?: License;
  columns: any[];
  items: UsageItem[] = [];
  totalItems = 0;
  
  // pagination: UI is 1-based; backend is 0-based
  page = 1;
  size = 5;
  
  private destroy$ = new Subject<void>();
  public isLoading$ = this.loaderService.isLoading$;
  
  constructor(
    private svc: LicenseService,
    private loaderService: LoaderService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute
  ) {}

  ngOnInit(): void {
    // Use the pre-loaded data from the resolver
    const resolvedData: LicenseInfoResponse = this.route.snapshot.data['licenseData'];
    this.setDataFromResponse(resolvedData, 1);

    this.columns = [
      { 
        display: 'Connection', 
        name: 'connectionTitle', 
        data: 'connectionTitle', 
        sortable: false, 
        style: {  'text-align': 'left' } 
      },
      { 
        display: 'API Operations', 
        name: 'totalUsage', 
        data: 'totalUsage', 
        sortable: false, 
        style: {width: '80px', 'text-align': 'center' } 
      },
    ];
  }
  
  loadPage(uiPage: number): void {
    const backendPage = Math.max(uiPage - 1, 0);
    
    this.loading = true;
    this.loaderService.show();
    
    this.svc.getLicenseInfo(backendPage, this.size)
      .pipe(
        finalize(() => {
          this.loading = false;
          this.loaderService.hide();
          this.cdr.markForCheck();
        }),
        takeUntil(this.destroy$)
      )
      .subscribe({
        next: (res: LicenseInfoResponse) => {
          this.setDataFromResponse(res, uiPage);
        },
        error: (err) => this.toast.error(err?.error?.message)
      });
  }
  
  onPageChange(nextPage: number): void {
    this.loadPage(nextPage);
  }

  /**
   * Set component data from a LicenseInfoResponse
   */
  private setDataFromResponse(res: LicenseInfoResponse, uiPage: number): void {
    this.license = res?.license;
    
    const usage: any = (res as any)?.usage;
    const content: UsageItem[] = Array.isArray(usage)
      ? usage
      : usage?.content ?? [];
    
    this.items = content ?? [];
    this.totalItems = usage?.totalItems ?? this.items.length;
    
    // If backend returns currentPage, sync (0->1)
    this.page = typeof usage?.currentPage === 'number' ? usage.currentPage + 1 : uiPage;
    
    this.cdr.markForCheck();
  }
  
  trackById = (_: number, row: UsageItem) => row.id;

  /**
   * Convert backend subscription type to user-friendly display name
   */
  getSubscriptionDisplayName(type: string): string {
    if (!type) return 'Unknown';
    
    const typeMap: Record<string, string> = {
      'admin': 'Admin',
      'sales_manager': 'Sales Manager',
      'duo_customer': 'Duo',
      'unlimited_customer': 'Unlimited',
      'professional': 'Professional',
      'enterprise': 'Enterprise',
      'enterprise_plus': 'Enterprise+',
      'starter_api': 'Starter API',
      'professional_api': 'Professional API',
      'enterprise_api': 'Enterprise API',
      'enterprise_plus_api': 'Enterprise+ API',
      'free': 'Free',
    };
    
    return typeMap[type.toLowerCase()] || type.split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  /**
   * Get badge color class based on subscription tier
   */
  getSubscriptionBadgeClass(type: string): string {
    if (!type) return 'bg-secondary';
    
    const lowerType = type.toLowerCase();
    
    // Free/Starter - Gray
    if (lowerType === 'free' || lowerType === 'starter_api') {
      return 'bg-secondary';
    }
    
    // Admin/Enterprise+ - Purple (Premium)
    if (lowerType === 'admin' || lowerType.includes('enterprise_plus')) {
      return 'bg-premium';
    }
    
    // Enterprise/Professional - Green
    if (lowerType.includes('enterprise') || lowerType.includes('professional')) {
      return 'bg-success';
    }
    
    // Duo/Unlimited - Cyan
    if (lowerType.includes('duo') || lowerType.includes('unlimited')) {
      return 'bg-info';
    }
    
    // Sales Manager - Blue
    if (lowerType.includes('sales')) {
      return 'bg-primary';
    }
    
    return 'bg-primary';
  }
  
  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
