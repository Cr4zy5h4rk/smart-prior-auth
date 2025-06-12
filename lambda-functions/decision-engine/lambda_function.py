import json
import boto3
from botocore.exceptions import ClientError, BotoCoreError
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import re

# Configuration du logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clients AWS avec gestion d'erreur
try:
    dynamodb = boto3.resource('dynamodb')
    bedrock = boto3.client('bedrock-runtime')
    table = dynamodb.Table('prior-auth-requests')
except Exception as e:
    logger.error(f"Erreur d'initialisation AWS : {e}")
    raise

# Règles d'assurance enrichies et structurées
INSURANCE_RULES = {
    "BlueCross": {
        "diabetes": "Nécessite un HbA1c > 8% et l'échec de 2 traitements antérieurs (metformine + sulfonylurée).",
        "mri": "IRM nécessite échec de traitement conservateur pendant 6 semaines et score de douleur > 7/10.",
        "specialty_drugs": "Médicaments spécialisés nécessitent échec de 2 alternatives génériques et approbation du médecin spécialiste.",
        "general": "Évaluation basée sur nécessité médicale documentée et alternatives moins coûteuses épuisées."
    },
    "Aetna": {
        "physical_therapy": "Nécessite 6 semaines de kinésithérapie documentées avec notes de progression.",
        "surgery": "Chirurgie nécessite 12 semaines de traitement conservateur documenté et second avis médical.",
        "imaging": "Imagerie avancée nécessite échec de diagnostic avec méthodes standard.",
        "general": "Approbation basée sur guidelines cliniques établies et documentation complète."
    },
    "UnitedHealthcare": {
        "cancer_treatment": "Traitements oncologiques nécessitent confirmation histologique et staging complet.",
        "mental_health": "Thérapies intensives nécessitent évaluation psychiatrique et échec de thérapie standard.",
        "durable_medical_equipment": "Équipement médical nécessite prescription détaillée et justification fonctionnelle.",
        "general": "Évaluation multifactorielle incluant coût-efficacité et outcomes cliniques."
    },
    "Cigna": {
        "cardiology": "Procédures cardiaques nécessitent écho et ECG récents, plus facteurs de risque documentés.",
        "orthopedic": "Interventions orthopédiques nécessitent imagerie récente et échec de traitements non-invasifs.",
        "general": "Approbation basée sur evidence-based medicine et necessity médicale claire."
    },
    "Humana": {
        "seniors": "Population Medicare nécessite attention particulière aux comorbidités et interactions médicamenteuses.",
        "preventive": "Soins préventifs couverts selon guidelines USPSTF sans autorisation préalable.",
        "general": "Évaluation tenant compte de l'âge, comorbidités et qualité de vie."
    }
}

# Configuration corrigée pour Amazon Titan Text Express
BEDROCK_CONFIG = {
    "model_id": "amazon.titan-text-express-v1",
    "max_tokens": 512,
    "temperature": 0.1,
    "top_p": 0.8
}

def get_insurance_rules(insurance: str, treatment_category: Optional[str] = None) -> str:
    """Récupère les règles d'assurance spécifiques ou générales."""
    insurance_data = INSURANCE_RULES.get(insurance, {})
    
    if treatment_category and treatment_category in insurance_data:
        return insurance_data[treatment_category]
    
    return insurance_data.get("general", "Aucune règle spécifique disponible pour cette assurance.")

def categorize_treatment(treatment: str) -> Optional[str]:
    """Catégorise le traitement pour appliquer les bonnes règles."""
    treatment_lower = treatment.lower()
    
    categories = {
        "diabetes": ["diabète", "metformine", "insuline", "hba1c", "glycémie"],
        "mri": ["irm", "mri", "résonance magnétique"],
        "physical_therapy": ["kinésithérapie", "physiothérapie", "rééducation"],
        "surgery": ["chirurgie", "opération", "intervention"],
        "imaging": ["scanner", "échographie", "radiographie", "imagerie"],
        "cancer_treatment": ["chimiothérapie", "radiothérapie", "oncologie", "cancer"],
        "mental_health": ["psychiatrie", "psychologie", "dépression", "anxiété"],
        "cardiology": ["cardiologie", "cœur", "cardiaque", "ecg"],
        "orthopedic": ["orthopédie", "os", "articulation", "fracture"]
    }
    
    for category, keywords in categories.items():
        if any(keyword in treatment_lower for keyword in keywords):
            return category
    
    return None

