# Task Tracker

## Status:

### Critical

- [x] 1. Compute engine job tracking race condition
- [x] 2. Compute engine env var pollution
- [x] 3. Analysis service missing transaction rollback
- [x] 4. Locks acquisition race condition
- [x] 7. Deterministic sample without seed
- [x] 8. Upload storage quota enforcement

### High Priority

- [x] 11. Non-atomic analysis version increment
- [x] 12. Dirty reads during schema cache population
- [x] 15. Silent schema extraction failures
- [x] 16. Partial upload cleanup on failure
- [x] 17. Preflight files TTL cleanup
- [x] 18. Notification failures surfaced
- [x] 1. UUID format validation on routes
- [x] 2. API datasource URL validation
- [x] 23. Unescaped filename in HTTP header
- [x] 24. DuckDB temp cleanup on exception
- [x] 25. Iceberg path symlink defense
- [x] 26. File format validation via magic numbers
- [x] 27. ETag/version headers for concurrency
- [x] 28. Draft restore validation vs server
- [x] 29. Join schema empty fallback handling
- [x] 30. Schema refresh delay
- [x] 31. Locks module tests
- [X] 32. Engine runs module tests
- [X] 33. Analysis versions tests
- [x] 34. Frontend unit tests coverage
- [x] 35. Performance tests baseline
- [x] 36. Disabled steps passthrough + output notifications
- [x] 37. Export datasets use uuid paths + schema evolution
- [x] 59. Build query plan includes pre-eager steps annotation
- [x] 60. AI/notification steps remain lazy (no internal collect)
- [x] 61. Test DB isolation (prevent tests from touching production DB)
- [x] 62. Unified compute requests with full analysis payload
- [x] 63. Backend compute preview/schema/export accept analysis_pipeline + tab_id
- [x] 64. Build payload endpoint added and wired for OutputNode
- [x] 65. Remove legacy compute endpoints and payload fallbacks

### Medium Priority

- [x] 41. Remove hardcoded CORS IPs
- [x] 42. Disable public IDB debug by default
- [x] 43. Encrypt SMTP passwords at rest
- [x] 44. Validate database URL
- [x] 45. Normalize DELETE status codes
- [x] 46. Telegram settings unified + notifications gating
- [x] 47. Notification UDF recipient source selection
- [x] 51. Remove bare except clauses
- [x] 52. Preserve error context in exceptions
- [x] 53. Standardize error handling patterns
- [x] 54. User-friendly error messages
- [x] 55. Timeout handling consistency
- [x] 56. Process lifecycle gaps
- [x] 57. Check-then-act cleanup races
- [x] 58. Queue reuse after corruption timeout
