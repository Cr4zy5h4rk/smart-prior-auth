import json
import boto3
import base64
import uuid
from datetime import datetime
import logging
from decimal import Decimal
import re
import imghdr
import io

# Logging configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
textract_client = boto3.client('textract')
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

# Configuration
TABLE_NAME = 'prior-auth-requests'  # Aligned with Lambda 2
AI_LAMBDA_FUNCTION_NAME = 'DecisionEngine'
S3_BUCKET = 'your-textract-documents-bucket'  # Bucket pour stocker les documents temporairement

dynamodb_table = dynamodb.Table(TABLE_NAME)

class DecimalEncoder(json.JSONEncoder):
    """Encoder to handle DynamoDB Decimal types"""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

def lambda_handler(event, context):
    """
    Main Lambda function for processing prior authorization requests
    with integrated AI analysis
    """
    try:
        # Log the received event
        logger.info(f"Event received: {json.dumps(event, default=str)}")
        
        # Extract body from API Gateway
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            body = event
        
        # Validate required fields
        required_fields = ['patient_name', 'insurance_type', 'treatment_type']
        for field in required_fields:
            if field not in body:
                return create_response(400, f"Missing required field: {field}")
        
        # Generate unique ID
        request_id = f"req_{str(uuid.uuid4())}"
        logger.info(f"Processing request: {request_id}")
        
        # Document processing (if provided)
        document_data = process_document(body.get('document'), request_id)
        
        # Extract patient info
        patient_info = {
            'name': body['patient_name'],
            'age': body.get('age'),
            'insurance_type': body['insurance_type'],
            'member_id': body.get('member_id'),
            'medical_history': body.get('medical_history', [])
        }
        
        # Treatment analysis
        treatment_analysis = analyze_treatment_type(
            body['treatment_type'],
            body['insurance_type']
        )
        
        # Initial save to DynamoDB
        save_to_dynamodb(
            request_id=request_id,
            patient_info=patient_info,
            treatment_analysis=treatment_analysis,
            document_data=document_data,
            treatment_type=body['treatment_type'],
            status='processed'
        )
        
        # Prepare base response
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
        
        # Add document processing results to response
        if document_data:
            response_data['document_processing'] = {
                'status': document_data.get('processing_status', 'unknown'),
                'confidence': document_data.get('confidence', 0),
                'extracted_fields': document_data.get('extracted_fields', {})
            }
        
        # Trigger AI analysis
        try:
            logger.info(f"Triggering AI analysis for request: {request_id}")
            ai_response = invoke_ai_analysis_lambda(request_id)
            
            if ai_response.get('statusCode') == 200:
                ai_body = ai_response.get('body', '{}')
                if isinstance(ai_body, str):
                    ai_data = json.loads(ai_body)
                else:
                    ai_data = ai_body
                
                # Enrich response with AI results
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
                # AI failed but we continue with base analysis
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
            # Continue without AI - graceful fallback
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

