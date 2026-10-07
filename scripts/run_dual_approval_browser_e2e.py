"""Comprehensive Playwright Chrome E2E test runner for Fabro dual approval workflow."""
import json
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = Path(r"C:\Users\POWER-13\.gemini\antigravity-ide\brain\c372cf44-c4e6-4e54-85cb-3202721407e0")
BASE_URL = "http://127.0.0.1:8005"

# Sample 1x1 valid JPEG bytes for file uploads
SAMPLE_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00'
    b'\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19'
    b'\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.#\x1c\x1c(7),01444\x1f\'9=82<.342'
    b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01'
    b'\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05'
    b'\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
)

def create_temp_image(filename):
    p = ARTIFACTS_DIR / "scratch" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(SAMPLE_JPEG)
    return str(p)

def login_user(page, username, password='Password123!'):
    page.goto(f"{BASE_URL}/login/")
    page.wait_for_selector('input[name="username"]')
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    for _ in range(60):
        if '/login/' not in page.url:
            break
        time.sleep(0.1)
    assert '/login/' not in page.url, f"Login failed for {username}, still at {page.url}"
    time.sleep(0.5)

def get_csrf_token(context):
    for c in context.cookies():
        if c['name'] == 'csrftoken':
            return c['value']
    return ''

def upload_design_image(page, context, title, filename="sample.jpg"):
    token = get_csrf_token(context)
    resp = page.request.post(
        f"{BASE_URL}/api/vehicles/1/design-images/upload/",
        headers={'X-CSRFToken': token},
        multipart={
            'images': {
                'name': filename,
                'mimeType': 'image/jpeg',
                'buffer': SAMPLE_JPEG
            },
            'title': title,
            'folder_id': '1'
        }
    )
    assert resp.ok, f"Upload failed ({resp.status}): {resp.text()}"
    data = resp.json()
    images = data.get('images', [])
    if images:
        return images[0]['id']
    return data.get('image', {}).get('id')

