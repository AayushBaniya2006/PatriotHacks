# PatriotHacks — Civic Match

A neutral, source-grounded candidate alignment engine powered by a **Kimi agent swarm**.

The app lives in [`civic-match/`](civic-match/) — full architecture diagram, pipeline
docs, and run instructions are in [`civic-match/README.md`](civic-match/README.md).

```
Landing → User info → Agent staging (minimize context)
       → Kimi swarm (parallel data-endpoint agents)
       → Output report → Verifier agent (double checks)
       → db of Politicians → Scoring (quant + qual) → Presentation
```

Quick start:

```bash
cd civic-match
npm install
npm run seed    # auto-query Nov Texas election + research candidates
npm run dev
```
