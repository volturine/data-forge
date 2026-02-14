# Propositions

Ideas and improvements discovered during development. User will vet and promote approved ones to `docs/bugs.md`.

---

1. **Lineage graph edge labels** — Show edge type ("derived", "uses") as text on connection lines, making relationships clearer without clicking nodes.

4. **Datasource search/filter** — As datasource count grows, a search bar + type filter on the datasources page would help navigation. Currently no filtering beyond the hidden toggle.

5. **Pipeline template library** — Save and reuse pipeline step sequences as templates. Common patterns (e.g., "clean → deduplicate → export") could be stored and applied to new tabs.

6. **Bulk schedule management** — Enable/disable/delete multiple schedules at once. Currently each schedule must be toggled individually.

7. **Export format options** — Support exporting to additional formats (JSON, Excel) beyond the current Parquet/CSV/Iceberg. The backend handler could be extended with format selection.

8. **Chart node interactivity** — Add tooltips, click-to-filter, and zoom on chart previews. Currently charts are static SVG renders.
