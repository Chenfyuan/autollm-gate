"""用 Playwright 无头浏览器截取控制台页面（1440x900，浅色）。

BASE=http://localhost:8080 TENANT_EMAIL=... TENANT_PASSWORD=... ADMIN_EMAIL=... ADMIN_PASSWORD=... OUT=dir python scripts/screenshots.py
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE, OUT = os.environ.get("BASE", "http://localhost:8080"), os.environ.get("OUT", "/workspace/autollm-gate-shots")
DARK = os.environ.get("DARK") == "1"
only = sys.argv[1:]


def shoot(page, path, name, full=False, wait="networkidle"):
    if only and name not in only:
        return
    page.goto(BASE + path, wait_until=wait)
    page.wait_for_timeout(900)
    page.screenshot(path=f"{OUT}/{name}.png", full_page=full)
    print("saved", name)


with sync_playwright() as p:
    b = p.chromium.launch(channel=os.environ.get("PW_CHANNEL", "chrome"))
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="zh-CN", timezone_id="Asia/Singapore",
                        color_scheme="dark" if DARK else "light")
    ctx.add_init_script(f"localStorage.setItem('theme', '{'dark' if DARK else 'light'}')")
    page = ctx.new_page()
    shoot(page, "/login", "tenant-login")
    r = page.request.post(BASE + "/api/auth/login", data={"email": os.environ["TENANT_EMAIL"], "password": os.environ["TENANT_PASSWORD"]})
    assert r.ok, r.text()
    shoot(page, "/console", "tenant-dashboard")
    shoot(page, "/console/usage", "tenant-usage")
    shoot(page, "/console/billing", "tenant-billing")
    shoot(page, "/console/keys", "tenant-keys")
    shoot(page, "/console/topup", "tenant-topup")
    shoot(page, "/console/docs", "tenant-docs")
    page2 = ctx.new_page()
    r = page2.request.post(BASE + "/api/admin/auth/login", data={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    assert r.ok, r.text()
    shoot(page2, "/admin", "admin-overview")
    shoot(page2, "/admin/tenants", "admin-tenants")
    if not only or "admin-tenant-detail" in only:
        page2.goto(BASE + "/admin/tenants", wait_until="networkidle")
        page2.locator("tbody tr").first.click()
        page2.wait_for_load_state("networkidle"); page2.wait_for_timeout(900)
        page2.screenshot(path=f"{OUT}/admin-tenant-detail.png"); print("saved admin-tenant-detail")
    shoot(page2, "/admin/settings", "admin-billing-settings")
    shoot(page2, "/admin/monitoring", "admin-monitoring", wait="load")
    shoot(page2, "/admin/upstreams", "admin-upstreams")
    shoot(page2, "/admin/models", "admin-models")
    b.close()
