# AI assistant (Phase 5A)

The assistant is **optional and off by default**. It helps an engineer in two ways:

1. **Describe what you need** (Configure → Requirements). The engineer types a sentence such as
   "3 departments with 40 users each, Wi-Fi on VLAN 30, OSPF to the core". The model returns a
   `ConfigPlan` JSON draft, and the draft fills in the form.
2. **Explain** buttons on a command block (preview and job), on a failed push or verification, and on a
   config diff (a job's backup compared with the previous backup of the same device).

The model never configures anything. Its output is either a form pre-fill that the engineer reviews or text
to read.

## Providers (all free)

| `AI_PROVIDER` | Where it runs | Key | Default model (`AI_MODEL` overrides) |
|---|---|---|---|
| `off` (default) | – | – | – |
| `ollama` | this PC, `http://127.0.0.1:11434` (nothing leaves the machine) | none | `llama3.1:8b` |
| `groq` | Groq free tier, https | `AI_API_KEY` | `openai/gpt-oss-120b` |
| `gemini` | Gemini API free tier, https | `AI_API_KEY` | `gemini-3.8-flash` |

The defaults were checked against the providers' model lists on 2026-11-21. Hosted models are retired often
(`llama-3.3-70b-versatile` was shut down on 2026-08-16 and `gemini-2.0-flash` on 2026-06-01). If a call
returns "refused (HTTP 404)", set `AI_MODEL` to a current model. Google's model page does not say which
models are on the free tier, so check that in AI Studio.

Ollama setup: install Ollama for Windows, then run `ollama pull llama3.1:8b`, and set `AI_PROVIDER=ollama`
in `backend\.env`. For the JSON drafts, a larger model (for example `qwen2.5:14b`) gives better results if
the PC has the memory for it.

The provider is called with Python's standard `urllib` (no new library). The URLs are fixed constants: https
for hosted providers, and plain http only for the exact loopback Ollama URL.

## How it is kept safe

| Risk | Control | Where |
|---|---|---|
| AI output changes a device | A draft only fills the form. It goes through the same validation, preview, denylist, management-interface checks and production approval as a hand-typed plan. No AI endpoint creates or runs a job. | `api/ai.py`, `AiDraft.jsx` |
| Draft contains credentials or raw CLI | The backend removes `ssh` and `custom_commands` from every draft and says so. The frontend removes sections the device does not support and names them. | `services/ai.py: parse_draft`, `lib/ai.js: onlySupported` |
| Malformed or hostile draft | Parsed as JSON, then `ConfigPlan.model_validate` (`extra="forbid"`, allowlists, `ipaddress` checks). Anything invalid becomes a clean 422 with the field paths. | `parse_draft` |
| Secrets sent to the provider | Every text is masked with the same `mask_text` used for job records before it is sent. Device credentials exist only in a running push job and never reach these endpoints. | `services/ai.py: clean` |
| Prompt injection from device output | Device text goes only into the user message, inside `<untrusted_data>` … `</untrusted_data>`. Any copy of these tags inside the text is removed first. The system prompt says the block is data. Control characters are stripped and the text is capped at 6000 characters. | `clean`, `EXPLAIN_SYSTEM` |
| Model echoes a secret or HTML | The answer is masked again, capped at 4000 characters, and shown as plain text: React escapes it, there is no `dangerouslySetInnerHTML`, and the CSP allows no inline script. | `explain`, `Explain.jsx` |
| API key leak | `SecretStr` in memory and sent only in a request header. It never appears in URLs, bodies, logs or the browser. | `config.py`, `complete` |
| Cost / quota abuse | Engineers only (viewers get 403), 10 requests per minute per user, 30 s timeout, replies capped at 200 kB. | `api/ai.py` |
| Audit | `ai.draft` / `ai.explain` entries store the size, a SHA-256 prefix and the provider. The text itself is never stored. | `api/ai.py` |

## Tests

- `backend/tests/api/test_ai.py`: each test runs for groq, gemini and ollama with a fake provider. It covers
  roles; that a draft is validated, stripped of credentials and never creates a job; clean 422/502 errors;
  that secrets never reach the provider; the prompt-injection delimiters, control characters and echoed
  secrets; input limits; https-only except local Ollama; and the rate limit.
- `frontend/src/components/Explain.test.jsx`: the answer is rendered as text (no `<img>` injection), long
  text is cut to the backend limit, the buttons are hidden for viewers and when the assistant is off, and the
  draft fills only supported sections.
- `frontend/src/lib/diff.test.js`: the line diff used for "Compare with the previous backup".

## Limitations

- No model has been tried against a live provider in this repository. Tests use a fake provider. Before a
  demo, run one draft and one explanation with the provider you plan to use.
- A small local model can return drafts that fail validation. The engineer sees which fields were wrong and
  can rephrase or fill them in by hand.
- The explanation can be wrong. The UI says so next to every answer.
