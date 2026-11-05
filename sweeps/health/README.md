# Health gap map sweep

A fork-local extension that sweeps literature and the Hugging Face Hub for leads on AI and
digital tools for community health workers in low-resource settings. It feeds the global
health gap map sheet (37 functions, Lancet Primary Care taxonomy plus our CHW additions). It
does not touch `sources/` or the main map pipeline.

## Run

```
python sweeps/health/sweep.py --since 2019            # Europe PMC + Hugging Face
python sweeps/health/sweep.py --since 2019 --skip-hf  # literature only
```

Standard library only, no keys needed. Output: `sweeps/health/out/leads_<date>.csv`.

## Files

| File | What it is |
|---|---|
| `queries.json` | Per-function Europe PMC queries (abstract-scoped), plus Hugging Face language and pipeline filters for 5.1 |
| `known_tools.json` | The 357 tool names already in the sheet; leads that mention one are tagged `known_tool` |
| `sweep.py` | The sweep |

## Reading the output

- `lead_status = new_lead` means the paper or model mentions no tool we already have. It is a
  lead to triage, not a tool row: someone still names the tool, assigns its function and fills
  the Tier 1 fields.
- A function with zero hits is a result. Record the query in the sheet's search log as
  "searched, found nothing".

## Sources

| Source | Status | Notes |
|---|---|---|
| Europe PMC | Primary | PubMed plus preprints, open API |
| Hugging Face Hub | Primary for 5.1 | Speech, TTS and translation models by LMIC language |
| Semantic Scholar, OpenAlex | Not wired | Both rate-limit unauthenticated use; add with an API key |
| GitHub API | Not wired | Needs a token; run locally |

## Known limits

- Literature finds tools that were studied. Ministry and NGO deployments that were never
  written up are invisible here and still need the agent sweep.
- Abstract-scoped boolean queries trade recall for precision. Widen a query in
  `queries.json` when a function looks thin for the wrong reason.
