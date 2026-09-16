"""Sits between buzz-acp and herdr-acp on stdio. The agent in the pane stays oblivious.

    buzz-acp --agent-command python --agent-args=tee.py,--channel,<id>,--pane,<pane>

Downstream (buzz-acp → herdr-acp): every JSON-RPC line is forwarded unchanged, except
`session/prompt`, whose text is reduced to just the humans' messages ("josh: hello") so the
agent burns no context on Buzz's routing boilerplate.
Upstream (herdr-acp → buzz-acp): every line is forwarded unchanged so buzz-acp keeps its typing
indicator and observer feed; on the side, everything the pane does (humans typing in it, the
agent's text, tool calls) is posted to the channel as the agent via the `buzz` CLI, so the
channel and the pane are one shared session. Env comes from bin/herdr-buzz.

Edit the templates below to change what gets posted. `--tools none` skips tool calls.
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading

# ---- what gets posted (edit freely) ----------------------------------------------------
TOOL_START = "▸ {title}"
TOOL_DONE = "✓ {title}"
TOOL_FAIL = "✗ {title}"
AGENT_TEXT = "{text}"          # every assistant text block, as it appears
PANE_INPUT = "{text}"          # a human typing in the pane: posted AS the pane's owner (BUZZ_OWNER_NSEC)
TITLE_MAX = 120
TEE_SESSION = "tee-session"    # id of the session/new the tee sends on the client's behalf

# buzz-acp's prompt, one block per event:  "From: josh (npub…, hex: …)\n…\nContent: <text>\nTags: […]"
EVENT = re.compile(r"^From: (\S+)(?:[^\n]*hex: ([0-9a-f]{64}))?[^\n]*\n.*?^Content: ?(.*?)\n(?:Tags:|\Z)", re.S | re.M)
OWNER = os.environ.get("BUZZ_OWNER_PUBKEY", "")  # the pane's owner: their messages arrive unlabeled


def events_of(blocks: list[str]) -> list[tuple[str, str, str]]:
    """(who, pubkey, what) per Buzz event in buzz-acp's prompt blocks."""
    return [(who, key, what.strip()) for b in blocks for who, key, what in EVENT.findall(b)]


def render_events(events) -> list[str]:
    """One block; the pane's owner speaks unlabeled, anyone else is 'who: what'."""
    return ["\n\n".join(what if OWNER and key == OWNER else f"{who}: {what}" for who, key, what in events)]


def reduce_prompt(blocks: list[str]) -> list[str]:
    """Collapse buzz-acp's prompt blocks (standing context, [Context], events) to the messages.
    Prompts with no recognizable event pass through unchanged."""
    events = events_of(blocks)
    return render_events(events) if events else blocks


def drop_echoes(blocks: list[str], echoes: list[str]) -> list[str] | None:
    """Remove events whose text the tee itself just posted as the owner (pane input coming back
    through Buzz). Returns None when nothing is left, i.e. the whole prompt was an echo."""
    events = events_of(blocks)
    if not events:
        return blocks
    keep = [e for e in events if e[2] not in echoes]
    return render_events(keep) if keep else None


class Renderer:
    """One session_update -> the line to post (or None). Remembers tool titles across updates."""

    def __init__(self, tools: bool = True):
        self.titles, self.tools = {}, tools

    def render(self, update: dict) -> str | None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            return AGENT_TEXT.format(text=update["content"].get("text", ""))
        if kind == "user_message_chunk":
            return PANE_INPUT.format(text=update["content"].get("text", ""))
        if not self.tools:
            return None
        if kind == "tool_call":
            title = (update.get("title") or "tool")[:TITLE_MAX]
            self.titles[update.get("toolCallId")] = title
            return TOOL_START.format(title=title)
        if kind == "tool_call_update":
            title = self.titles.get(update.get("toolCallId"), "tool")
            st = update.get("status")
            if st == "completed":
                return TOOL_DONE.format(title=title)
            if st == "failed":
                return TOOL_FAIL.format(title=title)
        return None


# ---- plumbing --------------------------------------------------------------------------
class Poster:
    """Posts to the channel in order, off the pipe threads."""

    def __init__(self, channel: str):
        self.channel, self.q = channel, queue.Queue()
        self.owner = os.environ.get("BUZZ_OWNER_NSEC")
        self.echoes = []  # texts posted as the owner; Buzz will hand them back as prompts
        threading.Thread(target=self._run, daemon=True).start()

    def post(self, text: str, as_owner: bool = False) -> None:
        if not text.strip():
            return
        if as_owner and self.owner:
            self.echoes = (self.echoes + [text.strip()])[-20:]
        self.q.put((text, as_owner and bool(self.owner)))

    def _run(self) -> None:
        while True:
            text, as_owner = self.q.get()
            env = dict(os.environ)
            if as_owner:  # the owner's own key, and no agent auth tag on a human's message
                env["BUZZ_PRIVATE_KEY"] = self.owner
                env.pop("BUZZ_AUTH_TAG", None)
            try:
                r = subprocess.run(["buzz", "messages", "send", "--channel", self.channel, "--content", "-"],
                                   input=text, capture_output=True, text=True, env=env)
                if r.returncode:
                    raise RuntimeError(r.stderr.strip()[:300])
            except Exception as e:  # the thread must outlive a missing/broken `buzz`
                print(f"tee: post failed: {e}", file=sys.stderr, flush=True)


