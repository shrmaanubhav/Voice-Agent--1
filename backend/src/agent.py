import logging
import json
import os
from datetime import datetime
from typing import Annotated, Optional, List, Dict
from dataclasses import dataclass, field, asdict
from decimal import Decimal 


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


CATALOG_FILE = "catalog.json"
ORDER_OUTPUT_DIR = "orders"
os.makedirs(ORDER_OUTPUT_DIR, exist_ok=True)

# Load catalog once at startup
try:
    with open(CATALOG_FILE, 'r') as f:
        CATALOG_DATA = json.load(f)
    CATALOG = {item['id']: item for item in CATALOG_DATA}
    print(f"✅ Loaded {len(CATALOG)} items from {CATALOG_FILE}")
except FileNotFoundError:
    CATALOG = {}
    print(f"⚠️ ERROR: {CATALOG_FILE} not found. Catalog is empty.")


# Hardcoded Recipes for "ingredients for X" intelligence
RECIPES = {
    "peanut butter sandwich": [
        {"id": "bread_white_500g", "qty": 1},
        {"id": "pb_creamy_500g", "qty": 1}
    ],
    "spaghetti dinner": [
        {"id": "pasta_spaghetti_500g", "qty": 1},
        {"id": "pasta_sauce_marinara", "qty": 1}
    ],
    "breakfast": [
        {"id": "eggs_dozen", "qty": 1},
        {"id": "milk_whole_1l", "qty": 1}
    ]
}


# --- Data Classes and Cart Management ---

@dataclass
class CartItem:
    id: str
    name: str
    price: float
    quantity: int
    size: str
    brand: str
    total_price: float = field(init=False)

    def __post_init__(self):
        # Calculate total price for the line item
        self.total_price = round(self.price * self.quantity, 2)


@dataclass
class Userdata:
    cart: List[CartItem] = field(default_factory=list)
    customer_name: Optional[str] = None

    def get_cart_total(self) -> float:
        """Calculates the total price of all items in the cart."""
        # Use Decimal for high-precision sum, then convert back to float for JSON/display
        total = sum(Decimal(str(item.total_price)) for item in self.cart)
        return float(round(total, 2))

    def add_item_to_cart(self, item_id: str, quantity: int = 1) -> Optional[str]:
        """Adds an item to the cart, merging if it already exists."""
        if item_id not in CATALOG:
            return None # Item not found

        item_data = CATALOG[item_id]

        # Check if item is already in cart to merge
        for item in self.cart:
            if item.id == item_id:
                item.quantity += quantity
                item.total_price = round(item.price * item.quantity, 2)
                return f"Updated {item_data['name']} quantity to {item.quantity}."
        
        # Add new item
        new_item = CartItem(
            id=item_id,
            name=item_data['name'],
            price=item_data['price'],
            quantity=quantity,
            size=item_data['size'],
            brand=item_data['brand'],
        )
        self.cart.append(new_item)
        return f"Added {quantity} x {item_data['name']} to your cart."

    def remove_item_from_cart(self, item_name: str) -> Optional[str]:
        """Removes the first matching item from the cart based on name."""
        item_name = item_name.lower().strip()
        for i, item in enumerate(self.cart):
            if item_name in item.name.lower():
                removed_name = item.name
                del self.cart[i]
                return f"Removed {removed_name} from your cart."
        return "Item not found in your cart."

    def list_cart_contents(self) -> str:
        """Returns a string summary of the current cart contents."""
        if not self.cart:
            return "Your cart is currently empty."
        
        summary = "Your cart currently contains:\n"
        for item in self.cart:
            summary += f"- {item.quantity} x {item.name} ({item.size}) at ${item.total_price:.2f}\n"
        summary += f"The current subtotal is **${self.get_cart_total():.2f}**."
        return summary


# --- Function Tools ---

@function_tool
async def add_to_cart(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="The name of the item to add (e.g., 'White Bread', 'Margherita Pizza').")],
    quantity: Annotated[int, Field(description="The quantity to add. Defaults to 1 if not specified by the user.")] = 1
) -> str:
    """
    🛒 Adds a specific item and quantity to the user's shopping cart.
    Use this when the user orders a single item.
    """
    print(f"🛒 ADDING TO CART: {quantity} x {item_name}")
    
    # Simple lookup by name (case-insensitive, partial match)
    match_id = None
    for item_id, item_data in CATALOG.items():
        if item_name.lower() in item_data['name'].lower():
            match_id = item_id
            break

    if not match_id:
        return f"I couldn't find an item named '{item_name}'. Please check the name or ask what's available."

    result = ctx.userdata.add_item_to_cart(match_id, quantity)
    return result


