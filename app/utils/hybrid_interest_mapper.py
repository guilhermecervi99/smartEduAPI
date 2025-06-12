# app/utils/hybrid_interest_mapper.py
import pickle
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
import re
from sentence_transformers import SentenceTransformer
from sklearn.preprocessing import StandardScaler
import pandas as pd


class HybridInterestMapper:
    """
    Sistema híbrido que combina:
    1. Análise do questionário estruturado
    2. Modelo PKL treinado para texto livre
    3. Sistema de balanceamento inteligente
    """

    def __init__(self, model_pkl_path: str = 'ultimate_classifier.pkl'):
        """
        Inicializa o mapeador híbrido

        Args:
            model_pkl_path: Caminho para o arquivo PKL do modelo treinado
        """
        self.model_pkl_path = model_pkl_path
        self.load_pkl_model()

        # Pesos para combinar questionário e texto livre
        self.combination_weights = {
            'questionnaire': 0.6,  # 60% para questionário
            'text_analysis': 0.4  # 40% para análise de texto
        }

        # Sistema de pesos do questionário (mantido do sistema anterior)
        self.question_weights = {
            1: 0.15,  # Tempo livre
            2: 0.20,  # Conteúdo internet
            3: 0.30,  # Papel no grupo
            4: 0.35,  # Matérias
            5: 0.40  # Profissão
        }

        # Penalidades para hobbies
        self.hobby_penalties = {
            "Esportes e Atividades Físicas": 0.3,
            "Artes e Cultura": 0.5,
            "Tecnologia e Computação": 0.7,
            "Literatura e Linguagem": 0.8
        }

        # Bônus de consistência
        self.consistency_bonus = {
            2: 1.1,
            3: 1.25,
            4: 1.4,
            5: 1.6
        }

    def load_pkl_model(self):
        """Carrega o modelo PKL treinado"""
        try:
            with open(self.model_pkl_path, 'rb') as f:
                model_data = pickle.load(f)

            self.ml_model = model_data['model']
            self.label_encoder = model_data['label_encoder']
            self.scaler = model_data['scaler']

            # Converter para defaultdicts se necessário
            self.keyword_weights = defaultdict(lambda: defaultdict(float))
            for k, v in model_data.get('keyword_weights', {}).items():
                for k2, v2 in v.items():
                    self.keyword_weights[k][k2] = v2

            self.category_patterns = defaultdict(list)
            for k, v in model_data.get('category_patterns', {}).items():
                self.category_patterns[k] = v

            self.category_vocab = defaultdict(set)
            for k, v in model_data.get('category_vocab', {}).items():
                self.category_vocab[k] = set(v)

            # Tentar carregar o embedder correto
            embedder_name = model_data.get('embedder_name', 'unknown')

            # Lista de embedders para tentar em ordem
            embedders_to_try = [
                embedder_name if embedder_name != 'unknown' else None,
                'sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
                'sentence-transformers/all-MiniLM-L12-v2',
                'sentence-transformers/all-MiniLM-L6-v2'
            ]

            embedder_loaded = False
            for emb_name in embedders_to_try:
                if emb_name:
                    try:
                        print(f"🔍 Tentando carregar embedder: {emb_name}")
                        self.embedder = SentenceTransformer(emb_name)

                        # Verificar dimensão do embedding
                        test_embedding = self.embedder.encode(["teste"])
                        embedding_dim = test_embedding.shape[1]
                        print(f"✅ Embedder carregado: {emb_name} (dim: {embedding_dim})")

                        embedder_loaded = True
                        break
                    except Exception as e:
                        print(f"❌ Falhou ao carregar {emb_name}: {e}")
                        continue

            if not embedder_loaded:
                raise Exception("Não foi possível carregar nenhum embedder compatível")

            print(f"✅ Modelo PKL carregado com sucesso!")
            print(f"📊 Categorias disponíveis: {list(self.label_encoder.classes_)}")

        except Exception as e:
            print(f"❌ Erro ao carregar modelo PKL: {e}")
            raise

    def preprocess_text(self, text: str) -> str:
        """Pré-processamento do texto (IDÊNTICO ao usado no treinamento)"""
        if pd.isna(text) or not text:
            return ""

        text = str(text).lower()

        # Expansão completa de abreviações - EXATAMENTE COMO NO TREINAMENTO
        expansions = {
            # Básicas
            r'\btb\b': 'também', r'\btbm\b': 'também', r'\btmb\b': 'também',
            r'\bpq\b': 'porque', r'\bpqp\b': 'porque', r'\bpk\b': 'porque',
            r'\bvc\b': 'você', r'\bvcs\b': 'vocês', r'\bcê\b': 'você',
            r'\bmt\b': 'muito', r'\bmto\b': 'muito', r'\bmts\b': 'muitos',
            r'\bq\b': 'que', r'\bqq\b': 'qualquer', r'\bqqr\b': 'qualquer',
            r'\bn\b': 'não', r'\bñ\b': 'não', r'\bnn\b': 'não não',
            r'\bta\b': 'está', r'\btá\b': 'está', r'\btão\b': 'estão',
            r'\bto\b': 'estou', r'\btô\b': 'estou', r'\btou\b': 'estou',

            # Gírias comuns
            r'\btop\b': 'ótimo', r'\bshow\b': 'ótimo',
            r'\bmassa\b': 'legal', r'\bdaora\b': 'legal',
            r'\bmaneiro\b': 'legal', r'\birado\b': 'legal',
            r'\bsuave\b': 'tranquilo', r'\bdeboa\b': 'tranquilo',
            r'\bblz\b': 'beleza', r'\bfmz\b': 'firmeza',

            # Expressões
            r'\btmj\b': 'estamos juntos',
            r'\bvlw\b': 'valeu', r'\bflw\b': 'falou',
            r'\bpdp\b': 'pode pá', r'\bpprt\b': 'papo reto',
            r'\bplmdds\b': 'pelo amor de deus',
            r'\bpdc\b': 'pode crer', r'\btlgd\b': 'tá ligado',
            r'\bmec\b': 'mano', r'\bmlk\b': 'moleque',
            r'\bctz\b': 'certeza', r'\bctza\b': 'certeza'
        }

        for pattern, replacement in expansions.items():
            text = re.sub(pattern, replacement, text)

        # Limpar mantendo estrutura
        text = re.sub(r'[^\w\s\-]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def extract_features_for_pkl(self, text: str) -> np.ndarray:
        """Extrai features do texto EXATAMENTE como no treinamento"""
        text_lower = text.lower()
        words = set(text_lower.split())

        features = []

        # 1. Features de keywords com pesos
        category_scores = defaultdict(float)
        match_counts = defaultdict(int)

        for termo, categoria_pesos in self.keyword_weights.items():
            if termo in text_lower:
                for categoria, peso in categoria_pesos.items():
                    if termo in words:
                        category_scores[categoria] += peso * 1.5
                        match_counts[categoria] += 1
                    else:
                        category_scores[categoria] += peso

        # Normalizar scores por categoria - ORDEM ALFABÉTICA
        categories = sorted(self.category_vocab.keys())
        for cat in categories:
            score = category_scores.get(cat, 0)
            matches = match_counts.get(cat, 0)
            vocab_size = len(self.category_vocab.get(cat, []))

            features.extend([
                score,
                matches,
                score / max(vocab_size, 1),
                matches / max(len(words), 1)
            ])

        # 2. Features linguísticas - EXATAMENTE 8 FEATURES
        linguistic_features = [
            len(words),
            len(text),
            len([w for w in words if len(w) > 6]),
            text.count('!') + text.count('?'),
            text.count(','),
            len(set(words)) / max(len(words), 1),
            sum(1 for c in text if c.isupper()) / max(len(text), 1),
            sum(1 for w in words if w in self.keyword_weights) / max(len(words), 1)
        ]
        features.extend(linguistic_features)

        # 3. Features de padrões
        pattern_features = []
        for cat in categories:
            patterns = self.category_patterns.get(cat, [])
            pattern_matches = sum(1 for p in patterns if re.search(p, text_lower))
            pattern_features.append(pattern_matches)
        features.extend(pattern_features)

        return np.array(features)

    def analyze_text_with_pkl(self, text: str) -> Dict[str, float]:
        """
        Analisa o texto livre usando o modelo PKL treinado

        Returns:
            Dict com área -> probabilidade
        """
        if not text or len(text.strip()) < 10:
            return {}

        try:
            # Pré-processar
            processed_text = self.preprocess_text(text)

            # Criar lista para processar (modelo espera lista)
            texts = [processed_text]

            # Extrair features manuais
            all_manual_features = []

            for text in texts:
                manual_features = self.extract_features_for_pkl(text)
                all_manual_features.append(manual_features)

            # Gerar embeddings
            embeddings = self.embedder.encode(texts, show_progress_bar=False, normalize_embeddings=True)

            # Combinar features
            manual_features = np.array(all_manual_features)
            all_features = np.hstack([embeddings, manual_features])

            # Debug: verificar dimensões
            print(
                f"📏 Dimensões - Embeddings: {embeddings.shape}, Manual: {manual_features.shape}, Total: {all_features.shape}")

            # Normalizar
            all_features = self.scaler.transform(all_features)

            # Predição com probabilidades
            probabilities = self.ml_model.predict_proba(all_features)[0]

            # Criar dicionário de resultados
            results = {}
            for idx, prob in enumerate(probabilities):
                area = self.label_encoder.classes_[idx]
                results[area] = float(prob)

            return results

        except Exception as e:
            print(f"❌ Erro na análise de texto: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def calculate_questionnaire_scores(
            self,
            responses: Dict[int, List[str]],
            question_options: Dict[int, Dict[str, Dict[str, Any]]]
    ) -> Dict[str, float]:
        """
        Calcula scores do questionário com o sistema balanceado
        """
        area_scores = defaultdict(float)
        area_appearances = defaultdict(set)
        area_question_scores = defaultdict(lambda: defaultdict(float))

        # Processar cada resposta
        for question_id, selected_options in responses.items():
            if question_id not in question_options:
                continue

            question_weight = self.question_weights.get(question_id, 0.2)
            num_selected = len(selected_options)

            if num_selected == 0:
                continue

            for option_id in selected_options:
                if option_id in question_options[question_id]:
                    option = question_options[question_id][option_id]
                    area = option.get('area')
                    weight = option.get('weight', 1.0)

                    if area:
                        score = (question_weight * weight) / num_selected
                        area_question_scores[area][question_id] = score
                        area_appearances[area].add(question_id)

        # Calcular pontuação total com bônus e penalidades
        for area, question_scores in area_question_scores.items():
            base_score = sum(question_scores.values())

            # Bônus de consistência
            num_appearances = len(area_appearances[area])
            consistency_multiplier = self.consistency_bonus.get(num_appearances, 1.0)

            # Penalidade se aparece APENAS como hobby
            if area_appearances[area] == {1} and area in self.hobby_penalties:
                consistency_multiplier *= self.hobby_penalties[area]

            area_scores[area] = base_score * consistency_multiplier

        # Normalizar
        if area_scores:
            max_score = max(area_scores.values())
            if max_score > 0:
                return {area: score / max_score for area, score in area_scores.items()}

        return dict(area_scores)

    def combine_scores(
            self,
            questionnaire_scores: Dict[str, float],
            text_scores: Dict[str, float],
            text_quality_factor: float = 1.0
    ) -> Dict[str, float]:
        """
        Combina scores do questionário e texto de forma inteligente

        Args:
            questionnaire_scores: Scores do questionário
            text_scores: Scores da análise de texto
            text_quality_factor: Fator de qualidade do texto (0-1)
        """
        combined_scores = defaultdict(float)

        # Ajustar pesos baseado na qualidade do texto
        adj_quest_weight = self.combination_weights['questionnaire']
        adj_text_weight = self.combination_weights['text_analysis'] * text_quality_factor

        # Re-normalizar pesos
        total_weight = adj_quest_weight + adj_text_weight
        if total_weight > 0:
            adj_quest_weight /= total_weight
            adj_text_weight /= total_weight

        # Combinar scores
        all_areas = set(questionnaire_scores.keys()) | set(text_scores.keys())

        for area in all_areas:
            q_score = questionnaire_scores.get(area, 0)
            t_score = text_scores.get(area, 0)

            # Média ponderada
            combined = (q_score * adj_quest_weight) + (t_score * adj_text_weight)

            # Bônus se há concordância entre questionário e texto
            if q_score > 0.5 and t_score > 0.5:
                combined *= 1.2  # 20% de bônus

            combined_scores[area] = min(combined, 1.0)  # Cap em 1.0

        # Normalizar resultado final
        if combined_scores:
            max_score = max(combined_scores.values())
            if max_score > 0:
                return {area: score / max_score for area, score in combined_scores.items()}

        return dict(combined_scores)

    def calculate_text_quality(self, text: str) -> float:
        """
        Calcula um fator de qualidade do texto (0-1)
        """
        if not text:
            return 0.0

        words = text.split()
        word_count = len(words)
        unique_words = len(set(words))

        # Fatores de qualidade
        factors = []

        # 1. Comprimento adequado (ideal: 20-200 palavras)
        if word_count < 10:
            factors.append(0.3)
        elif word_count < 20:
            factors.append(0.6)
        elif word_count <= 200:
            factors.append(1.0)
        else:
            factors.append(0.8)

        # 2. Diversidade léxica
        if word_count > 0:
            diversity = unique_words / word_count
            factors.append(min(diversity * 2, 1.0))
        else:
            factors.append(0.0)

        # 3. Presença de keywords relevantes
        keyword_density = sum(1 for w in words if w.lower() in self.keyword_weights)
        keyword_factor = min(keyword_density / max(word_count, 1) * 10, 1.0)
        factors.append(keyword_factor)

        # 4. Estrutura (pontuação, etc)
        has_punctuation = any(c in text for c in '.,!?;:')
        factors.append(1.0 if has_punctuation else 0.7)

        return np.mean(factors)

    def map_interests(
            self,
            questionnaire_responses: Dict[int, List[str]],
            question_options: Dict[int, Dict[str, Dict[str, Any]]],
            free_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mapeia interesses combinando questionário e texto livre

        Returns:
            Dict com resultados completos do mapeamento
        """
        results = {
            'questionnaire_scores': {},
            'text_scores': {},
            'combined_scores': {},
            'text_quality': 0.0,
            'recommended_area': None,
            'confidence': 0.0,
            'top_3_areas': [],
            'analysis_details': {}
        }

        # 1. Calcular scores do questionário
        results['questionnaire_scores'] = self.calculate_questionnaire_scores(
            questionnaire_responses,
            question_options
        )

        # 2. Analisar texto livre se fornecido
        if free_text and len(free_text.strip()) > 10:
            results['text_quality'] = self.calculate_text_quality(free_text)
            results['text_scores'] = self.analyze_text_with_pkl(free_text)

            # 3. Combinar scores
            if results['text_scores']:  # Só combinar se análise de texto funcionou
                results['combined_scores'] = self.combine_scores(
                    results['questionnaire_scores'],
                    results['text_scores'],
                    results['text_quality']
                )
            else:
                # Usar apenas questionário se análise de texto falhou
                results['combined_scores'] = results['questionnaire_scores']
        else:
            # Usar apenas questionário
            results['combined_scores'] = results['questionnaire_scores']
            results['text_quality'] = 0.0

        # 4. Determinar área recomendada e top 3
        if results['combined_scores']:
            sorted_areas = sorted(
                results['combined_scores'].items(),
                key=lambda x: x[1],
                reverse=True
            )

            results['recommended_area'] = sorted_areas[0][0]
            results['confidence'] = sorted_areas[0][1]

            results['top_3_areas'] = [
                {
                    'area': area,
                    'score': score,
                    'percentage': score * 100,
                    'questionnaire_contribution': results['questionnaire_scores'].get(area, 0),
                    'text_contribution': results['text_scores'].get(area, 0)
                }
                for area, score in sorted_areas[:3]
            ]

        # 5. Análise detalhada
        results['analysis_details'] = {
            'method': 'hybrid_pkl_model',
            'questionnaire_weight': self.combination_weights['questionnaire'],
            'text_weight': self.combination_weights['text_analysis'] * results['text_quality'],
            'areas_from_questionnaire': len([s for s in results['questionnaire_scores'].values() if s > 0]),
            'areas_from_text': len([s for s in results['text_scores'].values() if s > 0]),
            'agreement_score': self._calculate_agreement(
                results['questionnaire_scores'],
                results['text_scores']
            )
        }

        return results

    def _calculate_agreement(
            self,
            scores1: Dict[str, float],
            scores2: Dict[str, float]
    ) -> float:
        """Calcula concordância entre duas fontes de scores"""
        if not scores1 or not scores2:
            return 0.0

        # Top 3 de cada fonte
        top1 = set(sorted(scores1.items(), key=lambda x: x[1], reverse=True)[:3])
        top2 = set(sorted(scores2.items(), key=lambda x: x[1], reverse=True)[:3])

        top1_areas = {area for area, _ in top1}
        top2_areas = {area for area, _ in top2}

        # Concordância baseada em overlap
        overlap = len(top1_areas & top2_areas)
        return overlap / 3.0


# Função para integrar com o sistema FastAPI existente
def create_hybrid_mapper_for_api(pkl_path: str = 'ultimate_classifier.pkl') -> HybridInterestMapper:
    """
    Cria uma instância do mapeador híbrido para uso na API
    """
    return HybridInterestMapper(pkl_path)


# Exemplo de uso
if __name__ == "__main__":
    # Criar mapeador
    mapper = HybridInterestMapper('ultimate_classifier.pkl')

    # Exemplo de respostas do questionário
    questionnaire_responses = {
        1: ["3"],  # Praticar esportes
        2: ["1"],  # Tutoriais de tecnologia
        3: ["1"],  # Responsável pela parte técnica
        4: ["1"],  # Programação, robótica
        5: ["1"]  # Desenvolvedor de software
    }

    # Opções do questionário (simplificado)
    question_options = {
        1: {
            "3": {"area": "Esportes e Atividades Físicas", "weight": 0.4}
        },
        2: {
            "1": {"area": "Tecnologia e Computação", "weight": 0.9}
        },
        3: {
            "1": {"area": "Tecnologia e Computação", "weight": 1.2}
        },
        4: {
            "1": {"area": "Tecnologia e Computação", "weight": 1.5}
        },
        5: {
            "1": {"area": "Tecnologia e Computação", "weight": 2.0}
        }
    }

    # Texto livre
    free_text = """
    Gosto muito de programar e criar aplicativos. Nas horas vagas jogo futebol
    com os amigos mas meu sonho é trabalhar com inteligência artificial e 
    machine learning. Estou aprendendo Python e já fiz alguns projetos.
    """

    # Mapear interesses
    results = mapper.map_interests(
        questionnaire_responses,
        question_options,
        free_text
    )

    # Mostrar resultados
    print("\n=== RESULTADO DO MAPEAMENTO HÍBRIDO ===")
    print(f"\n✅ Área Recomendada: {results['recommended_area']}")
    print(f"📊 Confiança: {results['confidence']:.1%}")
    print(f"📝 Qualidade do texto: {results['text_quality']:.1%}")

    print("\n🏆 Top 3 Áreas:")
    for i, area in enumerate(results['top_3_areas'], 1):
        print(f"\n{i}. {area['area']} ({area['percentage']:.1f}%)")
        print(f"   - Questionário: {area['questionnaire_contribution']:.1%}")
        print(f"   - Texto: {area['text_contribution']:.1%}")

    print(f"\n📈 Taxa de concordância: {results['analysis_details']['agreement_score']:.1%}")