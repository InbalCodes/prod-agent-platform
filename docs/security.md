# Security

## Threat model (initial)

| Threat | Where it enters | Phase | Control |
|---|---|---|---|
| Log injection / forged log entries | `X-Request-ID` header | 0 | Strict allow-list validation before use |
| Internal detail leakage | Error responses | 0 | problem+json without exception messages or traces |
| Secret leakage via logs/config | Settings, LLM client | 1 | `SecretStr`, never log settings objects |
| **Indirect prompt injection** | Log lines / docs returned by tools | 1 | Treat tool output as data; dedicated eval case |
| Tool misuse / over-broad tool scope | Tool arguments chosen by the model | 1 | Pydantic-validated args, bounded results, read-only tools |
| Unauthorized access | Public API | Before deployment | AuthN/AuthZ, rate limiting |
| Sensitive actions without oversight | Write tools | V2 | Risk levels + human approval + audit trail |

## Tool risk levels

All Phase 1 tools are **LOW** (read-only). Approval flow is introduced with the first MEDIUM/HIGH tool (V2).
