# Fabro Leather Portal — Browser Web Push Setup & Operations Guide

## 1. Overview & Architecture

Fabro Leather Portal features production-ready, user-specific browser Web Push notifications. Web Push operates as an **additional notification channel** alongside the existing in-app notification system.

```text
Workflow Business Event (Assignment / Status / Approval / Chat)
                    │
                    ├──► Existing Fabro In-App Notification (Database & Notification Bell)
                    │
                    └──► Central Web Push Service (send_push_on_commit)
                                │
                                ├──► Recipient Device 1 (e.g., Laptop Chrome)
                                ├──► Recipient Device 2 (e.g., Android Chrome)
                                └──► Recipient Device 3 (e.g., Desktop Edge)
```

### Key Security & Architectural Principles
1. **Server-Side Authoritative Ownership:** The subscription ownership is strictly determined by `request.user`. Frontend payloads cannot choose or alter the recipient user ID.
2. **Push Is Not Authorization:** Notifications containing links (e.g., `/complaint/factory-review/FAC-1042/`) do not grant authorization. Standard Django authentication, workflow roles, and RBAC permissions remain strictly enforced when the link is opened.
3. **Graceful Degradation:** If Web Push is unconfigured, or if external push services fail, core Fabro business operations (complaint creation, updates, reviews, approvals, chat) continue unaffected.
4. **Shared Computer & Account Switching Safety:** If multiple employees share a browser, registering notifications under a new account re-assigns the browser endpoint to the currently logged-in user, preventing previous users' notifications from being delivered.
5. **Privacy Safe Payloads:** Push payloads contain minimal, non-sensitive summary details suitable for lock screens.

---

## 2. Environment Variables Configuration

Add the following environment variables to your deployment environment or `.env` file:

```env
# Browser Web Push Notifications (VAPID)
WEBPUSH_VAPID_PUBLIC_KEY=your_generated_vapid_public_key_here
WEBPUSH_VAPID_PRIVATE_KEY=your_generated_vapid_private_key_here
WEBPUSH_VAPID_SUBJECT=mailto:admin@fabroleather.com
```

> [!CAUTION]
> **Keep `WEBPUSH_VAPID_PRIVATE_KEY` strictly secret!** Never commit it to git, never expose it to client-side JavaScript, and never log it in production logs.

---

## 3. Verify the deployed key pair

Preserve the existing production VAPID pair. Replacing it can invalidate browser subscriptions. On the application server, set `WEBPUSH_VAPID_PUBLIC_KEY` and `WEBPUSH_VAPID_PRIVATE_KEY` in the deployment's private environment or `.env`; set `WEBPUSH_VAPID_SUBJECT` to a `mailto:` or `https://` contact. The environment of the running Django process takes precedence over `.env`. Restart that process after changing its configuration.

Check what Django actually loaded without printing either key:

```bash
python manage.py check_web_push
```

The command reports booleans for each variable's presence, each key's format, whether they match, and whether Django recognizes Web Push as configured. It never prints key material. `configured: True` confirms that the public key is a P-256 VAPID key and matches the private key. The authenticated `/notifications/push/status/` endpoint then returns `configured: true` and the public key only. Never paste a production private key into browser tools, logs, tickets, or chat.

---

## 4. HTTPS & Security Requirement

The W3C Push API and Service Workers require a **Secure Context**:
- **Production:** Must be served over **HTTPS** (e.g., with Let's Encrypt, Cloudflare, or reverse-proxy SSL termination).
- **Local Development:** `http://localhost` and `http://127.0.0.1` are treated as secure contexts by modern browsers for local testing.

---

## 5. Deployment & Setup Steps

### Step 1: Install Dependencies
Ensure `pywebpush` is installed in your Python environment:

```powershell
pip install -r requirements.txt
```

### Step 2: Run Database Migrations
Apply the PushSubscription migration:

```powershell
python manage.py migrate
```

### Step 3: Collect Static Files
Collect the dedicated service worker and frontend manager assets:

```powershell
python manage.py collectstatic --noinput
```

### Step 4: Restart the Application Server
Restart the actual application process after verifying whether the server runs the repository's Docker Compose setup or a systemd service. The service example in this repository uses placeholders and does not establish the live service name. See [the Scaleway release runbook](deployment/WEB_PUSH_SCALEWAY_RELEASE.md).

---

## 6. Verification & Testing

### 6.1 Service Worker Verification
Open your browser and navigate to:
```text
https://your-domain.com/sw.js
```
Confirm that:
- HTTP status is `200 OK`.
- Header `Content-Type: application/javascript; charset=utf-8` is present.
- Header `Service-Worker-Allowed: /` is present.

### 6.2 Frontend Subscription Verification
1. Log in to Fabro Leather Portal.
2. Go to **Profile Settings** (`/profile/`).
3. Locate the **Browser Notifications** card.
4. Click **Enable notifications**.
5. When the browser prompts, click **Allow**.
6. The UI status will update to **Notifications enabled**.

### 6.3 Database Verification
Verify that the subscription record exists:

```powershell
python manage.py shell -c "from management.models import PushSubscription; print(PushSubscription.objects.filter(is_active=True).values('id', 'user__username', 'endpoint', 'is_active'))"
```

### 6.4 User-Specific Delivery Test
You can test sending a test notification to a specific user via Django shell:

```powershell
python manage.py shell -c "from django.contrib.auth import get_user_model; from management.services.push_notifications import send_push_to_user; User = get_user_model(); user = User.objects.get(username='YOUR_USERNAME'); result = send_push_to_user(user, 'Fabro Test Alert', 'This is a test notification for your account.', url='/'); print('Result:', result)"
```

---

## 7. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **Notifications blocked** | Permission was denied in browser | Open site settings in your browser (lock icon in address bar) and set Notifications to "Allow". |
| **Notifications unavailable** | Unsupported browser or older device | Use modern Chrome, Edge, Firefox, or Safari (16.4+ on iOS/macOS). |
| **Secure connection required** | Accessed via plain HTTP | Access site using HTTPS or `http://localhost`. |
| **Server setup required** | Missing, invalid, or mismatched VAPID keys | Check the loaded settings and preserve the existing production pair. Restart Django after correcting its private environment. |
| **Push delivery failure (410/404)** | Browser subscription revoked or expired | The portal automatically deactivates expired subscriptions (`is_active=False`). Re-enable notifications from Profile Settings. |
| **Service worker registration failed** | Script blocked or wrong path | Confirm `/sw.js` loads with status 200 and header `Service-Worker-Allowed: /`. |
