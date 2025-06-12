import json
import boto3
import base64
import uuid
from datetime import datetime
import logging
from decimal import Decimal

# Configuration du logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clients AWS
textract_client = boto3.client('textract')
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

# Configuration
TABLE_NAME = 'prior-auth-requests'  # Harmonisé avec Lambda 2AI_LAMBDA_FUNCTION_NAME = 'prior-auth-ai-analyzer'  # Nom de votre Lambda IA
AI_LAMBDA_FUNCTION_NAME = 'DecisionEngine'

dynamodb_table = dynamodb.Table(TABLE_NAME)

class DecimalEncoder(json.JSONEncoder):
    """Encoder pour gérer les Decimal de DynamoDB"""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

def lambda_handler(event, context):
    """
    Fonction principale Lambda pour le traitement des demandes d'autorisation
    avec analyse IA intégrée
    """
    try:
        # Log de l'événement reçu
        logger.info(f"Event received: {json.dumps(event, default=str)}")
        
        # Extraction du body depuis API Gateway
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            body = event
        
        # Validation des champs requis
        required_fields = ['patient_name', 'insurance_type', 'treatment_type']
        for field in required_fields:
            if field not in body:
                return create_response(400, f"Missing required field: {field}")
        
        # Génération ID unique
        request_id = f"req_{str(uuid.uuid4())}"
        logger.info(f"Processing request: {request_id}")
        
        # Traitement du document (si fourni)
        document_data = process_document(body.get('document'), request_id)
        
        # Extraction infos patient
        patient_info = {
            'name': body['patient_name'],
            'age': body.get('age'),
            'insurance_type': body['insurance_type'],
            'member_id': body.get('member_id'),
            'medical_history': body.get('medical_history', [])
        }
        
        # Analyse du traitement
        treatment_analysis = analyze_treatment_type(
            body['treatment_type'],
            body['insurance_type']
        )
        
        # Sauvegarde initiale en DynamoDB
        save_to_dynamodb(
            request_id=request_id,
            patient_info=patient_info,
            treatment_analysis=treatment_analysis,
            document_data=document_data,
            treatment_type=body['treatment_type'],
            status='processed'
        )
        
        # Préparation de la réponse de base
        response_data = {
            'request_id': request_id,
            'status': 'success',
            'patient': patient_info['name'],
            'treatment': body['treatment_type'],
            'insurance': body['insurance_type'],
            'approval_probability': float(treatment_analysis['approval_probability']),
            'next_steps': treatment_analysis['next_steps'],
            'timestamp': datetime.now().isoformat()
        }
        
        # Déclencher l'analyse IA
        try:
            logger.info(f"Triggering AI analysis for request: {request_id}")
            ai_response = invoke_ai_analysis_lambda(request_id)
            
            if ai_response.get('statusCode') == 200:
                ai_body = ai_response.get('body', '{}')
                if isinstance(ai_body, str):
                    ai_data = json.loads(ai_body)
                else:
                    ai_data = ai_body
                
                # Enrichissement de la réponse avec les résultats IA
                response_data.update({
                    'ai_analysis': {
                        'decision': ai_data.get('decision', 'UNKNOWN'),
                        'confidence_score': ai_data.get('confidence_score', 0),
                        'reason': ai_data.get('reason', 'No reason provided'),
                        'missing_documentation': ai_data.get('missing_documentation', []),
                        'alternative_treatments': ai_data.get('alternative_treatments', []),
                        'appeal_guidance': ai_data.get('appeal_guidance', '')
                    },
                    'processing_status': 'ai_analysis_completed'
                })
                
                logger.info(f"AI analysis completed for {request_id}: {ai_data.get('decision')}")
                
            else:
                # IA a échoué mais on continue avec l'analyse de base
                response_data.update({
                    'ai_analysis': {
                        'decision': 'AI_ERROR',
                        'reason': 'AI analysis failed, using rule-based analysis only'
                    },
                    'processing_status': 'ai_analysis_failed'
                })
                logger.warning(f"AI analysis failed for {request_id}")
                
        except Exception as ai_error:
            logger.error(f"AI analysis error for {request_id}: {str(ai_error)}")
            # On continue sans l'IA - fallback gracieux
            response_data.update({
                'ai_analysis': {
                    'decision': 'AI_ERROR',
                    'reason': f'AI analysis unavailable: {str(ai_error)}'
                },
                'processing_status': 'ai_analysis_error'
            })
        
        return create_response(200, response_data)
        
    except Exception as e:
        logger.error(f"Error in main handler: {str(e)}", exc_info=True)
        return create_response(500, {"error": "Internal server error", "details": str(e)})

