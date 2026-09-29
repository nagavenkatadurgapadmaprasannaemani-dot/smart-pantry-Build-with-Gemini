# ruff: noqa
import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

FIRESTORE_PROJECT = "qwiklabs-gcp-03-0957fd4e6089"
GCS_BUCKET_NAME = "smart-pantry-media-qwiklabs-gcp-03-0957fd4e6089"
MEMORY_BANK_ID = "510399894683385856"

schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Smart Pantry AI, a helpful kitchen and inventory management assistant. "
        "You track and remember all user allergies, dietary restrictions, and food preferences across sessions. "
        "Whenever a user states an allergy (e.g., peanuts, gluten, dairy, shellfish, eggs, tree nuts), save it to memory "
        "and ensure all future recipe suggestions, pantry items, and meal recommendations strictly accommodate and warn about these allergies. "
        "Use your function tools (get_pantry_items, add_pantry_item, update_pantry_quantity, search_recipes, "
        "search_online_recipes, geocode_address, find_nearby_places, generate_dish_image, generate_dish_video, PreloadMemoryTool) "
        "and Python sandbox code execution to assist the user."
    ),
    workflow_description="Analyze the request, call relevant tools if needed, and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property (\'h1\', \'h2\', \'body\') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or \'kind\'/\'data\'/\'metadata\' objects."
    ),
    include_schema=True,
    include_examples=True,
)

# Load Agent Engine resource ID from deployment_metadata.json for code execution
metadata_path = Path(__file__).parent.parent / "deployment_metadata.json"
agent_engine_resource_name = None
if metadata_path.exists():
    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id")
    except Exception:
        pass

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


# WRITE: after each turn, send the session to Memory Bank for extraction.
async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        print(f"Memory callback notice: {e}")
    return None


# Memory service builder for production / redeployments
def memory_bank_service_builder():
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


SAMPLE_RECIPES = [
    {
        "name": "Garlic Tomato Penne",
        "category": "Italian",
        "ingredients": ["Penne Pasta", "Canned Tomatoes", "Fresh Garlic", "Extra Virgin Olive Oil", "Parmesan Cheese"],
        "instructions": "Boil pasta. Saute garlic in olive oil, add tomatoes and simmer. Toss pasta with sauce and top with parmesan.",
        "prep_time_mins": 20,
    },
    {
        "name": "Classic Scrambled Eggs",
        "category": "Breakfast",
        "ingredients": ["Fresh Eggs", "Extra Virgin Olive Oil", "Parmesan Cheese"],
        "instructions": "Whisk eggs. Heat olive oil in pan, cook eggs gently over low heat, top with grated parmesan.",
        "prep_time_mins": 10,
    },
    {
        "name": "Garlic Olive Oil Pasta (Aglio e Olio)",
        "category": "Italian",
        "ingredients": ["Penne Pasta", "Fresh Garlic", "Extra Virgin Olive Oil", "Parmesan Cheese"],
        "instructions": "Cook pasta. Saute sliced garlic in generous olive oil until golden. Toss pasta in garlic oil and parmesan.",
        "prep_time_mins": 15,
    },
]


def _get_firestore_client():
    return firestore.Client(project=FIRESTORE_PROJECT)


def get_pantry_items(category: str = "") -> str:
    """Retrieve items stored in the pantry inventory.

    Args:
        category: Optional category filter (e.g. 'Grains', 'Dairy', 'Produce', 'Pantry Staples').
                 If empty or not provided, returns all pantry items.

    Returns:
        JSON string listing pantry items and their details.
    """
    try:
        db = _get_firestore_client()
        collection_ref = db.collection("pantry_items")

        if category:
            docs = collection_ref.where("category", "==", category).stream()
        else:
            docs = collection_ref.stream()

        items = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            items.append(data)

        if not items:
            return f"No items found in pantry" + (f" for category '{category}'" if category else "") + "."

        return json.dumps(items, indent=2)
    except Exception as e:
        return f"Error accessing Firestore: {str(e)}"


