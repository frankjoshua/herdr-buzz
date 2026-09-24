# NOTES (herdr-buzz)

## Decisions
- **The pane agent is oblivious** (2026-09-13). It gets no Buzz key, no footer, no
  instructions, and burns no tokens on Buzz. `tee.py` sits on the stdio pipe between buzz-acp and
  herdr-acp: it strips buzz-acp's prompt down to `who: message`, and posts tool calls
  (`▸ Bash: pwd` / `✓ Bash: pwd`) and the final assistant text to the channel as the agent.
  Templates are module-level strings in tee.py; `--tools none` posts only the reply;
  `--raw-prompt` forwards buzz-acp's prompt untouched.
- **Everything in the pane mirrors to the channel** (2026-09-13): `⌨ <text>` when a human types in
  the pane, every assistant text block as it appears, `▸`/`✓`/`✗` per tool call. Verified both
  directions on the real relay. buzz-acp accepts updates between turns without complaint.
- **Pane input posts as the pane's owner** (2026-09-13). `user_message_chunk` is sent with `BUZZ_OWNER_NSEC`
  (no auth tag) so it reads as a message from the pane's owner, not from the agent. Buzz then hands
  that message back to the bridge as a prompt; the tee recognises its own recent owner posts and
  answers `end_turn` without touching the pane (`drop_echoes`).
- **The tee opens a session at startup** (`session/new`, id `tee-session`) because buzz-acp only
  opens one on the first channel message; without it nothing typed in the pane is mirrored until
  someone posts in Buzz. herdr-acp restarts its tail under buzz-acp's real session when it comes.
- **buzz-acp reads the agent's stdout only while a prompt is in flight** (found 2026-09-16 when the
  support bridge went silent). Between turns the pipe filled (64 KB), the tee blocked on write,
  herdr-acp blocked behind it, and the next Buzz prompt sat unanswered. The tee now forwards
  `session/update` upstream only between a `session/prompt` and its response; between turns it
  posts to the channel and drops the upstream copy. Tool results are no longer duplicated in
  `rawOutput` (buzz-acp's observer frames hit NIP-44's 64 KB limit).
- A Codex started by the Codex desktop harness runs inside `tmux -L codex-account-<pid>`; Herdr
  can't see it. herdr-acp follows the tmux socket to the pane process (transport.process()).
- buzz-acp still sees the full ACP stream during turns, so typing indicator and observer feed are unchanged.
- Caveat: a Claude session that previously received Buzz instructions keeps replying itself
  from memory. Start a fresh session when switching a pane to the tee.

- **No bridge pane, no decoration** (2026-09-18). The bridge is a background process group per pane
  (`setsid`; pid file + log in `HERDR_PLUGIN_STATE_DIR`). `prefix+y` opens a popup (plugin pane,
  placement `popup`) for the focused pane with status, log tail and controls; the action relays the
  focused pane id through `menu.target` because a plugin pane gets no target pane of its own.
  A `pane.closed` event detaches. The sidebar decoration was dropped: it did not render for Josh.

## Buzz UI facts (learned the hard way)
- "View activity" (owner-only tool-call/thought transcript) only appears on members whose channel
  role is `bot`. A key that *creates* a channel is `owner`, and cannot change its own role
  (`missing p tag`); another admin/owner must set it: `buzz channels add-member --pubkey <agent> --role bot`.
- Channels created by an agent key are invisible to the owner until the owner is added as a member.

- **Tool calls / thoughts in Buzz Desktop** show in the per-agent session panel (click the agent in a
  channel), fed by relay observer frames (kind 24200, encrypted to the owner). Two prerequisites:
  1. buzz-acp `--relay-observer` (the launcher passes it).
  2. The agent key's kind:0 profile must carry a NIP-OA `auth` tag signed by the owner's key.
     That is what turns "owner unavailable" into "managed by <owner>" AND what makes the desktop ingest
     the observer frames (`ownerByPubkey == me`). Only Buzz Desktop's create-agent flow mints one;
     no CLI does. Managed agents' `auth_tag` lives in
     `~/.local/share/xyz.block.buzz.app/agents/managed-agents.json`, the nsec in the OS keyring.
     Decision (2026-09-01): no desktop involved. The owner's nsec lives in `owner.env` and
     `mint.py` signs the tag itself (BIP-340 in stdlib Python, checked against the NIP-OA test
     vector).


## Reply-post failures on w24:p1 (CIO-62, 2026-09-24)
- **Two paths, one hostname.** Read: buzz-acp's WebSocket `wss://nostr-relay.stork-spica.ts.net`.
  Posting: `tee.py` → `buzz messages send` → `POST https://nostr-relay.stork-spica.ts.net/events`
  (NIP-98, one HTTPS call per post when the text has no `@`, up to 3 attempts). Both come from
  `BUZZ_RELAY_URL` in `owner.env`/`agents/<name>.env`. The relay (tailscaled serve on
  100.103.219.102:443 → :3000) logs every HTTP post with pubkey and status (`docker logs
  buzz-prod-relay-1 | grep "HTTP bridge request"`). That log is the ground truth: 3,509 posts from
  the CTO key were accepted between 2026-09-22 14:40Z and 2026-09-24 00:00Z. The tee logs failures
  only, so a log with no successful posts in it does not mean nothing was delivered.
- **`UnrecognisedName` is not the relay.** The relay's tailscaled answers a wrong SNI with
  `internal_error` and logged no handshake errors that day. When the tailnet's DNS for
  `stork-spica.ts.net` goes away, glibc (`hosts: … dns`) retries the name with the search list.
  `tesseractmobile.net` is on that list and has a wildcard record, so
  `nostr-relay.stork-spica.ts.net.tesseractmobile.net` resolves to the office WAN
  (24.241.106.254), which rejects the SNI with alert 112. You can reproduce it without sending
  anything: `getent ahostsv4 no-such-node.stork-spica.ts.net` returns 24.241.106.254.
  On 2026-09-22 at 15:23:09Z an agent ran `tailscale switch` on the primary daemon (the stork
  tailnet), and the switch lasted 51 s. The relay shows no posts between 15:22:55Z and 15:24:06Z,
  and buzz-acp's pong timed out in the same window. The real fix is on the host (the search
  domain or the wildcard record), not in this repo.
- **The 429s came from a replay.** At 23:49:20Z on 2026-09-23 someone ran `omp --resume` in the
  pane. herdr-acp built its PiSession before OMP had opened the session file, found the file
  later and read it from byte 0. That replayed 1,661 agent and 20 owner messages, about 300
  posts/min for 6 minutes. The relay's HTTP admission is `LimitType::ApiCalls` per pubkey per
  60 s fixed window (Redis INCR; rejected calls count but do not extend the window).
  The limit is `BUZZ_RATE_LIMIT_HUMAN_API_CALLS_PER_MIN`, default 300, and the deployment does
  not override it. The CTO key got 20 rejections, the owner key none. TLS failures never reach
  the relay, so they spend no quota. The fix belongs in herdr-acp (`reader.py`: when a session
  is found after the reader was built, start at the first line stamped after the process
  start). It is not a tee-side throttle.
- The tee's failure line now carries a UTC timestamp and the identity (`as agent`/`as owner`).
