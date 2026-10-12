"""Opt-in isolated UI regression. Start a TEST server at 8889 first.
Run with: uv run --with playwright --python 3.12 python scripts/verify_ui.py
Uses installed Chrome headlessly; never opens a user profile or paid model.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

out = Path('app/verification/ui')
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8889/')
    # The app uses a perpetual SSE connection, so networkidle may never occur.
    try:page.wait_for_load_state('networkidle', timeout=2000)
    except PlaywrightTimeout:pass
    page.get_by_text('独立任务进程运行中', exact=False).first.wait_for()
    page.screenshot(path=str(out/'workbench.png'))
    print(page.get_by_role('button').all_text_contents())

    def fail_create(route):
        if route.request.method == 'POST':route.abort('connectionrefused')
        else:route.continue_()
    page.route('**/api/projects', fail_create)
    page.get_by_role('button', name='新建作品', exact=True).click()
    name = page.get_by_placeholder('为你的故事起一个名字')
    name.fill('公开验证 · 原创演示')
    page.get_by_role('button', name='创建作品', exact=True).click()
    alert = page.get_by_role('alert')
    alert.wait_for()
    assert '本地后台未连接' in alert.inner_text()
    assert name.input_value() == '公开验证 · 原创演示'
    assert alert.evaluate('(el) => !!el.closest("dialog[open]")')
    page.screenshot(path=str(out/'foreground-error.png'))

    page.unroute('**/api/projects', fail_create)
    page.get_by_role('button', name='创建作品', exact=True).click()
    page.locator('dialog').wait_for(state='detached')
    assert page.get_by_text('公开验证 · 原创演示', exact=False).count() > 0
    page.route('**/api/health', lambda route: route.abort('connectionrefused'))
    page.get_by_text('本地服务已断开。', exact=False).wait_for(timeout=15000)
    page.screenshot(path=str(out/'disconnected.png'))
    assert not errors, errors
    page.unroute('**/api/health')
    result = {'foreground_error':True, 'input_preserved':True, 'retry_succeeded':True,
              'persistent_disconnect_notice':True, 'page_errors':errors,
              'paid_model_calls':0, 'browser':'installed Chrome, headless test context'}
    (out/'proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))
    browser.close()
