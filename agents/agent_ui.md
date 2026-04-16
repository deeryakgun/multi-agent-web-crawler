# Agent: UI Agent

## Role
Designs and implements the single-page dashboard UI.

## Responsibilities
- Implement `frontend/index.html` as a single self-contained file
- Design the dark-mode aesthetic and component system
- Implement real-time polling (3-second interval)
- Show queue depth progress bar with back-pressure colour coding
- Implement the search interface with autocomplete and pagination
- Ensure the file is served correctly by Flask's static route

## Prompt
> "You are the UI Agent. Build a single HTML file (no frameworks, no build step) that serves as the complete dashboard for the crawler system. Sections: (1) Dashboard with global stats and live active-job monitors, (2) New Crawl form, (3) Crawl Jobs list with pause/resume/stop controls and an expandable log terminal, (4) Search with TF-IDF results, autocomplete, pagination, and sort options. Use a clean light theme design (white backgrounds, soft borders, indigo accents, Inter font, JetBrains Mono for code). Poll every 3 seconds. Show back-pressure as a red 'High Load' badge."

## Key Design Decisions

### Polling Strategy
- `setInterval(refreshStats, 3000)` on page load
- Polls `/index/stats` and `/index/list` simultaneously
- Search does not auto-refresh (user-triggered only)

### Back Pressure Visualisation
```
ratio = queue_depth / queue_cap
green  < 50%
yellow 50–80%
red    > 80%  + "High Load" badge
```

### Log Terminal
- Collapsed by default per job
- Opens on demand via "📋 Logs" button
- Shows last 60 log lines in monospace terminal style
- Auto-scrolls to bottom

### Autocomplete
- Debounced 250 ms input handler
- Calls `/search/suggest?q=<prefix>`
- Closes on outside click or Escape key

## Critique Received from Human
"Queue meter should show percentage AND absolute count."
**Resolution:** Updated meter label to `X% of N,000` format.

## Outputs
- `frontend/index.html` — complete SPA (single file, ~550 lines)
