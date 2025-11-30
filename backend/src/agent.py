import logging
import json
import os
import uuid
from datetime import datetime
from typing import Annotated, Optional, List, Dict, Union
from dataclasses import dataclass, field, asdict

# LiveKit and Plugin imports
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    FunctionTool,
    RunContext,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel


from dotenv import load_dotenv
from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass


logger = logging.getLogger("agent")
load_dotenv(".env.local")


@pydantic_dataclass
class Product:
    """Structured data model for a product in the catalog."""
    id: str = Field(description="Unique product identifier (e.g., 'mug-001').")
    name: str = Field(description="Display name of the product.")
    description: str = Field(description="A brief description of the product.")
    price: int = Field(description="Price in the smallest currency unit (e.g., 800 for 8.00 INR).")
    currency: str = Field(default="INR", description="Currency code (e.g., 'INR').")
    category: str = Field(description="Product category (e.g., 'mug', 't-shirt', 'hoodie').")
    color: Optional[str] = Field(default=None, description="Available color.")
    size: Optional[str] = Field(default=None, description="Available size (e.g., 'S', 'M', 'L').")

@pydantic_dataclass
class LineItem:
    """Structured data model for an item within an order."""
    product_id: str = Field(description="ID of the product being purchased.")
    quantity: int = Field(description="Number of units of this product.")

@pydantic_dataclass
class Order:
    """Structured data model for a confirmed order."""
    id: str = Field(description="Unique order identifier.")
    items: List[LineItem] = Field(description="List of line items in the order.")
    total: int = Field(description="Total price of the order in the smallest currency unit.")
    currency: str = Field(default="INR", description="Currency code (e.g., 'INR').")
    created_at: str = Field(description="ISO 8601 timestamp of order creation.")


PRODUCTS: List[Product] = []
ORDERS: List[Order] = []
CATALOG_FILE = "catalogue.json"

def load_products_from_json(file_path: str) -> List[Product]:
    """Loads product data from a JSON file into Product dataclass objects."""
    if not os.path.exists(file_path):
        logger.error(f"Catalog file not found at: {file_path}. Please create it.")
        return []
        
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            # Use a list comprehension to parse each dict into a Product object
            return [Product(**item) for item in data]
    except Exception as e:
        logger.error(f"Error loading or parsing catalog file: {e}")
        return []

PRODUCTS = load_products_from_json(CATALOG_FILE)
if not PRODUCTS:
    # Add a fallback product if the file loading fails or the file is empty
    logger.warning("Using fallback product as catalogue.json is empty or missing.")
    PRODUCTS.append(Product(
        id="fb-001", 
        name="Fallback Demo Product", 
        description="A default item for testing.", 
        price=500, 
        currency="INR", 
        category="demo", 
        color="red"
    ))
# --- End of loading section ---


def list_products(
    category: Optional[str] = None,
    max_price_inr: Optional[int] = None,
    color: Optional[str] = None,
    size: Optional[str] = None
) -> List[Dict]:
    """
    Searches the product catalog based on filtering criteria.

    Args:
        category: Filter by product category (e.g., 'mug', 't-shirt', 'hoodie').
        max_price_inr: Maximum price, in INR (e.g., 1000 for 10.00 INR).
        color: Filter by product color.
        size: Filter by product size.

    Returns:
        A list of matching products, as dictionaries.
    """
    logger.info(f"Listing products with filters: category={category}, max_price={max_price_inr}, color={color}, size={size}")
    
    filtered_products = PRODUCTS
    
    # Simple, case-insensitive filtering
    if category:
        filtered_products = [p for p in filtered_products if p.category and p.category.lower() == category.lower()]
    
    if max_price_inr is not None:
        filtered_products = [p for p in filtered_products if p.price <= max_price_inr]
    
    if color:
        filtered_products = [p for p in filtered_products if p.color and p.color.lower() == color.lower()]
        
    if size:
        filtered_products = [p for p in filtered_products if p.size and p.size.lower() == size.lower()]
        
    # Convert dataclasses to dicts for tool return
    return [asdict(p) for p in filtered_products]


