"""Generate a publication-grade, comprehensive PDF report of the FABRO Leather Portal."""

import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "FABRO_Portal_Complete_System_Specification_Report.pdf"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FABRO Leather Portal - Complete System Specification & Operational Architecture</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    @page {
        size: A4 portrait;
        margin: 18mm 15mm 20mm 15mm;
        @bottom-right {
            content: "Page " counter(page) " of " counter(pages);
            font-family: 'Inter', sans-serif;
            font-size: 8pt;
            color: #71717a;
        }
        @bottom-left {
            content: "FABRO Leather Portal — Complete System Specification & Architecture";
            font-family: 'Inter', sans-serif;
            font-size: 8pt;
            color: #71717a;
        }
    }

    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }

    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #18181b;
        background-color: #ffffff;
        font-size: 9.5pt;
        line-height: 1.55;
    }

    /* Cover Page */
    .cover-page {
        page-break-after: always;
        height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        padding: 40mm 20mm 25mm 20mm;
        background: linear-gradient(145deg, #09090b 0%, #18181b 50%, #27272a 100%);
        color: #ffffff;
        border-radius: 12px;
        position: relative;
        overflow: hidden;
    }

    .cover-page::before {
        content: '';
        position: absolute;
        top: -100px;
        right: -100px;
        width: 380px;
        height: 380px;
        background: radial-gradient(circle, rgba(220, 38, 38, 0.45) 0%, transparent 70%);
        border-radius: 50%;
    }

    .cover-brand {
        display: flex;
        align-items: center;
        gap: 14px;
    }

    .brand-pill {
        background: #dc2626;
        color: #ffffff;
        padding: 6px 14px;
        font-weight: 800;
        font-size: 13pt;
        letter-spacing: 2px;
        border-radius: 6px;
        text-transform: uppercase;
        display: inline-block;
    }

    .brand-tagline {
        color: #a1a1aa;
        font-size: 9.5pt;
        letter-spacing: 1px;
        text-transform: uppercase;
    }

    .cover-title-box {
        margin-top: 60px;
    }

    .cover-title {
        font-size: 32pt;
        font-weight: 800;
        line-height: 1.15;
        letter-spacing: -0.5px;
        background: linear-gradient(135deg, #ffffff 0%, #f4f4f5 50%, #dc2626 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 16px;
    }

    .cover-subtitle {
        font-size: 13pt;
        color: #d4d4d8;
        font-weight: 400;
        line-height: 1.4;
        max-width: 90%;
    }

    .cover-meta {
        border-top: 1px solid rgba(255, 255, 255, 0.15);
        padding-top: 25px;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 20px;
    }

    .meta-item-label {
        font-size: 7.5pt;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: #a1a1aa;
        margin-bottom: 4px;
    }

    .meta-item-value {
        font-size: 9.5pt;
        font-weight: 600;
        color: #fafafa;
    }

    /* Content Styling */
    .page {
        page-break-after: always;
        padding-top: 5mm;
    }

    h1, h2, h3, h4 {
        color: #09090b;
        font-weight: 700;
        letter-spacing: -0.3px;
    }

    h1 {
        font-size: 18pt;
        border-bottom: 2px solid #dc2626;
        padding-bottom: 6px;
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    h2 {
        font-size: 13pt;
        margin-top: 20px;
        margin-bottom: 10px;
        color: #18181b;
        border-left: 3.5px solid #dc2626;
        padding-left: 8px;
    }

    h3 {
        font-size: 10.5pt;
        margin-top: 14px;
        margin-bottom: 6px;
        color: #27272a;
    }

    p {
        margin-bottom: 10px;
        text-align: justify;
    }

    ul, ol {
        margin-left: 20px;
        margin-bottom: 12px;
    }

    li {
        margin-bottom: 4px;
    }

    code {
        font-family: 'JetBrains Mono', monospace;
        font-size: 8.5pt;
        background: #f4f4f5;
        padding: 2px 5px;
        border-radius: 4px;
        border: 1px solid #e4e4e7;
        color: #b91c1c;
    }

    /* Tables */
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 16px 0;
        font-size: 8.5pt;
    }

    th {
        background-color: #18181b;
        color: #ffffff;
        text-align: left;
        padding: 7px 9px;
        font-weight: 600;
        font-size: 8pt;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        border: 1px solid #18181b;
    }

    td {
        padding: 6px 9px;
        border: 1px solid #e4e4e7;
        vertical-align: top;
    }

    tr:nth-child(even) {
        background-color: #fafafa;
    }

    /* Badges & Pills */
    .badge {
        display: inline-block;
        font-size: 7pt;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }

    .badge-red { background: #fee2e2; color: #991b1b; }
    .badge-amber { background: #fef3c7; color: #92400e; }
    .badge-blue { background: #dbeafe; color: #1e40af; }
    .badge-green { background: #d1fae5; color: #065f46; }
    .badge-purple { background: #ede9fe; color: #5b21b6; }
    .badge-gray { background: #f4f4f5; color: #3f3f46; }

    /* Callout Boxes */
    .callout {
        border-left: 4px solid #dc2626;
        background: #fef2f2;
        padding: 10px 14px;
        border-radius: 0 6px 6px 0;
        margin: 12px 0;
        font-size: 9pt;
    }

    .callout-title {
        font-weight: 700;
        color: #991b1b;
        margin-bottom: 3px;
        text-transform: uppercase;
        font-size: 8pt;
        letter-spacing: 0.5px;
    }

    .callout-info {
        border-left-color: #2563eb;
        background: #eff6ff;
    }
    .callout-info .callout-title { color: #1e40af; }

    .callout-green {
        border-left-color: #10b981;
        background: #ecfdf5;
    }
    .callout-green .callout-title { color: #065f46; }

    /* Workflow Diagram Box */
    .workflow-step-box {
        display: flex;
        align-items: center;
        background: #f4f4f5;
        border: 1px solid #e4e4e7;
        padding: 9px 12px;
        border-radius: 6px;
        margin-bottom: 8px;
    }

    .step-number {
        font-size: 11pt;
        font-weight: 800;
        color: #dc2626;
        width: 32px;
        flex-shrink: 0;
    }

    .step-content {
        flex: 1;
    }

    .step-title {
        font-weight: 700;
        color: #18181b;
        font-size: 9pt;
        margin-bottom: 2px;
    }

    .step-desc {
        color: #52525b;
        font-size: 8pt;
        margin: 0;
    }

    .grid-2 {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin: 10px 0;
    }

    .feature-card {
        border: 1px solid #e4e4e7;
        background: #ffffff;
        padding: 10px 12px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }

    .feature-card h4 {
        color: #dc2626;
        font-size: 9pt;
        margin-bottom: 4px;
    }

    .feature-card p {
        font-size: 8pt;
        color: #52525b;
        margin: 0;
    }
</style>
</head>
<body>

<!-- Cover Page -->
<div class="cover-page">
    <div class="cover-brand">
        <span class="brand-pill">FABRO</span>
        <span class="brand-tagline">Automotive Interior Quality Platform</span>
    </div>

    <div class="cover-title-box">
        <h1 class="cover-title">Complete System Specification & Architecture Report</h1>
        <p class="cover-subtitle">Comprehensive functional documentation, multi-round approval engine, user permission matrix, interactive windows, and live credential directory.</p>
    </div>

    <div class="cover-meta">
        <div>
            <div class="meta-item-label">Platform Version</div>
            <div class="meta-item-value">Django 5.2 Enterprise</div>
        </div>
        <div>
            <div class="meta-item-label">Generated Date</div>
            <div class="meta-item-value">September 2026</div>
        </div>
        <div>
            <div class="meta-item-label">Classification</div>
            <div class="meta-item-value">System & User Manual</div>
        </div>
    </div>
</div>

<!-- Section 1: Executive Summary & Architecture -->
<div class="page">
    <h1>1. Executive Summary & Technology Stack</h1>
    
    <h2>1.1 System Purpose & Mission</h2>
    <p>The <strong>FABRO Leather Portal</strong> is a specialized enterprise quality assurance, defect tracking, and multi-tier workflow execution management platform built specifically for high-precision automotive leather products (car seat upholstery, door trim covers, and interior panels). The platform bridges global sales channels, regional country offices, factory production lines, engineering teams, and executive management through a unified real-time workflow.</p>

    <h2>1.2 Core Architectural Stack</h2>
    <table>
        <tr>
            <th style="width: 25%;">Layer / Component</th>
            <th style="width: 35%;">Technology Used</th>
            <th style="width: 40%;">Architectural Role & Description</th>
        </tr>
        <tr>
            <td><strong>Backend Engine</strong></td>
            <td>Python 3.12, Django 5.2 Framework</td>
            <td>Model-Template-View (MTV) core, transactional workflow state machine, ORM with database locking.</td>
        </tr>
        <tr>
            <td><strong>Database Layer</strong></td>
            <td>PostgreSQL (Cloud Supabase Instance)</td>
            <td>Relational data integrity, foreign key constraints, connection pooling, and automated schema migrations.</td>
        </tr>
        <tr>
            <td><strong>REST API Service</strong></td>
            <td>Django REST Framework (DRF)</td>
            <td>Token-authenticated endpoints located in <code>management/api_views.py</code> serving the Flutter mobile app.</td>
        </tr>
        <tr>
            <td><strong>Client Presentation</strong></td>
            <td>HTML5, Vanilla Modern CSS, JavaScript</td>
            <td>Modern dark/light glassmorphic UI, HTMX seamless fragment swaps, full LTR layout default across all languages.</td>
        </tr>
        <tr>
            <td><strong>Localization</strong></td>
            <td>Django gettext i18n & Client Catalog</td>
            <td>Persistent English, Arabic, and Hindi language support with language-appropriate system typography.</td>
        </tr>
        <tr>
            <td><strong>File & Media Storage</strong></td>
            <td>Garage S3-Compatible Object Storage</td>
            <td>Secure presigned upload URLs for complaint media (up to 100 MB per file, max 10 attachments per record).</td>
        </tr>
    </table>

    <h2>1.3 Complaint Categories & Identification Codes</h2>
    <p>Every complaint filed in the system receives a strictly sequential, month-prefixed alphanumeric identifier generated automatically:</p>
    <table>
        <tr>
            <th style="width: 20%;">Complaint Type</th>
            <th style="width: 20%;">ID Format</th>
            <th style="width: 30%;">Scope & Primary Cause</th>
            <th style="width: 30%;">Who Can Register</th>
        </tr>
        <tr>
            <td><span class="badge badge-purple">Pattern Complaint</span></td>
            <td><code>PAT-YYMMXXXX</code></td>
            <td>Dimension mismatches, cutting defects, layout code template deviations.</td>
            <td>Country Executive, Factory Executive, Admin</td>
        </tr>
        <tr>
            <td><span class="badge badge-amber">Production Complaint</span></td>
            <td><code>PRO-YYMMXXXX</code></td>
            <td>Material flaws, hide discoloration, stitching errors, assembly defects.</td>
            <td>Country Executive, Factory Executive, Admin</td>
        </tr>
        <tr>
            <td><span class="badge badge-blue">Quality Complaint</span></td>
            <td><code>QUA-YYMMXXXX</code></td>
            <td>Quality-assurance defects, grading inconsistencies, packaging wear.</td>
            <td>Country Executive, Factory Executive, Admin</td>
        </tr>
        <tr>
            <td><span class="badge badge-red">Factory Complaint</span></td>
            <td><code>FAC-YYMMXXXX</code></td>
            <td>Urgent factory/assembly-line fitment emergencies requiring rapid review.</td>
            <td>Factory Complaint Registrar, Admin</td>
        </tr>
    </table>

    <div class="callout callout-info">
        <div class="callout-title">ID Generation Guarantee</div>
        Complaint IDs are formatted sequentially per year/month (e.g., <code>PAT-26090001</code>). Generation uses transactional row-locking to ensure zero collisions, gaps, or duplicate IDs during high-concurrency operations.
    </div>
</div>

<!-- Section 2: User Roles & Permissions -->
<div class="page">
    <h1>2. Roles & Permissions Architecture (RBAC)</h1>
    <p>The system enforces strict Role-Based Access Control (RBAC) across views, APIs, navigation bars, and data visibility:</p>

    <h2>2.1 Role Profiles</h2>
    <table>
        <tr>
            <th style="width: 25%;">Workflow Role</th>
            <th style="width: 35%;">Responsibilities & Scope</th>
            <th style="width: 40%;">Data & Workflow Boundaries</th>
        </tr>
        <tr>
            <td><strong>Country Executive</strong></td>
            <td>Files customer/distributor complaints originating from their assigned market country.</td>
            <td>Scoped strictly to <code>profile.country</code>. Cannot create Factory complaints or access complaints from foreign territories.</td>
        </tr>
        <tr>
            <td><strong>Factory Complaint Registrar</strong></td>
            <td>Registers urgent factory/assembly-line fitment issues directly at manufacturing hubs.</td>
            <td>Dedicated role authorized to create <strong>Factory (Line) complaints only</strong>. Normal complaint viewing privileges.</td>
        </tr>
        <tr>
            <td><strong>Factory Viewer</strong></td>
            <td>Read-only global auditor across complaints and manufacturing metrics.</td>
            <td>Observer across all countries. Strictly forbidden from creating/editing complaints or entering approval workspaces.</td>
        </tr>
        <tr>
            <td><strong>Factory Executive</strong></td>
            <td>Technical plant lead assigned to diagnose defects, formulate action plans, and implement fixes.</td>
            <td>Submits root causes, action plans, priorities, executes approved plans, submits for verification, and closes complaints with CAD dates.</td>
        </tr>
        <tr>
            <td><strong>Approver (PM, OM, CAD, ED, MD)</strong></td>
            <td>Cross-functional leadership council reviewing, rejecting, or approving action plans and verifying execution.</td>
            <td>Accesses personal Approval Inbox and full Approvals Workspace. Votes in multi-round approval matrix and signs off on verification.</td>
        </tr>
        <tr>
            <td><strong>Workflow Admin / Superuser</strong></td>
            <td>Full system governance, catalog maintenance, user management, and security oversight.</td>
            <td>Unrestricted access to Master Settings, SKU/Vehicle Catalogs, User Groups, active session terminations, and audit logs.</td>
        </tr>
    </table>

    <h2>2.2 Granular Permissions Matrix</h2>
    <table>
        <tr>
            <th>Functional Capability</th>
            <th>Country Exec</th>
            <th>Registrar</th>
            <th>Factory Exec</th>
            <th>Approver</th>
            <th>Viewer</th>
            <th>Admin</th>
        </tr>
        <tr>
            <td>Create Pattern/Production/Quality</td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Create Factory (Line) Complaint</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Formulate Factory Action Plan</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Approve / Reject Action Plans</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Execute Approved Action Plan</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Verify Physical Execution</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Enter CAD Date & Close Case</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>Approvals Workspace Access</td>
            <td><span class="badge badge-green">Country</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Assigned</span></td>
            <td><span class="badge badge-green">All</span></td>
            <td><span class="badge badge-red">Hidden</span></td>
            <td><span class="badge badge-green">Full</span></td>
        </tr>
        <tr>
            <td>Master Settings & Catalogs CRUD</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
        <tr>
            <td>User Management & Session Termination</td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-red">No</span></td>
            <td><span class="badge badge-green">Yes</span></td>
        </tr>
    </table>
</div>

<!-- Section 3: End-to-End Complaint Lifecycle -->
<div class="page">
    <h1>3. End-to-End Complaint Lifecycle (Phases 1–7)</h1>
    <p>Every defect follows a strict 7-phase quality cycle to ensure no complaint is resolved without cross-functional consensus and verified physical execution:</p>

    <div class="workflow-step-box">
        <div class="step-number">01</div>
        <div class="step-content">
            <div class="step-title">Phase 1: Registration & Initial Intake (Status: <code>submitted</code>)</div>
            <div class="step-desc">The reporter enters Complaint Type, Vehicle details, SKU reference, Priority, and Description, attaching up to 10 photos/videos (max 100MB each). Sequential ID generated.</div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">02</div>
        <div class="step-content">
            <div class="step-title">Phase 2: Factory Assignment & Technical Review (Status: <code>factory_review</code>)</div>
            <div class="step-desc">The complaint is routed to the assigned Factory Executive. The executive analyzes the root cause and inputs <strong>Factory Reason</strong>, <strong>Action Plan</strong>, and <strong>Factory Priority</strong> (Low, Medium, Top).</div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">03</div>
        <div class="step-content">
            <div class="step-title">Phase 3: Multi-Role Approval Matrix (Status: <code>awaiting_approval</code> / <code>partially_approved</code>)</div>
            <div class="step-desc">Approval tickets are generated for all required approvers according to the Factory Priority matrix:
                <br>• <strong>Low Priority:</strong> PM (Project Manager), OM (Operations Manager), CAD (Design Specialist).
                <br>• <strong>Medium Priority:</strong> PM, OM, CAD, plus ED (Engineering Director).
                <br>• <strong>Top Priority:</strong> PM, OM, CAD, ED, plus MD (Managing Director).
            </div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">04</div>
        <div class="step-content">
            <div class="step-title">Phase 4: Rejection, Peer Reconsideration & Rework Loop (Status: <code>rework_required</code>)</div>
            <div class="step-desc">If any approver rejects, a mandatory comment is recorded. A <strong>Reconsideration Round</strong> is issued to all other required approvers. If ALL peers vote to proceed, the rejection is overridden. If ANY peer agrees with the objection, status shifts to <code>rework_required</code> and the plan returns to the Factory Executive for round revision.</div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">05</div>
        <div class="step-content">
            <div class="step-title">Phase 5: Approved Action Execution (Status: <code>approved</code> ➔ <code>action_in_progress</code>)</div>
            <div class="step-desc">Upon unanimous approval, the Factory Executive receives a green-light notification and clicks <strong>Start Action Plan</strong>. Physical adjustments (re-cutting, stitching modifications) begin.</div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">06</div>
        <div class="step-content">
            <div class="step-title">Phase 6: Execution Verification (Status: <code>awaiting_execution_verification</code>)</div>
            <div class="step-desc">Upon completing implementation, the Factory Executive submits execution for verification. The same matrix of approvers inspects photos/videos and votes to confirm correct implementation. Unanimous confirmation shifts status to <code>pending_final_update</code>.</div>
        </div>
    </div>

    <div class="workflow-step-box">
        <div class="step-number">07</div>
        <div class="step-content">
            <div class="step-title">Phase 7: Final Data Capture & Closure (Status: <code>pending_final_update</code> ➔ <code>closed</code>)</div>
            <div class="step-desc">The Factory Executive enters mandatory <strong>CAD Updated Date</strong> and <strong>New Production Container Number</strong>. The case is permanently marked <code>Closed</code> with timestamps and user attribution.</div>
        </div>
    </div>
</div>

<!-- Section 4: Interactive Windows & Features -->
<div class="page">
    <h1>4. Interactive Workspaces, Windows & Features</h1>

    <h2>4.1 System Dashboard (<code>/</code>)</h2>
    <p>The system homepage is built with a responsive two-column grid. For <strong>Approver Users and Admins</strong>, the left column automatically transforms into an optimized dual-card split view:</p>
    <ul>
        <li><strong>Upper Half — Existing Complaints:</strong> Compact section header (<code>0.92rem</code> typography), fast "+ Add" and "View All" shortcuts, and an independent scrollable table showing complaints with live status pills and collapsible quick-inspection rows.</li>
        <li><strong>Lower Half — Pending Approvals:</strong> Live pending count badge, direct "Workspace" shortcut to <code>/approvals/</code>, and a dedicated queue showing Item #, Date, Complaint ID, Review Stage badge (Initial, Reconsideration, Verification), Role Tag, Vehicle, Priority, and direct <strong>Review</strong> action button.</li>
        <li><strong>Right Column — System Statistics:</strong> Real-time counters for Open/Closed complaints, breakdown by Complaint Type, Monthly intake/resolved metrics, and direct catalog summaries.</li>
    </ul>

    <h2>4.2 Approvals Workspace Window (<code>/approvals/</code>)</h2>
    <p>Dedicated full-screen matrix interface providing real-time visibility into the approval pipeline:</p>
    <ul>
        <li><strong>Dual Sub-Workspaces:</strong> Clean toggle between <strong>Before Execution</strong> (action plan review) and <strong>Execution Verification</strong> (post-implementation sign-off).</li>
        <li><strong>Live Status Matrix:</strong> Transparently displays "where the approval is" across every required role (PM, OM, CAD, ED, MD) with timestamps, decision statuses, and reviewer comments.</li>
        <li><strong>Quick Decision Modal:</strong> Approvers can approve, reject, or submit reconsideration votes directly without leaving the workspace.</li>
    </ul>

    <h2>4.3 Complaint Directory & Server-Side Filtering (<code>/complaints/</code>)</h2>
    <p>Comprehensive complaint ledger featuring:</p>
    <ul>
        <li><strong>Header Column Filters:</strong> Instant dropdown filtering by Priority, Type, Workflow Status, Vehicle Brand, SubCategory, and Factory.</li>
        <li><strong>Instant Search:</strong> Full-text keyword search by Complaint ID, Vehicle, or Description.</li>
        <li><strong>CSV Export:</strong> One-click export of filtered complaint sets for offline engineering review.</li>
    </ul>

    <h2>4.4 Real-Time Chat Workspace (<code>/chat/</code>)</h2>
    <p>Integrated inter-user messaging system allowing Country Executives, Factory Executives, Approvers, and Admins to coordinate directly:</p>
    <ul>
        <li><strong>Complaint Context Attachment:</strong> Messages can be directly linked to a specific Complaint ID, allowing immediate preview and navigation.</li>
        <li><strong>Role Badging:</strong> User directory highlights active roles and assigned factories.</li>
    </ul>

    <h2>4.5 Master Settings & Catalogs (<code>/master-settings/</code>, <code>/car-details/</code>, <code>/add-sku/</code>)</h2>
    <div class="grid-2">
        <div class="feature-card">
            <h4>Vehicle Catalog</h4>
            <p>Comprehensive vehicle database tracking Brand (with logos), Model, SubModel, Year Range, seats, doors, and unique <strong>Layout Code</strong>. Includes bulk CSV import.</p>
        </div>
        <div class="feature-card">
            <h4>SKU Catalog</h4>
            <p>Inventory SKU directory linking item code, description, and regional distribution. Features dynamic keyboard-navigable search picker and CSV import.</p>
        </div>
        <div class="feature-card">
            <h4>Master Settings</h4>
            <p>Admin configuration of Channels (e.g. WhatsApp, Retail), Materials (Rexin, Leather), Series (Luxe), Regions, and Type catalogs.</p>
        </div>
        <div class="feature-card">
            <h4>Admin Security Suite</h4>
            <p>Active user session tracker with remote kill switch, dedicated user password reset, and user group management.</p>
        </div>
    </div>
</div>

<!-- Section 5: Security, Audit & Test Credentials -->
<div class="page">
    <h1>5. Security, Audit Logs & System User Directory</h1>

    <h2>5.1 Security & System Observability</h2>
    <ul>
        <li><strong>Active Session Management:</strong> The admin panel monitors all active HTTP sessions with IP address, device user-agent, and remote single/bulk termination controls (<code>terminate_session_view</code>).</li>
        <li><strong>Complaint Audit Trail (<code>ComplaintEditLog</code>):</strong> Preserves field-level before/after changes to report attributes, root causes, and approval decisions.</li>
        <li><strong>Workflow Timeline (<code>ComplaintTimeline</code>):</strong> Human-readable chronological audit history attached to every complaint record tracking every transition from submission to closure.</li>
        <li><strong>System Activity Log (<code>ActivityLog</code>):</strong> Comprehensive operational logging of user logins, catalog updates, and administrative modifications.</li>
        <li><strong>Directional Integrity (LTR Default):</strong> The portal layout remains strictly Left-to-Right by default across English, Arabic, and Hindi, utilizing Arabic/Hindi system font stacks without mirroring the interface.</li>
    </ul>

    <h2>5.2 Active System Users & Test Credentials Directory</h2>
    <p>The following table documents all user accounts currently registered in the database, including their workflow role, country/role scope, and verified access credentials:</p>

    <table>
        <tr>
            <th style="width: 18%;">Username</th>
            <th style="width: 22%;">Assigned Workflow Role</th>
            <th style="width: 18%;">Role / Country Scope</th>
            <th style="width: 24%;">Email Address</th>
            <th style="width: 18%;">Password</th>
        </tr>
        <tr>
            <td><code>admin</code></td>
            <td><span class="badge badge-red">Admin / Superuser</span></td>
            <td>Global / Superuser</td>
            <td><code>admin@fabro.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_admin</code></td>
            <td><span class="badge badge-red">Admin / Superuser</span></td>
            <td>Global / Superuser</td>
            <td><code>audit_admin@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_country</code></td>
            <td><span class="badge badge-blue">Country Executive</span></td>
            <td>KSA (Saudi Arabia)</td>
            <td><code>audit_country@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_faccomplaint</code></td>
            <td><span class="badge badge-purple">Factory Registrar</span></td>
            <td>Factory Complaints Only</td>
            <td><em>Not Assigned</em></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_factory</code></td>
            <td><span class="badge badge-amber">Factory Executive</span></td>
            <td>Assigned Factory Plant</td>
            <td><code>audit_factory@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_pm</code></td>
            <td><span class="badge badge-green">Approver (PM)</span></td>
            <td>Project Manager Matrix</td>
            <td><code>audit_pm@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_om</code></td>
            <td><span class="badge badge-green">Approver (OM)</span></td>
            <td>Operations Manager Matrix</td>
            <td><code>audit_om@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_cad</code></td>
            <td><span class="badge badge-green">Approver (CAD)</span></td>
            <td>CAD Specialist Matrix</td>
            <td><code>audit_cad@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_ed</code></td>
            <td><span class="badge badge-green">Approver (ED)</span></td>
            <td>Engineering Director Matrix</td>
            <td><code>audit_ed@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_md</code></td>
            <td><span class="badge badge-green">Approver (MD)</span></td>
            <td>Managing Director Matrix</td>
            <td><code>audit_md@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>audit_viewer</code></td>
            <td><span class="badge badge-gray">Factory Viewer</span></td>
            <td>Read-Only Global Observer</td>
            <td><code>audit_viewer@example.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>staffuser1</code></td>
            <td><span class="badge badge-gray">Factory Viewer</span></td>
            <td>Read-Only Observer</td>
            <td><code>staff@fabro.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
        <tr>
            <td><code>test</code></td>
            <td><span class="badge badge-gray">Factory Viewer</span></td>
            <td>Read-Only Observer</td>
            <td><code>test@test.com</code></td>
            <td><code>fabro123</code></td>
        </tr>
    </table>

    <div class="callout callout-green">
        <div class="callout-title">Unified Authentication Standard</div>
        All test and operational accounts listed above are fully verified and authenticated with password <code>fabro123</code> for seamless local evaluation and automated verification.
    </div>
</div>

</body>
</html>
"""

def main():
    print("Generating PDF from HTML template...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(HTML_CONTENT, wait_until="networkidle")
        page.pdf(
            path=str(PDF_PATH),
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            display_header_footer=False,
        )
        browser.close()
    print(f"Successfully generated PDF report at: {PDF_PATH}")
    print(f"File size: {PDF_PATH.stat().st_size / 1024:.2f} KB")

if __name__ == "__main__":
    main()
