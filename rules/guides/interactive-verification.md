# Interactive verification (the default way to check things in a running game)

Whenever a test, a probe or any runtime analysis needs the player to do something or to judge what they see, check it
**with the player, one step at a time, through the in-game overlay**. Don't hand them a list of things to try, and
don't ask them to switch to the chat window while they're playing.

## The loop

1. **Wait until the player is ready, by an event, never a timer.** Examples: the agent connected, the scene loaded,
   the device the test needs showed up in the game's log, or a "Ready" prompt was answered.
   - Don't start a timed step right after a chat message: the player may still be switching windows (remote play
     often means a second app for the chat).
   - If you do need a delay, say so in the game first, and give generous time.
2. **Ask one thing per prompt** (`live_prompt`, the agent's `overlay.prompt`):
   - the message says exactly what to do and what should happen;
   - the buttons are the expected outcome first, then the likely failures;
   - always add a typed answer (`text_button`, e.g. "Something else"), so the player can say what really happened
     without leaving the game;
   - keep the button labels short.
3. **Wait for the answer** (`overlay.promptResult`), then act on it:
   - expected → go on to the next step;
   - a failure → investigate, fix, and re-check only that step;
   - typed text → read it carefully; it often holds the real problem.
4. **Close every loop.** After anything the player had to wait or hold still for (a screenshot, a capture, a long
   step), notify them at once that it's done and what comes next (`live_notify`). The same goes at the end ("all done,
   you can quit"). A player left waiting can't tell a slow step from a hung one.
5. **Record the results** as the test's or probe's evidence: step, expected outcome, the answer, and any typed text.

## Good practice

- **Prompts in gameplay:** if the player has to pause to answer (the cursor is locked in gameplay), say so in the
  first prompt ("press Start to answer, Start again to resume"). The pause doubles as a check of the pause control.
- **Screenshots of what the player sees:** ask them to keep it on screen and press a button. Take the screenshot when
  the answer arrives, then notify them right away.
- **Notification history:** missed notifications aren't lost. The expanded overlay's Activity tab lists them, and open
  questions can be answered there too. Point the player to it if they mention missing something.
- **Device checks before input tests:** when a test depends on a device (a gamepad, a wheel), first confirm the game
  sees it (a log line, a readiness prompt). If it doesn't, look for something hiding the device from the game before
  blaming the player's setup. One example: Steam Input hides controllers from games that start the Steam API.
- **Sequence:** go from the simplest check to the hardest (menus, then movement, then actions, then edge cases).
  Re-check after each fix.
- **Same rule for runtime analysis:** whenever runtime analysis needs a gameplay state the agent can't produce by
  itself, ask for it the same way ("Please open a chest, then press Done").
