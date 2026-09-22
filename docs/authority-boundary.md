# Authority boundary

The application is intentionally useful without becoming authoritative.

- Synthetic artifacts and receipts are disposable views.
- Evidence/state authority remains with external deterministic workers.
- The Edge Agent can explain or propose a next review step, but cannot execute workers, write evidence, or mutate infrastructure.
- The Web UI can request only the bounded application APIs configured for its environment.
- Optional model integration is disabled by default and remains on the inspection side of the boundary.
- Repository CI performs only read/build/test validation and contains no deployment or provider mutation step.

The boundary is enforced by application tests and by `scripts/check_projection.py`.
