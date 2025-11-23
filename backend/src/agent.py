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


def save_order(order):
    fname = f"order_{int(time.time())}.json"
    with open(fname, "w") as f:
        json.dump(order, f, indent=2)
    print("✔ Order saved:", fname)


class Assistant(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
You are CofeeBuddy — a friendly barista at CofeeBuddy Café.
Your job is to take voice-based coffee orders.

REQUIRED FIELDS:
{
  "drinkType": "string",
  "size": "string",
  "milk": "string",
  "extras": ["string"],   # extras may be empty
  "name": "string"
}

RULES:
- Extract only fields explicitly mentioned by the user.
- If the user says nothing relevant, reply normally.
- ALWAYS return ONLY this JSON format:
  {
    "updates": {},
    "message": "short reply"
  }
- No emojis, no markdown.
            """
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    order_state = {
        "drinkType": "",
        "size": "",
        "milk": "",
        "extras": [],     # EMPTY EXTRAS ALLOWED
        "name": "",
    }

    # Apply extracted updates from LLM
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

    # Next missing mandatory field
    def next_question():
        if not order_state["drinkType"]:
            return "What drink would you like?"
        if not order_state["size"]:
            return "What size should I make it?"
        if not order_state["milk"]:
            return "What type of milk do you prefer?"
        # ❌ Removed extras requirement
        if not order_state["name"]:
            return "May I have your name for the order?"
        return None

    # Voice session
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
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage Summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(agent=Assistant(), room=ctx.room)
    await ctx.connect()

    # Handle user text
    @session.on("input_text")
    async def on_input_text(ev):
        user_text = ev.text.strip()
        print("User said:", user_text)

        prompt = f"""
Extract ONLY the fields the user explicitly mentioned.

CURRENT ORDER:
{json.dumps(order_state)}

USER SAID: "{user_text}"

RULES:
- If the user did NOT mention order details, respond:
  {{"updates": {{}}, "message": "normal"}}
- If they DID mention order fields, return:
  {{"updates": {{...}}, "message": "short reply"}}

STRICT JSON ONLY.
"""

        try:
            response = await session.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            llm_resp = json.loads(response.text)

        except Exception as e:
            print("LLM error:", e)
            await session.say("Sorry, could you repeat that?")
            return

        updates = llm_resp.get("updates", {})
        message = llm_resp.get("message", "")

        # Only speak meaningful replies
        if message and message != "normal":
            await session.say(message)

        merge_updates(updates)

        # Ask next missing field
        next_q = next_question()

        if next_q:
            await session.say(next_q)
        else:
            # ORDER COMPLETE 🎉
            await session.say("Your order is complete. Saving it now.")
            save_order(order_state)

            # Notify frontend
            await session.send_data(
                kind="webhook",
                data=json.dumps({
                    "type": "order_complete",
                    "order": order_state
                })
            )

            await session.say("Thanks for ordering at BrewBuddy!")
            await ctx.end()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="assistant",
        )
    )
