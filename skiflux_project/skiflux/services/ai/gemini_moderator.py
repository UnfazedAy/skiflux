import json
from google import genai
from django.conf import settings


class GeminiModerator:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def moderate(self, text: str) -> dict:
        prompt = f"""
            You are a content moderation classifier for an online learning platform.
            Analyze the following comment and determine if it violates 
            community guidelines.

            Violations include:
            - Toxic or offensive language (insults, slurs, hate speech)
            - Harassment or personal attacks
            - Spam or unsolicited external promotion
            - Inappropriate solicitation (e.g. asking users to DMs for favors)
            - Explicit or sexual content

            Comment:
            \"\"\"{text}\"\"\"

            Respond ONLY with a JSON object. No explanation, no markdown, no preamble.
            Format:
            {{
            "flagged": True or False,
            "reason": "short reason if flagged, empty string if not",
            "confidence": 0.0 to 1.0,
            "category": one of [
                "toxic_language",
                "harassment",
                "spam",
                "inappropriate_solicitation",
                "hate",
                "violence",
                "insult",
                "sexual",
                "other"
                ]
            }}
        """

        response = self.client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )

        text = response.text.strip()

        # optional safety cleanup
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
