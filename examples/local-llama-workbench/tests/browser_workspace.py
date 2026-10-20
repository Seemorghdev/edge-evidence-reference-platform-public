"""Production UI in real Chromium + in-process FastAPI TestClient, MOCK inference.

Chromium policy in this sandbox refuses loopback navigation, so these are NOT
live HTTP/Ollama browser end-to-end tests. No external requests are made.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright, expect
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'runtime'))
from panel_api import create_app
from panel_supervisor import PanelSupervisor,MockTransport
SHOTS=Path(os.environ.get('EDGE_PANEL_SCREENSHOTS',ROOT/'screenshots'))
SHOTS.mkdir(parents=True,exist_ok=True)
HTML=(ROOT/'ui/index.html').read_text()
# Navigation to localhost is blocked in the sandbox. Remove only network asset
# references; load the exact production CSS and JS from local bytes below.
HTML=re.sub(r'<link rel="stylesheet" href="/styles.css">','',HTML)
HTML=re.sub(r'<script defer src="/app.js"></script>','',HTML)
HTML=re.sub(r'<script defer src="/proof.js"></script>','',HTML)
CSS=(ROOT/'ui/styles.css').read_text()
JS=(ROOT/'ui/app.js').read_text()
PROOF_JS=(ROOT/'ui/proof.js').read_text()
ORIGIN='http://127.0.0.1:8765'

class ModelMock(MockTransport):
    def run(self,report,fixture,question,turn):
        super().run(report,fixture,question,turn)
        if self.outcome=='hostile':
            report['status']='RESPONSE_OBSERVED'
            report['answer']=json.dumps({'explanation':'<img src=x onerror=alert(123)> The inspector performed the processing.'})


def setup(page,api,mock):
    requests=[]
    page.on('request',lambda req:requests.append(req.url))
    def bridge(url,options):
        assert url.startswith('/api/')
        assert all(x not in url for x in ('http:','https:','..'))
        method=options.get('method','GET')
        headers={'Host':'127.0.0.1:8765','Origin':ORIGIN} if method=='POST' else {'Host':'127.0.0.1:8765'}
        if method=='POST':r=api.request(method,url,content=options.get('body','{}'),headers={**headers,'Content-Type':'application/json'})
        else:r=api.request(method,url,headers=headers)
        return {'status':r.status_code,'body':r.json()}
    page.expose_function('__apiBridge',bridge)
    page.expose_function('__mockOutcome',lambda mode,delay: (setattr(mock,'outcome',mode),setattr(mock,'delay',delay),True)[-1])
    page.goto('about:blank')
    page.set_content(HTML,wait_until='domcontentloaded')
    page.add_style_tag(content=CSS)
    page.evaluate('''() => {window.fetch=async (url,opts={}) => {
       const payload=await window.__apiBridge(String(url),opts);
       return {ok:payload.status>=200&&payload.status<300,status:payload.status,json:async()=>payload.body};
     }}''')
    # In-process FastAPI bridge cannot carry EventSource; exercise polling fallback.
    page.evaluate("() => { Object.defineProperty(window,'EventSource',{value:undefined,configurable:true}); }")
    page.add_script_tag(content=PROOF_JS)
    page.add_script_tag(content=JS)
    expect(page.locator('#fact-classification')).to_have_text('prepared-awaiting-catch-up',timeout=8000)
    expect(page.locator('#mock-banner')).to_be_visible()
    assert not requests, f'Unexpected actual network request: {requests}'
    return requests


def ask(page,question=None):
    if question:page.locator('#question').fill(question)
    page.locator('#ask').click()
    expect(page.locator('.turn-card').last.locator('.outcome')).not_to_have_text('In progress',timeout=8000)
    if page.evaluate('innerWidth')>900:
        trail=page.locator('#trail').bounding_box()
        latest=page.locator('.turn-card').last.bounding_box()
        assert latest['y']<trail['y']+trail['height'], 'New turn is below the visible trail'
        assert latest['y']+latest['height']>trail['y'], 'New turn is above the visible trail'


def check_shell_layout(page):
    """Production layout geometry; no clipped surfaces or full-window slab navigation."""
    width=page.evaluate("innerWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    nav=page.locator('.mobile-nav').bounding_box()
    assert nav is not None
    for control in page.locator('#prepare-model,#clear,#switch-record,.preset,.tab').all():
        box=control.bounding_box()
        if box is not None:
            assert box['height']>=43.5, f"Touch target below 44px: {box}"
    if width>900:
        assert nav['width']<=200, f"Nav became a full-width strip at {width}: {nav}"
        assert page.locator('.mobile-nav .tab').first.bounding_box()['width']<=190
    else:
        assert nav['height']<=80, f"Mobile nav too tall at {width}: {nav}"
    section=page.locator('.workspace').get_attribute('data-section')
    if section=='scenarios':
        expect(page.locator('#scenarios')).to_be_visible()
        expect(page.locator('#inspector')).to_be_visible()
        if width>900:
            left=page.locator('#scenarios').bounding_box()
            right=page.locator('#inspector').bounding_box()
            assert right['x']>=left['x']+left['width']-2
    elif section=='conversation':
        expect(page.locator('#conversation')).to_be_visible()
        expect(page.locator('#inspector')).to_be_visible()
        composer=page.locator('.composer-wrap').bounding_box()
        assert composer['x']>=-1 and composer['x']+composer['width']<=width+1
        assert page.locator('#question').bounding_box()['width']>=200
    elif section=='proof':
        expect(page.locator('#proof-view')).to_be_visible()
        assert page.locator('#proof-view').bounding_box()['width']<=width+1


def main():
    mock=ModelMock(delay=.12)
    svc=PanelSupervisor(transport=mock)
    with TestClient(create_app(svc,port=8765),base_url=ORIGIN) as api:
      with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('EDGE_CHROMIUM_BIN') or None,args=['--no-sandbox'])
        desktop=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
        network=setup(desktop,api,mock)
        check_shell_layout(desktop)
        expect(desktop.locator('#inspect-ask')).to_be_visible()
        desktop.screenshot(path=str(SHOTS/'shell-mocked-1440-inspect.png'),full_page=True)
        # Reflow all three views at desktop, intermediate and tablet widths.
        for width in (1280,1040,760):
            desktop.set_viewport_size({'width':width,'height':900})
            for section in ('scenarios','proof','conversation'):
                desktop.locator(f'[data-view="{section}"]').click()
                check_shell_layout(desktop)
        desktop.set_viewport_size({'width':1440,'height':900})
        desktop.locator('[data-view="scenarios"]').click()
        desktop.locator('#inspect-ask').click()
        check_shell_layout(desktop)
        assert 'synthetic, read-only' in desktop.locator('.orientation summary').inner_text()
        assert not desktop.locator('.orientation').evaluate('(node) => node.open')
        desktop.locator('.orientation summary').click()
        assert 'independent inspector facts' in desktop.locator('.orientation').inner_text()
        assert not desktop.locator('#activity-details').evaluate('(node) => node.open')
        assert 'not evidence of a model tool call' in desktop.locator('#activity-summary').inner_text()
        assert desktop.locator('#fact-mutation').inner_text()=='No'
        assert desktop.locator('#record-raw').inner_text()!='Input record unavailable'
        desktop.locator('[data-view="proof"]').click()
        expect(desktop.locator('#proof-ready')).to_be_visible()
        assert desktop.locator('#proof-cache').inner_text()=='Original reported cached: true'
        assert '2026-10-19T10:55:05Z' in desktop.locator('#proof-retrieved').inner_text()
        assert 'unknown' in desktop.locator('#proof-executed').inner_text()
        assert 'Captured HTTP payload SHA-256:' in desktop.locator('#proof-attestation').inner_text()
        assert desktop.locator('#proof-step-readback').inner_text()=='Supported by snapshot'
        assert desktop.locator('#proof-step-replay').inner_text()=='Supported by snapshot'
        assert desktop.locator('#proof-replay-verified').inner_text()=='0'
        assert desktop.locator('#proof-source-sha').inner_text()==desktop.locator('#proof-target-sha').inner_text()
        assert desktop.locator('#proof-first-published').inner_text()=='1'
        assert desktop.locator('#proof-replay-published').inner_text()=='0'
        assert mock.calls==0
        check_shell_layout(desktop)
        desktop.screenshot(path=str(SHOTS/'shell-mocked-1440-proof.png'),full_page=True)
        desktop.locator('#proof-return-ask').click()
        expect(desktop.locator('#conversation')).to_be_visible()
        desktop.locator('#question').fill('What does this recorded state mean?')
        desktop.locator('#question').press('Control+Enter')
        expect(desktop.locator('.turn-card')).to_have_count(1,timeout=8000)
        expect(desktop.locator('.outcome')).to_have_text('Explanation',timeout=8000)
        assert 'does not verify' in desktop.locator('#activity-summary').inner_text()
        desktop.locator('#activity-details summary').click()
        expect(desktop.locator('.activity .event-title')).to_contain_text(['Question accepted','Mock · Inspector result observed','Explanation display check observed','Mock · Owned turn cleanup verified','Mock · Model request allowed by HTTP gate','Mock · Local model HTTP response received'])
        assert desktop.locator('#technical-count').inner_text()!='0'
        assert desktop.locator('#fact-classification').inner_text()=='prepared-awaiting-catch-up'
        assert desktop.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        check_shell_layout(desktop)
        desktop.screenshot(path=str(SHOTS/'shell-mocked-1440-ask.png'),full_page=True)
        desktop.locator('#evidence-details summary').click()
        # Old-turn inspector facts must not be relabeled when selecting a new record.
        desktop.locator('[data-view="scenarios"]').click()
        desktop.locator('[data-fixture="complete"]').click()
        expect(desktop.locator('#fact-classification')).to_have_text('healthy-complete')
        desktop.locator('[data-view="conversation"]').click()
        desktop.locator('.turn-card').first.click()
        expect(desktop.locator('#fact-classification')).to_have_text('prepared-awaiting-catch-up')
        assert 'frozen evidence' in desktop.locator('#inspector-context').inner_text()
        # Hostile model output is not HTML, including in the raw detail drawer.
        desktop.evaluate('window.__mockOutcome("hostile",.03)')
        desktop.locator('[data-view="scenarios"]').click()
        desktop.locator('[data-fixture="complete"]').click()
        desktop.locator('[data-view="conversation"]').click()
        ask(desktop,'Explain the state')
        expect(desktop.locator('.outcome').last).to_have_text('Output withheld')
        assert 'withheld' in desktop.locator('#activity-summary').inner_text().lower()
        assert desktop.locator('.fallback-label').last.is_visible()
        assert desktop.locator('img').count()==0
        assert '<img src=x' in desktop.locator('#raw-answer').inner_text()
        check_shell_layout(desktop)
        desktop.screenshot(path=str(SHOTS/'shell-mocked-1440-withheld.png'),full_page=True)
        assert not network
        desktop.close()
        # Independent mobile viewport: keyboard/tab drawer and failure behavior.
        mock.outcome='completed';mock.delay=.05
        mobile=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True,reduced_motion='reduce')
        network=setup(mobile,api,mock)
        for width in (400,390):
            mobile.set_viewport_size({'width':width,'height':844})
            check_shell_layout(mobile)
        mobile.locator('[data-view="scenarios"]').click()
        expect(mobile.locator('#scenarios')).to_be_visible()
        mobile.locator('#guide summary').click()
        mobile.locator('[data-guide="deferred"]').click()
        expect(mobile.locator('#scenarios')).to_be_visible()
        expect(mobile.locator('#fact-classification')).to_have_text('bounded-defer')
        mobile.locator('[data-view="conversation"]').click()
        expect(mobile.locator('#conversation')).to_be_visible()
        ask(mobile)
        mobile.locator('#inspector').scroll_into_view_if_needed()
        check_shell_layout(mobile)
        mobile.screenshot(path=str(SHOTS/'shell-mocked-390-ask.png'),full_page=True)
        mobile.locator('[data-view="proof"]').click()
        check_shell_layout(mobile)
        mobile.screenshot(path=str(SHOTS/'shell-mocked-390-proof.png'),full_page=True)
        mobile.locator('[data-view="conversation"]').click()
        mock.outcome='timeout'
        ask(mobile,'Does this prove every stored copy was verified?')
        expect(mobile.locator('.outcome').last).to_have_text('Timed out',timeout=8000)
        mobile.locator('#inspector').scroll_into_view_if_needed()
        assert 'timed out' in mobile.locator('#activity-summary').inner_text().lower()
        expect(mobile.locator('#inspector')).to_be_visible()
        mobile.locator('#activity-details summary').click()
        assert mobile.locator('.activity .event-title').count()>0
        assert mobile.locator('#fact-mutation').inner_text()=='No'
        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        mobile.locator('#evidence-details summary').click()
        check_shell_layout(mobile)
        mobile.screenshot(path=str(SHOTS/'shell-mocked-390-timeout.png'),full_page=True)
        assert mobile.evaluate('getComputedStyle(document.querySelector(".scenario")).transitionDuration')=='0s'
        # A pending request is cancelled on a scenario switch, old turn is retained.
        mobile.locator('[data-view="conversation"]').click()
        mock.outcome='completed';mock.delay=.6
        mobile.locator('#ask').click()
        expect(mobile.locator('#cancel')).to_be_enabled(timeout=8000)
        mobile.screenshot(path=str(SHOTS/'shell-mocked-390-pending.png'),full_page=True)
        mobile.locator('[data-view="proof"]').click()
        expect(mobile.locator('#cancel-global')).to_be_enabled(timeout=8000)
        expect(mobile.locator('#proof-view')).to_be_visible()
        assert 'active' in mobile.locator('#active-turn-message').inner_text().lower()
        mobile.locator('[data-view="scenarios"]').click()
        assert mobile.locator('#cancel-global').is_enabled()
        mobile.locator('[data-view="scenarios"]').click()
        mobile.locator('[data-fixture="prepared"]').click()
        expect(mobile.locator('#ask')).to_be_enabled(timeout=8000)
        expect(mobile.locator('.outcome').last).to_have_text('Cancelled',timeout=8000)
        mobile.locator('[data-view="conversation"]').click()
        mock.delay=.03
        ask(mobile,'Explain prepared state')
        expect(mobile.locator('.outcome').last).to_have_text('Explanation',timeout=8000)
        # Explicit clear while pending requests cancellation before wiping the trail.
        mock.delay=.6
        mobile.locator('#ask').click()
        expect(mobile.locator('#cancel')).to_be_enabled(timeout=8000)
        mobile.locator('#clear').click()
        expect(mobile.locator('.turn-card')).to_have_count(0,timeout=8000)
        expect(mobile.locator('#ask')).to_be_enabled()
        assert not network
        # Malformed proof response stays unavailable; no optimistic status or inference.
        broken=browser.new_page(viewport={'width':394,'height':844},device_scale_factor=1)
        setup(broken,api,mock)
        broken.evaluate("""() => { const original=window.fetch;window.fetch=(u,opts)=>String(u)==='/api/proof'?
          Promise.resolve({ok:true,json:async()=>({snapshot:{},provenance:{},projection:{steps:{}}})}):original(u,opts); }""")
        broken.locator('[data-view="proof"]').click()
        expect(broken.locator('#proof-error')).to_be_visible()
        expect(broken.locator('#proof-ready')).to_be_hidden()
        assert broken.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        broken.close()
        browser.close()
    print('PASS: Chromium desktop/mobile production DOM, in-process FastAPI API, explicitly mocked model transport')
    print('NOTE: loopback browser navigation blocked by Chromium policy; not live HTTP or Ollama browser acceptance')
    for name in ('shell-mocked-1440-inspect.png','shell-mocked-1440-proof.png',
                 'shell-mocked-1440-ask.png','shell-mocked-1440-withheld.png',
                 'shell-mocked-390-ask.png','shell-mocked-390-proof.png',
                 'shell-mocked-390-timeout.png','shell-mocked-390-pending.png'):
        print('Screenshot:', SHOTS/name)

if __name__=='__main__':main()
