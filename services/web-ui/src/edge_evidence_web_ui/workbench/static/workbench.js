'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const labels={complete:'Recorded complete',deferred:'Deferred',prepared:'Prepared, awaiting catch-up'};
  let selectedId=null,records=[],inspections=new Map(),seq=0,proofLoaded=false;
  const t=(id,val)=>{$(id).textContent=val===undefined||val===null?'Not established':String(val)};
  const json=(id,val)=>t(id,JSON.stringify(val,null,2));
  const stateName=record=>labels[record?.state]||'Unrecognized example';
  const cell=(text,tag='td')=>{const c=document.createElement(tag);c.textContent=text;return c};
  const short=digest=>typeof digest==='string'&&digest.length>19?digest.slice(0,19)+'…':String(digest);
  let currentView='inspect';
  function setView(view){
    currentView=view;
    for(const name of ['inspect','proof','ask']) $(name+'-view').hidden=name!==view;
    document.querySelectorAll('[data-view]').forEach(b=>{
      const on=b.dataset.view===view;b.classList.toggle('active',on);
      if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    });
    if(view==='proof'&&!proofLoaded)loadProof();
  }
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
  async function inspect(record){
    const response=await fetch('/api/v1/inspect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(record),cache:'no-store'});
    if(!response.ok)throw Error('Inspect failed');
    const inspection=await response.json();
    if(inspection.artifact_id!==record.artifact_id||inspection.mutation_authorized!==false)throw Error('Inspector boundary mismatch');
    return inspection;
  }
  async function loadRecords(){
    try{
      const caps=await (await fetch('/api/review/capabilities',{cache:'no-store'})).json();
      if(caps.mode!=='hosted'||caps.llama!=='local-only-unavailable-here')throw Error('Unsafe capabilities');
      $('fixture-flag').hidden=!caps.test_fixture_services;
      const resp=await fetch('/api/v1/artifacts',{cache:'no-store'});if(!resp.ok)throw Error('Missing artifacts');
      const received=await resp.json();if(!Array.isArray(received)||!received.length)throw Error('No artifacts');
      records=received;
      for(const record of records)inspections.set(record.artifact_id,await inspect(record));
      const body=$('records-body');body.replaceChildren();
      for(const record of records){
        const inspection=inspections.get(record.artifact_id),row=document.createElement('tr');
        row.dataset.artifactId=record.artifact_id;
        const first=document.createElement('td'),button=document.createElement('button');
        button.type='button';button.className='row-select';button.textContent=record.artifact_id;
        button.addEventListener('click',()=>selectRecord(record));first.append(button);
        const approval=inspection.requires_human_approval===true?'required':inspection.requires_human_approval===false?'not required':'unknown';
        row.append(first,cell(String(record.state||'unknown')),cell(inspection.classification),cell(approval),cell(short(record.digest)));
        row.addEventListener('click',e=>{if(e.target!==button)selectRecord(record)});
        body.append(row);
      }
      $('records-table').hidden=false;
      selectRecord(records[0]);
    }catch(error){t('inspect-status','Record or inspector service unavailable. No classification is inferred.');$('records-table').hidden=true;$('facts-content').hidden=true;}
  }
  function selectRecord(record){
    const turn=++seq;selectedId=record.artifact_id;
    document.querySelectorAll('#records-body tr').forEach(r=>{const on=r.dataset.artifactId===selectedId;r.classList.toggle('selected',on);r.querySelector('button').setAttribute('aria-pressed',String(on))});
    const inspection=inspections.get(record.artifact_id);
    if(turn!==seq||!inspection)return;
    t('fact-title',record.artifact_id+' — '+stateName(record));
    t('fact-explanation',inspection.explanation);t('fact-classification',inspection.classification);
    t('fact-approval',String(inspection.requires_human_approval));
    t('fact-mutation',String(inspection.mutation_authorized));t('fact-eligible',String(record.snapshot_eligible));
    t('fact-id',record.artifact_id);t('fact-digest',record.digest);
    json('record-raw',record);json('inspection-raw',inspection);
    $('facts-content').hidden=false;
    t('inspect-status',records.length+' records · inspector response bound to each record');
  }
  // Playback only quotes recorded snapshot fields; it never runs, fetches or computes results.
  let playbackSteps=[],stepIndex=0;
  const shown=val=>typeof val==='string'?val:JSON.stringify(val,null,2);
  function renderRecorded(id,recorded){
    const body=$(id);body.replaceChildren();
    for(const field of recorded){
      const row=document.createElement('tr'),path=document.createElement('td'),value=document.createElement('td');
      const code=document.createElement('code');code.textContent=field.path;path.append(code);
      const pre=document.createElement('pre');pre.textContent=shown(field.value);value.append(pre);
      row.append(path,value);body.append(row);
    }
  }
  function showStep(index){
    stepIndex=index;const step=playbackSteps[index];
    document.querySelectorAll('.step-button').forEach((b,i)=>{const on=i===index;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',String(on))});
    t('step-position',(index+1)+'/'+playbackSteps.length);t('step-title',step.title);
    t('step-presentation',step.presentation);renderRecorded('step-recorded',step.recorded);
    $('step-prev').disabled=index===0;$('step-next').disabled=index===playbackSteps.length-1;
  }
  function renderPlayback(playback){
    if(playback?.kind!=='recorded-playback'||playback.executes!==false||!Array.isArray(playback.steps)||!playback.steps.length)throw Error('Unexpected playback');
    playbackSteps=playback.steps;
    const list=$('proof-steps');list.replaceChildren();
    playbackSteps.forEach((step,i)=>{
      const item=document.createElement('li'),button=document.createElement('button');
      button.type='button';button.className='step-button';button.textContent=(i+1)+' '+step.title;
      button.addEventListener('click',()=>showStep(i));item.append(button);list.append(item);
    });
    t('aggregate-presentation',playback.aggregate.presentation);renderRecorded('aggregate-recorded',playback.aggregate.recorded);
    renderRecorded('context-recorded',playback.context.recorded);
    showStep(0);
  }
  $('step-prev').addEventListener('click',()=>{if(stepIndex>0)showStep(stepIndex-1)});
  $('step-next').addEventListener('click',()=>{if(stepIndex<playbackSteps.length-1)showStep(stepIndex+1)});
  document.addEventListener('keydown',e=>{
    if(currentView!=='proof'||!playbackSteps.length||e.altKey||e.ctrlKey||e.metaKey)return;
    if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
    if(e.key==='ArrowRight'&&stepIndex<playbackSteps.length-1){showStep(stepIndex+1);e.preventDefault();}
    if(e.key==='ArrowLeft'&&stepIndex>0){showStep(stepIndex-1);e.preventDefault();}
  });
  async function loadProof(){
    $('proof-content').hidden=true;$('proof-error').hidden=true;
    try{
      const response=await fetch('/api/review/proof',{cache:'no-store'});if(!response.ok)throw Error('Proof unavailable');
      const data=await response.json(),h=data.snapshot?.summary?.handoff,meta=data.provenance;
      if(!h||!meta||data.verification?.bytes_sha256_checked!==true)throw Error('Incomplete proof');
      const src=h.source,rep=h.replication;
      if(!src||!rep)throw Error('Missing proof fields');
      if(src.sha256!==rep.target_sha256||src.byte_size!==rep.target_byte_size)throw Error('Contradictory snapshot');
      t('proof-source-digest',src.sha256);t('proof-target-digest',rep.target_sha256);
      renderPlayback(data.playback);
      t('proof-meta',(data.snapshot.cached===true?'cached: true':'cache status not verified')+' · sha256 '+meta.snapshot_sha256+' checked');
      t('proof-time',meta.execution_time_utc?meta.execution_time_utc:'unknown — no fresh run');
      t('proof-retrieved',(meta.source_retrieved_utc||'unknown')+' (client time, not execution time)');
      json('proof-raw',data.snapshot);json('provenance-raw',meta);
      $('proof-content').hidden=false;proofLoaded=true;
    }catch(e){$('proof-content').hidden=true;$('proof-error').hidden=false;}
  }
  loadRecords();
})();
