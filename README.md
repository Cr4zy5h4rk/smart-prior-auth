Here is your complete and professional `README.md` in **English**, formatted and ready to paste directly into your GitHub repository:

---


# 🏥 Medical Prior Authorization System with AWS Lambda & Bedrock

This project implements an intelligent system to automate **medical prior authorization** requests using **AWS Lambda**, **Amazon Bedrock**, and **DynamoDB**. It analyzes incoming requests, evaluates them against insurer-specific rules, and generates a structured decision response.


---

## 🚀 Key Features

- 🔍 Natural language analysis of prior authorization requests
- 📑 Rule-based eligibility verification per insurance provider
- 🤖 Automated decision generation: `APPROVED`, `PENDING`, or `REJECTED` with explanation
- 🧠 Intelligent prompt generation for Bedrock LLM
- 📦 Real-time update of request records in DynamoDB
- 🔁 Built-in error handling with decision fallback
- 🛡️ Data validation and treatment categorization

---

## ⚙️ Architecture Overview

```plaintext
   [API Gateway]
         |
     [Lambda Function]
         |
 ┌────> Categorization (NLP)
 |       |
 |  [Rules Matching]
 |       |
 |  [Prompt Generation]
 |       |
 |   [Amazon Bedrock]
 |       |
 └──< JSON Decision Output
         |
   [DynamoDB Record Update]
````

---

## 🧠 How AWS Lambda Is Used

This project is powered by an **AWS Lambda** function, acting as the core processing engine for evaluating and responding to authorization requests.

### Lambda Responsibilities

1. Triggered via **API Gateway** or **event input**
2. **Fetches the request** data from DynamoDB using a `request_id`
3. **Validates and sanitizes** the input
4. **Categorizes the treatment** using medical keywords
5. **Applies insurer-specific rules**
6. **Generates a custom prompt** for the Bedrock LLM
7. **Invokes the Titan Text Express v1 model**
8. **Parses the JSON decision output**
9. **Updates DynamoDB** with the decision and metadata
10. Returns the **structured JSON response**

---

## 📚 Technologies Used

| Component          | Description                                 |
| ------------------ | ------------------------------------------- |
| AWS Lambda         | Serverless compute for processing requests  |
| Amazon Bedrock     | Foundation model for decision generation    |
| DynamoDB           | NoSQL database for request storage          |
| boto3              | Python SDK for AWS service integration      |
| Python 3.9+        | Programming language                        |
| re, json, datetime | Standard libraries for text & data handling |
| logging            | Detailed logging of steps and errors        |

---

## 📁 Project Structure

```
.
├── lambda_function.py       # Main application logic
├── README.md                # Documentation (this file)
└── requirements.txt         # Optional dependencies
```

---

## 🧪 Example Workflow

1. A request is stored in DynamoDB:

```json
{
  "request_id": "req_123",
  "patient_info": "Mrs. Dupont, 65 years old",
  "treatment": "MRI of the right knee",
  "insurance": "BlueCross",
  "urgency": "High",
  "history": "Persistent pain for 3 months, conservative treatments failed",
  "provider_notes": "Pain score 9/10, limited mobility"
}
```

2. Lambda is invoked with:

```json
{
  "request_id": "req_123"
}
```

3. Response from Lambda:

```json
{
  "decision": "APPROVED",
  "reason": "MRI justified after failure of conservative treatment for more than 6 weeks with pain >7/10.",
  "confidence_score": 91,
  "missing_documentation": [],
  "alternative_treatments": [],
  "appeal_guidance": "",
  "request_id": "req_123",
  "processing_time_seconds": 0.87,
  "treatment_category": "mri"
}
```

---

## 🧑‍⚕️ Supported Insurance Rules

Custom business rules are implemented for insurers such as:

* **BlueCross**: diabetes, MRI, specialty drugs
* **Aetna**: surgery, physical therapy, imaging
* **UnitedHealthcare**: oncology, mental health
* **Cigna**: cardiology, orthopedics
* **Humana**: senior care, preventive treatment

---

## 🛠️ Deployment

### 1. Prerequisites

* AWS CLI configured
* IAM Role with access to:

  * DynamoDB
  * Amazon Bedrock
  * CloudWatch Logs

### 2. Manual Deployment via AWS Console

* Create a Lambda function with Python 3.9
* Set environment variables if needed
* Assign the proper IAM role
* Link a trigger (API Gateway, EventBridge, etc.)

### 3. (Optional) Deploy with AWS SAM or Terraform

*TODO: Add `template.yaml` for SAM or equivalent for Terraform if needed.*

---

## Screenshots

### AWS Lambda Functions Configuration

**DocumentProcessor Lambda Function**  
![Configuration of DocumentProcessor Lambda Function](https://live.staticflickr.com/65535/54585003910_8fb360860b_b.jpg)

**DecisionEngine Lambda Function**  
![Configuration of DecisionEngine Lambda Function](https://live.staticflickr.com/65535/54583824502_630e939b59_b.jpg)

**Timeout Configuration for DecisionEngine AI Processing**  
![Timeout setup for DecisionEngine Lambda Function](https://live.staticflickr.com/65535/54585003915_e483156a4b_b.jpg)

---

### API Gateway Configuration

![API Gateway configuration view 1](https://live.staticflickr.com/65535/54585003875_9a38e81b37_b.jpg)  
![API Gateway configuration view 2](https://live.staticflickr.com/65535/54584692111_93e82c6e26_b.jpg)  
![API Gateway configuration view 3](https://live.staticflickr.com/65535/54583824492_eae9722322_b.jpg)  
![API Gateway configuration view 4](https://live.staticflickr.com/65535/54583824452_1554287e4f_b.jpg)  
![API Gateway configuration view 5](https://live.staticflickr.com/65535/54585003820_f9063696c3_b.jpg)

---

### DynamoDB - `prior-auth-request` Table

![DynamoDB prior-auth-request table structure](https://live.staticflickr.com/65535/54585003800_2ee41769c6_b.jpg)  
![DynamoDB prior-auth-request table overview](https://live.staticflickr.com/65535/54585003795_6372a7e42a_b.jpg)  
![DynamoDB table keys and items](https://live.staticflickr.com/65535/54584876914_09bd92cdf9_z.jpg)

---

### AWS Bedrock - Titan Text G1 Model

![AWS Bedrock Titan Text G1 Express model configuration](https://live.staticflickr.com/65535/54584692036_34e61b3319.jpg)

---

### IAM & Permissions

![IAM role permissions for Lambda](https://live.staticflickr.com/65535/54583824377_6a207caa1e_b.jpg)  
![IAM role trust relationship](https://live.staticflickr.com/65535/54584876854_6d96c9b87a_b.jpg)  
![IAM policy summary view](https://live.staticflickr.com/65535/54584691966_4cde9987e0_b.jpg)  
![IAM permission list view 1](https://live.staticflickr.com/65535/54584909838_5010fddd0b_b.jpg)  
![IAM permission list view 2](https://live.staticflickr.com/65535/54614134222_d5857a0122_h.jpg)  
![IAM user/role detail view](https://live.staticflickr.com/65535/54585003725_6e0a4c8d47_b.jpg)

---

### AWS S3 Bucket Configuration

![S3 bucket for prior-authorization document storage](https://live.staticflickr.com/65535/54584691976_09401ec6f8_b.jpg)  
![S3 bucket configuration details](https://live.staticflickr.com/65535/54584876849_ed623de47c_b.jpg)


## ✅ Best Practices Followed

* Structured and readable logs
* Clear separation of concerns
* Minimal and precise prompt design
* Robust JSON extraction with regular expressions
* Fallback decision (`PENDING`) if LLM fails
* Stop sequences to avoid excessive model output

---

## 🔐 Security Considerations

* No sensitive patient data is exposed
* Logs are sanitized from PII
* IAM permissions follow the principle of least privilege
* API Gateway can be protected with usage plans and keys

---

## 📌 Limitations & Future Improvements

* 📤 Add a web/mobile interface for providers
* 🔄 Fine-tune the LLM with proprietary medical data
* 📊 Add historical search and analytics layer
* 🔐 Encrypt sensitive fields at rest

---

## 👨‍💻 Author

**Name:** \[Your Name or Handle]
**Contact:** \[GitHub Profile / Email]
**Organization:** \[Optional]

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
