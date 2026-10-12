"""Capture a running synthetic-demo server at 8889; never point at production data."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('docs/images')
out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.goto('http://127.0.0.1:8889/')
    page.get_by_text('独立任务进程运行中',exact=False).first.wait_for()
    page.get_by_text('已保存 · v',exact=False).first.wait_for()
    page.locator('nav.stages button').nth(1).click()
    page.get_by_text('SCRIPT TO SCREEN',exact=True).wait_for()
    page.locator('.v12-hero video').wait_for()
    page.wait_for_function('document.querySelector(".v12-hero video").readyState >= 2')
    page.screenshot(path=str(out/'workbench.png'))
    browser.close()
