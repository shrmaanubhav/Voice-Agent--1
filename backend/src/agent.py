import logging
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import asyncio

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    tokenize,
)
from livekit.plugins import murf, silero, google, deepgram
from livekit.plugins.turn_detector.multilingual import MultilingualModel


logger = logging.getLogger("agent")
load_dotenv(".env.local")


print("🚀 Zepto Customer Service Agent (B2C) Loaded")


COMPANY_INFO = {
    "name": "Zepto",
    "tagline": "India's fastest instant commerce platform, delivering groceries and essentials in minutes.",
    "description": (
        "Zepto is a quick commerce service specializing in 10-20 minute delivery of "
        "groceries, fresh produce, and daily essentials. We operate in major Indian cities "
        "using a dark store model to ensure speed and freshness."
    ),
    "delivery_promise": "Guaranteed delivery in 10-20 minutes in serviceable areas.",
    "service_areas": [
        "Mumbai", "Delhi NCR", "Bengaluru", "Chennai", "Pune", "Hyderabad",
    ],
}

POLICY_INFO = {
    "zepto_pass": {
        "name": "Zepto Pass",
        "description": "A paid subscription loyalty program offering benefits for frequent users.",
        "benefits": [
            "Reduced or zero delivery fees on orders over a minimum value.",
            "Exclusive discounts and early access to sales.",
            "Priority customer support.",
        ],
        "pricing_note": "Pricing is charged monthly or annually and is subject to change. Check the app for the latest price.",
    },
    "delivery_fees": "Standard delivery fees may apply, typically waived for orders over a minimum cart value or with Zepto Pass.",
    "return_policy": "Easy returns and refunds for damaged, incorrect, or missing items. Must be initiated within 24 hours of delivery through the app.",
    "operating_hours": "Typically 6:00 AM to 1:00 AM, but hours may vary by city and dark store location.",
}


FAQ_DATA = [
    {
        "question": "How fast is Zepto's delivery?",
        "answer": (
            "Zepto specializes in quick commerce with a target delivery time of 10 to 20 minutes "
            "from the moment you place your order to it arriving at your doorstep."
        ),
        "category": "delivery",
    },
    {
        "question": "What is Zepto Pass?",
        "answer": (
            "Zepto Pass is our subscription service that gives you benefits like reduced delivery "
            "fees and special discounts on certain items for a low monthly fee."
        ),
        "category": "loyalty",
    },
    {
        "question": "Can I return a damaged product?",
        "answer": (
            "Yes, we have an easy return policy. If you receive a damaged, incorrect, or "
            "missing item, please report it via the app within 24 hours for a refund."
        ),
        "category": "policy",
    },
    {
        "question": "What areas does Zepto cover?",
        "answer": (
            "We operate in major Indian metro areas, including Mumbai, Bengaluru, Delhi NCR, "
            "and others. You can check your specific pincode in the app."
        ),
        "category": "location",
    },
    {
        "question": "What kind of products do you sell?",
        "answer": (
            "We sell a wide range of products including fresh fruits and vegetables, dairy, "
            "packaged groceries, personal care items, and other daily essentials."
        ),
        "category": "products",
    },
]


def build_knowledge_blob() -> str:
    blob = {
        "company": COMPANY_INFO,
        "policies": POLICY_INFO,
        "faq": FAQ_DATA,
    }
    return json.dumps(blob, ensure_ascii=False, indent=2)


LEADS_FILE = Path("zepto_customer_records.json")


def load_existing_leads():
    if LEADS_FILE.exists():
        try:
            return json.loads(LEADS_FILE.read_text())
        except:
            return []
    return []


def save_lead(lead: Dict[str, Any], summary: str):
    leads = load_existing_leads()
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "summary": summary,
        "customer_info": lead,
    }
    leads.append(entry)
    LEADS_FILE.write_text(json.dumps(leads, indent=2))
    print("✔ Saved customer record to zepto_customer_records.json")


