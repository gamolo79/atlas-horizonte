import json
import logging
import os
from typing import List, Dict, Any, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

LOGGER = logging.getLogger(__name__)

class AIClient:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = None
        if self.api_key and OpenAI:
            self.client = OpenAI(api_key=self.api_key)
        else:
            LOGGER.warning("OpenAI API key not found or library missing. AI features will be disabled/mocked.")

    def get_embedding(self, text: str) -> List[float]:
        """
        Get vector embedding for text using text-embedding-3-small (lower cost).
        """
        if not self.client:
            return []
        
        try:
            # Truncate text to stay within tokens limit if needed (approx)
            clean_text = text[:8000]
            response = self.client.embeddings.create(
                input=clean_text,
                model="text-embedding-3-small"
            )
            return response.data[0].embedding
        except Exception as e:
            LOGGER.error(f"Embedding error: {e}")
            return []

    def classify_article(self, title: str, body: str, entity_names: List[str]) -> Dict[str, Any]:
        """
        Classifies article editorial details and sentiment towards specific entities.
        """
        if not self.client:
            return self._mock_classification(entity_names)

        system_prompt = """
        Eres un analista editorial experto en política mexicana. 
        Tu trabajo es clasificar una noticia y evaluar el sentimiento HACIA actores específicos encontrados en ella.
        
        Salida JSON requerida:
        {
            "content_type": "informativo" | "opinion" | "boletin" | "analisis",
            "scope": "federal" | "estatal" | "municipal",
            "institutional_type": "ejecutivo" | "legislativo" | "partido" | "judicial" | "organo_autonomo" | "general",
            "entities_sentiment": [
                {"name": "Nombre Actor 1", "sentiment": "positivo" | "neutro" | "negativo", "rationale": "breve explicacion"}
            ],
            "topics": ["Tema 1", "Tema 2"],
            "summary": "Resumen de una frase"
        }
        
        Reglas:
        1. El sentimiento debe ser hacia la entidad específica, no el tono general de la nota.
        2. 'Boletin' si es comunicado oficial o promoción evidente. 'Opinion' si es columna/editorial.
        3. Topics deben ser cortos y relevantes (politica publica, seguridad, economia, etc).
        """

        user_prompt = f"""
        TÍTULO: {title}
        TEXTO: {body[:3000]}
        
        ACTORES DETECTADOS (Evalúa el sentimiento para estos si aparecen): {", ".join(entity_names)}
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Cost-effective model
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            LOGGER.error(f"Classification error: {e}")
            return self._mock_classification(entity_names)

    def _mock_classification(self, entity_names):
        return {
            "content_type": "informativo",
            "scope": "estatal",
            "institutional_type": "general",
            "entities_sentiment": [{"name": e, "sentiment": "neutro", "rationale": "Mock/No API"} for e in entity_names],
            "topics": ["General"],
            "summary": "Clasificación simulada (API Key missing)"
        }
