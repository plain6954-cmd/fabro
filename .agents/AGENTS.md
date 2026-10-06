# FABRO Leather Portal — Complete System Architecture & Operational Workflow

> [!IMPORTANT]
> **AUTONOMOUS EXECUTION DIRECTIVE:**
> DO ANY ACTION THAT CAN BE DONE THEMSELVES WITHOUT ASKING APPROVAL FROM ME INCLUDING APPS and PERFORMING and VERIFICATION.

This document serves as the authoritative specification for the **FABRO Leather Portal** codebase, architecture, role permissions, and end-to-end complaint tracking workflow.

---

## 1. System Overview & Technology Stack

* **Core Purpose:** Quality management and workflow tracking platform for automotive leather products (car seat covers, interior upholstery, door panels).
* **Backend:** Django 5.2 (Python) web framework with Django ORM.
* **Database:** PostgreSQL (Supabase host).
* **REST API:** Django REST Framework (DRF) endpoints in `management/api_views.py` serving the Flutter mobile app in `mobile/`.
* **Frontend:** Server-rendered HTML5 templates (`management/templates/`) styled with vanilla CSS (dark/light mode support) and JavaScript.
* **File Storage:** Local filesystem / Garage S3-compatible object storage for brand logos and complaint media files (up to 100 MB per file, max 10 files per complaint).

---

## 2. Core Domain Models & Schemas

### 2.1 Complaint Types
* **Pattern Complaints (`PAT-YYMMXXXX`):** Dimension mismatches, template issues, or cutting errors.
* **Production Complaints (`PRO-YYMMXXXX`):** Manufacturing defects, leather material flaws, or stitching errors.
* **Factory Complaints (`FAC-YYMMXXXX`, internal code `line`):** Urgent factory/assembly-line fitment issues. Generates `FAC` prefix codes while retaining backward-compatibility with historical `LIN`/`LINE` codes.

### 2.2 Workflow Statuses
1. `submitted`: Initial state upon creation.
2. `assigned_to_factory`: Forwarded to assigned Factory Executive.
3. `factory_review`: Factory Executive is formulating the action plan.
4. `awaiting_approval`: Action plan submitted, pending approver reviews.
5. `partially_approved`: Some required approvers have approved, others pending.
6. `rework_required`: Plan rejected after reconsideration; returned to factory for revision.
7. `approved`: All required approvers have granted approval (green light).
8. `action_in_progress`: Factory Executive is executing the approved plan.
9. `pending_final_update`: Execution complete; waiting for final CAD/container numbers.
10. `closed`: Final updates saved; complaint fully resolved.
11. `on_hold`: Manually paused complaint.

### 2.3 Master & Catalog Entities
* **Master Settings:** Categories for `Channel`, `Country`, `Reported By`, `Type`, `Series`, `Material`, `Region`.
* **Vehicle Catalog:** `Brand` (with logo), `Model`, `SubModel`, `YearRange` (with `year_start`, `year_end`, `number_of_seats`, `number_of_doors`, and unique `layout_code`).
* **SKU Catalog:** `SKU` with unique `code`, `description`, and `region` reference.

---

## 3. Workflow Roles & Permissions (RBAC)

1. **Country Executive:**
   * Scoped strictly to their assigned country (`profile.country`).
   * Can create and view **Pattern** and **Production** complaints.
   * Cannot create **Line** complaints. Cannot view complaints from other countries.
2. **Factory Viewer:**
   * Read-only observer across all complaints and countries. Cannot create or edit complaints or approve actions.
3. **Factory Executive:**
   * Receives complaints assigned to their factory.
   * Conducts **Factory Review** (inputs `Factory Reason`, `Factory Action Plan`, `Factory Priority`).
   * Receives notifications for rework or green light.
   * Executes approved action plans (`Action In Progress`) and submits CAD dates and container numbers to close complaints.
4. **Approver (PM, OM, CAD, ED, MD):**
   * Configured with specific approval roles. Accesses a personal **Approval Inbox**.
   * Approves or rejects action plans during initial and reconsideration rounds.
5. **Workflow Admin / Superuser:**
   * Unrestricted management access to Master Settings, Vehicle/SKU Catalogs, User & Group creation, Session termination, and System Activity Logs.
