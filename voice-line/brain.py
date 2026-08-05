"""The warm Claude Agent SDK session.

One ClaudeSDKClient for the whole voice session, created at launch.
cwd points at the Jarvis working folder so this session boots with the
same CLAUDE.md identity as a terminal session. Replies stream in as
partial text deltas, get chunked into sentences, and each finished
chunk is handed to the mouth immediately.

The first turn pays a prompt-cache toll of several seconds; main.py
hides it behind a spoken greeting fired at startup.
"""

import re

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent

JARVIS_CWD = "/Users/mike/Documents/Jarvis"

# The warmup turn does double duty: it hides the first-turn prompt-cache
# toll AND boots the session's memory. It used to say "don't use tools",
# so every voice session came up blind -- greeting Serge with none of the
# vault read, and only reading the log when he noticed and asked.
WARMUP_PROMPT = (
    "The voice line just came up and this is the warmup turn. Before you say "
    "anything, run the full startup sequence from CLAUDE.md, using tools "
    "silently -- no spoken narration between the reads. Read VAULT-INDEX.md at "
    "the vault root; read today's daily note and yesterday's in the daily notes "
    "folder; read Active Priorities.md; read the last 20 lines of "
    "voice-line/.stack-events.jsonl -- the stack event log, which records what "
    "happened to the server and the brain while this session did not exist, "
    "including your own restart; then sign this session in on "
    "Session Board.md (channel: voice line, the real system time, and 'booting "
    "-- awaiting direction'). Only when that is done, reply with one short "
    "spoken sentence: greet Serge and confirm you're on the line. Do not "
    "summarize what you read unless he asks."
)

SPOKEN_DISCIPLINE = """
# Voice mode -- write for the ear

Your reply is spoken aloud by TTS at Serge's desk. He is listening,
not reading.

- Short, conversational sentences. Contractions are good.
- No markdown, no code blocks, no headings, no emoji, and no bullet
  lists read aloud. If a list is unavoidable, speak it: "three
  things: first..., second..., third...".
- Don't read URLs, paths, or symbols character by character; describe
  them ("the vault index", "the daily notes folder").
- TTS performs your punctuation. Vary sentence length, use commas,
  dashes and questions the way a speaker would -- dull text is dull
  audio.
- Default to a couple of sentences and stop when the point is made;
  Serge will ask when he wants more.
- Before you use a tool, first say one short natural line about what
  you're doing ("On it -- checking the vault."), then run the tool.
- Numbers and dates read naturally: "August first", not "2026-08-01".
"""

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_BREAK = re.compile(r"(?<=[,;:])\s+|\s+(?:--|—|–)\s+")
FIRST_CLAUSE_MIN_CHARS = 24