def process_document(document_base64, request_id):
    """
    Processes medical documents with AWS Textract with enhanced format validation
    """
    if not document_base64:
        logger.info(f"No document provided for request: {request_id}")
        return None
        
    try:
        logger.info(f"Processing document for request: {request_id}")
        
        # Decode base64 document
        try:
            document_bytes = base64.b64decode(document_base64)
        except Exception as decode_error:
            logger.error(f"Base64 decode failed for {request_id}: {str(decode_error)}")
            return {
                'document_type': 'decode_failed',
                'error': f'Invalid base64 encoding: {str(decode_error)}',
                'processing_status': 'decode_failed'
            }
        
        # Validate document size (Textract limit: 10MB for synchronous)
        if len(document_bytes) > 10 * 1024 * 1024:
            logger.warning(f"Document too large for synchronous processing: {len(document_bytes)} bytes")
            return {
                'document_type': 'large_document',
                'error': 'Document exceeds 10MB limit for real-time processing',
                'processing_status': 'size_limit_exceeded'
            }
        
        # Validate document format
        format_validation = validate_document_format(document_bytes, request_id)
        if not format_validation['is_valid']:
            return {
                'document_type': 'unsupported_format',
                'error': format_validation['error'],
                'detected_format': format_validation.get('detected_format', 'unknown'),
                'processing_status': 'format_not_supported'
            }
        
        # Analyze document with Textract
        try:
            response = textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=['FORMS', 'TABLES']
            )
            
            logger.info(f"Textract analysis completed for {request_id}")
            
            # Extract medical information
            extracted_data = extract_medical_info(response)
            
            # Calculate confidence score
            confidence = calculate_confidence(response)
            
            return {
                'document_type': format_validation['detected_format'],
                'confidence': confidence,
                'extracted_fields': extracted_data,
                'processing_status': 'textract_processed',
                'textract_metadata': {
                    'blocks_count': len(response.get('Blocks', [])),
                    'pages': response.get('DocumentMetadata', {}).get('Pages', 1)
                }
            }
            
        except Exception as textract_error:
            error_message = str(textract_error)
            logger.error(f"Textract processing failed for {request_id}: {error_message}")
            
            # Provide specific error handling
            if "UnsupportedDocumentException" in error_message:
                return {
                    'document_type': 'unsupported_by_textract',
                    'error': 'Document format not supported by Textract. Please use PDF, JPEG, or PNG format.',
                    'processing_status': 'textract_format_error'
                }
            elif "InvalidParameterException" in error_message:
                return {
                    'document_type': 'invalid_document',
                    'error': 'Document appears to be corrupted or invalid',
                    'processing_status': 'textract_invalid_document'
                }
            else:
                return {
                    'document_type': 'processing_failed',
                    'error': error_message,
                    'processing_status': 'textract_failed'
                }
        
    except Exception as e:
        logger.error(f"Document processing failed for {request_id}: {str(e)}")
        return {
            'error': str(e),
            'processing_status': 'general_failure'
        }

def validate_document_format(document_bytes, request_id):
    """
    Validates if the document format is supported by Textract
    """
    try:
        # Create a BytesIO object for format detection
        doc_stream = io.BytesIO(document_bytes)
        
        # Check if it's an image format
        image_format = imghdr.what(doc_stream)
        if image_format:
            if image_format.lower() in ['jpeg', 'jpg', 'png']:
                logger.info(f"Detected supported image format: {image_format} for {request_id}")
                return {
                    'is_valid': True,
                    'detected_format': f'image_{image_format.lower()}',
                    'format_type': 'image'
                }
            else:
                return {
                    'is_valid': False,
                    'detected_format': f'image_{image_format.lower()}',
                    'error': f'Image format {image_format} not supported. Use JPEG or PNG.',
                    'format_type': 'image'
                }
        
        # Check if it's a PDF
        if document_bytes.startswith(b'%PDF'):
            logger.info(f"Detected PDF format for {request_id}")
            return {
                'is_valid': True,
                'detected_format': 'pdf',
                'format_type': 'pdf'
            }
        
        # Check for other common formats that are NOT supported
        format_signatures = {
            b'\x50\x4B\x03\x04': 'ZIP/Office document (DOCX, XLSX, etc.)',
            b'\xD0\xCF\x11\xE0': 'Microsoft Office (DOC, XLS, PPT)',
            b'GIF87a': 'GIF image',
            b'GIF89a': 'GIF image',
            b'\x89PNG': 'PNG image',  # Should be caught by imghdr
            b'\xFF\xD8\xFF': 'JPEG image',  # Should be caught by imghdr
            b'BM': 'BMP image',
            b'RIFF': 'RIFF container (could be WebP)',
            b'\x00\x00\x00\x20\x66\x74\x79\x70': 'HEIF/HEIC image'
        }
        
        detected_format = 'unknown'
        for signature, format_name in format_signatures.items():
            if document_bytes.startswith(signature):
                detected_format = format_name
                break
        
        # Try to detect text-based formats
        try:
            text_content = document_bytes.decode('utf-8')[:100]
            if text_content.strip().startswith('<?xml'):
                detected_format = 'XML document'
            elif text_content.strip().startswith('{') or text_content.strip().startswith('['):
                detected_format = 'JSON document'
            elif 'html' in text_content.lower():
                detected_format = 'HTML document'
        except:
            pass  # Not a text-based format
        
        return {
            'is_valid': False,
            'detected_format': detected_format,
            'error': f'Unsupported format: {detected_format}. Textract only supports PDF, JPEG, and PNG files.',
            'format_type': 'unsupported'
        }
        
    except Exception as e:
        logger.error(f"Format validation failed for {request_id}: {str(e)}")
        return {
            'is_valid': False,
            'detected_format': 'validation_error',
            'error': f'Could not validate document format: {str(e)}',
            'format_type': 'error'
        }

