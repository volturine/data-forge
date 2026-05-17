# Build Preview PRD Checklist

Source: `docs/prd/build-preview.md`

## Status legend

- [x] Done
- [~] Partial
- [ ] Missing
- [!] Bug / regression

## Goals

- [x] G-1 Users see which step is currently executing
- [x] G-2 Visual progress bar with percentage and ETA
- [x] G-3 Per-step timing shown live as steps complete
- [~] G-4 Query plan visible before and during execution
- [x] G-5 Resource usage visible during build
- [~] G-6 Remote build monitoring from any device

## US-1 Live Build Progress Bar

- [x] Progress panel appears when build starts
- [x] Progress bar shows percentage, current step, elapsed time, ETA
- [x] ETA calculated from progress so far
- [x] Progress updates during execution
- [x] Completion shows terminal result state
- [x] Failure shows terminal error state

## US-2 Step-by-Step Build Visualization

- [x] Step list shown alongside progress
- [x] Pending / running / completed / failed states rendered
- [x] Current step visually emphasized
- [x] Completed steps show duration
- [x] Total steps count shown

## US-3 Query Plan Preview

- [x] Query plan tab exists
- [x] Optimized/unoptimized toggle exists
- [x] Plan available during build start flow
- [ ] Syntax highlighting for plan text
- [ ] Current executing plan node highlighting

## US-4 Resource Monitoring During Build

- [x] Resource panel shows CPU / memory / threads
- [x] Resource updates stream during build
- [x] Historical mini-chart / sparkline
- [x] Warning indicator when memory exceeds 80%
- [x] Engine configuration summary shown (`max_threads`, `max_memory_mb`)

## US-5 Build Log Streaming

- [x] Log panel exists with streamed output
- [x] Log entries include level/message and optional step context
- [x] Filter by level
- [x] Auto-scroll pauses when user scrolls up
- [x] Copy logs to clipboard

## US-6 Remote Build Monitoring

- [x] Monitoring page shows currently running builds
- [~] Running build row shows analysis + current step + progress
- [ ] Filter by status / user / analysis / date range
- [~] Starter/user attribution visible in build list and detail
- [x] Live progress updates via websocket for visible running builds
- [x] Accessible from another authenticated session

## Security / robustness

- [x] WebSocket auth enforced
- [x] Resource monitoring scoped to engine process
- [ ] Log sanitization for sensitive data
- [ ] Rate limiting on websocket event emission

## Known bugs found during audit

- [~] Real build flow event-loop scheduling guarded against `no running event loop` (mitigated with `call_soon_threadsafe` + fallback; not a hard failure)

## Definition of done for this PRD

- [ ] All checklist items above completed or explicitly re-scoped
- [ ] `just verify` passes
- [ ] `just test` passes
- [ ] `just test-e2e` passes
- [ ] Real build preview flow is stable and bug-free
- [ ] Remote monitoring flow is stable and bug-free
