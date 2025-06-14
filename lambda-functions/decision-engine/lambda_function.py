import json
import boto3
from botocore.exceptions import ClientError, BotoCoreError
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import re

# Logger configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients with error handling
try:
    dynamodb = boto3.resource('dynamodb')
    bedrock = boto3.client('bedrock-runtime')
    table = dynamodb.Table('prior-auth-requests')
except Exception as e:
    logger.error(f"AWS initialization error: {e}")
    raise

# Enhanced and structured insurance rules with specific criteria
INSURANCE_RULES = {
    "BlueCross": {
        "diabetes": {
            "criteria": "Requires HbA1c > 8% and failure of 2 prior treatments (metformin + sulfonylurea)",
            "required_docs": ["HbA1c test results", "Prior treatment history", "Physician notes"],
            "typical_denial_reasons": ["Insufficient trial duration", "Missing lab results", "Alternative treatments not tried"],
            "minimum_requirements": ["hba1c_test", "prior_treatments_2"]
        },
        "mri": {
            "criteria": "MRI requires failure of conservative treatment for 6 weeks and pain score > 7/10",
            "required_docs": ["Physical therapy records", "Pain assessment", "X-ray results"],
            "typical_denial_reasons": ["Conservative treatment not attempted", "Insufficient duration", "Pain score too low"],
            "minimum_requirements": ["conservative_treatment_6weeks", "pain_score_7", "x_ray_performed"]
        },
        "imaging": {
            "criteria": "Advanced imaging requires 6 weeks conservative treatment and standard imaging failure",
            "required_docs": ["Conservative treatment records", "Standard imaging results", "Clinical rationale"],
            "typical_denial_reasons": ["Conservative treatment not attempted", "Standard imaging not performed"],
            "minimum_requirements": ["conservative_treatment_6weeks", "standard_imaging_done"]
        },
        "general": {
            "criteria": "Evaluation based on documented medical necessity and exhausted lower-cost alternatives",
            "required_docs": ["Medical records", "Treatment history", "Physician justification"],
            "typical_denial_reasons": ["Insufficient medical necessity", "Alternative treatments available"],
            "minimum_requirements": ["medical_necessity", "alternatives_tried"]
        }
    },
    "UnitedHealthcare": {
        "imaging": {
            "criteria": "Advanced imaging requires diagnostic failure with standard methods and 8 weeks conservative treatment",
            "required_docs": ["Previous imaging results", "Clinical examination", "Conservative treatment records"],
            "typical_denial_reasons": ["Standard imaging not performed", "Insufficient clinical indication", "Conservative treatment not attempted"],
            "minimum_requirements": ["standard_imaging_done", "conservative_treatment_8weeks", "clinical_indication"]
        },
        "mri": {
            "criteria": "MRI requires 8 weeks conservative treatment, standard imaging failure, and pain score > 6/10",
            "required_docs": ["X-ray results", "Physical therapy records", "Pain assessment", "Conservative treatment documentation"],
            "typical_denial_reasons": ["X-ray not performed", "Physical therapy not attempted", "Insufficient conservative treatment duration"],
            "minimum_requirements": ["x_ray_performed", "physical_therapy_attempted", "conservative_treatment_8weeks", "pain_score_6"]
        },
        "cancer_treatment": {
            "criteria": "Oncology treatments require histological confirmation and complete staging",
            "required_docs": ["Pathology report", "Staging studies", "Oncology consultation"],
            "typical_denial_reasons": ["Missing pathology confirmation", "Incomplete staging", "Treatment not standard of care"],
            "minimum_requirements": ["pathology_confirmed", "staging_complete", "oncology_consult"]
        },
        "mental_health": {
            "criteria": "Intensive therapies require psychiatric evaluation and failure of standard therapy",
            "required_docs": ["Psychiatric evaluation", "Previous therapy records", "Treatment plan"],
            "typical_denial_reasons": ["No psychiatric evaluation", "Standard therapy not tried", "Insufficient severity"],
            "minimum_requirements": ["psychiatric_eval", "standard_therapy_tried"]
        },
        "general": {
            "criteria": "Multifactorial evaluation including cost-effectiveness and clinical outcomes",
            "required_docs": ["Clinical evidence", "Cost-benefit analysis", "Outcome measures"],
            "typical_denial_reasons": ["Cost-effectiveness not demonstrated", "Insufficient clinical evidence"],
            "minimum_requirements": ["clinical_evidence", "cost_effectiveness"]
        }
    },
    "Aetna": {
        "physical_therapy": {
            "criteria": "Requires 6 weeks of documented physical therapy with progress notes",
            "required_docs": ["PT evaluation", "Progress notes", "Treatment plan"],
            "typical_denial_reasons": ["Insufficient PT duration", "Lack of progress documentation"],
            "minimum_requirements": ["pt_evaluation", "progress_notes", "treatment_plan"]
        },
        "surgery": {
            "criteria": "Surgery requires 12 weeks of documented conservative treatment and second medical opinion",
            "required_docs": ["Conservative treatment records", "Second opinion", "Surgical consultation"],
            "typical_denial_reasons": ["Conservative treatment duration insufficient", "No second opinion", "Surgery not medically necessary"],
            "minimum_requirements": ["conservative_treatment_12weeks", "second_opinion", "surgical_consult"]
        },
        "imaging": {
            "criteria": "Advanced imaging requires diagnostic failure with standard methods",
            "required_docs": ["Previous imaging results", "Clinical examination", "Diagnostic rationale"],
            "typical_denial_reasons": ["Standard imaging not performed", "Insufficient clinical indication"],
            "minimum_requirements": ["standard_imaging_done", "clinical_indication"]
        },
        "general": {
            "criteria": "Approval based on established clinical guidelines and complete documentation",
            "required_docs": ["Clinical documentation", "Guideline compliance", "Medical necessity"],
            "typical_denial_reasons": ["Incomplete documentation", "Not meeting clinical guidelines"],
            "minimum_requirements": ["clinical_documentation", "guideline_compliance"]
        }
    }
}

