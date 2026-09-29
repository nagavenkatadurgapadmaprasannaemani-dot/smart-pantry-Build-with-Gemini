import sys
from google.cloud import firestore

FIRESTORE_PROJECT = "qwiklabs-gcp-03-0957fd4e6089"

SEED_ITEMS = [
    {
        "id": "penne_pasta",
        "name": "Penne Pasta",
        "category": "Grains",
        "quantity": 500.0,
        "unit": "g",
        "expiration_date": "2026-12-31",
    },
    {
        "id": "olive_oil",
        "name": "Extra Virgin Olive Oil",
        "category": "Pantry Staples",
        "quantity": 750.0,
        "unit": "ml",
        "expiration_date": "2027-06-30",
    },
    {
        "id": "canned_tomatoes",
        "name": "Canned Tomatoes",
        "category": "Pantry Staples",
        "quantity": 3.0,
        "unit": "cans",
        "expiration_date": "2026-10-31",
    },
    {
        "id": "eggs",
        "name": "Fresh Eggs",
        "category": "Dairy",
        "quantity": 12.0,
        "unit": "items",
        "expiration_date": "2026-10-15",
    },
    {
        "id": "garlic",
        "name": "Fresh Garlic",
        "category": "Produce",
        "quantity": 2.0,
        "unit": "heads",
        "expiration_date": "2026-10-20",
    },
    {
        "id": "parmesan",
        "name": "Parmesan Cheese",
        "category": "Dairy",
        "quantity": 200.0,
        "unit": "g",
        "expiration_date": "2026-11-15",
    },
]


def seed_database():
    print(f"Connecting to Firestore with project ID: {FIRESTORE_PROJECT}")
    db = firestore.Client(project=FIRESTORE_PROJECT)
    collection_ref = db.collection("pantry_items")

    for item in SEED_ITEMS:
        doc_id = item["id"]
        data = {k: v for k, v in item.items() if k != "id"}
        collection_ref.document(doc_id).set(data)
        print(f"  ✓ Seeded item '{item['name']}' (ID: {doc_id})")

    print("\n✅ Successfully seeded Firestore collection 'pantry_items'.")


if __name__ == "__main__":
    seed_database()
