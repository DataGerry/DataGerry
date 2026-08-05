// Minimal stand-in for @angular/core so the pure wizard services can be bundled for Node.
// Only the decorators the services actually use are needed; they carry no runtime behaviour here.
export function Injectable() {
    return function (target) {
        return target;
    };
}

export function inject() {
    throw new Error('inject() is not available outside an Angular injection context');
}
