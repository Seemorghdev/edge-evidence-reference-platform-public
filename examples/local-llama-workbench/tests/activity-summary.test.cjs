'use strict';
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const {test} = require('node:test');
const assert = require('node:assert/strict');
const source = readFileSync(join(__dirname, '../ui/app.js'), 'utf8');
const start = source.indexOf('  function activitySummary(');
const end = source.indexOf('  function renderActivity(', start);
assert.ok(start >= 0 && end > start);
const summary = runInNewContext(`${source.slice(start, end)}; activitySummary`);

test('a blocked turn does not deny already observed model inference', () => {
  const text = summary([{type:'http_response_observed'}], {result:{state:'request_blocked'}});
  assert.match(text, /Model activity may already have occurred/);
  assert.match(text, /no accepted explanation/);
  assert.doesNotMatch(text, /not accepted for inference/);
});

test('invalid input is distinguished from a post-inference boundary block', () => {
  for (const state of ['invalid_input', 'invalid_record']) {
    assert.match(summary([], {result:{state}}), /not accepted for inference/);
  }
});

test('successful display checks are not described as truth verification', () => {
  assert.match(summary([], {result:{state:'completed',display_origin:'MODEL_EXPLANATION'}}), /does not verify/);
  assert.match(summary([], null), /not evidence of a model tool call/);
});

test('optional model metrics display observed counters and clear stale values', () => {
  const from = source.indexOf('  function detailsData(');
  const to = source.indexOf('  function activityDescription(', from);
  const values = {};
  const details = runInNewContext(`${source.slice(from,to)}; detailsData`, {
    setText:(id,value)=>{values[id]=value;}, $:()=>({hidden:false})
  });
  details({result:{http_metrics:[{eval_count:22}]}});
  assert.deepEqual(JSON.parse(values['model-metrics']), [{eval_count:22}]);
  details({facts:{}});
  assert.equal(values['model-metrics'], 'Unavailable');
});

test('scope disclosure describes inspection limits without denying the existence of verified copies', () => {
  const html = readFileSync(join(__dirname, '../ui/index.html'), 'utf8');
  const scope = html.match(/<details class="scope-note">([\s\S]*?)<\/details>/);
  assert.ok(scope);
  assert.match(scope[1], /Read-only inspection · verification limits/);
  assert.match(scope[1], /does not verify other copies or systems/);
  assert.doesNotMatch(scope[1], /no writes or verified copies/);
});
