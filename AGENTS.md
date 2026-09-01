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
* **File Storage:** Local filesystem / Supabase Storage for brand logos and complaint media files (up to 100 MB per file, max 10 files per complaint).

---

## 2. Core Domain Models & Schemas

### 2.1 Complaint Types
* **Pattern Complaints (`PAT-YYMMXXXX`):** Dimension mismatches, template issues, or cutting errors.
* **Production Complaints (`PRO-YYMMXXXX`):** Manufacturing defects, leather material flaws, or stitching errors.
* **Quality Complaints (`QUA-YYMMXXXX`):** Quality-related complaints using the same report fields and workflow as the existing complaint types.
* **Factory Complaints (`LIN-YYMMXXXX`, internal code `line`):** Urgent factory/assembly-line fitment issues. The legacy internal code and ID prefix remain stable for compatibility.

### 2.2 Workflow Statuses
1. `submitted`: Initial state upon creation.
2. `assigned_to_factory`: Forwarded to assigned Factory Executive.
3. `factory_review`: Factory Executive is formulating the action plan.
4. `awaiting_approval`: Action plan submitted, pending approver reviews.
5. `partially_approved`: Some required approvers have approved, others pending.
6. `rework_required`: Plan rejected after reconsideration; returned to factory for revision.
7. `approved`: All required approvers have granted approval (green light).
8. `action_in_progress`: Factory Executive is executing the approved plan.
9. `awaiting_execution_verification`: Execution was submitted to the original action-plan approvers for verification.
10. `execution_partially_verified`: Some required approvers verified execution; others remain pending.
11. `pending_final_update`: Every required approver verified execution; waiting for final CAD/container numbers.
12. `closed`: Final updates saved; complaint fully resolved.
13. `on_hold`: Manually paused complaint.

### 2.3 Master & Catalog Entities
* **Master Settings:** Editable categories are `Channel`, four complaint-specific type catalogs (`Pattern Complaint Type`, `Production Complaint Type`, `Quality Complaint Type`, `Factory Complaint Type`), `Series`, `Material`, and `Region`. A complaint can use only a Type from its own catalog. Complaint reporter identity and reporting country are system-assigned and are not editable master-setting options. Country records remain internal reference data for user assignment and historical complaints.
* **Vehicle Catalog:** `Brand` (with logo), `Model`, `SubModel`, `YearRange` (with `year_start`, `year_end`, `number_of_seats`, `number_of_doors`, and unique `layout_code`).
* **SKU Catalog:** `SKU` with unique `code`, `description`, and `region` reference.

---

## 3. Workflow Roles & Permissions (RBAC)

1. **Country Executive:**
   * Scoped strictly to their assigned country (`profile.country`).
   * Their profile flag and every complaint they create use their assigned country automatically.
   * Can create and view **Pattern**, **Production**, and **Quality** complaints.
   * Cannot create **Factory** complaints. Cannot view complaints from other countries.
2. **Factory Complaint Registrar:**
   * Can register **Factory** complaints only; cannot register Pattern, Production, or Quality complaints.
   * Retains normal complaint visibility, while Factory Executives and Approvers continue the existing workflow.
3. **Factory Viewer:**
   * Read-only observer across all complaints and countries. Cannot create or edit complaints or approve actions.
4. **Factory Executive:**
   * Receives complaints assigned to their factory.
   * Can register **Pattern**, **Production**, and **Quality** complaints, but not Factory complaints.
   * Conducts **Factory Review** (inputs `Factory Reason`, `Factory Action Plan`, `Factory Priority`).
   * Receives notifications for rework or green light.
   * Executes approved action plans (`Action In Progress`) and submits CAD dates and container numbers to close complaints.
5. **Approver (PM, OM, CAD, ED, MD):**
   * Configured with specific approval roles. Accesses a personal **Approval Inbox**.
   * Approves or rejects action plans during initial and reconsideration rounds.
   * After execution, the same approver accounts that reviewed the final action-plan matrix verify whether the approved plan was executed correctly.