def invoke_ai_analysis_lambda(request_id):
    """
    Invoque la Lambda d'analyse IA de façon synchrone
    """
    try:
        payload = {
            'request_id': request_id
        }
        
        logger.info(f"Invoking AI Lambda with payload: {payload}")
        
        response = lambda_client.invoke(
            FunctionName=AI_LAMBDA_FUNCTION_NAME,
            InvocationType='RequestResponse',  # Synchrone
            Payload=json.dumps(payload)
        )
        
        # Lecture de la réponse
        response_payload = response['Payload'].read().decode('utf-8')
        logger.info(f"AI Lambda response payload: {response_payload}")
        
        return json.loads(response_payload)
        
    except Exception as e:
        logger.error(f"AI Lambda invocation failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500, 
            'body': json.dumps({"error": f"AI analysis failed: {str(e)}"})
        }

def process_document(document_base64, request_id):
    """
    Traite les documents médicaux avec Textract
    """
    if not document_base64:
        return None
        
    try:
        logger.info(f"Processing document for request: {request_id}")
        
        # Simulation pour la démo (remplacer par Textract en production)
        simulated_data = {
            'document_type': 'prescription',
            'confidence': 0.95,
            'extracted_fields': {
                'medication': 'Ozempic',
                'dosage': '0.5mg weekly', 
                'prescriber': 'Dr. Smith',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'codes': ['E11.9']  # ICD-10 for Diabetes
            },
            'processing_status': 'simulated'
        }
        
        # Code pour production avec Textract:
        """
        try:
            # Décoder le document base64
            document_bytes = base64.b64decode(document_base64)
            
            # Analyser avec Textract
            response = textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=['FORMS', 'TABLES']
            )
            
            # Extraire les données pertinentes
            extracted_data = extract_medical_info(response)
            
            return {
                'document_type': 'medical_document',
                'confidence': calculate_confidence(response),
                'extracted_fields': extracted_data,
                'processing_status': 'textract_processed'
            }
            
        except Exception as textract_error:
            logger.error(f"Textract processing failed: {textract_error}")
            return {
                'document_type': 'unknown',
                'error': str(textract_error),
                'processing_status': 'textract_failed'
            }
        """
        
        return simulated_data
        
    except Exception as e:
        logger.error(f"Document processing failed: {str(e)}")
        return {
            'error': str(e),
            'processing_status': 'failed'
        }

def analyze_treatment_type(treatment, insurance):
    """
    Analyse la probabilité d'approbation basée sur les règles métier
    """
    logger.info(f"Analyzing treatment: {treatment} for insurance: {insurance}")
    
    # Base de règles métier enrichie
    rules = {
        'BlueCross': {
            'Ozempic': {
                'probability': 0.85,
                'requirements': ['Prior metformin use documented', 'HbA1c > 7%', 'BMI documentation'],
                'time': '2-3 business days',
                'category': 'diabetes'
            },
            'MRI': {
                'probability': 0.70,
                'requirements': ['6 weeks physical therapy documented', 'X-ray results', 'Pain scale documentation'],
                'time': '5-7 business days',
                'category': 'imaging'
            },
            'Humira': {
                'probability': 0.75,
                'requirements': ['Failed MTX therapy', 'Rheumatologist referral', 'Inflammatory markers'],
                'time': '7-10 business days',
                'category': 'specialty_drugs'
            }
        },
        'Aetna': {
            'Ozempic': {
                'probability': 0.78,
                'requirements': ['BMI > 30 documented', '2+ diabetes medications tried', 'Endocrinologist notes'],
                'time': '3-5 business days',
                'category': 'diabetes'
            },
            'Physical Therapy': {
                'probability': 0.90,
                'requirements': ['Physician referral', 'Diagnosis code', 'Treatment plan'],
                'time': '1-2 business days',
                'category': 'physical_therapy'
            }
        },
        'UnitedHealthcare': {
            'Ozempic': {
                'probability': 0.80,
                'requirements': ['Step therapy completed', 'Clinical documentation', 'Prior authorization form'],
                'time': '4-6 business days',
                'category': 'diabetes'
            }
        },
        'Cigna': {
            'MRI': {
                'probability': 0.65,
                'requirements': ['Conservative treatment failure', 'Imaging necessity justification'],
                'time': '5-7 business days',
                'category': 'imaging'
            }
        }
    }
    
    # Récupération des règles spécifiques
    insurance_rules = rules.get(insurance, {})
    treatment_rules = insurance_rules.get(treatment, {
        'probability': 0.65,
        'requirements': ['Standard prior authorization required', 'Complete medical documentation'],
        'time': '7-10 business days',
        'category': 'general'
    })
    
    # Conversion en Decimal pour DynamoDB
    prob = Decimal(str(treatment_rules['probability']))
    
    # Détermination des next steps basée sur la probabilité
    if prob >= Decimal('0.8'):
        next_steps = [
            "High approval probability - submit immediately",
            "Ensure all documentation is complete",
            "Expected approval within " + treatment_rules['time']
        ]
        recommendation = "SUBMIT_NOW"
    elif prob >= Decimal('0.6'):
        next_steps = [
            "Moderate approval chance - review requirements carefully", 
            "Consider gathering additional supporting documentation",
            "Review alternatives if denied"
        ]
        recommendation = "REVIEW_REQUIREMENTS"
    else:
        next_steps = [
            "Low approval probability - consider alternatives first",
            "Gather comprehensive supporting documentation",
            "Consult with medical team for strategy"
        ]
        recommendation = "CONSIDER_ALTERNATIVES"
    
    return {
        'approval_probability': prob,
        'requirements': treatment_rules['requirements'],
        'approval_time': treatment_rules['time'],
        'treatment_category': treatment_rules['category'],
        'next_steps': next_steps,
        'recommendation': recommendation,
        'analysis_timestamp': datetime.now().isoformat()
    }

