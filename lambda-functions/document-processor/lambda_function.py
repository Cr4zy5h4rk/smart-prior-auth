import json
import boto3
import base64
import uuid
from datetime import datetime
import logging

# Configuration du logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clients AWS
textract_client = boto3.client('textract')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Nom de la table DynamoDB (à créer)
TABLE_NAME = 'prior-auth-requests'

def lambda_handler(event, context):
    """
    Fonction Lambda pour traiter les documents de demande d'autorisation
    Trigger: API Gateway POST /process-document
    """
    
    try:
        # Logging de l'événement reçu
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extraction des données de la requête
        body = json.loads(event.get('body', '{}'))
        
        # Validation des données requises
        required_fields = ['patient_name', 'insurance_type', 'treatment_type']
        for field in required_fields:
            if field not in body:
                return create_response(400, f"Missing required field: {field}")
        
        # Génération d'un ID unique pour la demande
        request_id = str(uuid.uuid4())
        
        # Traitement du document si fourni
        document_data = None
        if 'document' in body:
            document_data = process_document(body['document'], request_id)
        
        # Extraction des informations du patient
        patient_info = extract_patient_info(body)
        
        # Analyse du type de traitement
        treatment_analysis = analyze_treatment_type(body['treatment_type'], body['insurance_type'])
        
        # Sauvegarde en DynamoDB
        save_to_dynamodb(request_id, patient_info, treatment_analysis, document_data)
        
        # Réponse de succès
        response_data = {
            'request_id': request_id,
            'status': 'processed',
            'patient_name': patient_info['name'],
            'treatment_type': body['treatment_type'],
            'estimated_approval_chance': treatment_analysis['approval_probability'],
            'processing_time': datetime.now().isoformat(),
            'next_steps': treatment_analysis['next_steps']
        }
        
        logger.info(f"Successfully processed request {request_id}")
        return create_response(200, response_data)
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return create_response(500, {"error": "Internal server error", "details": str(e)})

def process_document(document_base64, request_id):
    """
    Traite un document uploadé avec AWS Textract
    """
    try:
        # Décodage du document base64
        document_bytes = base64.b64decode(document_base64)
        
        # Pour la demo, on simule Textract avec des données prédéfinies
        # En production, vous utiliseriez textract_client.analyze_document()
        
        # Simulation d'extraction Textract
        extracted_data = {
            'document_type': 'prescription',
            'confidence': 0.95,
            'extracted_fields': {
                'medication_name': 'Ozempic',
                'dosage': '0.5mg weekly',
                'prescriber': 'Dr. Smith',
                'date': '2025-06-10',
                'icd_codes': ['E11.9']  # Diabetes Type 2
            }
        }
        
        logger.info(f"Document processed for request {request_id}")
        return extracted_data
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        return None

def extract_patient_info(body):
    """
    Extrait et structure les informations du patient
    """
    return {
        'name': body['patient_name'],
        'age': body.get('age', 'Not specified'),
        'insurance_type': body['insurance_type'],
        'member_id': body.get('member_id', 'Not provided'),
        'medical_history': body.get('medical_history', [])
    }

def analyze_treatment_type(treatment_type, insurance_type):
    """
    Analyse le type de traitement et prédit les chances d'approbation
    Basé sur des règles métier simplifiées
    """
    
    # Base de données simplifiée des critères d'assurance
    insurance_criteria = {
        'BlueCross': {
            'Ozempic': {
                'approval_probability': 0.85,
                'requirements': ['Prior diabetes medications tried', 'HbA1c > 7%'],
                'typical_approval_time': '48-72 hours'
            },
            'MRI': {
                'approval_probability': 0.70,
                'requirements': ['6 weeks conservative treatment', 'Failed physical therapy'],
                'typical_approval_time': '3-5 days'
            }
        },
        'Aetna': {
            'Ozempic': {
                'approval_probability': 0.78,
                'requirements': ['2 prior medications failed', 'BMI criteria'],
                'typical_approval_time': '5-7 days'
            }
        },
        'UnitedHealth': {
            'Ozempic': {
                'approval_probability': 0.82,
                'requirements': ['Metformin trial', 'A1C documentation'],
                'typical_approval_time': '2-4 days'
            }
        }
    }
    
    # Récupération des critères pour cette combinaison
    criteria = insurance_criteria.get(insurance_type, {}).get(treatment_type, {
        'approval_probability': 0.65,  # Probabilité par défaut
        'requirements': ['Standard prior authorization requirements'],
        'typical_approval_time': '5-10 days'
    })
    
    # Détermination des prochaines étapes
    next_steps = []
    if criteria['approval_probability'] > 0.8:
        next_steps.append("High approval probability - submit immediately")
    elif criteria['approval_probability'] > 0.6:
        next_steps.append("Moderate approval probability - review requirements")
        next_steps.append("Consider additional documentation")
    else:
        next_steps.append("Low approval probability - review case carefully")
        next_steps.append("Consider alternative treatments")
    
    return {
        'approval_probability': criteria['approval_probability'],
        'requirements': criteria['requirements'],
        'typical_approval_time': criteria['typical_approval_time'],
        'next_steps': next_steps
    }

def save_to_dynamodb(request_id, patient_info, treatment_analysis, document_data):
    """
    Sauvegarde les données dans DynamoDB
    """
    try:
        table = dynamodb.Table(TABLE_NAME)
        
        item = {
            'request_id': request_id,
            'timestamp': datetime.now().isoformat(),
            'patient_info': patient_info,
            'treatment_analysis': treatment_analysis,
            'document_data': document_data,
            'status': 'analyzed',
            'created_at': int(datetime.now().timestamp())
        }
        
        table.put_item(Item=item)
        logger.info(f"Data saved to DynamoDB for request {request_id}")
        
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {str(e)}")
        raise

def create_response(status_code, body):
    """
    Crée une réponse HTTP formatée pour API Gateway
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        },
        'body': json.dumps(body, default=str)
    }