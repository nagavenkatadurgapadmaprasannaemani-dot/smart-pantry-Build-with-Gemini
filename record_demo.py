import os
import glob
import time
import asyncio
from playwright.async_api import async_playwright
from google.cloud import storage

GCS_BUCKET_NAME = "smart-pantry-media-qwiklabs-gcp-03-0957fd4e6089"
FIRESTORE_PROJECT = "qwiklabs-gcp-03-0957fd4e6089"
VIDEO_DIR = "/config/Desktop/Session1/smart-pantry/videos"

os.makedirs(VIDEO_DIR, exist_ok=True)

async def run_demo():
    print("Starting Playwright demo recording...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        print("Navigating to http://localhost:8080...")
        await page.goto("http://localhost:8080/")
        await page.wait_for_timeout(2000)

        # 1. First prompt: Pantry database query
        print("Submitting Prompt 1: Pantry inventory lookup...")
        await page.fill("#input", "What items are currently in my pantry?")
        await page.click("button[type='submit']")

        print("Waiting for agent pantry response...")
        await page.wait_for_timeout(8000)

        # 2. Second richer prompt: Generate Omni video tool call
        print("Submitting Prompt 2: Video generation tool call...")
        await page.fill("#input", "Generate a short video for Garlic Tomato Penne dish")
        await page.click("button[type='submit']")

        print("Waiting for Omni video generation tool call response...")
        await page.wait_for_timeout(15000)

        # Extra 3s pause at end
        await page.wait_for_timeout(3000)

        await page.close()
        await context.close()
        await browser.close()
        print("Browser closed. Video recording complete.")

    # Find recorded video file
    video_files = glob.glob(os.path.join(VIDEO_DIR, "*.webm"))
    if not video_files:
        print("No video file found in VIDEO_DIR.")
        return None

    video_path = video_files[0]
    print(f"Recorded video file: {video_path}")

    # Copy to artifacts directory
    artifact_dir = "/config/.gemini/antigravity/brain/3348c492-020a-49b2-a981-fb32f07f464a"
    artifact_video_path = os.path.join(artifact_dir, "demo_video.webm")
    with open(video_path, "rb") as f_in:
        video_bytes = f_in.read()

    with open(artifact_video_path, "wb") as f_out:
        f_out.write(video_bytes)
    print(f"Saved artifact video to {artifact_video_path}")

    # Upload to Cloud Storage
    storage_client = storage.Client(project=FIRESTORE_PROJECT)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob_name = "smart_pantry_demo.webm"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(video_path, content_type="video/webm")
    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob_name}"
    print(f"Uploaded demo video to GCS: {public_url}")
    return public_url

if __name__ == "__main__":
    asyncio.run(run_demo())
