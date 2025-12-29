import requests
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("JQUANTS_API_KEY")

print(f"Testing API Key (v2): {API_KEY[:5]}...{API_KEY[-5:]}")

# v2 Base URL
API_URL = "https://api.jquants.com/v2"

endpoints = [
    f"{API_URL}/listed/info",
    f"{API_URL}/equities/master",
]

headers = {"x-api-key": API_KEY}

for url in endpoints:
    print(f"--- Testing: {url} ---")
    try:
        res = requests.get(url, headers=headers)
        print(f"Status Code: {res.status_code}")
        try:
            print(f"Response: {res.json()}")
        except:
            print(f"Response (text): {res.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
