import { expect, type Page, type Request } from '@playwright/test';

const ignoredConsolePatterns = [
  /favicon/i,
  /fontawesome/i,
  /Failed to load resource/i
];

const ignoredRequestPatterns = [
  /favicon/i,
  /fontawesome/i,
  /s3\.ap-south-2\.amazonaws\.com/i
];

export function attachPageDiagnostics(page: Page) {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const pageErrors: string[] = [];

  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (!ignoredConsolePatterns.some((pattern) => pattern.test(text))) {
      consoleErrors.push(text);
    }
  });

  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });

  page.on('requestfailed', (request: Request) => {
    const url = request.url();
    if (!ignoredRequestPatterns.some((pattern) => pattern.test(url))) {
      failedRequests.push(`${request.method()} ${url} ${request.failure()?.errorText || ''}`.trim());
    }
  });

  return {
    async assertClean() {
      expect(pageErrors, 'uncaught page errors').toEqual([]);
      expect(consoleErrors, 'browser console errors').toEqual([]);
      expect(failedRequests, 'failed network requests').toEqual([]);
      await expect(page.locator('body')).not.toBeEmpty();
    }
  };
}

export async function expectNoDjangoError(page: Page) {
  await expect(page.locator('body')).not.toContainText(/Traceback|Exception Type|ValueError|ClientError|NameError/i);
}

export async function expectTheme(page: Page, mode: 'dark' | 'light') {
  const body = page.locator('body');
  if (mode === 'light') {
    await expect(body).toHaveClass(/light-mode/);
  } else {
    await expect(body).not.toHaveClass(/light-mode/);
  }
}