# Configuration for Amazon Titan Text Express
BEDROCK_CONFIG = {
    "model_id": "amazon.titan-text-express-v1",
    "max_tokens": 512,
    "temperature": 0.1,  # Reduced for more consistent decisions
    "top_p": 0.8
}

def get_insurance_rules(insurance: str, treatment_category: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves specific or general insurance rules with detailed criteria."""
    insurance_mapping = {
        "bcbs": "BlueCross",
        "bluecross": "BlueCross",
        "blue cross": "BlueCross",
        "aetna": "Aetna",
        "united": "UnitedHealthcare",
        "unitedhealthcare": "UnitedHealthcare",
        "cigna": "Cigna",
        "humana": "Humana"
    }
    
    normalized_insurance = insurance_mapping.get(insurance.lower(), insurance)
    insurance_data = INSURANCE_RULES.get(normalized_insurance, {})
    
    if treatment_category and treatment_category in insurance_data:
        return insurance_data[treatment_category]
    
    return insurance_data.get("general", {
        "criteria": "No specific rules available for this insurance",
        "required_docs": [],
        "typical_denial_reasons": [],
        "minimum_requirements": []
    })

def categorize_treatment(treatment: str) -> Optional[str]:
    """Categorizes treatment to apply correct rules."""
    treatment_lower = treatment.lower()
    
    categories = {
        "diabetes": ["diabetes", "metformin", "insulin", "hba1c", "blood sugar", "glucophage", "lantus", "ozempic", "semaglutide"],
        "mri": ["mri", "magnetic resonance"],
        "imaging": ["scan", "ultrasound", "x-ray", "imaging", "ct", "pet", "mri", "magnetic resonance"],
        "physical_therapy": ["physical therapy", "physiotherapy", "rehabilitation", "pt"],
        "surgery": ["surgery", "operation", "procedure", "surgical"],
        "cancer_treatment": ["chemotherapy", "radiotherapy", "oncology", "cancer", "chemo", "radiation"],
        "mental_health": ["psychiatry", "psychology", "depression", "anxiety", "therapy", "counseling"],
        "cardiology": ["cardiology", "heart", "cardiac", "ecg", "echo", "stress test"],
        "orthopedic": ["orthopedic", "bone", "joint", "fracture", "arthritis", "knee", "hip"]
    }
    
    for category, keywords in categories.items():
        if any(keyword in treatment_lower for keyword in keywords):
            return category
    
    return None

def extract_clinical_facts(data: Dict[str, str]) -> Dict[str, Any]:
    """Extract clinical facts from the request data for validation."""
    facts = {
        "x_ray_performed": False,
        "physical_therapy_attempted": False,
        "conservative_treatment_weeks": 0,
        "pain_score": 0,
        "standard_imaging_done": False,
        "clinical_indication": False,
        "peace_of_mind_request": False,
        "medical_necessity": False
    }
    
    # Combine all text for analysis
    all_text = f"{data['history']} {data['provider_notes']} {data['treatment']}".lower()
    
    # Check for X-ray
    if "x-ray" in all_text and ("performed" in all_text or "done" in all_text or "completed" in all_text):
        facts["x_ray_performed"] = True
    elif "x-ray" in all_text and ("not performed" in all_text or "not done" in all_text):
        facts["x_ray_performed"] = False
    
    # Check for physical therapy
    if any(term in all_text for term in ["physical therapy", "physiotherapy", "pt session"]):
        if not any(term in all_text for term in ["not attempted", "not tried", "not done"]):
            facts["physical_therapy_attempted"] = True
    
    # Extract conservative treatment duration
    duration_patterns = [
        r"(\d+)\s*weeks?\s*(?:of\s*)?(?:conservative\s*)?treatment",
        r"(?:conservative\s*)?treatment\s*(?:for\s*)?(\d+)\s*weeks?",
        r"(\d+)\s*weeks?\s*(?:of\s*)?(?:nsaids?|anti-inflammatory)"
    ]
    
    for pattern in duration_patterns:
        match = re.search(pattern, all_text)
        if match:
            facts["conservative_treatment_weeks"] = max(facts["conservative_treatment_weeks"], int(match.group(1)))
    
    # Extract pain score
    pain_patterns = [
        r"(\d+)/10\s*(?:on\s*)?(?:pain\s*)?(?:scale)?",
        r"pain\s*(?:level|score)\s*(?:of\s*)?(\d+)",
        r"(\d+)\s*out\s*of\s*10\s*pain"
    ]
    
    for pattern in pain_patterns:
        match = re.search(pattern, all_text)
        if match:
            facts["pain_score"] = int(match.group(1))
            break
    
    # Check for peace of mind request
    if any(term in all_text for term in ["peace of mind", "reassurance", "worried", "anxious about"]):
        facts["peace_of_mind_request"] = True
    
    # Check for medical necessity indicators
    if any(term in all_text for term in ["severe", "chronic", "persistent", "worsening", "debilitating"]):
        facts["medical_necessity"] = True
    
    return facts

def validate_against_rules(facts: Dict[str, Any], rules: Dict[str, Any], insurance: str) -> Dict[str, Any]:
    """Validate clinical facts against insurance rules."""
    minimum_requirements = rules.get("minimum_requirements", [])
    violations = []
    
    # Check each minimum requirement
    for requirement in minimum_requirements:
        if requirement == "x_ray_performed" and not facts["x_ray_performed"]:
            violations.append("X-ray not performed - required before advanced imaging")
        elif requirement == "physical_therapy_attempted" and not facts["physical_therapy_attempted"]:
            violations.append("Physical therapy not attempted - required before advanced imaging")
        elif requirement == "conservative_treatment_8weeks" and facts["conservative_treatment_weeks"] < 8:
            violations.append(f"Conservative treatment duration insufficient: {facts['conservative_treatment_weeks']} weeks (minimum 8 required)")
        elif requirement == "conservative_treatment_6weeks" and facts["conservative_treatment_weeks"] < 6:
            violations.append(f"Conservative treatment duration insufficient: {facts['conservative_treatment_weeks']} weeks (minimum 6 required)")
        elif requirement == "pain_score_6" and facts["pain_score"] < 6:
            violations.append(f"Pain score insufficient: {facts['pain_score']}/10 (minimum 6 required)")
        elif requirement == "pain_score_7" and facts["pain_score"] < 7:
            violations.append(f"Pain score insufficient: {facts['pain_score']}/10 (minimum 7 required)")
    
    # Special validation for UnitedHealthcare imaging/MRI
    if insurance.lower() in ["united", "unitedhealthcare"]:
        if facts["peace_of_mind_request"]:
            violations.append("Request for 'peace of mind' is not a valid medical indication")
        
        if not facts["medical_necessity"]:
            violations.append("Insufficient medical necessity documentation")
    
    # Determine if request should be auto-denied
    auto_deny = len(violations) > 0
    
    return {
        "violations": violations,
        "auto_deny": auto_deny,
        "facts_summary": facts
    }

def create_enhanced_titan_prompt(data: Dict[str, str], rules: Dict[str, Any], validation_result: Dict[str, Any]) -> str:
    """Creates a more structured prompt with validation context."""
    
    prompt = f"""You are a medical insurance prior authorization reviewer. Analyze this request strictly according to insurance rules.

PATIENT INFORMATION:
- Patient: {data['patient_info']}
- Insurance: {data['insurance']}
- Treatment: {data['treatment']}
- Medical History: {data['history']}
- Provider Notes: {data['provider_notes']}
- Urgency: {data['urgency']}

INSURANCE RULES ({data['insurance']}):
- Criteria: {rules.get('criteria', 'Standard review')}
- Required Documentation: {', '.join(rules.get('required_docs', []))}
- Common Denial Reasons: {', '.join(rules.get('typical_denial_reasons', []))}

CLINICAL FACTS EXTRACTED:
{json.dumps(validation_result['facts_summary'], indent=2)}

RULE VIOLATIONS DETECTED:
{chr(10).join(f"- {v}" for v in validation_result['violations']) if validation_result['violations'] else "None"}

CRITICAL INSTRUCTIONS:
1. If any rule violations are detected, the decision MUST be "DENIED"
2. "Peace of mind" requests without medical necessity should be DENIED
3. Insufficient conservative treatment duration requires DENIAL
4. Missing required preliminary tests (X-ray, PT) requires DENIAL
5. Only approve if ALL insurance criteria are met

EXAMPLES OF DECISIONS:
- DENIED: "Patient requests MRI for peace of mind without medical necessity"
- DENIED: "Conservative treatment duration 2 weeks, minimum 8 weeks required"
- DENIED: "X-ray not performed, required before MRI authorization"
- APPROVED: "All criteria met: 12 weeks PT, X-ray negative, pain 8/10, medical necessity documented"

Based on the rules and violations, provide your decision in JSON format:
{{
    "decision": "APPROVED|DENIED|CONDITIONAL",
    "reason": "Detailed explanation referencing specific rule violations or compliance",
    "confidence_score": 0-100,
    "missing_documentation": ["list of missing items"],
    "alternative_treatments": ["list of alternatives"],
    "appeal_guidance": "guidance for appeals if denied"
}}

JSON Response:"""
    
    return prompt

def apply_safety_validation(ai_decision: Dict[str, Any], validation_result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply safety validation to override incorrect AI decisions."""
    
    # If rule violations detected, force DENIAL regardless of AI decision
    if validation_result["auto_deny"]:
        logger.warning(f"Overriding AI decision due to rule violations: {validation_result['violations']}")
        
        return {
            "decision": "DENIED",
            "reason": f"Request denied due to insurance rule violations: {'; '.join(validation_result['violations'])}",
            "confidence_score": 95,
            "missing_documentation": ai_decision.get("missing_documentation", []),
            "alternative_treatments": ai_decision.get("alternative_treatments", []),
            "appeal_guidance": "Address all rule violations listed in the denial reason before resubmitting",
            "safety_override": True,
            "original_ai_decision": ai_decision.get("decision", "UNKNOWN")
        }
    
    # If AI approved but facts don't support it, investigate
    if ai_decision.get("decision") == "APPROVED" and validation_result["violations"]:
        logger.warning("AI approved request despite rule violations - applying safety override")
        return {
            "decision": "DENIED",
            "reason": f"Safety override: {'; '.join(validation_result['violations'])}",
            "confidence_score": 90,
            "missing_documentation": ai_decision.get("missing_documentation", []),
            "alternative_treatments": ai_decision.get("alternative_treatments", []),
            "appeal_guidance": "Address rule violations before resubmitting",
            "safety_override": True,
            "original_ai_decision": "APPROVED"
        }
    
    # Return original AI decision if no safety issues
    return ai_decision

def call_bedrock_api(prompt: str) -> Dict[str, Any]:
    """Calls Bedrock API with enhanced error handling and response parsing."""
    try:
        request_body = {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": BEDROCK_CONFIG["max_tokens"],
                "temperature": BEDROCK_CONFIG["temperature"],
                "topP": BEDROCK_CONFIG["top_p"]
            }
        }
        
        logger.info(f"Calling Bedrock with model: {BEDROCK_CONFIG['model_id']}")
        
        response = bedrock.invoke_model(
            modelId=BEDROCK_CONFIG["model_id"],
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read().decode('utf-8'))
        
        if 'results' in response_body and len(response_body['results']) > 0:
            generated_text = response_body['results'][0].get('outputText', '').strip()
        else:
            logger.error("Unexpected Bedrock response structure")
            return create_fallback_response("Unexpected response structure")
        
        logger.info(f"Generated text: {generated_text}")
        return extract_and_validate_json(generated_text)
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"Bedrock ClientError - Code: {error_code}, Message: {error_message}")
        return create_fallback_response(f"Bedrock error: {error_code}")
            
    except Exception as e:
        logger.error(f"Unexpected error calling Bedrock: {e}", exc_info=True)
        return create_fallback_response("Bedrock technical error")