def get_format_conversion_suggestions(detected_format):
    """
    Provides suggestions for converting unsupported formats
    """
    suggestions = {
        'Microsoft Office (DOC, XLS, PPT)': [
            'Convert to PDF using Microsoft Office',
            'Use online converters like SmallPDF or ILovePDF',
            'Save as PDF from the original application'
        ],
        'ZIP/Office document (DOCX, XLSX, etc.)': [
            'Open in Microsoft Office and save as PDF',
            'Use Google Docs/Sheets to convert to PDF',
            'Use online DOCX to PDF converters'
        ],
        'GIF image': [
            'Convert to PNG using image editing software',
            'Use online image converters',
            'Save as JPEG (if photo) or PNG (if diagram/text)'
        ],
        'BMP image': [
            'Convert to PNG or JPEG using image editing software',
            'Use online image converters'
        ],
        'HTML document': [
            'Print to PDF from web browser',
            'Use browser\'s "Save as PDF" function',
            'Convert using online HTML to PDF converters'
        ]
    }
    
    return suggestions.get(detected_format, [
        'Convert document to PDF format',
        'If it\'s an image, save as JPEG or PNG',
        'Use online document converters'
    ])

# Amélioration de la fonction principale pour inclure les suggestions
def process_document_with_suggestions(document_base64, request_id):
    """
    Version améliorée avec suggestions de conversion
    """
    result = process_document(document_base64, request_id)
    
    # Ajouter des suggestions si le format n'est pas supporté
    if result and result.get('processing_status') in ['format_not_supported', 'textract_format_error']:
        detected_format = result.get('detected_format', 'unknown')
        suggestions = get_format_conversion_suggestions(detected_format)
        result['conversion_suggestions'] = suggestions
        
        # Message utilisateur amélioré
        result['user_message'] = f"Le format de document détecté ({detected_format}) n'est pas supporté par Textract. Veuillez convertir votre document en PDF, JPEG ou PNG."
    
    return result

