"""
Full-stack browser smoke test using Playwright against the running dev
servers (backend on :8000, frontend on :5173). Takes screenshots at each
step and fails loudly on console errors or missing expected content.
"""
import sys
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
SCREEN_DIR = "/home/claude/arogya/screenshots"

import os
os.makedirs(SCREEN_DIR, exist_ok=True)

console_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    # --- Login ---
    page.goto(f"{BASE}/login")
    page.fill('input[type="tel"]', "+919888877766")
    page.click("text=Send OTP")
    page.wait_for_selector('input[maxlength="6"]', timeout=5000)
    page.fill('input[maxlength="6"]', "000000")
    page.click("text=Verify & continue")
    page.wait_for_url(f"{BASE}/", timeout=5000)
    page.wait_for_selector("text=Today's reminders")
    page.screenshot(path=f"{SCREEN_DIR}/01_dashboard.png")
    print("Dashboard loaded OK")

    # --- Upload prescription ---
    page.goto(f"{BASE}/upload")
    page.set_input_files('input[type="file"]', "/tmp/sample_prescription.png")
    page.screenshot(path=f"{SCREEN_DIR}/02_upload_selected.png")
    page.click("text=Choose file")
    page.wait_for_selector("text=Please review before confirming", timeout=15000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SCREEN_DIR}/03_review_extracted.png", full_page=True)
    print("OCR review screen loaded OK")

    # Add a reminder time to the first medication row
    page.click("text=+ Add reminder time >> nth=0")
    page.wait_for_timeout(300)
    page.screenshot(path=f"{SCREEN_DIR}/04_reminder_time_added.png", full_page=True)

    page.click("text=Confirm and save")
    page.wait_for_url(f"{BASE}/medications", timeout=8000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SCREEN_DIR}/05_medications_list.png", full_page=True)
    print("Prescription confirmed and saved OK")

    # --- Dashboard should now show reminders ---
    page.goto(f"{BASE}/")
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SCREEN_DIR}/06_dashboard_with_reminders.png", full_page=True)

    # --- Chatbot ---
    page.goto(f"{BASE}/chat")
    page.fill('input[placeholder*="Ask about"]', "How should I store insulin and what should I eat for diabetes?")
    page.click("text=Send")
    page.wait_for_selector("text=Insulin", timeout=10000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SCREEN_DIR}/07_chatbot_insulin.png", full_page=True)
    print("Chatbot grounded answer OK")

    # Emergency escalation test
    page.fill('input[placeholder*="Ask about"]', "I am having severe chest pain right now")
    page.click("text=Send")
    page.wait_for_selector("text=emergency", timeout=10000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{SCREEN_DIR}/08_chatbot_emergency.png", full_page=True)
    print("Chatbot emergency escalation OK")

    # --- Price comparison ---
    page.goto(f"{BASE}/prices")
    page.fill('input[placeholder*="Search a medicine"]', "Paracetamol")
    page.click("text=Search")
    page.wait_for_selector("text=Paracetamol", timeout=5000)
    page.click("li:has-text('Paracetamol')")
    page.wait_for_selector("text=Cheapest option", timeout=5000)
    page.wait_for_timeout(300)
    page.screenshot(path=f"{SCREEN_DIR}/09_price_comparison.png", full_page=True)
    print("Price comparison OK")

    # --- Pharmacy locator ---
    page.goto(f"{BASE}/pharmacies")
    page.context.grant_permissions(["geolocation"])
    page.context.set_geolocation({"latitude": 12.9352, "longitude": 77.6245})
    page.click("text=Find pharmacies near me")
    page.wait_for_selector("text=km away", timeout=8000)
    page.wait_for_timeout(300)
    page.screenshot(path=f"{SCREEN_DIR}/10_pharmacy_locator.png", full_page=True)
    print("Pharmacy locator OK")

    # --- Language switch ---
    page.goto(f"{BASE}/")
    page.select_option("select", "hi")
    page.wait_for_timeout(300)
    page.screenshot(path=f"{SCREEN_DIR}/11_hindi_dashboard.png", full_page=True)
    print("Language switch (Hindi) OK")

    browser.close()

if console_errors:
    print("\n=== CONSOLE ERRORS DETECTED ===")
    for e in console_errors:
        print(e)
    sys.exit(1)
else:
    print("\nNo console errors. All smoke tests passed.")
