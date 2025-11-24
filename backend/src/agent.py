import logging
import json
import time
import os
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    tokenize,
    metrics,
    MetricsCollectedEvent,
)

from livekit.plugins import silero, google, deepgram, murf
from livekit.plugins.turn_detector.multilingual import MultilingualModel


# ---------------------------------------------------------------------
# INIT
# ---------------------------------------------------------------------
logger = logging.getLogger("agent")
load_dotenv(".env.local")

LOG_FILE = "wellness_log.json"


# ---------------------------------------------------------------------
# JSON LOG HELPERS
# ---------------------------------------------------------------------
def load_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            f.write("[]")
        return []

    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def save_log(entry):
    log = load_log()
    log.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    print("✔ Wellness log updated!")


# ---------------------------------------------------------------------
# ASSISTANT
# ---------------------------------------------------------------------
class WellnessAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are a daily health & wellness companion.
You are supportive, grounded, and NEVER give medical or diagnostic advice.

Your job:
1. Ask about mood
2. Ask about energy level
3. Ask about stress
4. Ask for 1–3 goals for today
5. Provide a SHORT supportive suggestion
6. Recap the check-in
7. End conversation

Behavior rules:
- Speak normally, with short replies.
- No emojis.
- No markdown.
- No therapy, no clinical advice.
- Keep the tone supportive and realistic.
"""
        )


# ---------------------------------------------------------------------
# PREWARM
# ---------------------------------------------------------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


# ---------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # --------------------------
    # STATE MACHINE
    # --------------------------
    conversation = {
        "phase": "intro",
        "mood": "",
        "energy": "",
        "stress": "",
        "goals": [],
        "suggestion": "",
    }

    # Load past logs
    past_log = load_log()
    last_entry = past_log[-1] if past_log else None

    # --------------------------
    # SESSION SETUP
    # --------------------------
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # Start & join
    await session.start(agent=WellnessAssistant(), room=ctx.room)
    await ctx.connect()

    # Initial message
    if last_entry:
        await session.say(
            f"Welcome back. Last time you mentioned feeling {last_entry['mood']} and your energy was {last_entry['energy']}. "
            "Let's check in again. How are you feeling today?"
        )
    else:
        await session.say("Hi, good to see you. How are you feeling today?")

    conversation["phase"] = "mood"

    # ------------------------------------------------------------------
    # HANDLE USER TEXT
    # ------------------------------------------------------------------
    @session.on("input_text")
    async def on_input_text(ev):
        user = ev.text.strip()
        phase = conversation["phase"]
        print(f"[PHASE={phase}] User:", user)

        # --------- MOOD ----------
        if phase == "mood":
            conversation["mood"] = user
            conversation["phase"] = "energy"
            await session.say("Got it. How's your energy today?")
            return

        # --------- ENERGY ----------
        if phase == "energy":
            conversation["energy"] = user
            conversation["phase"] = "stress"
            await session.say("Thanks. Anything stressing you out today?")
            return

        # --------- STRESS ----------
        if phase == "stress":
            conversation["stress"] = user
            conversation["phase"] = "goals"
            await session.say("What are 1 to 3 things you'd like to get done today?")
            return

        # --------- GOALS ----------
        if phase == "goals":
            # Split into goals by commas or sentences
            goals = [g.strip() for g in user.replace(".", ",").split(",") if g.strip()]
            conversation["goals"] = goals
            conversation["phase"] = "suggestion"

            # Get LLM suggestion
            prompt = f"""
You are a supportive wellness companion.
Give ONE SHORT suggestion based on:

Mood: {conversation['mood']}
Energy: {conversation['energy']}
Stress: {conversation['stress']}
Goals: {conversation['goals']}

Rules:
- Simple and grounded.
- No medical or diagnostic guidance.
- Short sentence.
"""
            try:
                suggestion_rsp = await session.llm.complete(
                    messages=[{"role": "user", "content": prompt}]
                )
                suggestion = suggestion_rsp.text.strip()
            except:
                suggestion = "Try to keep things simple and take short breaks if needed."

            conversation["suggestion"] = suggestion

            await session.say(suggestion)

            # Move to recap
            conversation["phase"] = "recap"
            await session.say(
                f"Here's your recap. You're feeling {conversation['mood']}, "
                f"your energy is {conversation['energy']}, "
                f"stress level: {conversation['stress']}. "
                f"Your goals are: {', '.join(conversation['goals'])}. "
                "Does this sound right?"
            )
            return

        # --------- RECAP CONFIRMATION ----------
        if phase == "recap":
            await session.say("Great. I'll save this check-in. Talk to you next time!")

            entry = {
                "timestamp": int(time.time()),
                "mood": conversation["mood"],
                "energy": conversation["energy"],
                "stress": conversation["stress"],
                "goals": conversation["goals"],
                "summary": conversation["suggestion"],
            }

            save_log(entry)
            await ctx.end()

    # end on_input_text


# ---------------------------------------------------------------------
# RUN APP
# ---------------------------------------------------------------------
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="wellness_assistant",
        )
    )
