# Fabro Leather Portal Testing

This project now has two automated test layers:

- Django backend tests for routes, CRUD persistence, authentication protection, JSON endpoints, export, and media upload fallback.
- Playwright end-to-end browser tests for login/logout, navigation, dashboard, complaint management, vehicles, SKU, master settings, profile, themes, responsiveness, console errors, failed requests, and page runtime errors.

## Prerequisites

Install Python dependencies and keep the virtual environment available:

```powershell
.\env\Scripts\python.exe -m pip install -r requirements.txt
```

Install Node test dependencies:

```powershell
npm install
npx playwright install
```

The Playwright tests create and reset this local test login automatically:

```text
Username: fabro_e2e_admin
Password: FabroE2E!234
```

You can override those with:

```powershell
$env:E2E_USERNAME="your_user"
$env:E2E_PASSWORD="your_password"
$env:E2E_EMAIL="your_email@example.com"
```

## Start The Website Locally

Playwright starts an isolated Django test server automatically on port `8001`.
It uses `.e2e.sqlite3` and `.e2e-media/`, so browser tests never modify the
normal local database or media used by the website on port `8000`.

To run the normal site manually:

```powershell
.\start_fabro.bat
```

Then open:

```text
http://127.0.0.1:8000/
```

## Run Tests

Run backend and browser tests:

```powershell
npm test
```

Run only Django backend tests:

```powershell
npm run test:backend
```

Run only Playwright E2E tests:

```powershell
npm run test:e2e
```

Run Playwright headed:

```powershell
npm run test:e2e:headed
```

Open Playwright UI mode:

```powershell
npm run test:e2e:ui
```

View the last HTML report:

```powershell
npm run test:e2e:report
```

Run a single test file:

```powershell
npx playwright test tests/e2e/complaints.spec.ts
```

Run one device project:

```powershell
npx playwright test --project=desktop
```

## Coverage

Backend tests cover:

- Anonymous redirects for protected pages
- Authenticated rendering of main pages
- Complaint create, edit, delete, media upload fallback
- Vehicle create and delete
- SKU create
- Master setting create and delete
- JSON dropdown endpoints
- CSV export

Playwright tests cover:

- Valid and invalid login
- Logout and session persistence
- Protected route redirects
- Dashboard cards and navigation
- Complaint add, clear, cancel, upload, save, search, view modal, edit, delete
- Vehicle add, search, edit, delete
- SKU add, search, edit, delete
- Master setting add, edit modal, delete
- Profile load and save
- Dark/light theme toggle and persistence
- Header/profile menu navigation
- Desktop, tablet, and mobile smoke coverage
- Console errors, page runtime errors, failed requests, blank page checks

## Test Structure

```text
tests/
  e2e/
    api.spec.ts
    auth.spec.ts
    complaints.spec.ts
    dashboard.spec.ts
    master.spec.ts
    navigation.spec.ts
    profile.spec.ts
    responsive.spec.ts
    sku.spec.ts
    theme.spec.ts
    vehicles.spec.ts
  helpers/
    assertions.ts
    auth.ts
    globalSetup.ts
    navigation.ts
    testData.ts
```

## Adding New Tests

Add shared helpers to `tests/helpers/`.

Add browser tests under `tests/e2e/` and prefer stable selectors:

- Real visible text
- Labels
- Button/link names
- Existing classes only when the UI has no accessible label

If a UI control is hard to select reliably, add a small `data-testid` attribute to the template and use `page.getByTestId(...)`.
