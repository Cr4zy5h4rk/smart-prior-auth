import boto3
import json
from decimal import Decimal

from botocore.exceptions import ClientError

def create_dynamodb_table():
    """
    Crée la table DynamoDB pour stocker les demandes d'autorisation
    """
    
    dynamodb = boto3.client('dynamodb')
    
    table_name = 'prior-auth-requests'
    
    # Configuration de la table
    table_config = {
        'TableName': table_name,
        'KeySchema': [
            {
                'AttributeName': 'request_id',
                'KeyType': 'HASH'  # Partition key
            }
        ],
        'AttributeDefinitions': [
            {
                'AttributeName': 'request_id',
                'AttributeType': 'S'  # String
            },
            {
                'AttributeName': 'timestamp',
                'AttributeType': 'S'  # String (ISO format)
            },
            {
                'AttributeName': 'status',
                'AttributeType': 'S'  # String
            }
        ],
        'BillingMode': 'PAY_PER_REQUEST',  # Pas de provisioning - idéal pour Free Tier
        'GlobalSecondaryIndexes': [
            {
                'IndexName': 'timestamp-index',
                'KeySchema': [
                    {
                        'AttributeName': 'timestamp',
                        'KeyType': 'HASH'
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'  # Inclut tous les attributs
                }
            },
            {
                'IndexName': 'status-index',
                'KeySchema': [
                    {
                        'AttributeName': 'status',
                        'KeyType': 'HASH'
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'
                }
            }
        ],
        'StreamSpecification': {
            'StreamEnabled': True,
            'StreamViewType': 'NEW_AND_OLD_IMAGES'  # Pour déclencher d'autres Lambda
        },
        'Tags': [
            {
                'Key': 'Project',
                'Value': 'SmartPriorAuth'
            },
            {
                'Key': 'Environment',
                'Value': 'Development'
            }
        ]
    }
    
    try:
        # Création de la table
        response = dynamodb.create_table(**table_config)
        print(f"Table '{table_name}' creation initiated...")
        print(f"Table ARN: {response['TableDescription']['TableArn']}")
        
        # Attendre que la table soit active
        waiter = dynamodb.get_waiter('table_exists')
        print("Waiting for table to be active...")
        waiter.wait(TableName=table_name)
        
        print(f"✅ Table '{table_name}' created successfully!")
        
        # Insertion de données de test
        insert_sample_data(table_name)
        
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceInUseException':
            print(f"⚠️  Table '{table_name}' already exists")
            return True
        else:
            print(f"❌ Error creating table: {e}")
            return False

def insert_sample_data(table_name):
    """
    Insert sample data for testing
    """
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    sample_data = [
    {
        'request_id': 'demo-001',
        'timestamp': '2025-06-10T10:00:00Z',
        'status': 'analyzed',
        'patient_info': {
            'name': 'John Doe',
            'age': 45,
            'insurance_type': 'BlueCross',
            'member_id': 'BC123456789'
        },
        'treatment_analysis': {
            'approval_probability': Decimal('0.85'),  # <-- Decimal au lieu de float
            'treatment_type': 'Ozempic',
            'requirements': ['Prior diabetes medications tried', 'HbA1c > 7%'],
            'typical_approval_time': '48-72 hours'
        },
        'created_at': 1717992000
    },
    {
        'request_id': 'demo-002',
        'timestamp': '2025-06-10T11:00:00Z',
        'status': 'submitted',
        'patient_info': {
            'name': 'Jane Smith',
            'age': 38,
            'insurance_type': 'Aetna',
            'member_id': 'AE987654321'
        },
        'treatment_analysis': {
            'approval_probability': Decimal('0.92'),  # Decimal ici aussi
            'treatment_type': 'MRI Knee',
            'requirements': ['6 weeks conservative treatment completed'],
            'typical_approval_time': '3-5 days'
        },
        'created_at': 1717995600
    },
    {
        'request_id': 'demo-003',
        'timestamp': '2025-06-10T12:00:00Z',
        'status': 'approved',
        'patient_info': {
            'name': 'Robert Johnson',
            'age': 62,
            'insurance_type': 'UnitedHealth',
            'member_id': 'UH456789123'
        },
        'treatment_analysis': {
            'approval_probability': Decimal('0.78'),  # Decimal ici aussi
            'treatment_type': 'Insulin Pump',
            'requirements': ['Type 1 diabetes confirmed', 'CGM experience'],
            'typical_approval_time': '5-7 days'
        },
        'created_at': 1717999200,
        'approval_date': '2025-06-10T14:30:00Z',
        'approval_number': 'AUTH-2025-001234'
    }
]
    
    try:
        with table.batch_writer() as batch:
            for item in sample_data:
                batch.put_item(Item=item)
        
        print(f"✅ Sample data inserted successfully!")
        print(f"📊 Inserted {len(sample_data)} sample records")
        
    except Exception as e:
        print(f"❌ Error inserting sample data: {e}")

def verify_table_setup(table_name):
    """
    Vérifie que la table est correctement configurée
    """
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    
    try:
        # Test de lecture
        response = table.scan(Limit=5)
        items = response.get('Items', [])
        
        print(f"✅ Table verification successful!")
        print(f"📊 Found {len(items)} items in table")
        
        # Affichage des premiers éléments
        for item in items[:2]:
            print(f"   - Request ID: {item['request_id']} | Status: {item['status']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error verifying table: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Setting up DynamoDB table for Smart Prior Auth...")
    
    if create_dynamodb_table():
        verify_table_setup('prior-auth-requests')
        print("\n🎉 DynamoDB setup complete!")
        print("\n📋 Next steps:")
        print("   1. Deploy the Lambda function")
        print("   2. Set up API Gateway")
        print("   3. Test the integration")
    else:
        print("\n❌ DynamoDB setup failed!")