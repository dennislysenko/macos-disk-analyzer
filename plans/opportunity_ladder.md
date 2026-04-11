# Opportunity Ladder

## Goal

Turn scan output into a cleanup queue that starts with the safest, largest, most reversible opportunities and only later surfaces smaller or riskier items.

The product behavior should feel like:

1. Show low-hanging fruit first.
2. Progressively climb to higher-hanging fruit.
3. Treat risk as "higher hanging."
4. Treat smaller size as "higher hanging" within the same risk/tier.

This is a better fit than a flat "largest matched directory first" sort.

## Why This Exists

The current recommendation engine in `cleanup_recommendations.py` already:

- matches known path patterns
- deduplicates parent/child overlaps
- sorts by size descending

That gets some useful results, but it does not explicitly model "fruit height."

Example from the April 10, 2026 run (`output/2026-04-10_21-41-00`):

- `19G` `~/Library/Developer/Xcode/DerivedData`
- `9.8G` `~/Library/Caches`
- `6.9G` `/Library/Developer/CoreSimulator`
- `6.8G` `~/Library/Developer/Xcode/Archives`
- `5.5G` `~/Library/Developer/Xcode/iOS DeviceSupport`
- `4.1G` `~/Library/Developer/CoreSimulator`
- `2.5G` `~/dev/bird-app/venv`

Those are not equally actionable. `DerivedData` and `Library/Caches` should always outrank Xcode archives, even when the archive is larger than some lower-risk candidate.

The same run also contains much larger but higher-risk buckets:

- `60G` `~/Library/Messages/Attachments`
- `12G` `~/Library/Application Support/Claude/vm_bundles`
- `5.4G` `~/Library/Application Support/Arc/User Data`

These should not appear ahead of obviously safe reclaimable space.

## Deterministic Tool

The best low-hanging implementation is a deterministic "Opportunity Ladder."

### Core Idea

Each matched directory gets:

- `tier`: broad actionability bucket
- `risk`: safety within the tier
- `size_bytes`
- `reclaimability`: whether the space is likely to come back automatically, be rebuilt on demand, or require user review

Then sort in this order:

1. `risk`
2. `size_bytes desc`
3. `tier`

This is intentionally not a fuzzy score. A lexicographic ordering is easier to reason about, easier to debug, and easier to trust.

### Proposed Tiers

#### `purge_now`

Fully reversible and usually safe to delete immediately.

Examples:

- trash
- caches
- logs
- code cache
- GPU cache
- updater residue
- package-manager caches

#### `rebuildable_dev`

Developer artifacts that can be recreated, but may cost time or require reinstall/build steps.

Examples:

- Xcode `DerivedData`
- simulator data/runtime caches
- `venv`
- `node_modules`
- Swift `.build`
- Rust `target`
- downloaded device support

#### `reviewable_state`

Large runtime state or app-owned working sets that are often removable, but should be presented as inspect/review items rather than instant-delete items.

Examples:

- Xcode Archives
- Claude `vm_bundles`
- IDE extension stores
- Docker Desktop data
- large app support directories with mixed cache/runtime contents

#### `human_data`

Real user content or user-curated working sets. Never treat as low-hanging fruit.

Examples:

- Messages attachments
- Downloads
- backups
- Photos
- browser profiles
- project folders
- notes/export folders

## Ranking Rules

### Deterministic Ordering

Use explicit ordering tables, not numeric heuristics hidden in code.

```python
TIER_ORDER = {
    "purge_now": 0,
    "rebuildable_dev": 1,
    "reviewable_state": 2,
    "human_data": 3,
}

RISK_ORDER = {
    "safe": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}
```

Then:

```python
recommendations.sort(
    key=lambda r: (
        RISK_ORDER[r.risk],
        -r.size_bytes,
        TIER_ORDER[r.tier],
    )
)
```

### Display Model

Each row should expose:

- path
- size
- tier
- risk
- why it is considered removable
- how to restore/rebuild it
- suggested action verb: `delete`, `review`, `archive`, or `ignore`

### Tier-Specific Wording

- `purge_now`: "Safe to delete"
- `rebuildable_dev`: "Rebuildable"
- `reviewable_state`: "Review before deleting"
- `human_data`: "User data; inspect manually"

## Rule Expansion For Current Data

The current rules cover a useful subset, but the April 10 run shows several obvious candidates to add.

### Strong deterministic additions

