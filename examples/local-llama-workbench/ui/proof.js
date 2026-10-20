'use strict';
/* Separate, retained synthetic proof; never used as inspector facts or model context. */
(() => {
  let loaded=false,loading=false;
  const $=id=>document.getElementById(id);
  const put=(id,value)=>{$(id).textContent=value===null||value===undefined?'Unknown':String(value);};
  const count=value=>Number.isInteger(value)&&value>=0?value:'Not reported';
  const stages=['processor','handoff','replication','readback','replay'];
  function unavailable(){loaded=false;$('proof-error').hidden=false;$('proof-ready').hidden=true;}
  function render(data){
    if(!data||!data.snapshot||!data.provenance||!data.projection)throw Error('Missing proof');
    const payload=data.snapshot,meta=data.provenance,p=data.projection;
    if(!p.steps||stages.some(x=>!['supported','contradicted','not_established'].includes(p.steps[x])))throw Error('Invalid projection');
    for(const key of stages){
      const status=p.steps[key],element=$('proof-step-'+key);
      element.dataset.status=status;
      element.textContent=status==='supported'?'Supported by snapshot':status==='contradicted'?'Contradictory evidence':'Not established';
    }
    put('proof-cache',payload.cached===true?'Original reported cached: true':payload.cached===false?'Original reported cached: false':'Original cache status unknown');
    put('proof-retrieved',typeof meta.source_retrieved_utc==='string'?'Retrieved '+meta.source_retrieved_utc:'Original retrieval UTC not recorded');
    put('proof-executed',typeof meta.execution_time_utc==='string'?'Executed '+meta.execution_time_utc:'Original execution time unknown');
    put('proof-source-size',count(p.source_bytes));put('proof-target-size',count(p.target_bytes));
    put('proof-first-published',count(p.first_published));put('proof-first-verified',count(p.first_verified));
    put('proof-readback-verified',count(p.readback_verified));put('proof-replay-published',count(p.replay_published));
    put('proof-replay-verified',count(p.replay_verified));
    put('proof-source-sha',p.source_sha256);put('proof-target-sha',p.target_sha256);put('proof-target-id',p.target_id);
    put('proof-attestation',meta.raw_http_payload_sha256?'Captured HTTP payload SHA-256: '+meta.raw_http_payload_sha256:
      'Owner-pasted response, committed as a reserialized snapshot. The committed SHA-256 is checked; original HTTP bytes and retrieval UTC remain unverified.');
    const list=$('proof-limitations');list.replaceChildren();
    const limits=payload.summary?.limitations;
    if(Array.isArray(limits))for(const value of limits){if(typeof value==='string'){const item=document.createElement('li');item.textContent=value;list.append(item);}}
    if(!list.children.length){const item=document.createElement('li');item.textContent='Source limitations unavailable; no production claim is inferred.';list.append(item);}
    put('proof-raw',JSON.stringify(payload,null,2));put('proof-provenance',JSON.stringify(meta,null,2));
    $('proof-ready').hidden=false;$('proof-error').hidden=true;
  }
  async function load(){
    if(loaded||loading)return;
    loading=true;$('proof-error').hidden=true;
    try{const response=await fetch('/api/proof',{cache:'no-store'});if(!response.ok)throw Error('Proof unavailable');
      render(await response.json());loaded=true;
    }catch{unavailable();}
    finally{loading=false;}
  }
  window.EdgeProof={load};
})();
