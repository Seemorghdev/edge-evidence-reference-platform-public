'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const labels = {prepared:'Prepared, awaiting catch-up',deferred:'Bounded defer',complete:'Recorded complete'};
  const names = {pending:'In progress',completed:'Explanation',output_withheld:'Output withheld',invalid_record:'Invalid record',
    request_blocked:'Request blocked',timeout:'Timed out',cancelled:'Cancelled',model_unavailable:'Model unavailable',
    harness_error:'Setup or cleanup error',invalid_input:'Invalid input',connection_error:'Connection lost'};
  const kinds = {turn_accepted:'Question accepted',model_request_allowed:'Model request allowed by HTTP gate',
    http_response_observed:'Local model HTTP response received',tool_attempt_observed:'Inspector attempt observed',
    boundary_refusal_observed:'Transport or worker boundary refused an attempt',presentation_checked:'Explanation display check observed',
    cancel_requested:'Cancellation requested',owned_cleanup_verified:'Owned turn cleanup verified',cleanup_unverified:'Cleanup could not be verified',turn_slot_released:'Turn slot released'};
  let selected='prepared', selectionVersion=0, facts=null, factRows=new Map(), turns=[], focusId=null, pendingId=null;
  let pollTimer=null, clockTimer=null, streamSource=null, clearAfterCleanup=false, began=0, cancellationNeeded=false;
  const seenRevisions=new Map();
  let readinessTimer=null;
  let modelState='starting';
  let mobileView='scenarios';
  const post = (url, body) => fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
  const setText = (id, value) => {$(id).textContent=value == null ? '—' : String(value);};
  const updateComposer = (message) => {
    const ready=Boolean(facts), busy=Boolean(pendingId)||cancellationNeeded;
    const modelReady=['ready','mock'].includes(modelState);
    $('ask').disabled=!ready || busy || !modelReady;
    $('cancel').disabled=!pendingId;
    $('question').disabled=busy;
    $('turn-ribbon').hidden=!busy;
    $('cancel-global').disabled=!pendingId;
    setText('active-turn-message',pendingId?'Question active for frozen record · view switching does not cancel inference.':'Waiting for verified cleanup before another turn.');
    document.querySelectorAll('.preset').forEach(x => x.disabled=busy);
    setText('request-status',message || (busy?'One active turn · waiting for verified cleanup':!ready?'Inspector loading…':modelReady?'Ready · fresh independent turn':modelState==='warming'?'Model warming · inspector facts are ready':'Prepare the local model · inspector facts are ready'));
  };
  function view(name) {
    const section=name==='inspector'?'conversation':name;
    if(!['scenarios','proof','conversation'].includes(section))return;
    mobileView=section;
    document.querySelector('.workspace').dataset.section=section;
    $('proof-view').hidden=section!=='proof';
    document.querySelectorAll('.tab').forEach(node=>{
      const active=node.dataset.view===section;
      node.classList.toggle('active',active);
      if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');
    });
    if(section==='proof')window.EdgeProof?.load();
    if(name==='inspector')$('inspector').scrollIntoView({block:'start'});
  }
  document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
  $('inspect-ask').addEventListener('click',()=>view('conversation'));
  $('switch-record').addEventListener('click',()=>view('scenarios'));
  $('proof-return-ask').addEventListener('click',()=>view('conversation'));
  $('cancel-global').addEventListener('click',()=>cancelActive());
  function detailsData(payload) {
    const f=payload && payload.facts;
    setText('fact-identity',f?.artifact_id);
    setText('fact-classification',f?.classification);
    setText('fact-approval',typeof f?.requires_human_approval==='boolean'?(f.requires_human_approval?'Yes':'No'):null);
    setText('fact-mutation',typeof f?.mutation_authorized==='boolean'?(f.mutation_authorized?'Yes':'No'):null);
    setText('fact-readback','Not established');
    $('facts-error').hidden=Boolean(f);
    const record=payload?.record;
    setText('record-raw',record ? JSON.stringify(record,null,2) : 'Input record unavailable');
    setText('inspector-raw',f ? JSON.stringify(f,null,2) : 'Inspector result unavailable');
    setText('record-state',record?.state);
    setText('snapshot-eligible',typeof record?.snapshot_eligible==='boolean'?String(record.snapshot_eligible):null);
    setText('record-source',record ? `${record.source} / ${record.labels?.fixture || '—'}`:null);
    setText('record-created',record?.created_at);
    setText('record-digest',record?.digest);
    const res=payload?.result;
    setText('request-count',res?.request_count);
    setText('tool-count',res?.tool_count);
    setText('guard-reasons',res ? (res.guard_reasons||[]).join(', ')||'None recorded':null);
    setText('display-origin',res?.display_origin);
    setText('elapsed',typeof res?.elapsed_seconds==='number'?`${res.elapsed_seconds.toFixed(2)} s` : 'Not measured');
    setText('error-type',res?.error_type || 'None recorded');
    setText('raw-answer',res?.raw_model_answer==null?'No model output.':res.raw_model_answer);
    setText('model-metrics',Array.isArray(res?.http_metrics)&&res.http_metrics.length?JSON.stringify(res.http_metrics,null,2):'Unavailable');
  }
  function activityDescription(event) {
    const d=event.data||{};
    if(event.type==='turn_accepted') return `Question bound to ${labels[d.fixture_id]||'the selected record'}. No model answer yet.`;
    if(event.type==='model_request_allowed') return `Request ${d.observation_index} permitted; not proof of server receipt.`;
    if(event.type==='http_response_observed') return `Response ${d.observation_index} · HTTP ${d.status_code ?? 'unknown'} · ${d.metrics_available===false?'model metrics unavailable':`transport ${typeof d.response_wall_seconds==='number'?d.response_wall_seconds+' s':'time unavailable'}`} · ${Object.keys(d.metrics||{}).map(k=>k+'='+d.metrics[k]).join(', ')||'no timing fields observed'}${d.mock_transport?' · test-only simulation':''}.`;
    if(event.type==='tool_attempt_observed') return d.accepted_result===true?`Independent inspector result accepted for ${d.fixture_id||'the selected record'}.`:'Inspector attempt refused or not accepted; no validated tool result established.';
    if(event.type==='boundary_refusal_observed') return `Blocked attempt ${d.observation_index}; details withheld from UI.`;
    if(event.type==='presentation_checked') return `${names[d.state]||'Unknown outcome'} · ${d.display_origin||'unknown source'}. The format/scope check does not certify truth.`;
    if(event.type==='cancel_requested')return 'Requested, not yet proof of stopped inference.';
    if(event.type==='owned_cleanup_verified')return `${d.worker==='VERIFIED_STOPPED'?'Turn worker stopped.':'No inference worker was started.'} ${d.server==='VERIFIED_STOPPED'?'Owned model server stopped; port release verified.':'Owned model server may remain running.'}`;
    if(event.type==='turn_slot_released')return 'No process-cleanup observation recorded. Do not infer that a worker ran.';
    if(event.type==='cleanup_unverified')return 'New inference remains blocked.';
    return 'Observation recorded.';
  }
  function activitySummary(events,row){
    const result=row?.result, state=result?.state;
    const observed=type=>events.some(ev=>ev.type===type);
    const toolAccepted=events.some(ev=>ev.type==='tool_attempt_observed'&&ev.data?.accepted_result===true);
    if(state==='output_withheld')return 'Optional explanation withheld by the display check. Any provisional draft has been removed; rely on the separate inspector facts.';
    if(state==='cancelled')return 'Turn cancelled. Provisional text is removed; previous inspector facts remain available.';
    if(state==='timeout')return 'Turn timed out without an accepted explanation. The read-only inspector facts have not changed.';
    if(state==='request_blocked')return 'A boundary blocked this turn. Model activity may already have occurred; no accepted explanation is available. Review the observed activity and independent facts.';
    if(state==='invalid_record'||state==='invalid_input')return 'Request was not accepted for inference. Review the reason in this question; no model result should be inferred.';
    if(state==='model_unavailable'||state==='connection_error'||state==='harness_error')return 'No accepted model explanation is available. Review the non-success outcome and independent facts before retrying.';
    if(state==='completed'&&result?.display_origin==='MODEL_EXPLANATION')return 'Optional explanation passed a display format/scope check. This does not verify that its claims are true.';
    if(result)return 'A deterministic fallback is displayed, not an accepted model explanation. Inspector facts remain independent.';
    if(row?.stream?.phase==='draft'&&row.stream.text)return 'A provisional explanation is arriving from this turn. It is unreviewed; the final display check may still withhold it.';
    if(toolAccepted)return 'An inspector result has been accepted for this turn. No accepted explanation has arrived yet.';
    if(observed('http_response_observed'))return 'A local model HTTP response was observed. That alone is not an accepted inspector result or explanation.';
    if(observed('model_request_allowed'))return 'The HTTP gate allowed a model request; this does not prove model receipt.';
    if(observed('turn_accepted'))return 'Question accepted and bound to its record. No model answer yet.';
    return row?'Waiting for an observed turn event.':'These inspector facts were loaded separately. This is not evidence of a model tool call.';
  }
  function renderActivity(events=[],row=null) {
    $('activity').replaceChildren();$('technical-list').replaceChildren();
    setText('event-count',`${events.length} ${events.length===1?'EVENT':'EVENTS'}`);
    const technical=events.filter(ev=>['boundary_refusal_observed','model_request_allowed','http_response_observed'].includes(ev.type));
    setText('activity-summary',activitySummary(events,row));
    setText('technical-count',technical.length);
    if(!events.length){$('activity').append(safeNode('li','activity-empty','No observed activity for this selection.'));return;}
    for(const ev of events){
      const target=technical.includes(ev)?$('technical-list'):$('activity');
      const li=document.createElement('li');
      li.append(safeNode('div','event-title',(ev.data?.mock_transport?'Mock · ':'')+(ev.type==='tool_attempt_observed'?(ev.data?.accepted_result===true?'Inspector result observed':'Inspector attempt not accepted'):kinds[ev.type]||'Observed event')),
        safeNode('div','event-detail',activityDescription(ev)),
        safeNode('div','event-time',`Observed at ${ev.observed_at||'unknown time'}`));
      target.append(li);
    }
    if(!$('activity').children.length)$('activity').append(safeNode('li','activity-empty','Technical observations are available below.'));
  }
  function rowById(id){return turns.find(t=>t.turn_id===id);}
  function refreshInspector(){
    const row=focusId && rowById(focusId);
    if(row){
      setText('inspector-context',`${labels[row.fixture_id]||row.fixture_id} · frozen evidence for this question, not the current scenario.`);
      detailsData({facts:row.facts_snapshot,record:row.record_snapshot,result:row.result});
      renderActivity(row.events,row);
    }else{
      setText('inspector-context',`${labels[selected]} · current pinned inspector facts, no model inference required.`);
      detailsData(facts ? {facts:facts.facts,record:facts.record} : null);
      renderActivity([],null);
    }
  }
  function safeNode(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!=null)node.textContent=String(text);return node;}
  function renderTrail(){
    $('trail').replaceChildren();
    if(!turns.length){
      const empty=safeNode('div','empty-trail');empty.id='empty-trail';
      empty.append(safeNode('div','empty-glyph','◎'),safeNode('h3','', 'Start with the evidence.'),safeNode('p','', 'Each response is independent. A model failure stays visible; no answer is cached or silently retried.'));
      $('trail').append(empty);return;
    }
    for(const row of turns){
      const res=row.result;const state=res?.state || (row.status==='finished'?'harness_error':'pending');
      const card=safeNode('button','turn-card');card.type='button';card.dataset.turnId=row.turn_id;
      card.classList.toggle('selected',focusId===row.turn_id);card.setAttribute('aria-pressed',String(focusId===row.turn_id));
      const q=safeNode('div','question-bubble');q.append(safeNode('div','question-text',row.question));
      const meta=safeNode('div','turn-meta');meta.append(safeNode('span','',labels[row.fixture_id]||row.fixture_id),safeNode('span','',row.started_at||''));q.append(meta);
      const ans=safeNode('div','answer-bubble');const head=safeNode('div','answer-head');head.append(safeNode('span','answer-kind',row.stream?.phase==='draft'?'Generating · unreviewed draft':res?.state==='completed'?'Optional model explanation':res?'Turn outcome':'Awaiting optional explanation'));
      const badge=safeNode('span','outcome',names[state]||state);badge.dataset.state=state;head.append(badge);ans.append(head);
      ans.append(safeNode('div','answer-text',res?.explanation || (row.stream?.phase==='draft'&&row.stream.text ? row.stream.text :
        row.status==='pending'?'Waiting for grounded model explanation…':'No model explanation was accepted.')));
      const info=safeNode('div','answer-info');info.append(safeNode('span','',res?.mock_transport?'MOCKED TRANSPORT':res?.display_origin==='MODEL_EXPLANATION'?'OPTIONAL MODEL TEXT':res?.state==='output_withheld'?'OUTPUT WITHHELD':res?.display_origin==='DETERMINISTIC_FALLBACK'?'DETERMINISTIC FALLBACK':row.stream?.phase==='draft'?'UNREVIEWED DRAFT':'PENDING'),safeNode('span','',typeof res?.elapsed_seconds==='number'?`${res.elapsed_seconds.toFixed(1)} s`:'Elapsed time pending'));
      ans.append(info);
      if(row.stream?.phase==='draft')ans.append(safeNode('div','draft-note','Unreviewed draft · full response check pending'));
      if(res && res.display_origin!=='MODEL_EXPLANATION')ans.append(safeNode('div','fallback-label','Non-model fallback · not an accepted model explanation'));
      if(res && res.state!=='completed'){
        const retry=safeNode('span','retry-hint','Retry only as a new question after verified cleanup; no automatic retry occurs.');ans.append(retry);
      }
      card.append(q,ans);card.addEventListener('click',()=>{focusId=row.turn_id;renderTrail();refreshInspector();if(window.innerWidth<=920)view('inspector');});$('trail').append(card);
    }
  }
  function updateTurn(row){
    const i=turns.findIndex(t=>t.turn_id===row.turn_id);if(i<0)return;
    // This record's snapshots can only be replaced by this server-issued ID.
    const previous=turns[i]; turns[i]=row;
    const card=Array.from($('trail').querySelectorAll('[data-turn-id]')).find(n=>n.dataset.turnId===row.turn_id);
    if(card && row.status==='pending' && previous.status==='pending'){
      const content=card.querySelector('.answer-text');const caption=card.querySelector('.answer-kind');
      if(content)content.textContent=row.stream?.phase==='draft'&&row.stream.text?row.stream.text:'Waiting for grounded model explanation…';
      if(caption)caption.textContent=row.stream?.phase==='draft'?'Generating · unreviewed draft':'Awaiting optional explanation';
      if(row.stream?.phase==='draft' && !card.querySelector('.draft-note'))card.querySelector('.answer-bubble').append(safeNode('div','draft-note','Unreviewed draft · full response check pending'));
      if(focusId===row.turn_id)refreshInspector();
    }else{const trail=$('trail'),scrolled=trail.scrollTop,nearBottom=trail.scrollHeight-trail.scrollTop-trail.clientHeight<90;
      renderTrail();trail.scrollTop=nearBottom?trail.scrollHeight:scrolled;
      if(focusId===row.turn_id)refreshInspector();}
  }
  async function cancelActive(){
    if(!pendingId)return;
    const id=pendingId;
    updateComposer('Cancellation requested · awaiting owned cleanup');
    try{const r=await post(`/api/turns/${encodeURIComponent(id)}/cancel`,{});if(!r.ok)throw Error('Cancellation rejected');}
    catch{updateComposer('Cancellation signal failed · inference remains active until deadline or cleanup');}
  }
  async function clearWorkspace(){
    if(pendingId){clearAfterCleanup=true;updateComposer('Clearing after cancellation and cleanup');await cancelActive();return;}
    try{
      const r=await post('/api/turns/clear',{});
      if(!r.ok)throw Error();
      turns=[];focusId=null;cancellationNeeded=false;renderTrail();refreshInspector();updateComposer('Workspace cleared · no transcript persisted');
    }catch{updateComposer('Clear blocked: active work or cleanup is unverified');}
  }
  function clearPolling(){if(streamSource){streamSource.close();streamSource=null;}
    if(pollTimer!==null){clearTimeout(pollTimer);pollTimer=null;}
    if(clockTimer!==null){clearInterval(clockTimer);clockTimer=null;}}
  async function acceptUpdate(id,row){
    if(pendingId!==id||row.turn_id!==id||!Number.isSafeInteger(row.revision))return;
    if(row.revision<=(seenRevisions.get(id)??-1))return;
    seenRevisions.set(id,row.revision);
    updateTurn(row);
    if(row.status==='finished'){
      pendingId=null;clearPolling();cancellationNeeded=false;updateComposer(`Turn finished · ${names[row.result?.state]||'review the result'}`);
      await updateReadiness();
      if(clearAfterCleanup){clearAfterCleanup=false;await clearWorkspace();}
    }
  }
  function stream(id){
    if(typeof EventSource==='undefined'){poll(id);return;}
    if(streamSource)streamSource.close();
    streamSource=new EventSource(`/api/turns/${encodeURIComponent(id)}/events`);
    streamSource.addEventListener('turn',event=>{
      try{const row=JSON.parse(event.data);acceptUpdate(id,row);}catch{updateComposer('Invalid activity event · awaiting reconnection');}
    });
    streamSource.onerror=()=>{
      if(pendingId!==id)return;
      updateComposer('Stream interrupted · reconnecting same turn; no new inference started');
      // Browser EventSource reconnects; polling reads the same turn if streaming unavailable.
    };
  }
  async function poll(id){
    if(pendingId!==id)return;
    try{
      const response=await fetch(`/api/turns/${encodeURIComponent(id)}`,{cache:'no-store'});
      if(!response.ok)throw Error();
      const row=await response.json();
      if(pendingId!==id || row.turn_id!==id)return;
      await acceptUpdate(id,row);
      if(!pendingId)return;
      updateComposer(cancellationNeeded?'Cancelling previous record · waiting for verified cleanup':'Local turn in progress · observations update when recorded');
    }catch{
      if(pendingId===id)updateComposer('Polling interrupted · turn remains reserved; retrying observation');
    }
    if(pendingId===id)pollTimer=setTimeout(()=>poll(id),350);
  }
  async function chooseFixture(id, navigate){
    if(!labels[id])return;
    selected=id;selectionVersion++;const v=selectionVersion;facts=null;
    document.querySelectorAll('.scenario').forEach(button=>{const on=button.dataset.fixture===id;button.classList.toggle('selected',on);button.setAttribute('aria-pressed',String(on));});
    setText('current-label',labels[id]);setText('composer-record',id);
    focusId=null;refreshInspector();updateComposer();
    if(pendingId){cancellationNeeded=true;cancelActive();}
    try{
      const response=await fetch(`/api/facts/${encodeURIComponent(id)}`,{cache:'no-store'});
      if(!response.ok)throw Error();
      const data=await response.json();if(v!==selectionVersion)return;
      // Record metadata returned by the server is fixed allowlisted synthetic data.
      facts=data;factRows.set(id,data);refreshInspector();updateComposer();
    }catch{if(v===selectionVersion){facts=null;refreshInspector();updateComposer('Pinned inspector unavailable · cannot ask');}}
    // Record selection while Inspect remains there; view switching never cancels inference.
    if(navigate && document.querySelector('.workspace').dataset.section==='conversation')view('conversation');
  }
  document.querySelectorAll('.scenario').forEach(button=>button.addEventListener('click',()=>chooseFixture(button.dataset.fixture,true)));
  document.querySelectorAll('[data-guide]').forEach(button=>button.addEventListener('click',()=>{
    const id=button.dataset.guide;const prompts={prepared:'What does prepared establish, and what does it not prove?',
      deferred:'Does the deferred record establish completed processing?',
      complete:'Does recorded complete independently verify every stored copy?'};
    $('question').value=prompts[id];chooseFixture(id,true);
  }));
  document.querySelectorAll('.preset').forEach(button=>button.addEventListener('click',()=>{$('question').value=button.dataset.question;$('question').focus();}));
  $('question').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();$('ask').click();}});
  $('cancel').addEventListener('click',cancelActive);
  $('clear').addEventListener('click',clearWorkspace);
  $('ask').addEventListener('click',async()=>{
    if(pendingId||cancellationNeeded||!facts)return;
    const id=selected,q=$('question').value.trim();if(!q){$('question').focus();return;}
    // Reserve the client immediately, so duplicate clicks cannot create two turns.
    cancellationNeeded=true;updateComposer('Submitting independent turn…');
    try{
      const response=await post('/api/turns',{fixture_id:id,question:q});
      const data=await response.json();
      if(!response.ok){
        const local={turn_id:`local-${Date.now()}`,fixture_id:id,question:q,status:'finished',started_at:new Date().toISOString(),
          facts_snapshot:factRows.get(id)?.facts||null,record_snapshot:factRows.get(id)?.record||null,events:[],
          result:{state:data.state||'harness_error',explanation:data.error||'Request not accepted',display_origin:'DETERMINISTIC_FALLBACK'}};
        turns.push(local);if(turns.length>20)turns.shift();focusId=local.turn_id;renderTrail();$('trail').scrollTop=$('trail').scrollHeight;refreshInspector();updateComposer('Request not accepted · see trail');return;
      }
      const turnId=data.turn_id;
      // This row is provisional until the server supplies frozen inspector facts.
      turns.push({turn_id:turnId,fixture_id:id,question:q,status:'pending',started_at:new Date().toISOString(),events:[],facts_snapshot:null,record_snapshot:null,result:null});
      if(turns.length>20)turns.shift();
      focusId=turnId;pendingId=turnId;began=performance.now();renderTrail();$('trail').scrollTop=$('trail').scrollHeight;refreshInspector();
      clockTimer=setInterval(()=>{if(pendingId===turnId){const secs=((performance.now()-began)/1000).toFixed(1);setText('request-status',`Turn active · ${secs} s including setup`);}},1000);
      cancellationNeeded=false;updateComposer();
      if(selected!==id){cancellationNeeded=true;cancelActive();} // Selection changed before acceptance.
      stream(turnId);
    }catch{
      updateComposer('Request transport failed · do not assume turn cancellation; check server before asking again');
      // Unknown server acceptance cannot safely unlock another inference.
      return;
    }finally{if(!pendingId && !($('request-status').textContent||'').includes('transport failed')){cancellationNeeded=false;updateComposer();}}
  });
  async function updateReadiness(){
    try{const response=await fetch('/api/model/readiness',{cache:'no-store'});if(!response.ok)return;
      const data=await response.json();const previous=modelState;modelState=data.state;
      const readinessNames={starting:'Starting',cold:'Cold',warming:'Warming',ready:'Ready',
        unavailable:'Unavailable',mock:'Mock transport',busy:'Busy',cleanup_blocked:'Cleanup blocked'};
      setText('model-readiness',`Llama 8B · ${readinessNames[data.state]||'Unavailable'}`);
      $('prepare-model').disabled=['busy','warming','cleanup_blocked','mock'].includes(data.state);
      $('model-readiness').dataset.state=data.state;
      if(previous!==modelState&&!pendingId){const current=focusId&&rowById(focusId);
        updateComposer(current?.result?`Turn finished · ${names[current.result.state]||'review the result'}`:undefined);}
    }catch{modelState='unavailable';setText('model-readiness','Llama 8B · unavailable');updateComposer();}
  }
  $('prepare-model').addEventListener('click',async()=>{
    $('prepare-model').disabled=true;
    try{const r=await post('/api/model/prepare',{});if(!r.ok)updateComposer('Model preparation blocked; inspect readiness');}
    catch{updateComposer('Model preparation could not be requested');}
    updateReadiness();
  });
  async function initialize(){
    try{const response=await fetch('/api/config',{cache:'no-store'});if(!response.ok)throw Error();const cfg=await response.json();
      if(cfg.mock_transport)$('mock-banner').hidden=false;
    }catch{updateComposer('Configuration unavailable');}
    await chooseFixture('prepared',false);
    await updateReadiness();readinessTimer=setInterval(updateReadiness,2000);
  }
  initialize();
})();