def extract_medical_info(textract_response):
    """
    Extracts relevant medical information from Textract response
    """
    extracted_fields = {}
    
    try:
        blocks = textract_response.get('Blocks', [])
        
        # Extract text blocks
        text_blocks = []
        for block in blocks:
            if block['BlockType'] == 'LINE':
                text_blocks.append(block.get('Text', ''))
        
        # Join all text for pattern matching
        full_text = ' '.join(text_blocks).upper()
        
        # Extract medication information
        medication_patterns = [
            r'(OZEMPIC|SEMAGLUTIDE|METFORMIN|INSULIN|HUMIRA|ADALIMUMAB)',
            r'MEDICATION[:\s]+([\w\s]+)',
            r'DRUG[:\s]+([\w\s]+)'
        ]
        
        for pattern in medication_patterns:
            match = re.search(pattern, full_text)
            if match:
                extracted_fields['medication'] = match.group(1).strip()
                break
        
        # Extract dosage information
        dosage_patterns = [
            r'(\d+\.?\d*\s*(MG|ML|UNITS?)\s*(DAILY|WEEKLY|MONTHLY|BID|TID|QID))',
            r'DOSE[:\s]+(\d+\.?\d*\s*\w+)',
            r'DOSAGE[:\s]+(\d+\.?\d*\s*\w+)'
        ]
        
        for pattern in dosage_patterns:
            match = re.search(pattern, full_text)
            if match:
                extracted_fields['dosage'] = match.group(1).strip()
                break
        
        # Extract prescriber information
        prescriber_patterns = [
            r'DR\.?\s+([A-Z][A-Z\s]+[A-Z])',
            r'PHYSICIAN[:\s]+([A-Z][A-Z\s]+)',
            r'PRESCRIBER[:\s]+([A-Z][A-Z\s]+)'
        ]
        
        for pattern in prescriber_patterns:
            match = re.search(pattern, full_text)
            if match:
                extracted_fields['prescriber'] = match.group(1).strip()
                break
        
        # Extract ICD codes
        icd_patterns = [
            r'([A-Z]\d{2}\.?\d*)',  # ICD-10 format
            r'ICD[:\s-]*(\w\d{2}\.?\d*)'
        ]
        
        icd_codes = []
        for pattern in icd_patterns:
            matches = re.findall(pattern, full_text)
            for match in matches:
                if isinstance(match, tuple):
                    code = match[0]
                else:
                    code = match
                if len(code) >= 3 and code not in icd_codes:
                    icd_codes.append(code)
        
        if icd_codes:
            extracted_fields['codes'] = icd_codes
        
        # Extract dates
        date_patterns = [
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{1,2},?\s+\d{4}'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, full_text)
            if match:
                extracted_fields['date'] = match.group(1).strip()
                break
        
        # Extract form fields (key-value pairs)
        form_fields = extract_form_fields(blocks)
        extracted_fields.update(form_fields)
        
        logger.info(f"Extracted fields: {extracted_fields}")
        
    except Exception as e:
        logger.error(f"Error extracting medical info: {str(e)}")
        extracted_fields['extraction_error'] = str(e)
    
    return extracted_fields

def extract_form_fields(blocks):
    """
    Extracts form fields from Textract blocks
    """
    form_fields = {}
    
    try:
        # Create maps for efficient lookup
        key_map = {}
        value_map = {}
        block_map = {}
        
        for block in blocks:
            block_id = block['Id']
            block_map[block_id] = block
            
            if block['BlockType'] == 'KEY_VALUE_SET':
                if 'KEY' in block['EntityTypes']:
                    key_map[block_id] = block
                else:
                    value_map[block_id] = block
        
        # Extract key-value relationships
        for key_block_id, key_block in key_map.items():
            value_block = get_value_block(key_block, value_map)
            if value_block:
                key_text = get_text_from_block(key_block, block_map)
                value_text = get_text_from_block(value_block, block_map)
                
                if key_text and value_text:
                    # Clean and normalize key
                    clean_key = key_text.strip().replace(':', '').lower()
                    form_fields[clean_key] = value_text.strip()
        
    except Exception as e:
        logger.error(f"Error extracting form fields: {str(e)}")
    
    return form_fields

def get_value_block(key_block, value_map):
    """
    Gets the value block associated with a key block
    """
    for relationship in key_block.get('Relationships', []):
        if relationship['Type'] == 'VALUE':
            for value_id in relationship['Ids']:
                if value_id in value_map:
                    return value_map[value_id]
    return None

def get_text_from_block(block, block_map):
    """
    Extracts text from a block using child relationships
    """
    text = ""
    
    if 'Relationships' in block:
        for relationship in block['Relationships']:
            if relationship['Type'] == 'CHILD':
                for child_id in relationship['Ids']:
                    child_block = block_map.get(child_id)
                    if child_block and child_block['BlockType'] == 'WORD':
                        text += child_block.get('Text', '') + ' '
    
    return text.strip()

def calculate_confidence(textract_response):
    """
    Calculates overall confidence score from Textract response
    """
    try:
        blocks = textract_response.get('Blocks', [])
        
        if not blocks:
            return 0.0
        
        total_confidence = 0
        block_count = 0
        
        for block in blocks:
            if 'Confidence' in block:
                total_confidence += block['Confidence']
                block_count += 1
        
        if block_count == 0:
            return 0.0
        
        average_confidence = total_confidence / block_count
        return round(average_confidence / 100, 3)  # Convert to 0-1 scale
        
    except Exception as e:
        logger.error(f"Error calculating confidence: {str(e)}")
        return 0.0

def invoke_ai_analysis_lambda(request_id):
    """
    Invokes the AI analysis Lambda synchronously
    """
    try:
        payload = {
            'request_id': request_id
        }
        
        logger.info(f"Invoking AI Lambda with payload: {payload}")
        
        response = lambda_client.invoke(
            FunctionName=AI_LAMBDA_FUNCTION_NAME,
            InvocationType='RequestResponse',  # Synchronous
            Payload=json.dumps(payload)
        )
        
        # Read response
        response_payload = response['Payload'].read().decode('utf-8')
        logger.info(f"AI Lambda response payload: {response_payload}")
        
        return json.loads(response_payload)
        
    except Exception as e:
        logger.error(f"AI Lambda invocation failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500, 
            'body': json.dumps({"error": f"AI analysis failed: {str(e)}"})
        }

def analyze_treatment_type(treatment, insurance):
    """
    Analyzes approval probability based on business rules
    """
    logger.info(f"Analyzing treatment: {treatment} for insurance: {insurance}")
    
    # Enhanced business rules database
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
    
    # Get specific rules
    insurance_rules = rules.get(insurance, {})
    treatment_rules = insurance_rules.get(treatment, {
        'probability': 0.65,
        'requirements': ['Standard prior authorization required', 'Complete medical documentation'],
        'time': '7-10 business days',
        'category': 'general'
    })
    
    # Convert to Decimal for DynamoDB
    prob = Decimal(str(treatment_rules['probability']))
    
    # Determine next steps based on probability
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
    Structured save to DynamoDB with format compatible with AI Lambda
    """
    try:
        logger.info(f"Saving to DynamoDB: {request_id}")
        
        # Structure compatible with AI Lambda
        item = {
            'request_id': request_id,
            'patient_info': f"{patient_info['name']}, Age: {patient_info.get('age', 'Unknown')}, Insurance: {patient_info['insurance_type']}",
            'treatment': treatment_type,
            'insurance': patient_info['insurance_type'],
            'history': format_medical_history(patient_info.get('medical_history', [])),
            'urgency': 'Standard',  # Can be parameterized
            'provider_notes': format_document_data(document_data),
            
            # Enriched data
            'treatment_analysis': treatment_analysis,
            'document_data': document_data or {},
            'status': status,
            'created_at': datetime.now().isoformat(),
            'ttl': int(datetime.now().timestamp()) + 2592000,  # 30 days
            
            # Metadata
            'processing_metadata': {
                'lambda_version': '2.0',
                'processing_stage': 'textract_processed',
                'ai_pending': True,
                'document_processed': document_data is not None
            }
        }

        # Convert floats to Decimal for DynamoDB
        item = convert_floats_to_decimals(item)

        # Save
        dynamodb_table.put_item(Item=item)
        logger.info(f"Successfully saved to DynamoDB: {request_id}")

    except Exception as e:
        logger.error(f"DynamoDB save failed for {request_id}: {str(e)}", exc_info=True)
        raise

def format_medical_history(medical_history):
    """Formats medical history for AI"""
    if not medical_history:
        return "No medical history provided"
    
    if isinstance(medical_history, list):
        return "; ".join(str(item) for item in medical_history)
    
    return str(medical_history)

def format_document_data(document_data):
    """Formats document data for AI with real Textract results"""
    if not document_data:
        return "No additional documentation provided"
    
    if document_data.get('processing_status') == 'textract_failed':
        return f"Document processing failed: {document_data.get('error', 'Unknown error')}"
    
    if document_data.get('processing_status') != 'textract_processed':
        return f"Document processing incomplete: {document_data.get('processing_status', 'Unknown status')}"
    
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
            codes = extracted['codes']
            if isinstance(codes, list):
                notes.append(f"ICD Codes: {', '.join(codes)}")
            else:
                notes.append(f"ICD Code: {codes}")
        if 'date' in extracted:
            notes.append(f"Date: {extracted['date']}")
        
        # Add confidence information
        confidence = document_data.get('confidence', 0)
        notes.append(f"Document confidence: {confidence:.1%}")
        
        return "; ".join(notes) if notes else "Document processed but no specific medical details extracted"
    
    return str(document_data)

def convert_floats_to_decimals(obj):
    """Recursively converts floats to Decimal for DynamoDB"""
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
    Generates a standardized API response
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