class SentenceChunker:
    """Accumulates streamed text; emits speakable chunks.

    The first chunk ships as soon as a clause of substance is ready --
    before its sentence even finishes (fastest first audio). After
    that, sentences ship in two-sentence breaths, because lone short
    sentences sound flat.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._pending: list[str] = []
        self._shipped = 0

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        parts = _SENTENCE_END.split(self._buffer)
        if len(parts) == 1:
            return self._first_clause()
        self._buffer = parts[-1]
        out: list[str] = []
        for sentence in parts[:-1]:
            sentence = sentence.strip()
            if sentence:
                out.extend(self._ready(sentence))
        return out

    def _first_clause(self) -> list[str]:
        """Nothing shipped and no finished sentence yet: peel one
        leading clause off the first sentence, so first audio starts
        about half a sentence early. Short lead-ins ("On it -- ...")
        stay whole; later chunks pace themselves off full sentences."""
        if self._shipped:
            return []
        for m in _CLAUSE_BREAK.finditer(self._buffer):
            if m.start() < FIRST_CLAUSE_MIN_CHARS:
                continue
            clause = self._buffer[:m.start()].strip()
            self._buffer = self._buffer[m.end():]
            self._shipped += 1
            return [clause]
        return []

    def _ready(self, sentence: str) -> list[str]:
        if self._shipped == 0:
            self._shipped += 1
            return [sentence]
        self._pending.append(sentence)
        if len(self._pending) >= 2:
            chunk = " ".join(self._pending)
            self._pending = []
            self._shipped += 1
            return [chunk]
        return []

    def flush(self) -> list[str]:
        """Ship whatever is buffered, finished sentence or not."""
        tail = self._buffer.strip()
        self._buffer = ""
        if tail:
            self._pending.append(tail)
        chunk = " ".join(self._pending).strip()
        self._pending = []
        if not chunk:
            return []
        self._shipped += 1
        return [chunk]


# The model the voice line runs on. One constant feeds both the SDK
# option and the HUD label, so the badge can never disagree with what
# is actually answering.
MODEL = "claude-opus-5"


class Brain:
    # HUD label. Read straight from the pin above -- it used to be
    # inferred from ResultMessage.model_usage, but background helper
    # calls run on Haiku and out-write short spoken turns, so the
    # busiest-key vote painted "claude-haiku-4-5" on an Opus line.
    model: str = MODEL

    def __init__(self, can_use_tool=None) -> None:
        # can_use_tool: optional async (tool_name, input, context) ->
        # PermissionResult. The browser server passes one so permission
        # prompts surface as an APPROVE button on the HUD; the terminal
        # line passes nothing and keeps today's behavior.
        self._client = ClaudeSDKClient(ClaudeAgentOptions(
            can_use_tool=can_use_tool,
            cwd=JARVIS_CWD,
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": SPOKEN_DISCIPLINE,
            },
            setting_sources=["user", "project", "local"],
            permission_mode="acceptEdits",
            include_partial_messages=True,
            # Voice wants fast first words: think only when the task
            # demands it, and keep reasoning shallow -- deep work
            # belongs in terminal sessions.
            thinking={"type": "adaptive"},
            effort="low",
            # Pin the model: unpinned, the line inherited a default and
            # ran on Haiku. Serge wants Opus on the voice line.
            model=MODEL,
            # Default 1 MB bursts when a turn reads a big file (a
            # screenshot came back as one >1 MB JSON message and
            # killed the reader mid-turn). 10 MB covers images.
            max_buffer_size=10 * 1024 * 1024,
        ))

        # Health of the last turn, for the server's rebuild decision.
        # A turn that yields no speakable text is NOT proof of a dead
        # brain -- a long tool-only turn does the same. The real signal
        # is whether the turn produced a ResultMessage, and whether that
        # result was an error. (2026-08-04: silence alone used to trigger
        # a rebuild, which threw away healthy conversations mid-session.)
        self.saw_result = False
        self.last_error: str | None = None
        # Serge talking over a turn in flight is NOT a broken brain
        # either. An interrupt makes the CLI close that turn with
        # is_error=True, subtype=error_during_execution and an empty
        # result string -- and that result lands on the NEXT stream(),
        # because the interrupt is nearly always the arrival of his
        # next sentence. So this flag deliberately survives across a
        # stream() boundary; it is consumed by the error result it
        # explains, not reset per turn. (2026-08-04: two healthy
        # brains were thrown away this way, and the conversation with
        # them -- the "dead brain (error_during_execution:)" lines in
        # visual-server.log, always after a long turn he spoke over.)
        self._interrupt_pending = False

    def looks_dead(self) -> bool:
        """True only when the last turn shows the subprocess is broken:
        no result at all (stream died), or a result flagged as an error
        (the stale-overnight-login case this check exists for).
        An interrupted turn is neither -- see _interrupt_pending."""
        return (not self.saw_result) or self.last_error is not None

    async def connect(self) -> None:
        await self._client.connect()

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            pass

    async def interrupt(self) -> None:
        # Armed before the call, and left armed even if the SDK raises:
        # the CLI may still have emitted its error result, and a false
        # "healthy" costs nothing while a false "dead" costs the
        # conversation.
        self._interrupt_pending = True
        try:
            await self._client.interrupt()
        except Exception:
            pass

    async def stream(self, prompt: str):
        """One turn: yield speakable chunks as the reply streams in."""
        self.saw_result = False
        self.last_error = None
        await self._client.query(prompt)
        chunker = SentenceChunker()
        speak_block = False
        async for message in self._client.receive_response():
            if isinstance(message, StreamEvent):
                if message.parent_tool_use_id:
                    continue  # subagent chatter is not for the speakers
                event = message.event
                etype = event.get("type")
                if etype == "content_block_start":
                    block_type = event.get("content_block", {}).get("type")
                    speak_block = block_type == "text"
                elif etype == "content_block_delta" and speak_block:
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        for chunk in chunker.feed(delta.get("text", "")):
                            yield chunk
                elif etype == "content_block_stop":
                    # CRITICAL: flush here. If we only flushed on
                    # sentence-ending punctuation, pre-tool filler like
                    # "On it, checking now" would sit silent through
                    # the whole tool run and then play glued to the
                    # answer.
                    for chunk in chunker.flush():
                        yield chunk
                    speak_block = False
            elif isinstance(message, ResultMessage):
                self.saw_result = True
                if message.is_error and self._interrupt_pending:
                    # This is the interrupt closing out, not a corpse.
                    # Consume the flag here so it explains exactly one
                    # error result and never masks a real failure later.
                    self._interrupt_pending = False
                elif message.is_error:
                    self.last_error = (
                        f"{message.subtype}: {message.result or ''}".strip())
                else:
                    # A clean result means the interrupt never produced
                    # an error result -- disarm, or the flag would eat
                    # the next genuine one.
                    self._interrupt_pending = False
                for chunk in chunker.flush():
                    yield chunk
