# app/utils/text_analysis.py
import re
import unicodedata
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import process, fuzz

from app.config import ABBREVIATION_MAP

# Modelo de embeddings (será carregado uma vez)
_embedding_model = None
_embeddings_cache = {}


def get_embedding_model():
    """Carrega o modelo de embeddings (singleton)"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
    return _embedding_model


def normalize_text(text: str) -> str:
    """
    Normaliza texto removendo acentos, caracteres especiais, e convertendo para minúsculas.
    """
    if not text or not isinstance(text, str):
        return ""

    # Remover acentos
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

    # Converter para minúsculas
    text = text.lower()

    # Remover caracteres especiais, manter apenas letras, números e espaços
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    # Remover espaços múltiplos
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def expand_abbreviations(text: str) -> str:
    """Expande abreviações comuns no texto"""
    if not text:
        return ""

    words = text.split()
    expanded_words = [ABBREVIATION_MAP.get(word.lower(), word) for word in words]
    return " ".join(expanded_words)


def calculate_text_similarity(text1: str, text2: str, method: str = "fuzzy") -> float:
    """
    Calcula similaridade entre dois textos

    Args:
        text1: Primeiro texto
        text2: Segundo texto
        method: Método de cálculo ("fuzzy" ou "embedding")

    Returns:
        Score de similaridade (0.0 a 1.0)
    """
    if method == "fuzzy":
        return fuzz.WRatio(text1, text2) / 100.0

    elif method == "embedding":
        model = get_embedding_model()

        # Verificar cache
        cache_key = f"{text1}||{text2}"
        if cache_key in _embeddings_cache:
            return _embeddings_cache[cache_key]

        # Calcular embeddings
        embeddings = model.encode([text1, text2])
        similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]

        # Cachear resultado
        _embeddings_cache[cache_key] = float(similarity)

        return float(similarity)

    return 0.0


def analyze_text_interests(
        text: str,
        interest_mappings: Dict[str, Tuple[str, str]],
        weights: Optional[Dict[str, float]] = None
) -> Dict[str, Dict[str, float]]:
    """
    Analisa texto para mapear interesses usando métodos avançados.

    Args:
        text: Texto a ser analisado
        interest_mappings: Dicionário de mapeamento de interesses
        weights: Pesos para diferentes métodos (direct, fuzzy, embedding)

    Returns:
        Dicionário com pontuações de áreas e subáreas
    """
    if weights is None:
        weights = {
            "direct": 0.3,
            "fuzzy": 0.9,
            "embedding": 2.0
        }

    # Normalizar e expandir texto
    normalized_text = normalize_text(text)
    expanded_text = expand_abbreviations(normalized_text)
    final_text = normalize_text(expanded_text) or normalized_text

    if not final_text:
        return {"area_scores": {}, "subarea_scores": {}}

    # Preparar candidatos
    candidates = list(interest_mappings.keys())
    normalized_candidates = {normalize_text(c): c for c in candidates}

    # Calcular scores para cada candidato
    candidate_scores = defaultdict(lambda: {"direct": 0.0, "fuzzy": 0.0, "embedding": 0.0})

    # 1. Correspondência direta
    for norm_candidate, original in normalized_candidates.items():
        if norm_candidate in final_text:
            candidate_scores[original]["direct"] = 1.0

    # 2. Correspondência fuzzy
    fuzzy_cutoff = 75
    for candidate in candidates:
        fuzzy_score = fuzz.WRatio(candidate, final_text)
        if fuzzy_score >= fuzzy_cutoff:
            candidate_scores[candidate]["fuzzy"] = fuzzy_score / 100.0

    # 3. Embedding semântico (top 5 candidatos)
    if len(candidates) > 0:
        model = get_embedding_model()
        text_embedding = model.encode([final_text])
        candidate_embeddings = model.encode(candidates)

        similarities = cosine_similarity(text_embedding, candidate_embeddings)[0]
        top_indices = np.argsort(similarities)[-5:][::-1]

        for idx in top_indices:
            if similarities[idx] > 0:
                candidate_scores[candidates[idx]]["embedding"] = float(similarities[idx])

    # Calcular pontuações totais ponderadas
    area_scores = defaultdict(float)
    subarea_scores = defaultdict(float)

    for candidate, scores in candidate_scores.items():
        total_score = (
                scores["direct"] * weights["direct"] +
                scores["fuzzy"] * weights["fuzzy"] +
                scores["embedding"] * weights["embedding"]
        )

        if total_score > 0 and candidate in interest_mappings:
            area, subarea = interest_mappings[candidate]
            area_scores[area] += total_score
            subarea_scores[(area, subarea)] += total_score

    # Normalizar pontuações
    if area_scores:
        max_area_score = max(area_scores.values())
        area_scores = {area: score / max_area_score for area, score in area_scores.items()}

    if subarea_scores:
        max_subarea_score = max(subarea_scores.values())
        subarea_scores = {subarea: score / max_subarea_score for subarea, score in subarea_scores.items()}

    return {
        "area_scores": dict(area_scores),
        "subarea_scores": dict(subarea_scores)
    }