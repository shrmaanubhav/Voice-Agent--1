import logging
import json
import os
from datetime import datetime
from typing import Annotated, Optional, List, Dict
from dataclasses import dataclass, field, asdict

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
    # Removed function_tool as we don't need tools for the GM
    RunContext,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")



@dataclass
class Userdata:
    """Holds simple user state for the session, though the GM relies primarily on chat history."""
    player_name: Optional[str] = None
    story_started: bool = False



class GameMasterAgent(Agent):
    def __init__(self):
        SYSTEM_PROMPT = """
            You are 'The Arcane Sage', a Game Master (GM) running a fantasy role-playing adventure.
            
            **Universe:** Medieval Fantasy, filled with ancient ruins, minor magic, and political intrigue between kingdoms.
            
            **Tone:** Dramatic, descriptive, and slightly mysterious. Focus on immersion and sensory details (sights, sounds, smells).
            
            **Role:** You describe scenes, react dynamically to the player's choices, and drive the interactive story forward.
            
            **Rules for Interaction (Follow Strictly):**
            1. **Never** break character or mention you are an AI or an agent.
            2. **Maintain Continuity:** Remember the player's past actions, character names, and locations mentioned previously in this conversation.
            3. **Keep It Going:** Your response should always end with a clear, direct prompt asking the player for their next action (e.g., "What do you do?", "Which path do you choose?", or "How do you respond to the guard?").
            4. **Initial Scene:** Start the game immediately with the first scene description without any introductory greeting.
            
            **Initial Scene:** You awaken in a damp, cold cell. The stone walls weep moisture, and the only light comes from a flickering torch in the hall, visible through a small iron-barred window. Your sword, 'Vindicator', is missing from your hip. You hear the slow, rhythmic footsteps of a guard approaching the door.
            """
        
        super().__init__(
            instructions=SYSTEM_PROMPT,
            # The Game Master requires no external tools; its only tool is the LLM itself.
            tools=[], 
        )


def prewarm(proc: JobProcess):
    # Reuse existing prewarm logic
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus", 
            style="Storyteller", 
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )
    
    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))