@function_tool
async def add_ingredients_for(
    ctx: RunContext[Userdata],
    dish_name: Annotated[str, Field(description="The name of the meal or dish (e.g., 'peanut butter sandwich', 'spaghetti dinner').")]
) -> str:
    """
    🧑‍🍳 Adds all necessary ingredients for a common meal (like a sandwich or pasta) to the cart.
    Use this when the user asks for 'ingredients for X'.
    """
    print(f"🧑‍🍳 ADDING INGREDIENTS FOR: {dish_name}")

    dish_name_key = dish_name.lower().strip()
    
    # Simple lookup in hardcoded recipes
    matched_recipe = None
    for key, recipe in RECIPES.items():
        if dish_name_key in key:
            matched_recipe = recipe
            break

    if not matched_recipe:
        return f"I don't have a recipe for '{dish_name}'. I can only add single items right now."

    added_items = []
    
    for ingredient in matched_recipe:
        item_id = ingredient['id']
        qty = ingredient.get('qty', 1)
        
        result = ctx.userdata.add_item_to_cart(item_id, qty)
        if result and item_id in CATALOG:
            added_items.append(f"{qty} x {CATALOG[item_id]['name']}")

    if added_items:
        return f"For your **{dish_name}**, I've added the following to your cart: {', '.join(added_items)}."
    else:
        return f"I found the recipe for {dish_name}, but was unable to add the ingredients to the cart."


@function_tool
async def list_cart(
    ctx: RunContext[Userdata],
) -> str:
    """
    📜 Reads back the current contents and total of the user's shopping cart.
    Use this when the user asks what is in their cart.
    """
    print("📜 LISTING CART")
    return ctx.userdata.list_cart_contents()


@function_tool
async def remove_from_cart(
    ctx: RunContext[Userdata],
    item_name: Annotated[str, Field(description="The name or partial name of the item to remove (e.g., 'bread', 'chips').")]
) -> str:
    """
    🗑️ Removes a specific item from the user's shopping cart.
    Use this when the user says to remove an item.
    """
    print(f"🗑️ REMOVING: {item_name}")
    return ctx.userdata.remove_item_from_cart(item_name)


@function_tool
async def checkout_and_save_order(
    ctx: RunContext[Userdata],
    customer_name: Annotated[str, Field(description="The customer's name for the order receipt.")],
    address: Annotated[Optional[str], Field(description="The delivery address provided by the user.")] = None
) -> str:
    """
    📦 Finalizes the order, saves the details to a JSON file, and clears the cart.
    Call this when the user says 'Place my order' or 'I'm done'.
    """
    print("📦 CHECKING OUT AND SAVING ORDER")

    if not ctx.userdata.cart:
        return "Your cart is empty. Please add items before placing an order."

    # 1. Create Order Object
    timestamp = datetime.now().isoformat()
    order_id = f"ORDER-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    order_data = {
        "order_id": order_id,
        "customer_name": customer_name,
        "delivery_address": address if address else "Not provided",
        "timestamp": timestamp,
        "total": ctx.userdata.get_cart_total(),
        "items": [asdict(item) for item in ctx.userdata.cart]
    }

    # 2. Save to JSON File
    filename = os.path.join(ORDER_OUTPUT_DIR, f"{order_id}.json")
    try:
        with open(filename, 'w') as f:
            json.dump(order_data, f, indent=4)
        
        final_total = order_data['total']
        
        # 3. Clear Cart for next session (or current session)
        ctx.userdata.cart = [] 
        
        return (f"Order successfully placed! The final total is **${final_total:.2f}**."
                f"Your order ID is {order_id}. Your receipt has been generated.")
    except Exception as e:
        return f"Error saving the order: {str(e)}. Please contact support."


# --- Agent Class ---

class GroceryAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are 'ZipCart', a friendly, efficient voice assistant for a local food and grocery store.
            Your job is to help the customer add items to their shopping cart and place their final order.

            🗣️ **TONE:** Friendly, helpful, and concise. Always confirm cart changes.

            🛒 **PRIMARY ACTIONS (Follow in order of conversation flow):**

            1.  **GREETING:** Greet the user and introduce yourself.
                - Ask: "What items can I get for you today, and what quantity?"
            
            2.  **ADDING ITEMS:**
                - Use `add_to_cart` for single item requests (e.g., "I need two loaves of bread").
                - Use `add_ingredients_for` for meal requests (e.g., "I need stuff for a sandwich").
                - Verbally confirm the item was added or updated after the tool returns.

            3.  **CART MANAGEMENT:**
                - Use `list_cart` when the user asks what they have so far (e.g., "What's in my cart?").
                - Use `remove_from_cart` when the user asks to remove an item.
            
            4.  **CHECKOUT:**
                - When the user indicates they are done (e.g., "That's all", "I'm ready to checkout"):
                    - First, use `list_cart` to confirm the final order and total.
                    - Then, ask for the customer's name and address.
                    - Finally, use the `checkout_and_save_order` tool with the name and address to finalize.
            
            ⚠️ **IMPORTANT:** Your catalog is limited. If the user asks for something you can't find, politely let them know and suggest alternatives.
            """,
            tools=[
                add_to_cart, 
                add_ingredients_for, 
                list_cart, 
                remove_from_cart, 
                checkout_and_save_order
            ],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    print("\n" + "🛒" * 25)
    print("🚀 STARTING GROCERY ORDER SESSION")
    
    # Initialize Userdata with an empty cart
    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus", 
            style="Conversational",      
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )
    
    await session.start(
        agent=GroceryAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))