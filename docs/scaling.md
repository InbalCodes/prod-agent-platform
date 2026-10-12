# Scaling

> Status: not started (V6). No measurements yet — no scaling decisions are made without them.

## Known considerations to measure later

- Python concurrency model: one event loop per process; CPU parallelism via multiple processes (uvicorn workers / more containers).
- Likely first bottleneck: LLM provider rate limits (tokens/min), not our CPU.
- Load tests will use realistic workloads (simple request, RAG request, agent job, multi-tool investigation), not `/health`.
