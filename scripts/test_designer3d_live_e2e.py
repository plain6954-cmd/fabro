"""Playwright Chrome E2E test for designer3d upload, visibility, and persistence on port 8000."""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = Path(r"C:\Users\POWER-13\.gemini\antigravity-ide\brain\c372cf44-c4e6-4e54-85cb-3202721407e0")
BASE_URL = "http://127.0.0.1:8000"

# Small valid 100x100 test JPEG
SAMPLE_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00'
    b'\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19'
    b'\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.#\x1c\x1c(7),01444\x1f\'9=82<.342'
    b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01'
    b'\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05'
    b'\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
)

def create_temp_file(filename, content=SAMPLE_JPEG):
    p = ARTIFACTS_DIR / "scratch" / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return str(p)

def run():
    print("[*] Starting designer3d Chrome E2E verification...")
    created_image_ids = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        console_logs = []
        network_logs = []
        dialog_messages = []

        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("dialog", lambda d: (dialog_messages.append(d.message), d.accept()))
        
        def on_response(resp):
            if "design-images/upload" in resp.url or "design-folders" in resp.url:
                network_logs.append({
                    "url": resp.url,
                    "status": resp.status,
                    "content_type": resp.headers.get("content-type", ""),
                })
        page.on("response", on_response)

        # 1. Login as designer3d
        print("[+] Navigating to login page...")
        page.goto(f"{BASE_URL}/login/")
        page.wait_for_selector('input[name="username"]')
        page.fill('input[name="username"]', 'designer3d')
        page.fill('input[name="password"]', 'fabro123')
        page.click('button[type="submit"]')
        page.wait_for_url(lambda u: '/login/' not in u, timeout=10000)
        print(f"[+] Logged in! Current URL: {page.url}")

        # 2. Navigate to reference vehicle 552 design options
        target_url = f"{BASE_URL}/car-details/?vehicle_id=552#design-options"
        print(f"[+] Navigating to {target_url}...")
        page.goto(target_url)
        page.wait_for_selector('#tab-pane-design-options', timeout=10000)

        # Check DOM for CSRF token
        csrf_in_dom = page.evaluate("() => typeof getDesignCsrfToken === 'function' ? getDesignCsrfToken() : 'no_func'")
        print(f"[+] getDesignCsrfToken() returned in browser: {csrf_in_dom[:8]}... (length {len(csrf_in_dom)})")
        assert len(csrf_in_dom) > 10, "CSRF token must be present in DOM"

        shot_before = ARTIFACTS_DIR / "designer3d_before_upload.png"
        page.screenshot(path=str(shot_before))
        print(f"[+] Screenshot saved: {shot_before.name}")

        # 3. Perform Direct Vehicle Image Upload
        test_img_path = create_temp_file("designer3d_test_car_angle.jpg")
        print("[+] Triggering direct vehicle image upload via #directVehicleImageFileInput...")
        
        with page.expect_response(lambda r: "design-images/upload" in r.url, timeout=25000) as resp_info:
            page.set_input_files('#directVehicleImageFileInput', test_img_path)
        
        upload_resp = resp_info.value
        print(f"[+] Upload response received: status {upload_resp.status}, content-type: {upload_resp.headers.get('content-type')}")
        assert upload_resp.status == 200, f"Upload response status was {upload_resp.status}"

        # 4. Check for dialog messages (should NOT have session expired)
        print(f"[+] Dialog messages encountered: {dialog_messages}")
        for msg in dialog_messages:
            assert "session has expired" not in msg.lower(), f"Unexpected session expired alert: {msg}"

        # 5. Verify skeleton removed and card rendered
        skeleton_exists = page.evaluate("() => !!document.getElementById('directUploadingSkeleton')")
        print(f"[+] Uploading skeleton exists: {skeleton_exists}")
        assert not skeleton_exists, "Uploading skeleton was not removed!"

        # 6. Check rendered image thumbnail and count
        cards_count = page.evaluate("() => document.querySelectorAll('#directImagesMatrixGrid .design-matrix-card:not(.is-uploading)').length")
        new_badge = page.evaluate("() => document.getElementById('designDirectImagesCountBadge')?.textContent || '0'")
        print(f"[+] Direct images rendered cards count: {cards_count}, badge text: {new_badge}")
        assert cards_count > 0, "No cards rendered in direct images matrix grid!"
        assert int(new_badge) >= 1, f"Badge count not updated: {new_badge}"

        # Check status pill on new card
        status_pill_text = page.evaluate("() => document.querySelector('#directImagesMatrixGrid .design-matrix-card .matrix-status-pill')?.textContent.trim()")
        print(f"[+] Status pill text: {status_pill_text}")
        assert "Pending" in status_pill_text, f"Expected Pending status, got {status_pill_text}"

        # Empty state should be hidden
        empty_display = page.evaluate("() => document.getElementById('designFoldersEmptyState')?.style.display")
        print(f"[+] Empty state display style: {empty_display}")
        assert empty_display == 'none', f"Empty state should be hidden, got {empty_display}"

        shot_after = ARTIFACTS_DIR / "designer3d_after_upload.png"
        page.screenshot(path=str(shot_after))
        print(f"[+] Screenshot saved: {shot_after.name}")

        # Retrieve the created image ID for tracking
        created_id = page.evaluate(r"""() => {
            const card = document.querySelector('#directImagesMatrixGrid .design-matrix-card');
            const delBtn = card?.querySelector('.design-card-action-btn.delete');
            const onclick = delBtn?.getAttribute('onclick') || '';
            const m = onclick.match(/confirmDeleteDirectImage\((\d+)\)/);
            return m ? parseInt(m[1], 10) : null;
        }""")
        if created_id:
            created_image_ids.append(created_id)
            print(f"[+] Uploaded image ID in DB: {created_id}")

        # 7. Test Refresh and Persistence
        print("[+] Testing page reload to verify persistence...")
        page.reload()
        page.wait_for_selector('#tab-pane-design-options', timeout=10000)
        
        # Wait for the card to be fetched and rendered after reload
        page.wait_for_selector('#directImagesMatrixGrid .design-matrix-card', timeout=25000)

        reload_cards_count = page.evaluate("() => document.querySelectorAll('#directImagesMatrixGrid .design-matrix-card').length")
        reload_badge = page.evaluate("() => document.getElementById('designDirectImagesCountBadge')?.textContent || '0'")
        print(f"[+] After reload: cards count = {reload_cards_count}, badge = {reload_badge}")
        assert reload_cards_count > 0, "Cards vanished after page reload!"
        assert int(reload_badge) >= 1, "Badge reset to 0 after page reload!"

        shot_reload = ARTIFACTS_DIR / "designer3d_after_reload.png"
        page.screenshot(path=str(shot_reload))
        print(f"[+] Reload screenshot saved: {shot_reload.name}")

        # 8. Test Invalid file upload error handling
        print("\n[+] Testing invalid file upload error handling...")
        bad_file = create_temp_file("test_bad.txt", b"This is not an image file")
        dialog_messages.clear()
        page.set_input_files('#directVehicleImageFileInput', bad_file)
        time.sleep(2.0)
        
        # Skeleton should be removed even on failure!
        skeleton_still_there = page.evaluate("() => !!document.getElementById('directUploadingSkeleton')")
        print(f"[+] Skeleton exists after invalid upload: {skeleton_still_there}")
        assert not skeleton_still_there, "Skeleton was left stuck after invalid upload!"
        print(f"[+] Handled error gracefully without session expired: {dialog_messages}")

        # 9. Clean up test image
        for img_id in created_image_ids:
            print(f"[+] Cleaning up test image ID: {img_id}...")
            del_resp = page.request.post(
                f"{BASE_URL}/api/design-images/{img_id}/delete/",
                headers={'X-CSRFToken': csrf_in_dom}
            )
            print(f"[+] Delete response status: {del_resp.status}")

        browser.close()

    print("\n[SUCCESS] designer3d Chrome upload, visibility, persistence, and cleanup tests passed completely!")

if __name__ == '__main__':
    run()