def extract_and_validate_json(text: str) -> Dict[str, Any]:
    """Enhanced JSON extraction with fallback for natural language responses."""
    try:
        text = text.strip()
        
        # Remove markdown code blocks if present
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
                if text.startswith('json'):
                    text = text[4:].strip()
        
        # Try direct JSON parsing first
        try:
            parsed_json = json.loads(text)
            return validate_and_fix_json(parsed_json)
        except json.JSONDecodeError:
            pass
        
        # Fallback: Find JSON blocks with regex
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        json_matches = re.findall(json_pattern, text, re.DOTALL)
        
        if json_matches:
            for json_str in json_matches:
                try:
                    parsed_json = json.loads(json_str.strip())
                    return validate_and_fix_json(parsed_json)
                except json.JSONDecodeError:
                    continue
        
        # Final fallback: Parse natural language response
        return parse_natural_language_response(text)
        
    except Exception as e:
        logger.error(f"JSON extraction error: {e}")
        return create_fallback_response("JSON extraction error")

def parse_natural_language_response(text: str) -> Dict[str, Any]:
    """Parse natural language response from Titan when JSON fails."""
    text_lower = text.lower()
    
    # Determine decision from text
    decision = "PENDING"
    if "approved" in text_lower or "authorize" in text_lower:
        decision = "APPROVED"
    elif "denied" in text_lower or "reject" in text_lower:
        decision = "DENIED"
    elif "conditional" in text_lower or "additional" in text_lower:
        decision = "CONDITIONAL"
    
    # Extract confidence if mentioned
    confidence_score = 75
    confidence_match = re.search(r'(\d+)%', text)
    if confidence_match:
        confidence_score = int(confidence_match.group(1))
    
    response = {
        "decision": decision,
        "reason": text[:200] + "..." if len(text) > 200 else text,
        "confidence_score": confidence_score,
        "missing_documentation": [],
        "alternative_treatments": [],
        "appeal_guidance": "Contact insurance provider for detailed review"
    }
    
    return response