def validate_request_data(item: Dict[str, Any]) -> Dict[str, str]:
    """Valide et nettoie les données de la demande."""
    return {
        'patient_info': str(item.get('patient_info', 'Non spécifié')).strip(),
        'treatment': str(item.get('treatment', 'Non spécifié')).strip(),
        'insurance': str(item.get('insurance', 'Inconnue')).strip(),
        'history': str(item.get('history', 'Non fourni')).strip(),
        'urgency': str(item.get('urgency', 'Standard')).strip(),
        'provider_notes': str(item.get('provider_notes', 'Aucune note')).strip()
    }

def create_titan_prompt(data: Dict[str, str], rules: str) -> str:
    """Crée un prompt optimisé spécifiquement pour Amazon Titan."""
    
    # Prompt très strict pour forcer le format JSON
    prompt = f"""Tu es un système d'autorisation médicale. Analyse cette demande et réponds UNIQUEMENT avec un objet JSON valide.

DEMANDE D'AUTORISATION:
Patient: {data['patient_info']}
Traitement: {data['treatment']}
Assurance: {data['insurance']}
Historique: {data['history']}
Urgence: {data['urgency']}
Notes: {data['provider_notes']}

RÈGLES: {rules}

Réponds OBLIGATOIREMENT avec ce format JSON exact (sans texte avant ou après):
{{
  "decision": "APPROVED",
  "reason": "Justification en une phrase",
  "confidence_score": 85,
  "missing_documentation": [],
  "alternative_treatments": []
}}

JSON:"""
    
    return prompt

def call_bedrock_api(prompt: str) -> Dict[str, Any]:
    """Appelle l'API Bedrock avec la configuration correcte pour Titan."""
    try:
        # Structure de requête CORRECTE pour Amazon Titan Text Express
        request_body = {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": BEDROCK_CONFIG["max_tokens"],
                "temperature": BEDROCK_CONFIG["temperature"],
                "topP": BEDROCK_CONFIG["top_p"]
            }
        }
        
        logger.info(f"Appel Bedrock avec modèle: {BEDROCK_CONFIG['model_id']}")
        logger.info(f"Taille du prompt: {len(prompt)} caractères")
        
        # Appel à Bedrock avec le bon Content-Type
        response = bedrock.invoke_model(
            modelId=BEDROCK_CONFIG["model_id"],
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )
        
        # Traitement de la réponse
        response_body = json.loads(response['body'].read().decode('utf-8'))
        logger.info(f"Réponse Bedrock reçue: {response_body}")
        
        # Extraction du texte généré
        if 'results' in response_body and len(response_body['results']) > 0:
            generated_text = response_body['results'][0].get('outputText', '').strip()
        else:
            logger.error("Structure de réponse Bedrock inattendue")
            return create_fallback_response("Structure de réponse inattendue")
        
        logger.info(f"Texte généré: {generated_text}")
        
        # Extraction du JSON de la réponse
        return extract_json_from_text(generated_text)
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"Erreur ClientError Bedrock - Code: {error_code}, Message: {error_message}")
        
        if error_code == 'ValidationException':
            return create_fallback_response("Erreur de validation des paramètres")
        elif error_code == 'AccessDeniedException':
            return create_fallback_response("Accès refusé au modèle Bedrock")
        elif error_code == 'ModelNotReadyException':
            return create_fallback_response("Modèle Bedrock non disponible")
        else:
            return create_fallback_response(f"Erreur Bedrock: {error_code}")
            
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de parsing JSON Bedrock: {e}")
        return create_fallback_response("Réponse Bedrock invalide")
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'appel Bedrock: {e}", exc_info=True)
        return create_fallback_response("Erreur technique Bedrock")

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Extrait et parse le JSON de la réponse textuelle."""
    try:
        # Recherche du JSON dans le texte
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        json_matches = re.findall(json_pattern, text, re.DOTALL)
        
        if not json_matches:
            logger.warning("Aucun JSON trouvé dans la réponse")
            return create_fallback_response("Aucun JSON dans la réponse")
        
        # Essai de parsing du premier JSON trouvé
        for json_str in json_matches:
            try:
                parsed_json = json.loads(json_str.strip())
                
                # Validation des champs requis
                if all(key in parsed_json for key in ['decision', 'reason']):
                    # Ajout des champs manquants avec des valeurs par défaut
                    if 'confidence_score' not in parsed_json:
                        parsed_json['confidence_score'] = 75
                    if 'missing_documentation' not in parsed_json:
                        parsed_json['missing_documentation'] = []
                    if 'alternative_treatments' not in parsed_json:
                        parsed_json['alternative_treatments'] = []
                    if 'appeal_guidance' not in parsed_json:
                        parsed_json['appeal_guidance'] = ""
                    
                    logger.info(f"JSON valide extrait: {parsed_json}")
                    return parsed_json
                    
            except json.JSONDecodeError:
                continue
        
        logger.warning("Aucun JSON valide trouvé")
        return create_fallback_response("JSON invalide dans la réponse")
        
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction JSON: {e}")
        return create_fallback_response("Erreur d'extraction JSON")

def create_fallback_response(error_reason: str) -> Dict[str, Any]:
    """Crée une réponse de secours en cas d'erreur."""
    return {
        "decision": "PENDING",
        "reason": f"Révision manuelle requise - {error_reason}",
        "confidence_score": 0,
        "missing_documentation": ["Évaluation manuelle nécessaire"],
        "alternative_treatments": [],
        "appeal_guidance": "Contactez le service client pour une révision manuelle"
    }

