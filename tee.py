"""Sits between buzz-acp and herdr-acp on stdio. The agent in the pane stays oblivious.

    buzz-acp --agent-command python --agent-args=tee.py,--channel,<id>,--pane,<pane>

Downstream (buzz-acp → herdr-acp): every JSON-RPC line is forwarded unchanged, except
`session/prompt`, whose text is reduced to just the humans' messages ("alice: hello") so the
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
TOOL_DONE = "✓ {title}{out}"     # {out} = result excerpt as a code block, "" when there was none
TOOL_FAIL = "✗ {title}{out}"
OUT_LINES, OUT_CHARS = 8, 600    # how much of a tool result to show
AGENT_TEXT = "{text}"          # every assistant text block, as it appears
PANE_INPUT = "{text}"          # a human typing in the pane: posted AS the pane's owner (BUZZ_OWNER_NSEC)
TITLE_MAX = 120
TEE_SESSION = "tee-session"    # id of the session/new the tee sends on the client's behalf

# buzz-acp's prompt, one block per event:  "From: alice (npub…, hex: …)\n…\nContent: <text>\nTags: […]"
EVENT = re.compile(r"^From: (\S+)(?:[^\n]*hex: ([0-9a-f]{64}))?[^\n]*\n.*?^Content: ?(.*?)\n(?:Tags:|\Z)", re.S | re.M)


def events_of(blocks: list[str]) -> list[tuple[str, str, str]]:
    """(who, pubkey, what) per Buzz event in buzz-acp's prompt blocks."""
    return [(who, key, what.strip()) for b in blocks for who, key, what in EVENT.findall(b)]


def render_events(events, owner: str) -> list[str]:
    """One block; the pane's owner speaks unlabeled, anyone else is 'who: what'."""
    return ["\n\n".join(what if owner and key == owner else f"{who}: {what}" for who, key, what in events)]


def drop_echoes(blocks: list[str], echoes: list[str]) -> list[tuple[str, str, str]] | None:
    """The prompt's events minus those whose text the tee itself just posted as the owner (pane
    input coming back through Buzz). None when every event was an echo; [] when the prompt
    carried no recognizable event (a heartbeat), which callers forward unchanged."""
    events = events_of(blocks)
    kept = [e for e in events if e[2] not in echoes]
    return kept if kept or not events else None


def excerpt(update: dict) -> str:
    """First lines of a tool result, fenced; '' when the result carried no text."""
    text = "".join((c.get("content") or {}).get("text", "") for c in update.get("content") or [] if isinstance(c, dict))
    lines = text.strip().splitlines()
    if not lines:
        return ""
    body = "\n".join(lines[:OUT_LINES])[:OUT_CHARS]
    more = " …" if len(lines) > OUT_LINES or len(text.strip()) > OUT_CHARS else ""
    return f"\n```\n{body}{more}\n```"


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
            if st in ("completed", "failed"):
                return (TOOL_DONE if st == "completed" else TOOL_FAIL).format(title=title, out=excerpt(update))
        return None


# ---- plumbing --------------------------------------------------------------------------
class Poster:
    """Posts to the channel in order, off the pipe threads."""

    def __init__(self, channel: str):
        self.channel, self.q = channel, queue.Queue()
        self.owner = os.environ.get("BUZZ_OWNER_NSEC")
        self.echoes = []  # texts posted as the owner; Buzz will hand them back as prompts
        threading.Thread(target=self._run, daemon=True).start()

    def post(self, text: str) -> None:
        """As the agent."""
        self._put(text, dict(os.environ))

    def post_as_owner(self, text: str) -> None:
        """As the pane's owner: their own key, no agent auth tag. As the agent when no owner key is set."""
        if not self.owner:
            return self.post(text)
        env = {**os.environ, "BUZZ_PRIVATE_KEY": self.owner}
        env.pop("BUZZ_AUTH_TAG", None)
        if self._put(text, env):
            self.echoes = (self.echoes + [text.strip()])[-20:]

    def _put(self, text: str, env: dict) -> bool:
        if not text.strip():
            return False
        self.q.put((text, env))
        return True

    def _run(self) -> None:
        while True:
            text, env = self.q.get()
            try:
                r = subprocess.run(["buzz", "messages", "send", "--channel", self.channel, "--content", "-"],
                                   input=text, capture_output=True, text=True, env=env)
                if r.returncode:
                    raise RuntimeError(r.stderr.strip()[:300])
            except Exception as e:  # the thread must outlive a missing/broken `buzz`
                print(f"tee: post failed: {e}", file=sys.stderr, flush=True)


