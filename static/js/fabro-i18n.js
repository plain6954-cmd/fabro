(function () {
    'use strict';

    const supportedLanguages = new Set(['en', 'ar', 'hi']);
    const documentLanguage = (document.documentElement.lang || '').toLowerCase().split('-')[0];
    const configuredLanguage = (window.FABRO_LANGUAGE || documentLanguage || 'en').toLowerCase();
    const language = supportedLanguages.has(configuredLanguage) ? configuredLanguage : 'en';

    const translate = (message) => {
        if (typeof window.gettext === 'function') return window.gettext(message);
        return message;
    };

    const translatePlural = (singular, plural, count) => {
        if (typeof window.ngettext === 'function') return window.ngettext(singular, plural, count);
        return count === 1 ? singular : plural;
    };

    const interpolateMessage = (format, values, named = true) => {
        if (typeof window.interpolate === 'function') return window.interpolate(format, values, named);
        if (!named) return format;
        return Object.entries(values || {}).reduce(
            (result, [key, value]) => result.replaceAll(`%(${key})s`, String(value)),
            format
        );
    };

    const translateMarkedElements = (root) => {
        if (!root || typeof root.querySelectorAll !== 'function') return;
        const elements = [];
        if (root.nodeType === Node.ELEMENT_NODE && root.hasAttribute('data-i18n')) elements.push(root);
        elements.push(...root.querySelectorAll('[data-i18n]'));
        elements.forEach((element) => {
            const message = element.dataset.i18n;
            if (message) element.textContent = translate(message);
        });

        ['placeholder', 'title', 'aria-label'].forEach((attribute) => {
            const dataAttribute = `data-i18n-${attribute}`;
            const targets = [];
            if (root.nodeType === Node.ELEMENT_NODE && root.hasAttribute(dataAttribute)) targets.push(root);
            targets.push(...root.querySelectorAll(`[${dataAttribute}]`));
            targets.forEach((element) => {
                const message = element.getAttribute(dataAttribute);
                if (message) element.setAttribute(attribute, translate(message));
            });
        });
    };

    const initialize = (root = document) => {
        document.documentElement.lang = language;
        document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
        translateMarkedElements(root);
        document.dispatchEvent(new CustomEvent('fabro:i18n-ready', {
            detail: { language, direction: document.documentElement.dir, root }
        }));
    };

    window.FABRO_LANGUAGE = language;
    window.FabroI18n = Object.freeze({
        language,
        direction: language === 'ar' ? 'rtl' : 'ltr',
        gettext: translate,
        ngettext: translatePlural,
        interpolate: interpolateMessage,
        init: initialize
    });

    if (!window.__fabroI18nLifecycleBound) {
        window.__fabroI18nLifecycleBound = true;
        document.addEventListener('htmx:afterSwap', (event) => {
            initialize(event.detail && event.detail.target ? event.detail.target : document);
        });
        document.addEventListener('htmx:historyRestore', () => initialize(document));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initialize(document), { once: true });
    } else {
        initialize(document);
    }
}());
