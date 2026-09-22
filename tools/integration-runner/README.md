# Integration runner

Credential-free HTTP integration check for the three-service application.

With Evidence API and Edge Agent running:

```bash
integration-runner run
```

The command reads synthetic artifacts, verifies both health boundaries, requests bounded inspection for each artifact, writes a local JSON result, and performs no worker or provider action.