class Tee:
    """The two pipe directions between `client` (buzz-acp's side of our stdio) and `child`
    (herdr-acp), plus the reply path for prompts the tee answers itself."""

    def __init__(self, child, client, poster, renderer: Renderer, owner: str, raw: bool = False):
        self.child, self.client, self.poster, self.renderer, self.owner = child, client, poster, renderer, owner
        # what the pane sees for a prompt's (blocks, surviving events): the humans' messages, or buzz-acp's text under --raw-prompt
        self.transform = (lambda blocks, events: blocks) if raw else (lambda blocks, events: render_events(events, owner))
        self.lock = threading.Lock()  # one writer to `client` at a time
        self.turn = threading.Event()  # a session/prompt is unanswered

    def reply(self, msg: dict) -> None:
        with self.lock:
            self.client.write((json.dumps(msg) + "\n").encode())
            self.client.flush()

    def downstream(self, src) -> None:
        """Forward src -> child; each session/prompt's text blocks go through `drop_echoes` and
        `transform`. A prompt that is only our own owner-posted pane input echoing back is
        answered with end_turn and never reaches the pane."""
        dst = self.child.stdin
        for line in src:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = {}
            if msg.get("method") == "session/prompt":
                self.turn.set()  # buzz-acp reads our stdout only while it waits for this answer
                try:
                    blocks = msg["params"].get("prompt", [])
                    texts = [b["text"] for b in blocks if b.get("type") == "text"]
                    if len(texts) == len(blocks):
                        events = drop_echoes(texts, self.poster.echoes)
                        if events is None:
                            self.turn.clear()
                            self.reply({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"stopReason": "end_turn"}})
                            continue
                        if events:
                            msg["params"]["prompt"] = [{"type": "text", "text": t} for t in self.transform(texts, events)]
                            line = (json.dumps(msg) + "\n").encode()
                except (KeyError, TypeError) as e:
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

    def upstream(self, src) -> None:
        """Forward src -> client (while a turn is open) and post every session/update to the channel."""
        for line in src:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = {}
            if msg.get("id") == TEE_SESSION:
                continue  # answer to our own early session/new; buzz-acp never asked
            # Between turns buzz-acp does not read this pipe, so forwarding would block once it fills
            # (64 KB) and stall everything behind it. The channel gets the updates either way.
            if msg.get("method") != "session/update" or self.turn.is_set():
                with self.lock:
                    self.client.write(line)
                    self.client.flush()
            if isinstance(msg.get("result"), dict) and "stopReason" in msg["result"]:
                self.turn.clear()
            if msg.get("method") == "session/update":
                u = msg["params"]["update"]
                out = self.renderer.render(u)
                if out:
                    (self.poster.post_as_owner if u.get("sessionUpdate") == "user_message_chunk" else self.poster.post)(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--pane", required=True)
    ap.add_argument("--tools", choices=["all", "none"], default="all")
    ap.add_argument("--raw-prompt", action="store_true", help="forward buzz-acp's prompt untouched")
    ap.add_argument("--herdr-acp", default=os.environ.get(
        "HERDR_ACP", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "herdr-acp")))
    a = ap.parse_args()
    child = subprocess.Popen([a.herdr_acp, "--pane", a.pane], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    owner = os.environ.get("BUZZ_OWNER_PUBKEY", "")  # the pane's owner: their messages arrive unlabeled
    tee = Tee(child, sys.stdout.buffer, Poster(a.channel), Renderer(tools=a.tools == "all"), owner, a.raw_prompt)
    threading.Thread(target=tee.downstream, args=(sys.stdin.buffer,), daemon=True).start()
    tee.upstream(child.stdout)
    sys.exit(child.wait())


def _selfcheck() -> None:
    import io
    from types import SimpleNamespace

    p = ["[Base] You are operating inside the Buzz platform…",
         "[Context]\nScope: channel\nChannel: t (#abc)\nHint: blah\nIMPORTANT: use --reply-to x",
         "[Buzz events — 2 events]\n\n--- Event 1 (all) ---\nEvent ID: e1\nChannel: t\nKind: 9\n"
         "From: alice (npub1x, hex: " + "a0" * 32 + ")\nTime: now\nContent: hello\nthere\nTags: [[\"h\",\"abc\"]]\n\n"
         "--- Event 2 (all) ---\nFrom: bob (hex: b1)\nTime: now\nContent: run pwd\nTags: []\n"]
    alice, bob = ("alice", "a0" * 32, "hello\nthere"), ("bob", "", "run pwd")
    assert events_of(p) == [alice, bob], repr(events_of(p))
    assert render_events([alice, bob], "") == ["alice: hello\nthere\n\nbob: run pwd"]
    owner = "a0" * 32  # alice owns the pane: no label for her, label for bob
    assert render_events([alice, bob], owner) == ["hello\nthere\n\nbob: run pwd"]
    assert drop_echoes(p, []) == [alice, bob]
    assert drop_echoes(p, ["hello\nthere"]) == [bob]  # our echo dropped, bob kept
    assert drop_echoes(p, ["hello\nthere", "run pwd"]) is None  # all echo: end_turn, never reaches the pane
    assert drop_echoes(["plain heartbeat"], ["x"]) == []  # no event: forwarded unchanged
    r = Renderer(tools=True)
    assert r.render({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Bash: pwd"}) == "▸ Bash: pwd"
    assert r.render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}) == "✓ Bash: pwd"
    out = {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed",
           "content": [{"type": "content", "content": {"type": "text", "text": "\n".join(f"line{i}" for i in range(12))}}]}
    got = r.render(out)
    assert got.startswith("✓ Bash: pwd\n```\nline0\n") and got.endswith("line7 …\n```"), got
    assert r.render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "failed",
                     "content": [{"type": "content", "content": {"type": "text", "text": "boom"}}]}) == "✗ Bash: pwd\n```\nboom\n```"
    assert r.render({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "in_progress"}) is None
    assert r.render({"sessionUpdate": "agent_thought_chunk"}) is None
    assert r.render({"sessionUpdate": "agent_message_chunk", "content": {"text": "hi"}}) == "hi"
    assert r.render({"sessionUpdate": "user_message_chunk", "content": {"text": "fix it"}}) == "fix it"
    assert Renderer(tools=False).render({"sessionUpdate": "tool_call", "toolCallId": "t2", "title": "x"}) is None

    # the pipes: a fake child (BytesIO stdin/stdout) and a fake poster that only records
    class Sink(io.BytesIO):
        def close(self): pass  # downstream closes the child's stdin; keep the bytes readable
        def lines(self): return [json.loads(l) for l in self.getvalue().splitlines()]

    class FakePoster:
        def __init__(self): self.echoes, self.posts = [], []
        def post(self, text): self.posts.append(("agent", text))
        def post_as_owner(self, text): self.posts.append(("owner", text))

    def rpc(**msg): return (json.dumps({"jsonrpc": "2.0", **msg}) + "\n").encode()
    def prompt(id, blocks): return rpc(id=id, method="session/prompt", params={"sessionId": "s", "prompt": [{"type": "text", "text": b} for b in blocks]})
    def update(text): return rpc(method="session/update", params={"sessionId": "s", "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": text}}})

    def tee(raw=False):
        child = SimpleNamespace(stdin=Sink(), stdout=None)
        t = Tee(child, Sink(), FakePoster(), Renderer(), owner, raw)
        return t, child.stdin, t.client
    # (a) initialize -> a session/new with id TEE_SESSION follows it to the child; heartbeat forwarded unchanged
    t, to_child, to_client = tee()
    t.downstream(io.BytesIO(rpc(id=1, method="initialize", params={}) + prompt(2, ["plain heartbeat"])))
    got = to_child.lines()
    assert [m.get("method") for m in got] == ["initialize", "session/new", "session/prompt"], got
    assert got[1]["id"] == TEE_SESSION and got[2]["params"]["prompt"][0]["text"] == "plain heartbeat", got
    assert t.turn.is_set() and to_client.getvalue() == b""
    # a real prompt is reduced (owner unlabeled), or forwarded verbatim under --raw-prompt
    t, to_child, _ = tee()
    t.downstream(io.BytesIO(prompt(3, p)))
    assert [b["text"] for b in to_child.lines()[0]["params"]["prompt"]] == ["hello\nthere\n\nbob: run pwd"], to_child.lines()
    t, to_child, _ = tee(raw=True)
    t.downstream(io.BytesIO(prompt(3, p)))
    assert [b["text"] for b in to_child.lines()[0]["params"]["prompt"]] == p
    # (c) a prompt that is only our own echo: end_turn to the client, nothing to the child, turn closed
    t, to_child, to_client = tee()
    t.poster.echoes = ["hello\nthere", "run pwd"]
    t.downstream(io.BytesIO(prompt(4, p)))
    assert to_child.getvalue() == b"" and to_client.lines() == [{"jsonrpc": "2.0", "id": 4, "result": {"stopReason": "end_turn"}}], to_client.lines()
    assert not t.turn.is_set()
    # (b) the child's answer to TEE_SESSION is swallowed; (d) updates are posted always, forwarded only during a turn
    t, _, to_client = tee()
    t.upstream(io.BytesIO(rpc(id=TEE_SESSION, result={"sessionId": "s"}) + update("between turns")))
    assert to_client.getvalue() == b"" and t.poster.posts == [("agent", "between turns")], (to_client.getvalue(), t.poster.posts)
    t.turn.set()
    t.upstream(io.BytesIO(update("in turn") + rpc(id=5, result={"stopReason": "end_turn"})))
    assert [m.get("method") for m in to_client.lines()] == ["session/update", None] and not t.turn.is_set(), to_client.lines()
    assert t.poster.posts[-1] == ("agent", "in turn")
    t.upstream(io.BytesIO(rpc(method="session/update", params={"sessionId": "s", "update": {"sessionUpdate": "user_message_chunk", "content": {"text": "typed"}}})))
    assert t.poster.posts[-1] == ("owner", "typed"), t.poster.posts
    print("tee ok")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
