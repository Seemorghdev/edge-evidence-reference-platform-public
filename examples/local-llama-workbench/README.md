# Edge Evidence local Llama workbench

Inspect synthetic records, examine a separate retained Processor/Replication result,
and ask a local model to explain one selected record. The deterministic inspector
is the authority; model prose is optional and may be wrong, withheld, or unavailable.
The three records are independent examples, not a live end-to-end pipeline.

## Run locally

Tested baseline: Python 3.12.13, Ollama 0.40.6, llama3.1:8b with model digest
`46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`.
Install Ollama from its official distribution and obtain the model separately,
subject to its license. No weights or model service are shipped here.

From this directory:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r dependencies/requirements.lock
export EDGE_EVIDENCE_OLLAMA_BIN="$(command -v ollama)"
export EDGE_EVIDENCE_MODEL_STORE="$HOME/.ollama/models"
python -B runtime/serve_panel.py
```

Open the printed loopback address. Select **Inspect**, choose a record, and use
**Ask** to prepare the model and submit a question. Each turn is independent.
The workbench owns only its isolated Ollama service on 127.0.0.1:11435.
It refuses a port already in use, and never reconfigures or terminates the normal
Ollama service on 11434. Residency is bounded; cancellation and cleanup are observed.

For explicit offline UI testing only:
`python -B runtime/serve_panel.py --mock-transport`.
Mock responses are labeled and are not model acceptance evidence.

## Boundaries and limitations

- The tools read only the selected, schema-checked synthetic record.
- Inspector facts remain separate from model explanations and streamed drafts.
- No tool runs Processor, replicates data, verifies a remote copy, or grants approval.
- The Proof view displays a digest-checked cached synthetic HTTP result. Its retrieval
  time is known; original worker execution time is not. It is not a fresh worker run.
- Streaming is provisional until the final guard completes. It can be delayed or
  bursty. Successful formatting/scope checks do not prove semantic correctness.
- Composite and wrong-record questions have produced unhelpful or withheld answers.
  This is a bounded engineering experiment, not a reliability or production claim.

## Offline checks

```sh
python -m unittest discover -s runtime -p 'test_*.py'
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/activity-summary.test.cjs
```

Browser harnesses use explicitly mocked inference unless a real service is supplied;
passing offline checks must not be reported as a successful model run.
SOURCE-MANIFEST.json pins the included public inspector source by revision, Git blob
and SHA-256. It is checked before use. Never silently replace it with a newer core.

## Rights

Original workbench code and supplied synthetic example/proof assets are Apache-2.0.
Preserved upstream source and notices remain in public-source/. Dependency licenses
are listed in DEPENDENCIES.json; installed dependencies retain their own terms.
Llama weights are not Apache-2.0 and are not redistributed. See NOTICE.