def downstream(src, dst, transform, poster: Poster, reply, turn: threading.Event) -> None:
    """Forward src -> dst; `transform(texts) -> texts` rewrites each session/prompt's text blocks.
    A prompt that is only our own owner-posted pane input echoing back is answered with end_turn
    via `reply(msg)` and never reaches the pane."""
    for line in src:
        try:
            msg = json.loads(line)
            if msg.get("method") == "session/prompt":
                turn.set()  # buzz-acp reads our stdout only while it waits for this answer
                blocks = msg["params"].get("prompt", [])
                texts = [b["text"] for b in blocks if b.get("type") == "text"]
                if len(texts) == len(blocks):
                    texts = drop_echoes(texts, poster.echoes)
                    if texts is None:
                        turn.clear()
                        reply({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"stopReason": "end_turn"}})
                        continue
                    msg["params"]["prompt"] = [{"type": "text", "text": t} for t in transform(texts)]
                line = (json.dumps(msg) + "\n").encode()
        except (ValueError, KeyError, TypeError) as e:
            print(f"tee: prompt not reduced: {e!r}", file=sys.stderr, flush=True)
        dst.write(line)
        dst.flush()
        if msg.get("method") == "initialize":
            # buzz-acp only opens a session on the first channel message; open one now so the pane
            # is mirrored from the start. herdr-acp re-keys its tail when the real session arrives.
            dst.write((json.dumps({"jsonrpc": "2.0", "id": TEE_SESSION, "method": "session/new",
                                   "params": {"cwd": "/", "mcpServers": []}}) + "\n").encode())
            dst.flush()
    dst.close()


def upstream(src, dst, lock, poster: Poster, renderer: Renderer, turn: threading.Event) -> None:
    for line in src:
        try:
            msg = json.loads(line)
        except ValueError:
            msg = {}
        if msg.get("id") == TEE_SESSION:
            continue  # answer to our own early session/new; buzz-acp never asked
        # Between turns buzz-acp does not read this pipe, so forwarding would block once it fills
        # (64 KB) and stall everything behind it. The channel gets the updates either way.
        if msg.get("method") == "session/update" and not turn.is_set():
            pass
        else:
            with lock:
                dst.write(line)
                dst.flush()
        if isinstance(msg.get("result"), dict) and "stopReason" in msg["result"]:
            turn.clear()
        if msg.get("method") == "session/update":
            u = msg["params"]["update"]
            out = renderer.render(u)
            if out:
                poster.post(out, as_owner=u.get("sessionUpdate") == "user_message_chunk")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--pane", required=True)
    ap.add_argument("--tools", choices=["all", "none"], default="all")
    ap.add_argument("--raw-prompt", action="store_true", help="forward buzz-acp's prompt untouched")
    ap.add_argument("--herdr-acp", default=os.environ.get(
        "HERDR_ACP", os.path.expanduser("~/development/workspace/herdr-acp/.venv/bin/herdr-acp")))
    a = ap.parse_args()
    child = subprocess.Popen([a.herdr_acp, "--pane", a.pane], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    poster = Poster(a.channel)
    transform = (lambda blocks: blocks) if a.raw_prompt else reduce_prompt
    lock = threading.Lock()
    turn = threading.Event()

    def reply(msg):
        with lock:
            sys.stdout.buffer.write((json.dumps(msg) + "\n").encode())
            sys.stdout.buffer.flush()

    t = threading.Thread(target=downstream, args=(sys.stdin.buffer, child.stdin, transform, poster, reply, turn), daemon=True)
    t.start()
    upstream(child.stdout, sys.stdout.buffer, lock, poster, Renderer(tools=a.tools == "all"), turn)
    sys.exit(child.wait())


def _selfcheck() -> None:
    p = ["[Base] You are operating inside the Buzz platform…",
         "[Context]\nScope: channel\nChannel: t (#abc)\nHint: blah\nIMPORTANT: use --reply-to x",
         "[Buzz events — 2 events]\n\n--- Event 1 (all) ---\nEvent ID: e1\nChannel: t\nKind: 9\n"
         "From: josh (npub1x, hex: " + "a0" * 32 + ")\nTime: now\nContent: hello\nthere\nTags: [[\"h\",\"abc\"]]\n\n"
         "--- Event 2 (all) ---\nFrom: sam (hex: b1)\nTime: now\nContent: run pwd\nTags: []\n"]
    global OWNER
    OWNER = ""
    assert reduce_prompt(p) == ["josh: hello\nthere\n\nsam: run pwd"], repr(reduce_prompt(p))
    OWNER = "a0" * 32  # josh owns the pane: no label for him, label for sam
    assert reduce_prompt(p) == ["hello\nthere\n\nsam: run pwd"], repr(reduce_prompt(p))
    assert reduce_prompt(["plain heartbeat"]) == ["plain heartbeat"]
    r = Renderer(tools=True)
    assert r.render({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Bash: pwd"}) == "▸ Bash: pwd"
    assert r.render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}) == "✓ Bash: pwd"
    assert r.render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "in_progress"}) is None
    assert r.render({"sessionUpdate": "agent_thought_chunk"}) is None
    assert r.render({"sessionUpdate": "agent_message_chunk", "content": {"text": "hi"}}) == "hi"
    assert r.render({"sessionUpdate": "user_message_chunk", "content": {"text": "fix it"}}) == "fix it"
    assert drop_echoes(p, ["hello\nthere"]) == ["sam: run pwd"]
    assert drop_echoes(p, ["hello\nthere", "run pwd"]) is None
    assert drop_echoes(["plain heartbeat"], ["x"]) == ["plain heartbeat"]
    assert Renderer(tools=False).render({"sessionUpdate": "tool_call", "toolCallId": "t2", "title": "x"}) is None
    print("tee ok")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
