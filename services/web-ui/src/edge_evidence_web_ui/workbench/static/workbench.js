'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const labels={complete:'Recorded complete',deferred:'Bounded defer',prepared:'Prepared, awaiting catch-up'};
  const copy={complete:'Recorded finish; not independent copy readback.',deferred:'Paused rather than completed.',prepared:'Ready for later work, not completed.'};
  let selectedId=null, records=[],seq=0,proofLoaded=false;
  const t=(id,val)=>{$(id).textContent=val===undefined||val===null?'Not established':String(val)};
  const json=(id,val)=>t(id,JSON.stringify(val,null,2));
  const stateName=record=>labels[record?.state]||'Unrecognized example';
  function setView(view){
    for(const name of ['inspect','proof','ask']) $(name+'-view').hidden=name!==view;
    document.querySelectorAll('[data-view]').forEach(b=>{
      const on=b.dataset.view===view;b.classList.toggle('active',on);
      if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    });
    if(view==='proof'&&!proofLoaded)loadProof();
  }
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
  async function loadRecords(){
    try{
      const caps=await (await fetch('/api/review/capabilities',{cache:'no-store'})).json();
      if(caps.mode!=='hosted'||caps.llama!=='local-only-unavailable-here')throw Error('Unsafe capabilities');
      $('fixture-flag').hidden=!caps.test_fixture_services;
      const resp=await fetch('/api/v1/artifacts',{cache:'no-store'});if(!resp.ok)throw Error('Missing artifacts');
      const received=await resp.json();if(!Array.isArray(received)||!received.length)throw Error('No artifacts');
      records=received;
      const buttons=$('record-buttons');buttons.replaceChildren();
      for(const record of records){
        const button=document.createElement('button');button.type='button';button.className='record-button';
        button.dataset.artifactId=record.artifact_id;
        const title=document.createElement('strong');title.textContent=stateName(record);
        const desc=document.createElement('small');desc.textContent=copy[record.state]||'Unrecognized state';
        const badge=document.createElement('span');badge.className='state-tag';badge.textContent=String(record.state||'unknown').toUpperCase();
        button.append(title,desc,badge);button.addEventListener('click',()=>selectRecord(record));buttons.append(button);
      }
      await selectRecord(records[0]);
    }catch(error){$('record-buttons').textContent='Record service unavailable.';$('inspect-status').textContent='Unable to load synthetic records; no inspection shown.';$('facts-content').hidden=true;}
  }
  async function selectRecord(record){
    const turn=++seq;selectedId=record.artifact_id;
    document.querySelectorAll('.record-button').forEach(b=>{const active=b.dataset.artifactId===selectedId;b.classList.toggle('selected',active);b.setAttribute('aria-pressed',String(active))});
    $('facts-content').hidden=true;t('inspect-status','Inspecting selected API record…');
    try{
      const response=await fetch('/api/v1/inspect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(record),cache:'no-store'});
      if(!response.ok)throw Error('Inspect failed');const inspection=await response.json();
      if(turn!==seq)return;
      if(inspection.artifact_id!==record.artifact_id||inspection.mutation_authorized!==false)throw Error('Inspector boundary mismatch');
      t('fact-title',stateName(record));t('fact-state',String(record.state||'unknown').toUpperCase());
      t('fact-explanation',inspection.explanation);t('fact-classification',inspection.classification);
      t('fact-approval',inspection.requires_human_approval===true?'Yes':inspection.requires_human_approval===false?'No':'Unknown');
      t('fact-mutation','No');t('fact-eligible',String(record.snapshot_eligible));
      t('fact-id',record.artifact_id);t('fact-digest',record.digest);
      json('record-raw',record);json('inspection-raw',inspection);
      $('facts-content').hidden=false;t('inspect-status','Inspector response matched the selected synthetic record. Stored bytes and external copies were not checked.');
    }catch(e){if(turn===seq){t('inspect-status','Inspector unavailable or returned conflicting facts. No classification is inferred.');$('facts-content').hidden=true;}}
  }
  async function loadProof(){
    $('proof-content').hidden=true;$('proof-error').hidden=true;
    try{
      const response=await fetch('/api/review/proof',{cache:'no-store'});if(!response.ok)throw Error('Proof unavailable');
      const data=await response.json(),h=data.snapshot?.summary?.handoff,meta=data.provenance;
      if(!h||!meta||data.verification?.bytes_sha256_checked!==true)throw Error('Incomplete proof');
      const src=h.source,rep=h.replication;
      if(!src||!rep)throw Error('Missing proof fields');
      t('source-size',src.byte_size);t('target-size',rep.target_byte_size);
      t('replay-count',rep.replay?.published);t('verified-count',rep.verification?.verified);
      t('proof-source-digest',src.sha256);t('proof-target-digest',rep.target_sha256);
      if(src.sha256!==rep.target_sha256||src.byte_size!==rep.target_byte_size)throw Error('Contradictory snapshot');
      t('proof-meta',data.snapshot.cached===true?'Retained JSON SHA-256 checked · snapshot reports cached':'Retained JSON SHA-256 checked · cache status not established');
      t('proof-time',meta.execution_time_utc?'Original execution recorded: '+meta.execution_time_utc:'Original execution time unknown · no fresh run');
      t('proof-retrieved','Captured snapshot retrieved: '+(meta.source_retrieved_utc||'Unknown'));
      json('proof-raw',data.snapshot);json('provenance-raw',meta);
      $('proof-content').hidden=false;proofLoaded=true;
    }catch(e){$('proof-content').hidden=true;$('proof-error').hidden=false;}
  }
  loadRecords();
})();