def add_pantry_item(item_name: str, category: str, quantity: float, unit: str, expiration_date: str = "") -> str:
    """Add a new item or update an existing item in the pantry inventory.

    Args:
        item_name: The name of the ingredient/item (e.g. 'Whole Wheat Bread').
        category: The category (e.g. 'Grains', 'Dairy', 'Produce', 'Pantry Staples').
        quantity: Numerical quantity (e.g. 2.0).
        unit: Unit of measurement (e.g. 'loaves', 'g', 'ml', 'items', 'cans').
        expiration_date: Optional expiration date in YYYY-MM-DD format.

    Returns:
        Confirmation message string.
    """
    try:
        db = _get_firestore_client()
        doc_id = item_name.lower().strip().replace(" ", "_")
        doc_ref = db.collection("pantry_items").document(doc_id)

        data = {
            "name": item_name.strip(),
            "category": category.strip(),
            "quantity": float(quantity),
            "unit": unit.strip(),
            "expiration_date": expiration_date.strip(),
        }

        doc_ref.set(data)
        return f"Successfully added/updated '{item_name}' ({quantity} {unit}) in category '{category}'."
    except Exception as e:
        return f"Error updating Firestore: {str(e)}"


def update_pantry_quantity(item_name: str, quantity_change: float) -> str:
    """Adjust the quantity of an existing item in the pantry (use positive to restock, negative to consume).

    Args:
        item_name: The name or ID of the pantry item.
        quantity_change: Amount to add (positive) or subtract (negative).

    Returns:
        Updated item status string.
    """
    try:
        db = _get_firestore_client()
        doc_id = item_name.lower().strip().replace(" ", "_")
        doc_ref = db.collection("pantry_items").document(doc_id)
        doc = doc_ref.get()

        if not doc.exists:
            return f"Item '{item_name}' was not found in the pantry."

        data = doc.to_dict()
        current_qty = data.get("quantity", 0.0)
        new_qty = max(0.0, current_qty + float(quantity_change))
        data["quantity"] = new_qty
        doc_ref.set(data)

        return f"Updated '{data.get('name', item_name)}' quantity from {current_qty} to {new_qty} {data.get('unit', '')}."
    except Exception as e:
        return f"Error updating quantity in Firestore: {str(e)}"


def search_recipes(query: str = "", ingredients: str = "") -> str:
    """Search for recipes in the local recipe database by dish name, query, or available ingredients.

    Args:
        query: Optional general search term or recipe name (e.g. 'pasta', 'eggs').
        ingredients: Optional comma-separated list of available ingredients (e.g. 'garlic, tomatoes, pasta').

    Returns:
        JSON string of matching recipes with details, ingredients, and instructions.
    """
    results = []
    q_lower = query.lower().strip()
    ing_list = [i.strip().lower() for i in ingredients.split(",") if i.strip()]

    for recipe in SAMPLE_RECIPES:
        name_match = not q_lower or q_lower in recipe["name"].lower() or q_lower in recipe["category"].lower()
        rec_ings = [ing.lower() for ing in recipe["ingredients"]]
        ing_match = not ing_list or any(any(user_ing in r_ing for r_ing in rec_ings) for user_ing in ing_list)

        if name_match and ing_match:
            results.append(recipe)

    if not results:
        results = SAMPLE_RECIPES[:2]

    return json.dumps(results, indent=2)


def search_online_recipes(query: str) -> str:
    """Fetch real-world recipes from TheMealDB public REST API by dish or ingredient keyword (e.g. 'chicken', 'pasta', 'soup').

    Args:
        query: Search term or ingredient to look up in the public recipe database.

    Returns:
        JSON string containing matching real-world recipe details, instructions, and ingredients.
    """
    api_key = os.environ.get("MEALDB_API_KEY", "1")
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={encoded_query}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartPantryAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                meals = data.get("meals")
                if not meals:
                    return f"No online recipes found matching '{query}'."

                results = []
                for meal in meals[:3]:
                    ingredients = []
                    for i in range(1, 21):
                        ing = meal.get(f"strIngredient{i}")
                        measure = meal.get(f"strMeasure{i}")
                        if ing and ing.strip():
                            ingredients.append(f"{measure.strip() if measure else ''} {ing.strip()}".strip())

                    results.append({
                        "id": meal.get("idMeal"),
                        "name": meal.get("strMeal"),
                        "category": meal.get("strCategory"),
                        "area": meal.get("strArea"),
                        "instructions": (meal.get("strInstructions") or "")[:250] + "...",
                        "image_url": meal.get("strMealThumb"),
                        "ingredients": ingredients,
                    })
                return json.dumps(results, indent=2)
            else:
                return f"Error from recipe service (status {response.status})"
    except Exception as e:
        return f"Failed to fetch online recipes: {str(e)}"


