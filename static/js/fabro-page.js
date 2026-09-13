(function () {
    'use strict';
    // A page owns its global listeners and asynchronous work until it is swapped.
    window.fabroCreatePageScope = function () {
        const controller = new AbortController();
        const cleanups = [];
        let disposed = false;
        function dispose() {
            if (disposed) return;
            disposed = true;
            controller.abort();
            cleanups.splice(0).forEach(cleanup => cleanup());
        }
        document.addEventListener('fabro:before-page-swap', dispose, {
            once: true, signal: controller.signal,
        });
        return {
            signal: controller.signal,
            listen(target, type, listener, options = {}) {
                if (type === 'fabro:before-page-swap') {
                    cleanups.push(listener);
                    return;
                }
                target.addEventListener(type, listener, {
                    ...(typeof options === 'boolean' ? {capture: options} : options),
                    signal: controller.signal,
                });
            },
            fetch(input, init = {}) {
                return fetch(input, { ...init, signal: init.signal || controller.signal });
            },
            onCleanup(cleanup) { cleanups.push(cleanup); },
            dispose,
        };
    };
})();
