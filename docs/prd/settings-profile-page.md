# PRD: Migrate Settings Under Profile Page
 
## Overview
 
Consolidate the existing standalone settings page into a tabbed section within the user profile page, creating a unified "account & configuration" hub. The profile page becomes the single entry point for user identity, preferences, and system-wide settings.
 
## Problem Statement
 
Settings and profile are currently separate destinations in the app. Users navigate to different pages to change their display name vs. configure SMTP or AI providers. This creates:
 
- **Fragmented UX**: Two separate navigation targets for closely related concepts.
- **Unclear information architecture**: Users don't know whether a setting lives under "profile" or "settings."
- **Wasted navigation**: Admin/system settings and personal preferences should live in the same place with clear separation.
 
### Current State
 
| Page | Contains | Route |
|------|----------|-------|
| Profile | Display name, avatar, password, sessions | `/profile` |
| Settings | SMTP, Telegram, AI providers, API keys | `/settings` |
 
### Target State
 
| Page | Contains | Route |
|------|----------|-------|
| Profile (unified) | All of the above, organized in tabs | `/profile` |
 
## Goals
 
| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Single destination for all user/system config | Users find all settings under profile within 1 click |
| G-2 | Clear tab separation | Personal vs. system settings visually distinct |
| G-3 | No functionality regression | Every setting accessible from the old page remains accessible |
| G-4 | Deep-linkable tabs | Each tab has a URL hash (e.g., `/profile#notifications`) |
 
## Non-Goals
 
- Role-based visibility of settings tabs (defer to Roles & Permissions PRD)
- Adding new settings — this is a reorganization of existing content
- Mobile-specific layouts (responsive design is sufficient)
 
## User Stories
 
### US-1: Navigate to Unified Profile
 
> As a user, I want one place to manage my account and application settings.
 
**Acceptance Criteria:**
 
1. Clicking profile avatar/name in the header navigates to `/profile`.
2. The profile page has a tab bar with sections:
   - **Account** — Display name, email, avatar, password change, active sessions.
   - **Notifications** — SMTP configuration, Telegram bot settings.
   - **AI Providers** — OpenRouter, OpenAI, Ollama, Hugging Face configuration.
   - **System** — General app settings, encryption key status, debug toggles.
3. The old `/settings` route redirects to `/profile#system` (or whichever tab is appropriate).
4. Tabs are deep-linkable: `/profile#notifications` opens the notifications tab.
 
### US-2: Manage Account Settings
 
> As a user, I want to update my profile information in the Account tab.
 
**Acceptance Criteria:**
 
1. Account tab shows: display name (editable), email (read-only), avatar URL (editable), "Change Password" button.
2. Active sessions listed with device info, IP, last active — "Revoke All" button.
3. Auth providers shown (password, Google, GitHub) with link/unlink actions.
4. Save triggers `PUT /auth/profile` and shows success toast.
 
### US-3: Configure Notifications
 
> As a user, I want to configure email and Telegram notifications in one place.
 
**Acceptance Criteria:**
 
1. Notifications tab shows SMTP fields: host, port, user, password (masked), "Test" button.
2. Telegram section: bot token (masked), enabled toggle, "Test" button.
3. Test buttons send a test notification and show success/failure inline.
4. Settings persist via existing `PUT /settings` API.
 
### US-4: Configure AI Providers
 
> As a user, I want to manage all AI provider settings in one tab.
 
**Acceptance Criteria:**
 
1. AI Providers tab shows expandable panels per provider (OpenRouter, OpenAI, Ollama, Hugging Face).
2. Each panel: API key (masked), endpoint URL, default model, "Test Connection" button.
3. Test validates connectivity and returns available models.
4. Settings persist via existing `PUT /settings` API.
 
## Technical Design
 
### Frontend Architecture
 
**Route change:**
- Remove `/settings` route (or redirect to `/profile`).
- Enhance `/profile` route with tab navigation.
 
**Component structure:**
```
src/routes/profile/
├── +page.svelte          # Tab container with hash-based navigation
├── AccountTab.svelte     # Existing profile fields + sessions
├── NotificationsTab.svelte  # SMTP + Telegram (moved from settings)
├── AiProvidersTab.svelte    # AI config (moved from settings)
└── SystemTab.svelte         # General settings (moved from settings)
```
 
**Tab navigation:**
- Use `$page.url.hash` to track active tab.
- Default to `#account` if no hash.
- Each tab lazy-loads its data on first activation.
 
### Backend Changes
 
No backend changes required — the existing `/auth/profile`, `/auth/password`, `/settings` endpoints remain unchanged. This is a purely frontend reorganization.
 
### Migration
 
1. Move settings components from the settings page into the profile route.
2. Add redirect from `/settings` → `/profile#system`.
3. Update all navigation links that pointed to `/settings`.
4. Update header profile dropdown menu items.
 
## Acceptance Criteria
 
- [ ] `/profile` shows a tabbed interface with Account, Notifications, AI Providers, System tabs
- [ ] Each tab hash is deep-linkable (`/profile#notifications`)
- [ ] Old `/settings` route redirects to `/profile` with appropriate tab
- [ ] All settings from the old page are accessible in the new layout
- [ ] Profile updates (name, avatar, password) work from the Account tab
- [ ] SMTP and Telegram test buttons work from the Notifications tab
- [ ] AI provider configuration works from the AI Providers tab
- [ ] No broken navigation links reference the old settings page
- [ ] `just verify` passes