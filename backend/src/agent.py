import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
)
from livekit.plugins import murf, silero, google, deepgram
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

# Load environment variables
load_dotenv(".env.local")


# ------------------------------
#       Assistant (LLM Brain)
# ------------------------------
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a helpful voice AI assistant. "
                "You respond clearly and concisely without emojis or special formatting. "
                "You are friendly and slightly humorous."
            )
        )


# ------------------------------
#       Worker Prewarm
# ------------------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


# ------------------------------
#        Main Entrypoint
# ------------------------------
async def entrypoint(ctx: JobContext):
    # Add metadata to log entries
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # ----------------------
    #  Voice AI Pipeline
    # ----------------------
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),               # Speech-to-text
        llm=google.LLM(model="gemini-2.5-flash"),       # LLM (your assistant brain)
        tts=murf.TTS(                                   # Text-to-speech (Murf Falcon)
            voice="en-US-matthew",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),             # Detect when user stops talking
        vad=ctx.proc.userdata["vad"],                   # Silero VAD
        preemptive_generation=True,                     # Start generating early
    )

    # ----------------------
    #   Metrics Collection
    # ----------------------
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage Summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # ----------------------
    #   Start Voice Session
    # ----------------------
    await session.start(
        agent=Assistant(),
        room=ctx.room,
    )

    # Connect agent to room
    await ctx.connect()


# ------------------------------
#       Run Worker
# ------------------------------
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="assistant",
        )
    )
