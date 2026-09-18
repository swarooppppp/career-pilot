import os
from dotenv import load_dotenv
from google import genai

load_dotenv(".env")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
response = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
    contents="Reply with today's date",
)
print(response.text)