6. **Workflow Admin / Superuser:**
   * Unrestricted management access to Master Settings, Vehicle/SKU Catalogs, User & Group creation, Session termination, and System Activity Logs.
   * Like every non-Country-Executive role, their profile flag and complaint reporting country default automatically to India.

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
                             [Phase 6: Execution Verification]
                                            │
                                            ▼
                              [Phase 7: Final Update & Closed]
```

### Phase 1: Creation & Initialization
1. Reporter fills complaint form (Complaint Type, Vehicle details, SKU, Channel, Priority, Description, Media uploads). Country and Factory Executives can register Pattern, Production, and Quality complaints; Factory Complaint Registrars can register Factory complaints only; admins can register every type. Reporter identity is the authenticated username. Country is assigned from a Country Executive's profile; all other roles report under India.
2. Unique ID generated sequentially per month (e.g., `PAT-26070001`).
3. Initial status set to `submitted`. Media files validated (max 10, max 100MB each, images/videos only).

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

### Phase 6: Execution Verification
1. When implementation is complete, the Factory Executive submits the execution for verification; status shifts to `awaiting_execution_verification`.
2. Verification tickets are issued to the same approver accounts from the latest action-plan approval matrix: Low = PM/OM/CAD, Medium = PM/OM/CAD/ED, Top = PM/OM/CAD/ED/MD.
3. While some verification decisions remain pending, status is `execution_partially_verified`.
4. If any verifier rejects, a mandatory correction comment is required, remaining verification tickets are superseded, and the complaint returns to `action_in_progress` for correction and resubmission.
5. Only unanimous verification grants the post-execution green light and changes status to `pending_final_update`.

### Phase 7: Final Update & Resolution
1. Only after unanimous execution verification does the Factory Executive see and enter mandatory **CAD Updated Date** and **New Production Container Number** (container number optional for Factory complaints).
2. Status shifts to `closed` (`status='Closed'`), setting `closed_at` timestamp and `closed_by` user.
3. Creator receives resolution notification.

---

## 5. Approvals Workspace Window (`/approvals/`)

* **Purpose & Layout:** Dedicated full-screen interactive workspace window (analogous to the chat workspace) providing live tracking and matrix visualization of complaints in both approval pipelines.
* **Separated Sub-Workspaces:** The window provides a **Before Execution** sub-workspace for action-plan approval/reconsideration and an **Execution Verification** sub-workspace for post-execution verification. Filters, counts, decisions, and history remain scoped to the selected sub-workspace.
* **Live Status Matrix:** Shows the complete reviewer grid for every complaint ("where the approval is") — highlighting each approver's role, status (`Approved`, `Rejected`, `Pending`), decision timestamp, and review comment.
* **Role-Based Access Control (RBAC):**
  * **Country Executive:** Can view approvals for complaints originating within their assigned country.
  * **Approvers (PM, OM, CAD, ED, MD):** Can view all active approvals and directly submit quick approval/reconsideration decisions via modal.
  * **Factory Executive:** Can view approvals for complaints assigned to their factory.
  * **Workflow Admin / Superuser:** Full visibility across all countries and stages.
  * **Factory Viewer:** **Strictly restricted / hidden.** Factory viewers cannot view or access the Approvals workspace window (HTTP 403 / excluded from navbar).

---

## 6. Security & System Features

* **Session Management:** Admin panel tracks active user login sessions and allows single or bulk session termination (`terminate_session_view`). Admins can reset a selected user's password through a dedicated action without submitting or modifying profile/workflow fields.
* **Activity Logging:** System changes write to `ActivityLog` (action, object type, user, timestamp).
* **Audit Edit Logs:** Field-level changes to report fields and approval decisions are preserved in `ComplaintEditLog`.
* **Timeline Events:** Every workflow transition writes a human-readable event to `ComplaintTimeline`.
* **Localization:** English is the default interface language. Authenticated users can persistently switch the portal to Arabic or Hindi from the profile dropdown. Arabic uses right-to-left document direction; Arabic and Hindi use language-appropriate system font stacks without changing the established component design.
