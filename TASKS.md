# To Do

## In Progress
- Re-record demo GIF showing unified TUI (scan + browse flow)

## Planned
- Re-run a folder from the browser (OmniDiskSweeper style — see plans/browser_update_action_plan.md)
- Delete a folder from the browser
- Homebrew tap for `brew install disk-analyzer`
- AI-powered explanations for what's using space (API key plumbing in place)
- Opportunity Ladder: deterministic cleanup ranking that shows low-hanging fruit first, then progressively higher-risk/smaller items (see plans/opportunity_ladder.md)
- Claude-assisted review queue for ambiguous large folders after deterministic ranking
- Use prior scan heuristics to improve ETA accuracy over time

## Ideas
- Naming/tagging runs by root folder in the browser
- Pie chart at each level (relative to total space)
- Show free space on the drive and keep updating it
- "Goal" mode — set a target for space to free up, track progress
- True storage amounts (APFS firmlinks can inflate system folder sizes)