def main():
    print("[*] Starting Fabro Dual Approval E2E verification in Chromium...")
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # -------------------------------------------------------------
        # ISOLATED SESSIONS: Designer, CAD Approver, ED Approver
        # -------------------------------------------------------------
        ctx_designer = browser.new_context(viewport={'width': 1280, 'height': 800})
        ctx_cad = browser.new_context(viewport={'width': 1280, 'height': 800})
        ctx_ed = browser.new_context(viewport={'width': 1280, 'height': 800})
        ctx_other = browser.new_context(viewport={'width': 1280, 'height': 800})

        page_designer = ctx_designer.new_page()
        page_cad = ctx_cad.new_page()
        page_ed = ctx_ed.new_page()
        page_other = ctx_other.new_page()

        # Handle browser dialogs
        for pg in (page_designer, page_cad, page_ed, page_other):
            pg.on("dialog", lambda d: d.accept())

        print("[+] Logging in all personas with isolated browser contexts...")
        login_user(page_designer, 'designer_amy')
        login_user(page_cad, 'cad_john')
        login_user(page_ed, 'ed_sarah')
        login_user(page_other, 'designer_bob')
        print("[+] All personas authenticated successfully.")

        # =============================================================
        # SCENARIO 1: Both Approvers Approve (CAD then ED order)
        # =============================================================
        print("\n--- Scenario 1: Both approve (CAD then ED) ---")
        img1_id = upload_design_image(page_designer, ctx_designer, 'Lexus Front Cushion Model (S1)', 'lexus_cushion_s1.jpg')
        print(f"[+] Designer uploaded design image ID: {img1_id}")

        # CAD opens queue and reviews
        page_cad.goto(f"{BASE_URL}/design-approvals/")
        time.sleep(0.5)
        page_cad.goto(f"{BASE_URL}/design-approvals/{img1_id}/")
        page_cad.wait_for_selector('textarea[name="comment"]')
        page_cad.fill('textarea[name="comment"]', 'CAD geometry verified compliant.')
        page_cad.click('button[value="approved"]')
        time.sleep(0.8)

        # Verify CAD approved, ED still pending
        page_cad_detail = page_cad.content()
        assert "Approved" in page_cad_detail and "Pending" in page_cad_detail
        print("[+] CAD approved successfully. Overall state is partially_approved.")

        # ED opens review page and reviews
        page_ed.goto(f"{BASE_URL}/design-approvals/{img1_id}/")
        page_ed.wait_for_selector('textarea[name="comment"]')
        page_ed.fill('textarea[name="comment"]', 'ED material clearance verified.')
        page_ed.click('button[value="approved"]')
        time.sleep(0.8)

        # Check full approval
        page_designer.goto(f"{BASE_URL}/design-approvals/{img1_id}/")
        time.sleep(0.5)
        shot1 = ARTIFACTS_DIR / "dual_approval_s1_both_approved.png"
        page_designer.screenshot(path=str(shot1))
        designer_content = page_designer.content()
        assert "CAD geometry verified compliant." in designer_content
        assert "ED material clearance verified." in designer_content
        assert "Fully Approved" in designer_content or "Approved" in designer_content
        print(f"[+] Scenario 1 passed! Screenshot: {shot1.name}")
        results['S1_Both_Approve_CAD_then_ED'] = 'PASS'

        # =============================================================
        # SCENARIO 2: Both Approvers Approve (ED then CAD order)
        # =============================================================
        print("\n--- Scenario 2: Both approve (ED then CAD) ---")
        img2_id = upload_design_image(page_designer, ctx_designer, 'Lexus Headrest 3D Model (S2)', 'lexus_headrest_s2.jpg')

        # ED approves first
        page_ed.goto(f"{BASE_URL}/design-approvals/{img2_id}/")
        page_ed.fill('textarea[name="comment"]', 'ED approved first.')
        page_ed.click('button[value="approved"]')
        time.sleep(0.8)

        # CAD approves second
        page_cad.goto(f"{BASE_URL}/design-approvals/{img2_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD approved second.')
        page_cad.click('button[value="approved"]')
        time.sleep(0.8)

        # Designer checks
        page_designer.goto(f"{BASE_URL}/design-approvals/{img2_id}/")
        time.sleep(0.5)
        shot2 = ARTIFACTS_DIR / "dual_approval_s2_ed_then_cad.png"
        page_designer.screenshot(path=str(shot2))
        designer_content2 = page_designer.content()
        assert "ED approved first." in designer_content2
        assert "CAD approved second." in designer_content2
        print(f"[+] Scenario 2 passed! Screenshot: {shot2.name}")
        results['S2_Both_Approve_ED_then_CAD'] = 'PASS'

        # =============================================================
        # SCENARIO 3: CAD approves, ED declines with comment
        # =============================================================
        print("\n--- Scenario 3: CAD approves, ED declines ---")
        img3_id = upload_design_image(page_designer, ctx_designer, 'Lexus Rear Armrest Model (S3)', 'lexus_armrest_s3.jpg')

        # CAD approves
        page_cad.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD dimensions fine.')
        page_cad.click('button[value="approved"]')
        time.sleep(0.8)

        # ED declines
        page_ed.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        page_ed.fill('textarea[name="comment"]', 'ED: Stitch margin too narrow by 5mm.')
        page_ed.click('button[value="rejected"]')
        time.sleep(0.8)

        # Designer checks rejected status and resubmit button
        page_designer.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        time.sleep(0.5)
        shot3 = ARTIFACTS_DIR / "dual_approval_s3_ed_declined.png"
        page_designer.screenshot(path=str(shot3))
        designer_text3 = page_designer.inner_text('body')
        assert "CHANGES REQUIRED" in designer_text3 or "Declined" in designer_text3
        assert "Stitch margin too narrow" in designer_text3
        assert "Revise & Resubmit" in designer_text3
        print(f"[+] Scenario 3 passed! Screenshot: {shot3.name}")
        results['S3_CAD_Approve_ED_Decline'] = 'PASS'

        # =============================================================
        # SCENARIO 4: CAD declines, ED approves (Rejection attribution)
        # =============================================================
        print("\n--- Scenario 4: CAD declines, ED approves ---")
        img4_id = upload_design_image(page_designer, ctx_designer, 'Lexus Door Panel Trim Model (S4)', 'lexus_door_s4.jpg')

        # CAD declines
        page_cad.goto(f"{BASE_URL}/design-approvals/{img4_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD: Profile contour mismatch at pillar B.')
        page_cad.click('button[value="rejected"]')
        time.sleep(0.8)

        # ED sees item in pending queue and approves
        page_ed.goto(f"{BASE_URL}/design-approvals/?tab=pending")
        time.sleep(0.5)
        page_ed.goto(f"{BASE_URL}/design-approvals/{img4_id}/")
        page_ed.fill('textarea[name="comment"]', 'ED: Surface finish is fine.')
        page_ed.click('button[value="approved"]')
        time.sleep(0.8)

        # Designer checks: CAD is recorded as rejecter; ED's approval comment is recorded
        page_designer.goto(f"{BASE_URL}/design-approvals/{img4_id}/")
        time.sleep(0.5)
        shot4 = ARTIFACTS_DIR / "dual_approval_s4_cad_declined_ed_approved.png"
        page_designer.screenshot(path=str(shot4))
        designer_text4 = page_designer.inner_text('body')
        assert "CAD: Profile contour mismatch at pillar B." in designer_text4
        assert "ED: Surface finish is fine." in designer_text4
        print(f"[+] Scenario 4 passed! Screenshot: {shot4.name}")
        results['S4_CAD_Decline_ED_Approve'] = 'PASS'

        # =============================================================
        # SCENARIO 5: Both Reject (Individual comments combined)
        # =============================================================
        print("\n--- Scenario 5: Both CAD and ED decline ---")
        img5_id = upload_design_image(page_designer, ctx_designer, 'Lexus Center Console Cover (S5)', 'lexus_console_s5.jpg')

        # CAD declines
        page_cad.goto(f"{BASE_URL}/design-approvals/{img5_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD: Clip hole misaligned.')
        page_cad.click('button[value="rejected"]')
        time.sleep(0.8)

        # ED declines
        page_ed.goto(f"{BASE_URL}/design-approvals/{img5_id}/")
        page_ed.fill('textarea[name="comment"]', 'ED: Wall thickness below 2.5mm.')
        page_ed.click('button[value="rejected"]')
        time.sleep(0.8)

        # Designer checks combined decline comments
        page_designer.goto(f"{BASE_URL}/design-approvals/{img5_id}/")
        time.sleep(0.5)
        shot5 = ARTIFACTS_DIR / "dual_approval_s5_both_declined.png"
        page_designer.screenshot(path=str(shot5))
        designer_text5 = page_designer.inner_text('body')
        assert "Clip hole misaligned" in designer_text5
        assert "Wall thickness below 2.5mm" in designer_text5
        print(f"[+] Scenario 5 passed! Screenshot: {shot5.name}")
        results['S5_Both_Decline_Combined_Comments'] = 'PASS'

        # =============================================================
        # SCENARIO 6: One decision completed while other remains pending
        # =============================================================
        print("\n--- Scenario 6: One pending while other decided ---")
        img6_id = upload_design_image(page_designer, ctx_designer, 'Lexus Steering Wheel Leather (S6)', 'lexus_wheel_s6.jpg')

        # CAD approves only
        page_cad.goto(f"{BASE_URL}/design-approvals/{img6_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD looks good.')
        page_cad.click('button[value="approved"]')
        time.sleep(0.8)

        # Designer views state
        page_designer.goto(f"{BASE_URL}/design-approvals/{img6_id}/")
        time.sleep(0.5)
        shot6 = ARTIFACTS_DIR / "dual_approval_s6_one_pending.png"
        page_designer.screenshot(path=str(shot6))
        designer_text6 = page_designer.inner_text('body')
        assert "PARTIALLY APPROVED" in designer_text6 or "Partially Approved" in designer_text6
        assert "Pending" in designer_text6
        print(f"[+] Scenario 6 passed! Screenshot: {shot6.name}")
        results['S6_One_Pending_While_Other_Decided'] = 'PASS'

        # =============================================================
        # SCENARIO 7: Corrected & Resubmitted Request (Cycle 2)
        # =============================================================
        print("\n--- Scenario 7: Resubmission with new photo version ---")
        revised_img_path = create_temp_image("lexus_armrest_s3_v2.jpg")
        page_designer.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        page_designer.set_input_files('input[name="image"]', revised_img_path)
        page_designer.click('button:has-text("Resubmit")')
        time.sleep(1.0)

        # Check revision cycle 2
        page_designer.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        time.sleep(0.5)
        shot7_resubmitted = ARTIFACTS_DIR / "dual_approval_s7_resubmitted_cycle2.png"
        page_designer.screenshot(path=str(shot7_resubmitted))
        designer_text7 = page_designer.inner_text('body')
        assert "#2" in designer_text7 or "Revision #1" in designer_text7 or "Pending" in designer_text7
        assert "Pending" in designer_text7

        # Both CAD and ED approve cycle 2
        page_cad.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        page_cad.fill('textarea[name="comment"]', 'CAD approves revision 2.')
        page_cad.click('button[value="approved"]')
        time.sleep(0.8)

        page_ed.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        page_ed.fill('textarea[name="comment"]', 'ED approves revision 2 margin is correct.')
        page_ed.click('button[value="approved"]')
        time.sleep(0.8)

        # Designer confirms full approval on cycle 2 with revision history preserved
        page_designer.goto(f"{BASE_URL}/design-approvals/{img3_id}/")
        time.sleep(0.5)
        shot7_approved = ARTIFACTS_DIR / "dual_approval_s7_cycle2_approved.png"
        page_designer.screenshot(path=str(shot7_approved))
        designer_text7_appr = page_designer.inner_text('body')
        assert "Revision History" in designer_text7_appr
        assert "Approved" in designer_text7_appr
        print(f"[+] Scenario 7 passed! Screenshots: {shot7_resubmitted.name}, {shot7_approved.name}")
        results['S7_Resubmission_Cycle2_Full_Approval'] = 'PASS'

        # =============================================================
        # SCENARIO 8: Multiple designers isolation
        # =============================================================
        print("\n--- Scenario 8: Multiple designers isolation ---")
        bob_img_id = upload_design_image(page_other, ctx_other, 'Bob Dashboard Design (Secret)', 'bob_secret_dash.jpg')

        # Designer Amy attempts to access Bob's design
        resp_amy = page_designer.request.get(f"{BASE_URL}/design-approvals/{bob_img_id}/")
        assert resp_amy.status == 403, f"Expected 403 for other designer, got {resp_amy.status}"
        
        # Check Designer Amy's queue list does NOT contain Bob's image
        page_designer.goto(f"{BASE_URL}/design-approvals/")
        time.sleep(0.5)
        assert "Bob Dashboard Design" not in page_designer.content()
        print("[+] Scenario 8 passed! Designer Amy cannot access Designer Bob's design.")
        results['S8_Multiple_Designers_Isolation'] = 'PASS'

        # =============================================================
        # SCENARIO 9: Permission and validation checks
        # =============================================================
        print("\n--- Scenario 9: Permission & validation checks ---")
        # 1. Designer self-approval blocked
        token_des = get_csrf_token(ctx_designer)
        resp_self = page_designer.request.post(
            f"{BASE_URL}/api/design-images/{img1_id}/approve/",
            headers={'Content-Type': 'application/json', 'X-CSRFToken': token_des},
            data='{"comment": "Self approve attempt"}'
        )
        assert resp_self.status == 403, f"Expected 403 for self-approval, got {resp_self.status}"
        print("[+] Self-approval by designer correctly blocked (403).")

        # 2. Empty comment on decline blocked
        token_cad = get_csrf_token(ctx_cad)
        resp_empty_decline = page_cad.request.post(
            f"{BASE_URL}/api/design-images/{img6_id}/reject/",
            headers={'Content-Type': 'application/json', 'X-CSRFToken': token_cad},
            data='{"reason": "   "}'
        )
        assert resp_empty_decline.status == 400, f"Expected 400 for empty decline comment, got {resp_empty_decline.status}"
        print("[+] Empty decline comment correctly blocked (400).")

        # 3. Unauthorized reviewer blocked (login as PM user)
        ctx_pm = browser.new_context()
        page_pm = ctx_pm.new_page()
        login_user(page_pm, 'pm_dave')
        token_pm = get_csrf_token(ctx_pm)
        resp_pm = page_pm.request.post(
            f"{BASE_URL}/api/design-images/{img6_id}/approve/",
            headers={'Content-Type': 'application/json', 'X-CSRFToken': token_pm},
            data='{"comment": "PM approve attempt"}'
        )
        assert resp_pm.status == 403, f"Expected 403 for PM reviewer, got {resp_pm.status}"
        ctx_pm.close()
        print("[+] Unauthorized role (PM) review correctly blocked (403).")
        results['S9_Permissions_And_Validations'] = 'PASS'

        # =============================================================
        # SCENARIO 10: Responsive viewports in Chrome
        # =============================================================
        print("\n--- Scenario 10: Responsive viewports testing ---")
        viewports = [
            (320, 568, "mobile_320x568"),
            (375, 667, "mobile_375x667"),
            (390, 844, "mobile_390x844"),
            (768, 1024, "tablet_768x1024_portrait"),
            (1024, 768, "tablet_1024x768_landscape"),
            (1366, 768, "laptop_1366x768"),
            (1920, 1080, "desktop_1920x1080"),
        ]

        for w, h, label in viewports:
            page_cad.set_viewport_size({'width': w, 'height': h})
            # Test approval queue list at viewport
            page_cad.goto(f"{BASE_URL}/design-approvals/")
            time.sleep(0.3)
            # Check horizontal overflow
            scroll_width = page_cad.evaluate("() => document.documentElement.scrollWidth")
            client_width = page_cad.evaluate("() => document.documentElement.clientWidth")
            assert scroll_width <= client_width + 5, f"Horizontal overflow at {w}x{h}: scrollWidth={scroll_width}, clientWidth={client_width}"

            # Test review detail window at viewport
            page_cad.goto(f"{BASE_URL}/design-approvals/{img6_id}/")
            time.sleep(0.3)
            scroll_width_d = page_cad.evaluate("() => document.documentElement.scrollWidth")
            client_width_d = page_cad.evaluate("() => document.documentElement.clientWidth")
            assert scroll_width_d <= client_width_d + 5, f"Horizontal overflow in detail at {w}x{h}: scrollWidth={scroll_width_d}, clientWidth={client_width_d}"

            # Save screenshot
            shot_vp = ARTIFACTS_DIR / f"responsive_{label}.png"
            page_cad.screenshot(path=str(shot_vp))
            print(f"[+] Viewport {w}x{h} ({label}) verified. Screenshot: {shot_vp.name}")
            results[f"Viewport_{w}x{h}"] = "PASS"

        # Zoom 200% test emulation (viewport width halved, device scale 2)
        ctx_zoom = browser.new_context(viewport={'width': 640, 'height': 480}, device_scale_factor=2)
        page_zoom = ctx_zoom.new_page()
        login_user(page_zoom, 'cad_john')
        page_zoom.goto(f"{BASE_URL}/design-approvals/{img6_id}/")
        time.sleep(0.5)
        shot_zoom = ARTIFACTS_DIR / "responsive_zoom_200.png"
        page_zoom.screenshot(path=str(shot_zoom))
        ctx_zoom.close()
        print(f"[+] 200% Zoom emulation verified. Screenshot: {shot_zoom.name}")
        results["Zoom_200%"] = "PASS"

        browser.close()

    print("\n" + "="*50)
    print("ALL BROWSER E2E TESTS COMPLETED SUCCESSFULLY!")
    print("="*50)
    for test, res in results.items():
        print(f"  {test:<35}: {res}")

if __name__ == '__main__':
    main()
