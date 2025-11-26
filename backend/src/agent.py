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


print("🚀 Freshworks Product Support Agent Loaded")


# --- FRESHWORKS KNOWLEDGE BASE ---
COMPANY_INFO = {
    "name": "Freshworks",
    "tagline": "Delivering AI-powered business software that customers and employees love.",
    "description": (
        "Freshworks provides a suite of customer engagement, IT service management, "
        "and HR management software products, including Freshdesk, Freshservice, and Freshteam."
    ),
    "core_products": [
        "Freshdesk (Customer Support)",
        "Freshservice (IT Service Management/ITSM)",
        "Freshteam (HR Management)",
        "Freshsales (CRM/Sales Automation)",
    ],
    "mission": "To make it easy for businesses to delight their customers and employees.",
}

POLICY_INFO = {
    "freshdesk_plans": {
        "name": "Freshdesk Support Plans",
        "description": "Subscription tiers for the customer support software.",
        "tiers": [
            "Free: Basic features for small teams.",
            "Growth: Essential features, automation, and reporting.",
            "Pro: Advanced features, skill-based routing, and customer segmentation.",
            "Enterprise: Custom roles, dedicated support, and data center options.",
        ],
        "pricing_note": "Pricing is charged per agent, per month (or annually for a discount). Check the official website for current rates.",
    },
    "trial_period": "All paid plans typically offer a 21-day free trial, no credit card required.",
    "support_channels": "Support is available via phone, email, chat, and self-service knowledge base, depending on your plan tier.",
    "onboarding_services": "Professional onboarding and implementation services are available for Pro and Enterprise plans.",
}


FAQ_DATA = [
    {
        "question": "What is the main purpose of Freshdesk?",
        "answer": (
            "Freshdesk is a customer support software that helps businesses manage and resolve "
            "customer inquiries from various channels (email, social media, chat) into a unified ticketing system."
        ),
        "category": "Freshdesk",
    },
    {
        "question": "How does Freshservice help businesses?",
        "answer": (
            "Freshservice is an IT Service Management (ITSM) tool that helps IT teams manage "
            "internal IT requests, assets, incidents, and service catalogs."
        ),
        "category": "Freshservice",
    },
    {
        "question": "Do I need a credit card for the free trial?",
        "answer": (
            "No, Freshworks typically offers a 21-day free trial on its paid plans without "
            "requiring a credit card upfront."
        ),
        "category": "Pricing/Trial",
    },
    {
        "question": "How is Freshworks software priced?",
        "answer": (
            "Freshworks products are generally priced on a subscription basis, usually 'per agent, "
            "per month.' Plans are often discounted when billed annually."
        ),
        "category": "Pricing",
    },
    {
        "question": "Does Freshworks offer a free plan?",
        "answer": (
            "Yes, products like Freshdesk and Freshservice often have a 'Free' or 'Starter' tier "
            "that includes basic features for small teams."
        ),
        "category": "Pricing",
    },
]
# --- END FRESHWORKS KNOWLEDGE BASE ---


def build_knowledge_blob() -> str:
    blob = {
        "company": COMPANY_INFO,
        "policies": POLICY_INFO,
        "faq": FAQ_DATA,
    }
    return json.dumps(blob, ensure_ascii=False, indent=2)


# Renamed customer records file to reflect the new company context
LEADS_FILE = Path("freshworks_prospect_records.json")


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
    print("✔ Saved customer record to freshworks_prospect_records.json")


class FreshworksSupportAgent(Agent):
    def __init__(self, knowledge_blob: str):
        super().__init__(
            instructions=f"""
You are the **Product Support and Sales Inquiry Agent** for **Freshworks**.
Your focus is to provide excellent service, answer product questions accurately, guide users to the right software, and collect prospect information for follow-up.

OFFICIAL FRESHWORKS PRODUCT AND POLICY DATA:
{knowledge_blob}

Your job:
- Warm, polite greeting, confirming they are contacting Freshworks.
- Answer customer questions accurately using ONLY the FRESHWORKS PRODUCT AND POLICY DATA provided.
- Collect basic prospect info naturally:
    name
    email
    phone_number
    company_name
    primary_product_interest (e.g., "Freshdesk", "Freshservice", "Pricing")
- If the issue requires a quote, complex troubleshooting, or an account check (like "What is my account limit?"), note the issue and set "escalate": true to hand off to a human sales or technical agent.
- Detect when the conversation is finished and mark "done": true
- NEVER invent facts that are not in the data.
- Be friendly, professional, and clear.

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

    # Renamed/updated lead state fields for a B2B software context
    lead_state = {
        "name": "",
        "email": "",
        "phone_number": "",
        "company_name": "",
        "primary_product_interest": "",
    }

    def merge_updates(up):
        if not isinstance(up, dict):
            return
        for k in lead_state:
            if k in up and up[k]:
                lead_state[k] = up[k]

    def make_summary():
        return (
            f"Prospect: {lead_state.get('name') or 'Unknown'} ({lead_state.get('email') or 'No email'}). "
            f"Company: {lead_state.get('company_name') or 'Unknown company'}. "
            f"Product Interest: {lead_state.get('primary_product_interest') or 'Not specified'}."
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
You are the Freshworks Product Support and Sales Inquiry Agent.

CURRENT PROSPECT INFO:
{json.dumps(lead_state, indent=2)}

User said: "{user_text}"

Your job:
- Respond politely and professionally
- Answer only from the provided product/policy data (in system instructions)
- Update relevant prospect fields (name, email, company_name, primary_product_interest)
- If the issue requires escalation (e.g., complex pricing, quote, technical troubleshooting), set "escalate": true
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
            print("Prospect state:", lead_state)
            
            # 1. Handle Escalation
            if escalate:
                await session.say("I understand. That sounds like a request for a detailed quote or specialized technical help.")

                if lead_state["phone_number"] or lead_state["email"]:
                    await session.say("I have your contact details. I am now transferring you to a dedicated human sales agent who can discuss pricing and features specific to your needs.")
                else:
                    await session.say("To ensure a human agent can follow up, could you please tell me your **email** and **company name**?")

                summary = make_summary()
                save_lead(lead_state, summary + " (STATUS: ESCALATED)")
                await ctx.end() # End agent session for human takeover
                return

            if reply:
                await session.say(reply)

            # 3. Handle Done
            if done:
                summary = make_summary()
                
                # Offer a final value proposition before hanging up
                if "trial_period" not in summary:
                    await session.say("Just a reminder: most of our paid plans offer a **21-day free trial** with no credit card required to get started!")

                save_lead(lead_state, summary)
                await session.say("Thank you for reaching out to Freshworks. We look forward to helping you delight your customers and employees!")
                await ctx.end()


    # ---- Start session ----
    await session.start(agent=FreshworksSupportAgent(knowledge_blob=knowledge_blob), room=ctx.room)
    await ctx.connect()

    await session.say(
        "Hello! Thank you for contacting Freshworks. I can answer questions about Freshdesk, Freshservice, pricing, and our free trials. How can I help you discover the right software today?"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))