def geocode_address(address: str) -> str:
    """Convert a street address or city name into geographic coordinates (latitude and longitude) using Google Geocoding API.

    Args:
        address: The street address, city, or location query (e.g. '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        JSON string containing the formatted address, latitude, and longitude.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is not configured in environment."

    encoded_address = urllib.parse.quote(address.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                location = result["geometry"]["location"]
                return json.dumps({
                    "formatted_address": result.get("formatted_address"),
                    "latitude": location.get("lat"),
                    "longitude": location.get("lng"),
                }, indent=2)
            return f"No coordinates found for address '{address}'. Status: {data.get('status')}"
    except Exception as e:
        return f"Geocoding API error: {str(e)}"


def find_nearby_places(query: str, location: str = "") -> str:
    """Find nearby places of a given type (e.g. 'grocery store', 'supermarket', 'bakery') using Google Places API (New).

    Args:
        query: Type of place or search text (e.g. 'grocery store', 'organic market', 'supermarket').
        location: Optional location name or city (e.g. 'San Francisco, CA'). If empty, defaults to general search.

    Returns:
        JSON string listing matching places with name, address, and location coordinates.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is not configured in environment."

    search_text = f"{query} near {location}" if location else query
    url = "https://places.googleapis.com/v1/places:searchText"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    body = json.dumps({"textQuery": search_text, "pageSize": 5}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            places = data.get("places", [])
            if not places:
                return f"No places found for query '{search_text}'."

            formatted_places = []
            for p in places:
                formatted_places.append({
                    "name": p.get("displayName", {}).get("text", ""),
                    "address": p.get("formattedAddress", ""),
                    "location": p.get("location", {}),
                })
            return json.dumps(formatted_places, indent=2)
    except Exception as e:
        return f"Places API error: {str(e)}"


def generate_dish_image(dish_name: str, tool_context: ToolContext) -> str:
    """Generate an appetizing food image for a dish or recipe item using gemini-3.1-flash-lite-image.

    Args:
        dish_name: The name or description of the dish or pantry item (e.g. 'Garlic Tomato Penne', 'Scrambled Eggs').

    Returns:
        The public HTTPS URL of the generated image stored in Cloud Storage.
    """
    try:
        genai_client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")
        prompt = f"Professional food photography of {dish_name}, appetizing presentation, gourmet kitchen setting, 4k"

        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
        )

        if not response.candidates or not response.candidates[0].content.parts:
            return "Error: Image generation returned no content."

        part = response.candidates[0].content.parts[0]
        if not part.inline_data or not part.inline_data.data:
            return "Error: Generated response did not contain image data."

        image_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "image/jpeg"

        clean_name = dish_name.lower().strip().replace(" ", "_")
        filename = f"{clean_name}.jpg"

        # 1. Save artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to GCS bucket (in-memory, no disk writing)
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return public_url
    except Exception as e:
        return f"Error generating dish image: {str(e)}"


def generate_dish_video(item_name: str, tool_context: ToolContext) -> str:
    """Generate a short video for a food item, dish, or recipe using gemini-omni-flash-preview in the global region.

    Args:
        item_name: The name or description of the food item, dish, or recipe (e.g. 'Garlic Tomato Penne', 'Scrambled Eggs').

    Returns:
        The public HTTPS URL of the generated video stored in Cloud Storage.
    """
    try:
        genai_client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT, location="global")
        prompt = f"Generate a short video loop showing {item_name}, appetizing presentation, gourmet kitchen setting"

        interaction = genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        if not hasattr(interaction, "output_video") or not interaction.output_video:
            return "Error: Video generation returned no video content."

        video_content = interaction.output_video
        raw_data = getattr(video_content, "data", None)
        if not raw_data:
            return "Error: Generated response did not contain video data."

        if isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        elif isinstance(raw_data, bytes):
            video_bytes = raw_data
        else:
            video_bytes = bytes(raw_data)

        mime_type = getattr(video_content, "mime_type", None) or "video/mp4"
        if hasattr(mime_type, "value"):
            mime_type = mime_type.value

        clean_name = item_name.lower().strip().replace(" ", "_")
        filename = f"{clean_name}.mp4"

        # 1. Save artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to GCS bucket (in-memory, no disk writing)
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return public_url
    except Exception as e:
        return f"Error generating dish video: {str(e)}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    code_executor=code_executor,
    tools=[
        get_pantry_items,
        add_pantry_item,
        update_pantry_quantity,
        search_recipes,
        search_online_recipes,
        geocode_address,
        find_nearby_places,
        generate_dish_image,
        generate_dish_video,
        PreloadMemoryTool(),
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
