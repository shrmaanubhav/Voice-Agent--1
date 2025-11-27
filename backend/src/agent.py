import logging
import json
import os
import sqlite3 # Import sqlite3 for database connection
from datetime import datetime
from typing import Annotated, Optional, List
from dataclasses import dataclass, asdict

# (Existing imports for the LiveKit Agent framework and plugins)
from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")

DB_FILE = "transactions.sqlite" 

def get_db_connection():
    """Returns a connection and cursor to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  
    return conn, conn.cursor()

@dataclass
class FraudCase:
    id: Optional[int] = None
    userName: str
    securityId: str       
    cardEnding: str
    transactionDescription: str 
    transactionAmount: float
    transactionTime: str
    transactionWebsite: str    
    case_status: str = "pending_review"  
    notes: str = ""

@dataclass
class Userdata:
    active_case: Optional[FraudCase] = None


@function_tool
async def lookup_customer(
    ctx: RunContext[Userdata],
    name: Annotated[str, Field(description="The name the user provides")]
) -> str:
    """
    🔍 Looks up a customer in the fraud database by name using SQLite.
    Call this immediately when the user says their name.
    """
    print(f"🔎 LOOKING UP: {name} in {DB_FILE}")
    
    conn, cursor = get_db_connection()
    try:
        query = "SELECT * FROM transactions WHERE userName = ? LIMIT 1;"
        cursor.execute(query, (name,))
        found_record = cursor.fetchone()
        
        if found_record:
            case_data = {
                "id": found_record["id"],
                "userName": found_record["userName"],
                "securityId": found_record["securityId"],
                "cardEnding": found_record["cardEnding"],
                "transactionDescription": found_record["transactionDescription"],
                "transactionAmount": found_record["transactionAmount"],
                "transactionTime": found_record["transactionTime"],
                "transactionWebsite": found_record["transactionWebsite"],
                "case_status": found_record["case_status"],
                "notes": found_record["notes"],
            }
            
            ctx.userdata.active_case = FraudCase(**case_data)
            
            return (f"Record Found. \n"
                    f"User: {case_data['userName']}\n"
                    f"Security ID (Expected): {case_data['securityId']}\n"
                    f"Transaction Details: ${case_data['transactionAmount']:.2f} at {case_data['transactionDescription']} ({case_data['transactionWebsite']})\n"
                    f"Instructions: Ask the user for their 'Security ID' to verify identity before discussing the transaction.")
        else:
            return "User not found in the fraud database. Ask them to repeat the name or contact support manually."
            
    except Exception as e:
        return f"Database error during lookup: {str(e)}"
    finally:
        conn.close()

@function_tool
async def resolve_fraud_case(
    ctx: RunContext[Userdata],
    status: Annotated[str, Field(description="The final status: 'confirmed_safe' or 'confirmed_fraud'")],
    notes: Annotated[str, Field(description="A brief summary of the user's response")]
) -> str:
    """
    💾 Updates the case status in the SQLite database.
    Call this after the user confirms or denies the transaction.
    """
    if not ctx.userdata.active_case or not ctx.userdata.active_case.id:
        return "Error: No active case selected or case ID missing."

    case = ctx.userdata.active_case
    case.case_status = status
    case.notes = notes
    
    conn, cursor = get_db_connection()
    try:
        query = """
        UPDATE transactions
        SET case_status = ?, notes = ?
        WHERE id = ?;
        """
        cursor.execute(query, (case.case_status, case.notes, case.id))
        conn.commit()
            
        print(f"✅ CASE UPDATED: {case.userName} (ID: {case.id}) -> {status}")
        
        if status == "confirmed_fraud":
            return "Case updated as FRAUD. Inform the user: Card ending in " + case.cardEnding + " is now blocked. A new card will be mailed."
        else:
            return "Case updated as SAFE. Inform the user: The restriction has been lifted. Thank you for verifying."

    except Exception as e:
        return f"Error saving to SQLite DB: {e}"
    finally:
        conn.close()


class FraudAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are 'Cubo', a Fraud Detection Specialist at State Bank Of India. 
            Your job is to verify a suspicious transaction with the customer efficiently and professionally.

            🛡️ **SECURITY PROTOCOL (FOLLOW STRICTLY):**
            
            1. **GREETING & ID:** - State that you are calling about a "security alert".
                - Ask: "Am I speaking with the account holder? May I have your first name?"
            
            2. **LOOKUP:**
                - Use tool `lookup_customer` immediately when you hear the name.
            
            3. **VERIFICATION:**
                - Once the record is loaded, ask for their **Security ID** (The tool output provides the expected ID).
                - Compare their answer to the data returned by the tool.
                - IF WRONG: Politely apologize and disconnect (pretend to end call).
                - IF CORRECT: Proceed.
            
            4. **TRANSACTION REVIEW:**
                - Read the transaction details clearly: "We flagged a charge of [Amount] at [Merchant] on [Time]."
                - Ask: "Did you make this transaction?"
            
            5. **RESOLUTION:**
                - **If User Says YES (Legit):** Use tool `resolve_fraud_case(status='confirmed_safe')`.
                - **If User Says NO (Fraud):** Use tool `resolve_fraud_case(status='confirmed_fraud')`.
            
            6. **CLOSING:**
                - Confirm the action taken (Card blocked OR Unblocked).
                - Say goodbye professionally.

            ⚠️ **TONE:** Calm, authoritative, reassuring. Do NOT ask for full card numbers or passwords.
            """,
            tools=[lookup_customer, resolve_fraud_case],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    print("\n" + "💼" * 25)
    print("🚀 STARTING FRAUD ALERT SESSION")
    
    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus", # A serious, professional male voice
            style="Conversational",      
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )
    
    # 3. Start
    await session.start(
        agent=FraudAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))