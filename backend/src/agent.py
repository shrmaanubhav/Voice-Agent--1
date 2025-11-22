import logging
import json
import time
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
    MetricsCollectedEvent,
)

from livekit.plugins import murf, silero, google, deepgram
from livekit.plugins.turn_detector.multilingual import MultilingualModel


logger = logging.getLogger("agent")
load_dotenv(".env.local")


# ---------------------------
# SAVE ORDER TO JSON
# ---------------------------
def save_order(order):
    fname = f"order_{int(time.time())}.json"
    with open(fname, "w") as f:
        json.dump(order, f, indent=2)
    print("✔ Order saved:", fname)


# ---------------------------
# LLM BARISTA ASSISTANT
# ---------------------------
class Assistant(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are BrewBuddy — a friendly barista at BrewBuddy Café.
Your job is to take voice-based coffee orders.

The order requires 5 fields:
{
  "drinkType": "string",
  "size": "string",
  "milk": "string",
  "extras": ["string"],
  "name": "string"
}

RULES:
- Extract only the fields the user explicitly mentions.
- DO NOT infer unknown fields.
- ALWAYS return JSON ONLY in this format:
  {
    "updates": { ... },
    "message": "your short reply"
  }
- After giving your reply, also ask the next missing question.
- When all fields are complete, say:
  "Your order is complete. Saving it now."

Extras examples: whipped cream, caramel, chocolate, cinnamon, mocha.
Milk examples: whole milk, skim milk, almond milk, oat milk.

No emojis. No markdown.
Keep replies short and conversational.
"""
        )


# ---------------------------
# PREWARM (load VAD early)
# ---------------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


# ---------------------------
# MAIN ENTRYPOINT
# ---------------------------
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # ORDER STATE
    order_state = {
        "drinkType": "",
        "size": "",
        "milk": "",
        "extras": [],
        "name": "",
    }

    # APPLY LLM UPDATES TO STATE
    def merge_updates(up):
        if not isinstance(up, dict):
            return

        if up.get("drinkType"):
            order_state["drinkType"] = up["drinkType"]

        if up.get("size"):
            order_state["size"] = up["size"]

        if up.get("milk"):
            order_state["milk"] = up["milk"]

        if up.get("extras") and isinstance(up["extras"], list):
            for x in up["extras"]:
                if x not in order_state["extras"]:
                    order_state["extras"].append(x)

        if up.get("name"):
            order_state["name"] = up["name"]

    # NEXT MISSING FIELD
    def next_question():
        if not order_state["drinkType"]:
            return "What drink would you like?"
        if not order_state["size"]:
            return "What size should I make it?"
        if not order_state["milk"]:
            return "What type of milk do you prefer?"
        if len(order_state["extras"]) == 0:
            return "Would you like any extras?"
        if not order_state["name"]:
            return "May I have your name for the order?"
        return None

    # ---------------------------
    # SESSION SETUP
    # ---------------------------
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

    # METRICS
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage Summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # START PIPELINE + JOIN ROOM
    await session.start(agent=Assistant(), room=ctx.room)
    await ctx.connect()

    # ---------------------------
    # HANDLE USER TEXT
    # ---------------------------
    @session.on("input_text")
    async def on_input_text(ev):
        user_text = ev.text.strip()
        print("User said:", user_text)

        # Build prompt including current order state
        prompt = f"""
Current order state:
{json.dumps(order_state)}

User: "{user_text}"

Extract only the fields user mentioned.
Return ONLY JSON of the form:
{{
  "updates": {{}},
  "message": "string"
}}
"""

        try:
            response = await session.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

            llm_resp = json.loads(response.text)
        except Exception as e:
            print("LLM error:", e)
            await session.say("Sorry, can you repeat that?")
            return

        updates = llm_resp.get("updates", {})
        message = llm_resp.get("message", "")

        # Speak LLM's reply
        if message:
            await session.say(message)

        # Merge updates
        merge_updates(updates)

        # Ask next question
        next_q = next_question()

        if next_q:
            await session.say(next_q)
        else:
            await session.say("Your order is complete. Saving it now.")
            save_order(order_state)
            print("FINAL ORDER:", order_state)
            await session.say("Thanks for ordering at BrewBuddy. Enjoy your drink!")
            await ctx.end()

    # END OF ENTRYPOINT


# RUN APP
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="assistant",
        )
    )