6. **3D Designer Freelancer:**
   * External CAD and 3D modeling specialist for seat patterns and vehicle upholstery.
   * Has access to Pattern Master (`/car-details/`), vehicle design folders, design image uploads/downloads, and Google Drive 3D CAD folder linking.
   * Can view pattern alterations and pattern complaints (`PAT-...`) in read-only mode to assess fitment issues.
   * Strictly restricted from internal Approvals workspace, Admin Suite, Master Settings, and registering complaints. Defaults to India.

---

## 4. End-to-End Complaint Lifecycle (From Start to Finish)

```
[Phase 1: Creation] ──► [Phase 2: Factory Review] ──► [Phase 3: Approval Matrix]
                                                              │
                                            ┌─────────────────┴─────────────────┐
                                            ▼                                   ▼
                                     (Full Approval)                     (Rejection)
                                            │                                   │
                                            ▼                                   ▼
                               [Phase 5: Action Execution] ◄─── [Phase 4: Reconsideration & Rework]
                                            │
                                            ▼
                                   [Phase 6: Closed]
```

### Phase 1: Creation & Initialization
1. Reporter fills complaint form (Complaint Type, Vehicle details, SKU, Channel, Priority, Description, Media uploads).
2. Unique ID generated sequentially per month (e.g., `PAT-26070001`).
3. Initial status set to `submitted`. Media files validated (max 10, max 10MB each, images/videos only).

### Phase 2: Factory Assignment & Review
1. Complaint assigned to Factory Executive; status shifts to `factory_review`.
2. Factory Executive inputs:
   * **Factory Reason** (root cause explanation)
   * **Factory Action Plan** (corrective steps)
   * **Factory Priority** (`low`, `medium`, `top`)
3. On submission, approval records are created for required approvers based on priority matrix. Status shifts to `awaiting_approval`.

### Phase 3: Multi-Round Approval Engine
1. Approvers receive real-time inbox items and notifications.
2. Each approver evaluates the plan and submits **Approve** or **Reject**.
3. Status advances to `partially_approved` as approvals arrive.

### Phase 4: Rejection, Peer Reconsideration & Rework Loop
1. **Initial Rejection:** If an approver rejects, a mandatory rejection comment is required.
2. **Reconsideration Round:** Instead of immediate termination, a reconsideration round is created. All *other* required approvers are notified with the rejection comment.
3. **Voting Options:**
   * **Approve ("Chose to proceed"):** Vote to proceed despite the objection.
   * **Reject ("Requested rework"):** Vote to return plan for rework.
4. **Resolution:**
   * If **ALL** other approvers vote to proceed, the rejection is overridden and the complaint is **`APPROVED`**.
   * If **ANY** approver agrees to reject, status shifts to **`rework_required`**.
5. **Rework Cycle:**
   * Factory Executive is notified; complaint returns to Factory Review.
   * Factory Executive updates reason, action plan, and priority.
   * Submission increments approval round number (e.g., Round 1 ➔ Round 2) and issues fresh approval tickets.

### Phase 5: Approved Action Execution
1. Once fully approved, status changes to `approved` and Factory Executive receives green-light notification.
2. Factory Executive clicks **Start Action Plan**; status shifts to `action_in_progress`.

### Phase 6: Final Update & Resolution
1. Factory Executive enters mandatory **CAD Updated Date** and **New Production Container Number** (container number optional for Line complaints).
2. Status shifts to `closed` (`status='Closed'`), setting `closed_at` timestamp and `closed_by` user.
3. Creator receives resolution notification.

---

## 5. Approvals Workspace Window (`/approvals/`)

* **Purpose & Layout:** Dedicated full-screen interactive workspace window (analogous to the chat workspace) providing live tracking and matrix visualization of complaints currently in the approval pipeline (`awaiting_approval`, `partially_approved`, `reconsideration`, `approved`).
* **Live Status Matrix:** Shows the complete reviewer grid for every complaint ("where the approval is") — highlighting each approver's role, status (`Approved`, `Rejected`, `Pending`), decision timestamp, and review comment.
* **Role-Based Access Control (RBAC):**
  * **Country Executive:** Can view approvals for complaints originating within their assigned country.
  * **Approvers (PM, OM, CAD, ED, MD):** Can view all active approvals and directly submit quick approval/reconsideration decisions via modal.
  * **Factory Executive:** Can view approvals for complaints assigned to their factory.
  * **Workflow Admin / Superuser:** Full visibility across all countries and stages.
  * **Factory Viewer:** **Strictly restricted / hidden.** Factory viewers cannot view or access the Approvals workspace window (HTTP 403 / excluded from navbar).

