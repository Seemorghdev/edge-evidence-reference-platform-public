"""Actual Chromium DOM/keyboard/responsive test with explicitly mocked browser transport.

Managed Chromium here blocks localhost navigation. To respect that policy, this
runs the exact local HTML/CSS/JS in an about:blank document, with a deliberately
mocked fetch implementation. Independent TestClient tests exercise HTTP API.
No model, local HTTP navigation or external network occurs.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'runtime'))
from panel_supervisor import PanelSupervisor, MockTransport
SHOTS = Path(os.environ.get('EDGE_PANEL_SCREENSHOTS', ROOT / 'screenshots'))
SHOTS.mkdir(parents=True, exist_ok=True)

# Literal production assets, not a duplicated UI implementation.
HTML = (ROOT / 'ui/index.html').read_text()
CSS = (ROOT / 'ui/styles.css').read_text()
JS = (ROOT / 'ui/app.js').read_text()
svc = PanelSupervisor(transport=MockTransport())
facts = {key: svc.facts(key) for key in ('complete', 'deferred', 'prepared')}

MOCK_FETCH = r"""
({ facts }) => {
  let mode='completed', delay=280, cancelled=false;
  const response=(body, status=200) => ({ok:status>=200&&status<300,status, json:async()=>body});
  globalThis.__mock = {
    outcome: (next, milliseconds=250) => { mode=next; delay=milliseconds; },
    calls: [],
  };
  window.fetch = async (url, options={}) => {
    const key=String(url); globalThis.__mock.calls.push({url:key, body:options.body||null});
    if(key==='/api/config') return response({model:'llama3.1:8b',mock_transport:true,synthetic:true});
    if(key.startsWith('/api/facts/')) return response(facts[key.split('/').pop()]||{error:'Unknown'},facts[key.split('/').pop()]?200:404);
    if(key==='/api/cancel'){cancelled=true;return response({cancellation_requested:true});}
    if(key==='/api/ask') {
      cancelled=false;
      const input=JSON.parse(options.body);
      const snap={mode,delay,input};
      await new Promise(r=>setTimeout(r,snap.delay));
      const state=cancelled?'cancelled':snap.mode;
      const explanation=state==='completed'?'This synthetic record has a recorded finished state.':
          'The optional model explanation is unavailable or was withheld. Use the separate recorded facts; this inspection does not perform work or establish independent copy verification.';
      const untrusted=state==='html'?'<img src=x onerror=alert(1)>':explanation;
      return response({state:state==='html'?'completed':state, explanation:untrusted,
        display_origin:state==='completed'||state==='html'?'MODEL_EXPLANATION':'DETERMINISTIC_FALLBACK',
        raw_model_answer:state==='html'?'<script>alert(1)</script>':null,
        guard_reasons:[],request_count:1,tool_count:1,elapsed_seconds:snap.delay/1000,mock_transport:true});
    }
    throw Error('Non-allowlisted fetch URL');
  };
}
"""

def load(page):
    page.goto('about:blank')
    # Browser policy blocks HTTP(S) navigation; this document only uses test mocks.
    page.set_content(HTML, wait_until='domcontentloaded')
    page.add_style_tag(content=CSS)
    page.evaluate(MOCK_FETCH, {'facts':facts})
    page.add_script_tag(content=JS)
    expect(page.get_by_text('TEST ONLY · EXPLICITLY MOCKED TRANSPORT · NOT AN OLLAMA RESULT')).to_be_visible()
    expect(page.locator('#fact-classification')).to_have_text('healthy-complete')


def main():
    assertions=0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        desktop = browser.new_page(viewport={'width':1440,'height':990}, device_scale_factor=1)
        load(desktop)
        desktop.locator('#fixture').select_option('deferred')
        expect(desktop.locator('#fact-classification')).to_have_text('bounded-defer')
        expect(desktop.locator('#fact-approval')).to_have_text('Yes')
        desktop.locator('#fixture').select_option('complete')
        expect(desktop.locator('#fact-classification')).to_have_text('healthy-complete')
        assertions+=1
        desktop.locator('#question').focus()
        desktop.locator('#question').fill('What does this recorded state mean?')
        desktop.locator('#question').press('Control+Enter')
        expect(desktop.locator('#ask')).to_be_disabled()
        expect(desktop.locator('#state-badge')).to_have_text('COMPLETED', timeout=6000)
        expect(desktop.locator('#answer')).to_contain_text('synthetic record')
        expect(desktop.locator('#request-count')).to_have_text('1')
        desktop.locator('.result-details summary').click()
        desktop.screenshot(path=str(SHOTS / 'mock-desktop.png'), full_page=True)
        assertions+=1
        desktop.evaluate('globalThis.__mock.outcome("html")')
        desktop.locator('#ask').click()
        expect(desktop.locator('#answer')).to_have_text('<img src=x onerror=alert(1)>')
        assert desktop.locator('#answer img').count()==0
        assert desktop.locator('script:not([src])').count()==1  # only the injected app script
        assertions+=1
        desktop.evaluate('globalThis.__mock.outcome("completed",600)')
        desktop.locator('#ask').click()
        desktop.locator('#fixture').select_option('prepared')
        expect(desktop.locator('#fact-classification')).to_have_text('prepared-awaiting-catch-up')
        expect(desktop.locator('#state-badge')).to_have_text('IDLE',timeout=6000)
        desktop.wait_for_timeout(800)
        assert 'synthetic record has a recorded finished' not in desktop.locator('#answer').inner_text()
        assertions+=1
        mobile = browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
        load(mobile)
        assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        mobile.locator('.preset').nth(1).click()
        expect(mobile.locator('#question')).to_have_value('Is processing recorded as complete?')
        mobile.locator('#ask').click()
        expect(mobile.locator('#state-badge')).to_have_text('COMPLETED',timeout=6000)
        mobile.screenshot(path=str(SHOTS / 'mock-mobile.png'), full_page=True)
        assertions+=1
        mobile.evaluate('globalThis.__mock.outcome("completed",500)')
        mobile.locator('#ask').click()
        expect(mobile.locator('#cancel')).to_be_enabled()
        mobile.locator('#cancel').click()
        expect(mobile.locator('#state-badge')).to_have_text('CANCELLED',timeout=6000)
        assertions+=1
        browser.close()
    print(f'PLAYWRIGHT PASS: {assertions} real Chromium desktop/mobile checks, explicit mocked fetch transport')
    print('NOTE: Host Chromium policy blocks all navigation; production assets injected into about:blank.')
    print(f'Desktop: {SHOTS/"mock-desktop.png"}')
    print(f'Mobile: {SHOTS/"mock-mobile.png"}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