def create_order(line_items: List[Annotated[LineItem, Field(description="A list of items to purchase, each with a product_id and quantity.")]]
) -> Dict:
    """
    Processes a list of items into a new order.

    Args:
        line_items: A list of LineItem objects to be included in the order.

    Returns:
        The newly created Order object as a dictionary.
    """
    logger.info(f"Attempting to create order with line items: {line_items}")
    
    total_price = 0
    currency = "INR" # Assuming single currency for simplicity
    
    # Dictionary for quick product lookup
    product_map = {p.id: p for p in PRODUCTS}
    
    parsed_items = []
    
    for item_data in line_items:
        # Ensure the item is an instance of LineItem (if LLM passed a dict, Pydantic handles conversion)
        item = item_data if isinstance(item_data, LineItem) else LineItem(**item_data)
        
        if item.product_id not in product_map:
            raise ValueError(f"Product ID {item.product_id} not found in catalog.")
            
        product = product_map[item.product_id]
        total_price += product.price * item.quantity
        parsed_items.append(item)

    # Create the new Order object
    new_order = Order(
        id=f"ORD-{uuid.uuid4().hex[:6].upper()}",
        items=parsed_items,
        total=total_price,
        currency=currency,
        created_at=datetime.now().isoformat()
    )
    
    # Persist the order
    ORDERS.append(new_order)
    
    logger.info(f"Order created successfully: {new_order.id}")
    return asdict(new_order)


def get_last_order() -> Optional[Dict]:
    """
    Retrieves the most recent order placed in this session.
    
    Returns:
        The last Order object as a dictionary, or None if no orders exist.
    """
    if not ORDERS:
        return None
        
    return asdict(ORDERS[-1])


# --- 3. Shopping Assistant Agent ---

class ShoppingAssistantAgent(Agent):
    def __init__(self):
        
        CATALOG_SUMMARY = "\n".join([
            f"- {p.name} ({p.category}) - {p.price/100:.2f} {p.currency}" 
            for p in PRODUCTS
        ])
        
        SYSTEM_PROMPT = f"""
            You are the 'ACP Shopping Assistant', a friendly, voice-driven AI agent for a small online store.
            
            **Your Primary Goal is to facilitate commerce using the provided tools.** You MUST use the `list_products` and `create_order` functions to handle all catalog browsing and purchasing requests. Do not invent product or order details.
            
            **Available Catalog Items (for context, but use the tools):**
            ---
            {CATALOG_SUMMARY}
            ---
            
            **Conversation Rules (Follow Strictly):**
            1. **Tool Use:** Always call the `list_products` tool when the user asks to browse, search, or filter products (e.g., "Show me mugs," "What hoodies do you have?").
            2. **Summarization:** When `list_products` returns results, summarize **up to 3** relevant products to the user, mentioning the **Name** and **Price**. If the list is empty, apologize and suggest different criteria.
            3. **Order Placement:** Always call the `create_order` tool when the user decides to buy something (e.g., "I'll take the first one," "Buy the black t-shirt"). You must resolve the product ID from the chat history and user request.
            4. **Order Confirmation:** After a successful `create_order` call, confirm the Order ID, Total Price, and the number of items bought back to the user.
            5. **Last Order:** Use `get_last_order` when the user asks to review their most recent purchase.
            6. **Pricing:** Prices are in INR. Always present the price to the user in the standard format (e.g., 800 price unit = "8.00 INR").
            7. **Keep it Conversational:** Be brief and helpful.
        """
        
        tools = [
            FunctionTool(
                name="list_products",
                description="Use this to search, browse, or filter the product catalog based on user criteria like category, color, size, or maximum price. Prices are in INR.",
                func=list_products,
            ),
            FunctionTool(
                name="create_order",
                description="Use this **only** when the user has explicitly decided to buy one or more specific products. Requires a list of product IDs and quantities.",
                func=create_order,
            ),
            FunctionTool(
                name="get_last_order",
                description="Use this when the user asks to review their most recent purchase.",
                func=get_last_order,
            ),
        ]
        
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=tools, 
        )


def prewarm(proc: JobProcess):
    """Pre-load models before job execution."""
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    userdata = {} 

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
        agent=ShoppingAssistantAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))