- `*/Library/Application Support/*/Cache*`
- `*/Code Cache`
- `*/GPUCache`
- `*/Dawn*Cache`
- `*/Library/Messages/Caches`
- `*/Library/Containers/*/Data/Library/Caches`
- `*/Library/Caches/ms-playwright`
- `*/Library/Caches/org.swift.swiftpm`
- `*/.cursor/extensions`
- `*/.windsurf/extensions`

### Important review-only additions

- `*/Library/Application Support/Claude/vm_bundles`
- `*/Library/Application Support/*/User Data`
- `*/Library/Application Support/Steam`
- `*/Library/Application Support/Google`
- `*/Library/Application Support/Arc`

These should not all share the same risk or tier. Some are clearly caches; others are app state or user profile data.

## Suggested Output For The April 10 Run

An Opportunity Ladder for that run should start roughly like this:

### Tier 1: Purge Now

- `19G` `~/Library/Developer/Xcode/DerivedData`
- `9.8G` `~/Library/Caches`
- `2.1G` `~/Library/Containers/com.apple.CoreDevice.CoreDeviceService/.../Caches`
- `963M` `~/.bun`
- `936M` `~/.yarn`
- `327M` `~/.npm`
- `175M` `~/Library/Logs`
- `514M` `~/.Trash`

### Tier 2: Rebuildable Dev

- `6.9G` `/Library/Developer/CoreSimulator`
- `5.5G` `~/Library/Developer/Xcode/iOS DeviceSupport`
- `4.1G` `~/Library/Developer/CoreSimulator`
- `2.5G` `~/dev/bird-app/venv`
- `1.0G` `~/dev/clients/scott/business-portal/node_modules`

### Tier 3: Reviewable State

- `6.8G` `~/Library/Developer/Xcode/Archives`
- `12G` `~/Library/Application Support/Claude/vm_bundles`
- `1.2G` `~/.cursor/extensions`
- `777M` `~/.windsurf/extensions`

### Tier 4: Human Data

- `60G` `~/Library/Messages/Attachments`
- `5.4G` `~/Library/Application Support/Arc/User Data`
- `4.4G` `~/Downloads`
- `3.3G` `~/NotesBackup`

## Claude-Powered Workflow

Claude should not replace the deterministic ladder. It should operate as a second-stage escalation path for ambiguous large buckets.

### Recommended Flow

1. Run deterministic ranking first.
2. Auto-surface `purge_now` and `rebuildable_dev`.
3. Send only unresolved `reviewable_state` and `human_data` candidates to Claude.
4. Ask Claude for a recommendation class, not free-form cleanup advice.

### Input Bundle Per Candidate

For each ambiguous candidate, provide:

- absolute path
- total size
- top children by size
- sample file names and extensions
- parent context
- app/vendor mapping if known
- modified-time summary if available
- whether the folder matches a known cache/profile/runtime pattern

### Claude Output Schema

Claude should return one of:

- `delete_now`
- `review_in_app`
- `archive_elsewhere`
- `leave_alone`

And for each:

- one-sentence rationale
- confidence
- user-facing caveat
- suggested next step

### Good Uses For Claude

- deciding whether a large app support folder is mostly cache vs profile data
- spotting stale app data from uninstalled apps
- identifying likely backup/export directories
- turning a noisy subtree into a concise human explanation

### Bad Uses For Claude

- ranking obviously safe caches
- replacing transparent deterministic rules
- issuing delete commands without human confirmation

## Implementation Notes

### Data Model Changes

Replace the current recommendation tuple with a richer structure:

- `path`
- `size_bytes`
- `size_human`
- `category`
- `tier`
- `risk`
- `action`
- `rationale`
- `regeneration`

The cleanup rule metadata should include `tier` and `action`, not just `risk`.

### UI Changes

The recommendations screen should group by tier or at least label each item clearly enough that the user can see why it is placed where it is.

Helpful additions:

- tier headers
- per-tier totals
- filter keys for `safe only` or `review items`
- a "why is this here?" detail view

### Non-Goals

- auto-delete
- opaque weighted scores
- AI-first ranking of obviously deterministic cases

## Recommended Sequence

1. Upgrade the deterministic recommendation engine into the Opportunity Ladder.
2. Expand rules for the buckets already visible in real scans.
3. Add grouped display in the TUI.
4. Add Claude review as an opt-in second pass for ambiguous large directories.

That order gets the highest user value with the least implementation risk.
