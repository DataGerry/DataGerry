export interface TypeAssistantResponse<T> {
    data: T;
    is_valid_type: boolean;
    message?: string; // optional backend message to display
  }
  