---

## 6. Security & System Features

* **Session Management:** Admin panel tracks active user login sessions and allows single or bulk session termination (`terminate_session_view`).
* **Activity Logging:** System changes write to `ActivityLog` (action, object type, user, timestamp).
* **Audit Edit Logs:** Field-level changes to report fields and approval decisions are preserved in `ComplaintEditLog`.
* **Timeline Events:** Every workflow transition writes a human-readable event to `ComplaintTimeline`.

---

## 7. Notification & Web Push Synchronization

Web Push is ALREADY implemented in Fabro.
Do NOT rebuild, duplicate, or replace the existing Web Push architecture.

For EVERY future workflow or business-logic change, perform a Notification Impact Check.
This applies especially to:
- assignments and reassignments
- approval requests
- approvals
- declines/rejections
- reviewer comments
- designer submissions
- designer resubmissions
- complaint status changes
- workflow status transitions
- completion/closure
- user-role changes
- permission changes
- URLs used as notification destinations

After implementing a workflow change, determine:
1. Does another user need to know this happened?
2. Has the notification recipient changed?
3. Has the notification trigger changed?
4. Has the notification message changed?
5. Has the notification destination URL changed?
6. Has authorization/visibility of the destination changed?
7. Should the event create an in-app notification?
8. Should the event create a Web Push notification?
9. Could the change cause duplicate notifications?
10. Are existing notification tests still correct?

If there is NO notification impact:
Do not modify the notification system unnecessarily.
Report: `NOTIFICATION IMPACT: None`

If there IS an impact:
Update the EXISTING Fabro notification architecture.
Do NOT create:
- another PushSubscription model
- another Web Push service
- another service worker
- another VAPID configuration
- duplicate subscription endpoints
- parallel notification architecture

Inspect and reuse the existing implementation.
Keep:
```
Business Event
    ├── In-App Notification
    └── Web Push when appropriate
```
Recipients must always be calculated server-side from the actual workflow.
Never trust frontend-supplied recipient IDs.
Use `request.user` and existing role/relationship logic where appropriate.
Notifications representing database changes should only be triggered after successful commits.
Reuse `transaction.on_commit()`, `send_push_on_commit()`, or the existing equivalent where appropriate.
Push failure must NEVER break the underlying Fabro operation.
Avoid duplicate notifications caused by multiple:
- views
- signals
- services
- model hooks
There should be one authoritative notification trigger for each business event.
Keep Web Push payloads privacy-safe.
Detailed comments, customer information, internal notes, phone numbers, or other sensitive information should remain inside authenticated Fabro pages.
Notification destination URLs must remain same-origin and must still pass normal Django authentication and authorization.
A notification NEVER grants access to its destination.

### Designer Approval Notification Rule
The Designer approval workflow has a permanent notification requirement.

Designer submits/resubmits a design:
* Recipients: CAD + ED
* Channels: In-App + existing Web Push

CAD approves/declines:
* Recipient: Designer who submitted the design
* Channels: In-App + existing Web Push

ED approves/declines:
* Recipient: Designer who submitted the design
* Channels: In-App + existing Web Push

CAD and ED are independent reviewers.
Decline requires a comment.
The Designer must be able to view the CAD and ED decisions and comments inside Fabro.
Do not include the complete reviewer comment in Web Push.
Overall approval requires: CAD Approved + ED Approved.
Either reviewer declining means changes are required.
A revised/resubmitted design must enter a new/current review cycle. Previous approvals must not accidentally count as approval of the revised design.
Resubmission must notify CAD + ED again.

### Required Testing
Whenever a workflow modification affects notifications, update tests to verify:
- correct recipient
- unrelated users are not notified
- correct in-app notification
- correct Web Push trigger
- correct destination
- no duplicate notification
- authorization still enforced
- push failure does not break the workflow
Mock external Web Push delivery during automated tests.

### Completion Requirement
Before declaring any workflow task complete, report:
`NOTIFICATION IMPACT: None`
or:
`NOTIFICATION IMPACT: Updated`
If updated, report:
Event:
Recipient(s):
In-App:
Web Push:
Destination:
Trigger:
Tests:
This Notification Impact Check is mandatory for all future Fabro workflow changes.