def save_to_dynamodb(request_id, patient_info, treatment_analysis, document_data, treatment_type, status):
    """
    Sauvegarde structurée en DynamoDB avec format compatible Lambda IA
    """
    try:
        logger.info(f"Saving to DynamoDB: {request_id}")
        
        # Structure compatible avec Lambda IA
        item = {
            'request_id': request_id,
            'patient_info': f"{patient_info['name']}, Age: {patient_info.get('age', 'Unknown')}, Insurance: {patient_info['insurance_type']}",
            'treatment': treatment_type,
            'insurance': patient_info['insurance_type'],
            'history': format_medical_history(patient_info.get('medical_history', [])),
            'urgency': 'Standard',  # Peut être paramétré
            'provider_notes': format_document_data(document_data),
            
            # Données enrichies
            'treatment_analysis': treatment_analysis,
            'document_data': document_data or {},
            'status': status,
            'created_at': datetime.now().isoformat(),
            'ttl': int(datetime.now().timestamp()) + 2592000,  # 30 jours
            
            # Métadonnées
            'processing_metadata': {
                'lambda_version': '1.0',
                'processing_stage': 'initial_analysis',
                'ai_pending': True
            }
        }

        # Conversion des floats en Decimal pour DynamoDB
        item = convert_floats_to_decimals(item)

        # Sauvegarde
        dynamodb_table.put_item(Item=item)
        logger.info(f"Successfully saved to DynamoDB: {request_id}")

    except Exception as e:
        logger.error(f"DynamoDB save failed for {request_id}: {str(e)}", exc_info=True)
        raise

def format_medical_history(medical_history):
    """Formate l'historique médical pour l'IA"""
    if not medical_history:
        return "No medical history provided"
    
    if isinstance(medical_history, list):
        return "; ".join(str(item) for item in medical_history)
    
    return str(medical_history)

def format_document_data(document_data):
    """Formate les données du document pour l'IA"""
    if not document_data:
        return "No additional documentation provided"
    
    if isinstance(document_data, dict):
        extracted = document_data.get('extracted_fields', {})
        notes = []
        
        if 'medication' in extracted:
            notes.append(f"Medication: {extracted['medication']}")
        if 'dosage' in extracted:
            notes.append(f"Dosage: {extracted['dosage']}")
        if 'prescriber' in extracted:
            notes.append(f"Prescriber: {extracted['prescriber']}")
        if 'codes' in extracted:
            notes.append(f"ICD Codes: {', '.join(extracted['codes'])}")
            
        return "; ".join(notes) if notes else "Document processed but no specific details extracted"
    
    return str(document_data)

def convert_floats_to_decimals(obj):
    """Convertit récursivement les floats en Decimal pour DynamoDB"""
    if isinstance(obj, list):
        return [convert_floats_to_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj

def create_response(status_code, body):
    """
    Génère une réponse API standardisée
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body, cls=DecimalEncoder, default=str, ensure_ascii=False)
    }