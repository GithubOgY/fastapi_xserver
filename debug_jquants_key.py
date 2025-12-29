import requests
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("JQUANTS_API_KEY")

print(f"Testing API Key: {API_KEY[:5]}...{API_KEY[-5:]} (Length: {len(API_KEY)})")

endpoints = [
    "https://api.jquants.com/v1/listed/info",
    "https://api.jquants.com/v1/equities/master",
    "https://api.jquants.com/v1/token/auth_user", # Just in case it expects API key here?
]

headers = {"x-api-key": API_KEY}

for url in endpoints:
    print(f"--- Testing: {url} ---")
    try:
        if "token" in url:
             # Just a get?
             res = requests.post(url, headers=headers) # Token usually POST
        else:
             res = requests.get(url, headers=headers)
        
        print(f"Status Code: {res.status_code}")
        try:
            print(f"Response: {res.json()}")
        except:
            print(f"Response (text): {res.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
