# docs/design

Sanitized copies of the documents the code and the other documents cite as the source of the design. They are
cited by bare file name (for example `VDEL_Modules_3_9_Build.md D.5`, `VDEL_REDESIGN.md C3`), and they live here.
`CLAUDE.md` at the repository root is the condensed summary of them and says where each rule comes from.

| File | What it is |
|---|---|
| `VDEL_Modules_1_2_Build.md` | Modules 1 and 2: the seven variables' formulas and the telemetry ingestion (collector, classifier, feature computation). `variables/*.py`, `collectors/` and `features/` are transcribed from it. |
| `VDEL_Modules_3_9_Build.md` | Modules 3 to 9: memory, the LLM gateway, the agents, the Reviewer, the backbone. Cited by section (`B.5`, `D.5`, `H.2`) and in a few places by line number, so its line positions are unchanged. |
| `VDEL_REDESIGN.md` | The critique and redesign of 2026-08-19 behind the completion-problem format (D-035, D-036): gaps, variants, executed tests, the schema in section 11. Cited by section (`§11`, `C3`, `8.3`). |

Sanitizing changed only personal content: names became roles, the school and employer became neutral, and lines about a
meeting or a schedule were reworded. Every formula, number, schema, example and section number is unchanged, and so is
every line position. Where the code and one of these documents disagree, `docs/DECISIONS.md` records which one wins and why.
