#!/usr/bin/env python3
"""
AWS Infrastructure Assessment Script

This script checks your AWS infrastructure setup for the AI Agent Orchestrator.
Run this to get a quick assessment of your current AWS configuration.

Requirements:
    pip install boto3

Usage:
    python scripts/aws_infrastructure_check.py
"""

import boto3
import sys
from typing import Dict, List, Any
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError


class AWSInfrastructureChecker:
    """Check AWS infrastructure setup."""
    
    def __init__(self):
        """Initialize the checker."""
        self.region = 'us-east-1'  # Default region
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.success: List[str] = []
        
    def check_credentials(self) -> bool:
        """Check if AWS credentials are configured."""
        try:
            sts = boto3.client('sts')
            identity = sts.get_caller_identity()
            self.success.append(f"✅ AWS credentials configured")
            self.success.append(f"   Account ID: {identity.get('Account', 'Unknown')}")
            self.success.append(f"   User/Role: {identity.get('Arn', 'Unknown')}")
            return True
        except NoCredentialsError:
            self.issues.append("❌ AWS credentials not found")
            self.issues.append("   Configure credentials using: aws configure")
            return False
        except Exception as e:
            self.issues.append(f"❌ Error checking credentials: {str(e)}")
            return False
    
    def check_bedrock_access(self) -> bool:
        """Check Bedrock access and permissions."""
        try:
            bedrock = boto3.client('bedrock-runtime', region_name=self.region)
            # Try to list foundation models (read-only operation)
            bedrock_list = boto3.client('bedrock', region_name=self.region)
            try:
                models = bedrock_list.list_foundation_models()
                self.success.append(f"✅ Bedrock access verified")
                self.success.append(f"   Region: {self.region}")
                model_count = len(models.get('modelSummaries', []))
                self.success.append(f"   Available models: {model_count}")
                return True
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == 'AccessDeniedException':
                    self.issues.append("❌ Bedrock access denied")
                    self.issues.append("   Check IAM permissions for bedrock:InvokeModel")
                else:
                    self.warnings.append(f"⚠️  Bedrock access issue: {error_code}")
                return False
        except Exception as e:
            self.issues.append(f"❌ Error checking Bedrock: {str(e)}")
            return False
    
    def check_ec2_instances(self) -> None:
        """Check for EC2 instances."""
        try:
            ec2 = boto3.client('ec2', region_name=self.region)
            instances = ec2.describe_instances()
            
            running_instances = []
            for reservation in instances.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    if instance['State']['Name'] == 'running':
                        running_instances.append(instance)
            
            if running_instances:
                self.success.append(f"✅ Found {len(running_instances)} running EC2 instance(s)")
                for inst in running_instances:
                    name = next(
                        (tag['Value'] for tag in inst.get('Tags', []) if tag['Key'] == 'Name'),
                        'Unnamed'
                    )
                    self.success.append(f"   - {name} ({inst['InstanceType']})")
            else:
                self.warnings.append("⚠️  No running EC2 instances found")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking EC2: {str(e)}")
    
    def check_ecs_clusters(self) -> None:
        """Check for ECS clusters."""
        try:
            ecs = boto3.client('ecs', region_name=self.region)
            clusters = ecs.list_clusters()
            
            if clusters.get('clusterArns'):
                self.success.append(f"✅ Found {len(clusters['clusterArns'])} ECS cluster(s)")
                for cluster_arn in clusters['clusterArns']:
                    cluster_name = cluster_arn.split('/')[-1]
                    self.success.append(f"   - {cluster_name}")
            else:
                self.warnings.append("⚠️  No ECS clusters found")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking ECS: {str(e)}")
    
    def check_lambda_functions(self) -> None:
        """Check for Lambda functions."""
        try:
            lambda_client = boto3.client('lambda', region_name=self.region)
            functions = lambda_client.list_functions()
            
            if functions.get('Functions'):
                self.success.append(f"✅ Found {len(functions['Functions'])} Lambda function(s)")
                for func in functions['Functions']:
                    self.success.append(f"   - {func['FunctionName']} ({func['Runtime']})")
            else:
                self.warnings.append("⚠️  No Lambda functions found")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking Lambda: {str(e)}")
    
    def check_secrets_manager(self) -> None:
        """Check for secrets in Secrets Manager."""
        try:
            secrets = boto3.client('secretsmanager', region_name=self.region)
            secret_list = secrets.list_secrets()
            
            if secret_list.get('SecretList'):
                self.success.append(f"✅ Found {len(secret_list['SecretList'])} secret(s) in Secrets Manager")
                for secret in secret_list['SecretList']:
                    self.success.append(f"   - {secret['Name']}")
            else:
                self.warnings.append("⚠️  No secrets found in Secrets Manager")
                self.warnings.append("   Consider storing API keys in Secrets Manager")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking Secrets Manager: {str(e)}")
    
    def check_parameter_store(self) -> None:
        """Check for parameters in Systems Manager Parameter Store."""
        try:
            ssm = boto3.client('ssm', region_name=self.region)
            params = ssm.describe_parameters(
                ParameterFilters=[
                    {'Key': 'Name', 'Values': ['orchestrator', 'api-key']}
                ]
            )
            
            if params.get('Parameters'):
                self.success.append(f"✅ Found {len(params['Parameters'])} relevant parameter(s)")
                for param in params['Parameters']:
                    self.success.append(f"   - {param['Name']}")
            else:
                self.warnings.append("⚠️  No orchestrator parameters found in Parameter Store")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking Parameter Store: {str(e)}")
    
    def check_cloudwatch_logs(self) -> None:
        """Check for CloudWatch log groups."""
        try:
            logs = boto3.client('logs', region_name=self.region)
            log_groups = logs.describe_log_groups(
                logGroupNamePrefix='/aws/'
            )
            
            orchestrator_logs = [
                lg for lg in log_groups.get('logGroups', [])
                if 'orchestrator' in lg['logGroupName'].lower()
            ]
            
            if orchestrator_logs:
                self.success.append(f"✅ Found {len(orchestrator_logs)} orchestrator log group(s)")
                for lg in orchestrator_logs:
                    self.success.append(f"   - {lg['logGroupName']}")
            else:
                self.warnings.append("⚠️  No orchestrator log groups found")
                self.warnings.append("   Set up CloudWatch logging for production")
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking CloudWatch: {str(e)}")
    
    def check_iam_permissions(self) -> None:
        """Check IAM permissions for Bedrock."""
        try:
            iam = boto3.client('iam')
            sts = boto3.client('sts')
            identity = sts.get_caller_identity()
            
            # Try to get current user/role policies
            arn = identity.get('Arn', '')
            if 'user' in arn:
                username = arn.split('/')[-1]
                try:
                    policies = iam.list_user_policies(UserName=username)
                    attached_policies = iam.list_attached_user_policies(UserName=username)
                    
                    all_policies = policies.get('PolicyNames', []) + [
                        p['PolicyName'] for p in attached_policies.get('AttachedPolicies', [])
                    ]
                    
                    if all_policies:
                        self.success.append(f"✅ IAM user has {len(all_policies)} policy/policies")
                    else:
                        self.warnings.append("⚠️  IAM user has no policies attached")
                except Exception:
                    pass
            elif 'role' in arn:
                self.success.append("✅ Using IAM role (recommended)")
            
        except Exception as e:
            self.warnings.append(f"⚠️  Error checking IAM: {str(e)}")
    
    def check_region(self) -> None:
        """Check and display current region."""
        try:
            session = boto3.Session()
            region = session.region_name or self.region
            self.success.append(f"✅ AWS Region: {region}")
            self.region = region
        except Exception:
            self.warnings.append(f"⚠️  Using default region: {self.region}")
    
    def run_all_checks(self) -> None:
        """Run all infrastructure checks."""
        print("🔍 AWS Infrastructure Assessment")
        print("=" * 50)
        print()
        
        # Basic checks
        self.check_region()
        print()
        
        if not self.check_credentials():
            print("\n".join(self.issues))
            print("\n⚠️  Cannot proceed without AWS credentials")
            return
        
        print("\n".join(self.success))
        self.success = []
        print()
        
        # Service checks
        print("Checking AWS Services...")
        print("-" * 50)
        
        self.check_bedrock_access()
        self.check_ec2_instances()
        self.check_ecs_clusters()
        self.check_lambda_functions()
        self.check_secrets_manager()
        self.check_parameter_store()
        self.check_cloudwatch_logs()
        self.check_iam_permissions()
        
        # Print results
        print()
        if self.success:
            print("✅ Success:")
            print("\n".join(self.success))
            print()
        
        if self.warnings:
            print("⚠️  Warnings:")
            print("\n".join(self.warnings))
            print()
        
        if self.issues:
            print("❌ Issues:")
            print("\n".join(self.issues))
            print()
        
        # Summary
        print("=" * 50)
        print("Summary:")
        print(f"  ✅ Success: {len(self.success)}")
        print(f"  ⚠️  Warnings: {len(self.warnings)}")
        print(f"  ❌ Issues: {len(self.issues)}")
        print()
        
        if self.issues:
            print("⚠️  Please fix the issues above before deploying to production.")
        elif self.warnings:
            print("💡 Consider addressing the warnings for better production setup.")
        else:
            print("✅ Your AWS infrastructure looks good!")


def main():
    """Main entry point."""
    try:
        checker = AWSInfrastructureChecker()
        checker.run_all_checks()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()

