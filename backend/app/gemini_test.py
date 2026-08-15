from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
location = os.environ["VERTEX_AI_LOCATION"]

client = genai.Client(
    vertexai=True,
    project=project_id,
    location=location,
)

response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Explain what a research claim is in a 150 word paragraph and give one example.",
)

print(response.text)