export interface Invoker {
    name: string;
    description?: string;
    hint?: string;
    icon?: string;
    authType?: 'token'|'basic'|'other'|string;
    requiredData: Record<string, ''>;  // keys define dynamic credential fields
  }
  