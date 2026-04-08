from dotenv import load_dotenv
import os
import json
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
def generate_llm_explanation(score, signals):
    prompt = f"""
You are an expert fraud detection system.

Fraud Score: {score}/100
Triggered Signals: {signals}

Give a structured response in JSON ONLY:

{{
  "explanation": "Clear reason why transaction is risky",
  "user_actions": ["action1", "action2"],
  "bank_actions": ["action1", "action2"]
}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        content = response.choices[0].message.content

        # Try parsing JSON
        data = json.loads(content)

        return data

    except Exception as e:
        print("LLM Error:", e)

        # Fallback (VERY IMPORTANT)
        return {
            "explanation": f"Transaction flagged due to {', '.join(signals)}",
            "user_actions": ["Verify transaction", "Freeze card if suspicious"],
            "bank_actions": ["Flag account", "Enable additional verification"]
        }