def validate_and_fix_json(parsed_json: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and fixes JSON response."""
    if 'decision' not in parsed_json:
        parsed_json['decision'] = 'PENDING'
    if 'reason' not in parsed_json:
        parsed_json['reason'] = 'Analysis completed'
    
    # Validate decision values
    valid_decisions = ['APPROVED', 'DENIED', 'CONDITIONAL', 'PENDING']
    if parsed_json['decision'] not in valid_decisions:
        parsed_json['decision'] = 'PENDING'
    
    # Add missing fields with defaults
    if 'confidence_score' not in parsed_json:
        parsed_json['confidence_score'] = 75
    if 'missing_documentation' not in parsed_json:
        parsed_json['missing_documentation'] = []
    if 'alternative_treatments' not in parsed_json:
        parsed_json['alternative_treatments'] = []
    if 'appeal_guidance' not in parsed_json:
        parsed_json['appeal_guidance'] = ""
    
    # Ensure proper data types
    try:
        parsed_json['confidence_score'] = int(parsed_json['confidence_score'])
    except:
        parsed_json['confidence_score'] = 75
    
    if not isinstance(parsed_json['missing_documentation'], list):
        parsed_json['missing_documentation'] = []
    if not isinstance(parsed_json['alternative_treatments'], list):
        parsed_json['alternative_treatments'] = []
    
    return parsed_json

def create_fallback_response(error_reason: str) -> Dict[str, Any]:
    """Creates fallback response for errors."""
    return {
        "decision": "PENDING",
        "reason": f"Manual review required - {error_reason}",
        "confidence_score": 0,
        "missing_documentation": ["Manual evaluation needed"],
        "alternative_treatments": [],
        "appeal_guidance": "Contact customer service for manual review"
    }

def validate_request_data(item: Dict[str, Any]) -> Dict[str, str]:
    """Validates and cleans request data."""
    return {
        'patient_info': str(item.get('patient_info', 'Not specified')).strip(),
        'treatment': str(item.get('treatment', 'Not specified')).strip(),
        'insurance': str(item.get('insurance', 'Unknown')).strip(),
        'history': str(item.get('history', 'Not provided')).strip(),
        'urgency': str(item.get('urgency', 'Standard')).strip(),
        'provider_notes': str(item.get('provider_notes', 'No notes')).strip()
    }

def update_dynamodb_record(request_id: str, decision_data: Dict[str, Any]) -> None:
    """Updates DynamoDB record with results."""
    try:
        update_expression = """
        SET decision_status = :status, 
            decision_reason = :reason, 
            confidence_score = :score,
            processed_timestamp = :timestamp,
            missing_documentation = :missing_docs,
            alternative_treatments = :alternatives,
            appeal_guidance = :appeal,
            safety_override = :safety_override
        """
        
        table.update_item(
            Key={'request_id': request_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues={
                ':status': decision_data.get('decision', 'UNKNOWN'),
                ':reason': decision_data.get('reason', 'No justification provided'),
                ':score': int(decision_data.get('confidence_score', 0)),
                ':timestamp': datetime.now().isoformat(),
                ':missing_docs': decision_data.get('missing_documentation', []),
                ':alternatives': decision_data.get('alternative_treatments', []),
                ':appeal': decision_data.get('appeal_guidance', ''),
                ':safety_override': decision_data.get('safety_override', False)
            }
        )
        logger.info(f"Record {request_id} updated successfully")
        
    except ClientError as e:
        logger.error(f"DynamoDB error: {e}")
        raise

def lambda_handler(event, context):
    """Main Lambda function with enhanced processing and safety validation."""
    start_time = datetime.now()
    
    try:
        # Input validation
        request_id = event.get('request_id')
        if not request_id:
            logger.warning("Missing request_id in event")
            return {
                'statusCode': 400, 
                'body': json.dumps({'error': 'Missing "request_id" field'})
            }
        
        logger.info(f"Processing request: {request_id}")
        
        # 1. Data retrieval
        try:
            response = table.get_item(Key={'request_id': request_id})
            item = response.get('Item')
            
            if not item:
                logger.warning(f"Request {request_id} not found")
                return {
                    'statusCode': 404, 
                    'body': json.dumps({'error': 'Request not found in DynamoDB'})
                }
        except ClientError as e:
            logger.error(f"DynamoDB read error: {e}")
            return {
                'statusCode': 500, 
                'body': json.dumps({'error': 'Database access error'})
            }
        
        # 2. Enhanced data processing
        data = validate_request_data(item)
        treatment_category = categorize_treatment(data['treatment'])
        rules = get_insurance_rules(data['insurance'], treatment_category)
        
        # 3. NOUVEAU: Extract clinical facts and validate against rules
        clinical_facts = extract_clinical_facts(data)
        validation_result = validate_against_rules(clinical_facts, rules, data['insurance'])
        
        logger.info(f"Clinical facts: {clinical_facts}")
        logger.info(f"Validation result: {validation_result}")
        
        # 4. Enhanced prompt generation and AI call
        prompt = create_enhanced_titan_prompt(data, rules, validation_result)
        ai_decision = call_bedrock_api(prompt)
        
        # 5. NOUVEAU: Apply safety validation to override incorrect AI decisions
        final_decision = apply_safety_validation(ai_decision, validation_result)
        
        # 6. Database update
        update_dynamodb_record(request_id, final_decision)
        
        # 7. Final response
        processing_time = (datetime.now() - start_time).total_seconds()
        
        response_body = {
            **final_decision,
            'request_id': request_id,
            'processing_time_seconds': round(processing_time, 2),
            'treatment_category': treatment_category,
            'insurance_rules_applied': rules.get('criteria', 'General rules'),
            'clinical_facts': clinical_facts,
            'rule_violations': validation_result['violations']
        }
        
        logger.info(f"Request {request_id} processed successfully in {processing_time:.2f}s")
        logger.info(f"Final decision: {final_decision['decision']}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body, ensure_ascii=False)
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500, 
            'body': json.dumps({'error': 'Internal server error'})
        }