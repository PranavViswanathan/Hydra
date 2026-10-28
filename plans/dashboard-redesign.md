# Dashboard redesign: "Patina"

Vulnerabilities are corrosion on a dependency tree; the agent is what keeps the
metal clean. The page reads like an inspection record for that metal: cool
mineral grounds, oxide colours for severity, verdigris for the agent.

## Audience and job

Engineers who check it daily (dense, calm, scannable) and judges watching a
demo on a projector at 1280x720 (one moment that tells the before/after story:
counts drop to zero when the PR merges).

## Color

Both themes follow `prefers-color-scheme`.

| Token | Light | Dark | Role |
|---|---|---|---|
| ground | `#ECEFEA` zinc | `#151D1A` bronze shadow | page |
| sheet | `#F8F9F6` | `#1C2622` | tables, raised surfaces |
| graphite | `#1C2522` | `#E4EBE6` | primary text |
| lichen | `#5A6762` | `#93A39C` | secondary text |
| rule | `#D3D9D4` | `#2C3833` | hairlines |
| verdigris | `#1F7562` | `#63C7AC` | the agent, actions, links |

Severity (spec 14.3 hues, tuned to the mineral ground):
critical oxide `#B8322A` / `#F0645A`, high rust `#C25E18` / `#F2934B`,
medium sulphur `#9A7E0C` / `#E2C04A`, low lead `#5F7484` / `#9AB0C0`,
unknown `#868C85` / `#8F968F`.

## Type

One family, with width as the expressive axis.

- Archivo variable (wght, wdth). Display at wdth 125, weight 650, tight
  tracking: page headline sentences, repository names. Body at wdth 100, 15px.
- Martian Mono variable, condensed (wdth 87): only for real code data such as
  package names, versions, advisory ids, PR numbers.
- Scale: 12.5 / 14 / 15 / 18 / 26 / 40.
- No all-caps labels. Table headers are sentence case in lichen.

## Layout

Left aligned, 1120px measure, 24px gutters (16px on phones).

```
VulnAgent                                   demo data   Pranav
---------------------------------------------------------------
13 open vulnerabilities
across 4 repositories.                    [Install GitHub App]
The agent is asleep.

[####|##########|##########|#########|#########]  exposure strip
 1 critical   3 high   3 medium   3 low   3 unknown

Repositories
 name, ecosystems      [mini strip] counts   agent   scanned   actions
```

Repository detail: the name in display type, the same strip for that repo,
then the run trace (five-segment progress bar plus an event rail), the
vulnerability table and past runs.

## Principles

1. The exposure strip is the one bold element. It appears on the overview, on
   each row and on the detail header, and its segments animate their width
   when counts change, so a merge visibly drains it.
2. Type does the talking: headlines are sentences about state, not labels.
3. No card kit. Surfaces separate by spacing and one hairline; radius has a
   hierarchy (strip 2px, controls 4px, sheets 6px).
4. Motion only for state change (strip, active step); all of it off under
   `prefers-reduced-motion`.

## Review against defaults

- Replaced the five identical count cards (big number, small label) with a
  sentence headline and a proportional strip.
- Dropped the slate and electric-blue dev-tool palette, which is what any
  dashboard gets by default.
- Dropped the uppercase tracked section titles and the middle-dot meta strings.
- Kept mono, but only where values are code.
