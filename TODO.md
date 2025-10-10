# TODO: Implement Auto-Mute on Repeat Blacklisted Words

## Completed Steps
- [x] Analyze user task: Modify Discord bot to warn on first blacklisted word usage and mute on repeat.
- [x] Read relevant files: moderation.py, moderation.json, blacklist.json.
- [x] Brainstorm plan: Add word_warning embed to moderation.json, create user_words.json database, modify on_message in moderation.py to track and handle first/repeat offenses.
- [x] Edit moderation.json: Add "word_warning" embed configuration.
- [x] Create user_words.json: Empty JSON file for storing user-word tracking.
- [x] Edit moderation.py: Load user_words, add save_user_words method, update send_dm to handle {word}, replace on_message logic to warn on first use, mute on repeat.
- [x] Test implementation: Ensure code compiles and logic is correct.

## Followup Steps
- [ ] Restart the bot to apply changes.
- [ ] Test in a Discord server: Send a blacklisted word (first time: should warn via DM and channel message), send again (should mute).
- [ ] Monitor user_words.json for correct data saving.
- [ ] Adjust embed text if needed based on feedback.