def update_dynamodb_record(request_id: str, decision_data: Dict[str, Any]) -> None:
    """Met à jour l'enregistrement DynamoDB avec les résultats."""
    try:
        update_expression = """
        SET decision_status = :status, 
            decision_reason = :reason, 
            confidence_score = :score,
            processed_timestamp = :timestamp,
            missing_documentation = :missing_docs,
            alternative_treatments = :alternatives,
            appeal_guidance = :appeal
        """
        
        table.update_item(
            Key={'request_id': request_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues={
                ':status': decision_data.get('decision', 'UNKNOWN'),
                ':reason': decision_data.get('reason', 'Pas de justification fournie'),
                ':score': int(decision_data.get('confidence_score', 0)),
                ':timestamp': datetime.now().isoformat(),
                ':missing_docs': decision_data.get('missing_documentation', []),
                ':alternatives': decision_data.get('alternative_treatments', []),
                ':appeal': decision_data.get('appeal_guidance', '')
            }
        )
        logger.info(f"Enregistrement {request_id} mis à jour avec succès")
        
    except ClientError as e:
        logger.error(f"Erreur DynamoDB: {e}")
        raise

def lambda_handler(event, context):
    """Fonction Lambda principale avec gestion d'erreur complète."""
    start_time = datetime.now()
    
    try:
        # Validation de l'entrée
        request_id = event.get('request_id')
        if not request_id:
            logger.warning("request_id manquant dans l'événement")
            return {
                'statusCode': 400, 
                'body': json.dumps({'error': 'Champ "request_id" manquant'})
            }
        
        logger.info(f"Traitement de la demande: {request_id}")
        
        # 1. Récupération des données
        try:
            response = table.get_item(Key={'request_id': request_id})
            item = response.get('Item')
            
            if not item:
                logger.warning(f"Demande {request_id} introuvable")
                return {
                    'statusCode': 404, 
                    'body': json.dumps({'error': 'Demande introuvable dans DynamoDB'})
                }
        except ClientError as e:
            logger.error(f"Erreur lecture DynamoDB: {e}")
            return {
                'statusCode': 500, 
                'body': json.dumps({'error': 'Erreur d\'accès à la base de données'})
            }
        
        # 2. Validation et nettoyage des données
        data = validate_request_data(item)
        treatment_category = categorize_treatment(data['treatment'])
        rules = get_insurance_rules(data['insurance'], treatment_category)
        
        logger.info(f"Catégorie de traitement identifiée: {treatment_category}")
        logger.info(f"Règles appliquées: {rules}")
        
        # 3. Génération du prompt et appel IA
        prompt = create_titan_prompt(data, rules)
        decision_data = call_bedrock_api(prompt)
        
        # 4. Validation de la réponse
        required_fields = ['decision', 'reason']
        for field in required_fields:
            if field not in decision_data:
                logger.error(f"Champ manquant dans réponse IA: {field}")
                decision_data = create_fallback_response("Réponse IA incomplète")
                break
        
        # 5. Mise à jour de la base de données
        update_dynamodb_record(request_id, decision_data)
        
        # 6. Réponse finale
        processing_time = (datetime.now() - start_time).total_seconds()
        
        response_body = {
            **decision_data,
            'request_id': request_id,
            'processing_time_seconds': round(processing_time, 2),
            'treatment_category': treatment_category
        }
        
        logger.info(f"Demande {request_id} traitée avec succès en {processing_time:.2f}s")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body, ensure_ascii=False)
        }
        
    except ValueError as e:
        logger.error(f"Erreur de validation: {e}")
        return {
            'statusCode': 502, 
            'body': json.dumps({'error': str(e)})
        }
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Erreur AWS: {e}")
        return {
            'statusCode': 500, 
            'body': json.dumps({'error': 'Erreur des services AWS'})
        }
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}", exc_info=True)
        return {
            'statusCode': 500, 
            'body': json.dumps({'error': 'Erreur interne du serveur'})
        }