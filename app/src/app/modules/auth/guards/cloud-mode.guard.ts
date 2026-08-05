import { inject } from '@angular/core';
import { CanActivateFn, CanActivateChildFn, Router } from '@angular/router';
import { environment } from '../../../../environments/environment';


// Functional Guard for CanActivate
export const cloudModeGuard: CanActivateFn = () => {
    const router = inject(Router);

    if (environment.cloudMode) {
        // Redirect to a default or error page
        router.navigate(['/error/404']);
        return false;
    }

    return true;
};

// Functional Guard for CanActivateChild
export const cloudModeChildGuard: CanActivateChildFn = () => {
    const router = inject(Router);

    if (environment.cloudMode) {
        // Redirect to a default or error page
        router.navigate(['/error/404']);
        return false;
    }

    return true;
};

// Cloud-only guard for routes that should be available only in cloud mode.
export const cloudOnlyGuard: CanActivateFn = () => {
    const router = inject(Router);

    if (!environment.cloudMode) {
        router.navigate(['/error/404']);
        return false;
    }

    return true;
};

// Cloud-only child guard for routes that should be available only in cloud mode.
export const cloudOnlyChildGuard: CanActivateChildFn = () => {
    const router = inject(Router);

    if (!environment.cloudMode) {
        router.navigate(['/error/404']);
        return false;
    }

    return true;
};