class ZeptoB2CAgent(Agent):
    def __init__(self, knowledge_blob: str):
        super().__init__(
            instructions=f"""
You are the Customer Support and Adoption Agent for Zepto, the instant commerce platform.
Your focus is to provide excellent service, answer questions, and encourage app usage and Zepto Pass adoption.

OFFICIAL ZEPTO CUSTOMER DATA:
{knowledge_blob}

Your job:
- Warm, polite greeting
- Answer customer questions accurately using ONLY the ZEPTO CUSTOMER DATA provided
- Collect basic customer info naturally:
    name
    email
    phone_number
    city
    primary_issue (e.g., "delivery delay", "Zepto Pass inquiry", "product question")
- If the issue is complex (like "delivery delay" or "refund status"), note the issue and set "escalate": true to hand off to a human.
- Detect when the conversation is finished and mark "done": true
- NEVER invent facts that are not in the data
- Be friendly, concise, and helpful. Use a polite, professional tone.

Return STRICT JSON:

{{
  "reply": "your agent reply",
  "lead_updates": {{...}},
  "done": false,
  "escalate": false 
}}

DO NOT return anything else.
            """
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()



async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    knowledge_blob = build_knowledge_blob()
    
    # Safety lock to prevent race conditions on concurrent input
    llm_lock = asyncio.Lock() 

    lead_state = {
        "name": "",
        "email": "",
        "phone_number": "",
        "city": "",
        "primary_issue": "",
    }

    def merge_updates(up):
        if not isinstance(up, dict):
            return
        for k in lead_state:
            if k in up and up[k]:
                lead_state[k] = up[k]

    def make_summary():
        return (
            f"Customer: {lead_state.get('name') or 'Unknown customer'} ({lead_state.get('email') or 'No email'}). "
            f"Location: {lead_state.get('city') or 'Unknown city'}. "
            f"Primary Issue: {lead_state.get('primary_issue') or 'Not specified'}."
        )

    # ---- Create session ----
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # ---- User input ----
    @session.on("input_text")
    async def on_input(ev):
        user_text = ev.text.strip()
        print("👂 User:", user_text)

        async with llm_lock:
            prompt = f"""
You are the Zepto Customer Support Agent.

CURRENT CUSTOMER INFO:
{json.dumps(lead_state, indent=2)}

User said: "{user_text}"

Your job:
- Respond politely and professionally
- Answer only from the provided customer data (in system instructions)
- Update relevant customer fields
- If the issue is complex (refund, delivery status, order ID required), set "escalate": true
- If the conversation is finished, set "done": true
- Output STRICT JSON only.
"""

            try:
                resp = await session.llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.text)
            except Exception as e:
                print("LLM error:", e)
                await session.say("I apologize, I'm having trouble connecting to my service. Could you repeat your question, please?")
                return

            reply = data.get("reply", "")
            updates = data.get("lead_updates", {}) or {}
            done = bool(data.get("done", False))
            escalate = bool(data.get("escalate", False))

            merge_updates(updates)
            print("Customer state:", lead_state)
            
            # 1. Handle Escalation
            if escalate:
                await session.say("I understand. That sounds like an issue that requires a specific order number or real-time check.")

                if lead_state["phone_number"] or lead_state["email"]:
                     await session.say("I have your contact details. I am now transferring you to a human agent who can access your account details directly.")
                else:
                    await session.say("Could you please tell me your **phone number** or **email** so a human agent can easily reach you about this order?")

                summary = make_summary()
                save_lead(lead_state, summary + " (STATUS: ESCALATED)")
                await ctx.end() # End agent session for human takeover
                return

            if reply:
                await session.say(reply)

            # 3. Handle Done
            if done:
                summary = make_summary()
                await session.say("I hope that answers your questions about Zepto.")
                
                # Offer a final value proposition before hanging up
                if "Zepto Pass" not in summary:
                     await session.say("If you plan to order often, don't forget to check out **Zepto Pass** for reduced delivery fees!")

                save_lead(lead_state, summary)
                await session.say("Thank you for choosing Zepto. Have a great day!")
                await ctx.end()


    # ---- Start session ----
    await session.start(agent=ZeptoB2CAgent(knowledge_blob=knowledge_blob), room=ctx.room)
    await ctx.connect()

    await session.say(
        "Hello! Welcome to Zepto Customer Support. I'm here to help you with your orders, Zepto Pass, or any questions about our 10-20 minute delivery promise. "
        "How can I assist you today?"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))