export interface LicenseMonthPeriod {
    startDate: number;
    endDate: number;
  }
  
  export interface License {
    subId: string;
    licenseId: string;
    type: string;
    startDate: number;
    endDate: number; // 0 => open
    duration: string;
    totalOperationUsage: number;
    currentOperationUsage: number;
    active: boolean;
    monthPeriod?: LicenseMonthPeriod | null;
    extraOps?: number | null;
  }
  
  export interface UsageItem {
    id: number;
    licenseId: string;
    subId: string;
    connectionTitle: string;
    totalUsage: number;
    createdAt: number;
    modifiedAt: number;
    fromConnector: string;
    toConnector: string;
  }
  
  export interface UsagePage {
    content: UsageItem[];
    currentPage: number;   // 0-based
    totalPages: number;
    totalItems: number;
  }
  
  /** Backend: { license: License, usage: UsagePage | UsageItem[] } */
  export interface LicenseInfoResponse {
    license: License;
    usage: UsagePage | { content: UsageItem[]; [k: string]: any } | UsageItem[];
  }
  