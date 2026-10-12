# development-lead cases

Newest first. There is one case per kind of help. A recurrence adds a line under **Occurrences**. **Lasting fix**
is `none`, `shot <shotfile>/<n>`, `plan <NNNN>` or `landed <plan> <date>`.

## 2026-10-03 · Finished plans wait for "the Mac is free" to run UI tests

- **Signature**: `asks` or `idle-in-plan`, where `said` asks whether the Mac is free, or reports that the screen is
  locked, before `build.sh check` / XCUITest.
- **Helped by**: okaying the landing with the UI tests run after it (the user's rule of 2026-10-03), and batching
  "unlock the Mac" for the user.
- **Occurrences**:
  - 2026-10-03 hal2 wt 04, 05, 06, 14.
- **Lasting fix**: none. The idea is a scheduled UI-test window (the farmer runs every waiting slot's UI tests one
  after the other while the user is away and the Mac is unlocked).
