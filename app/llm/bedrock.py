"""AWS Bedrock LLM provider implementation."""

import json
import asyncio
import boto3
from typing import Dict, Any, Optional, AsyncIterator
from botocore.exceptions import ClientError, BotoCoreError
from app.llm.base import LLMProvider
from app.core.config import settings
from app.core.retry import retry_async, RetryConfig
from app.core.exceptions import LLMProviderError
import time


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider using Claude models."""

    def __init__(
        self,
        region: Optional[str] = None,
        model: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None
    ):
        """
        Initialize Bedrock provider.

        Args:
            region: AWS region
            model: Model identifier
            access_key_id: AWS access key ID
            secret_access_key: AWS secret access key
        """
        self.region = region or settings.aws_region
        self.model = model or settings.llm_model
        self.bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=self.region,
            aws_access_key_id=access_key_id or settings.aws_access_key_id,
            aws_secret_access_key=secret_access_key or settings.aws_secret_access_key
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """
        Generate a text response using AWS Bedrock with retry logic.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters

        Returns:
            Generated text response
        """
        # Retry configuration for Bedrock calls
        retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0,
            retryable_exceptions=(ClientError, BotoCoreError, ConnectionError, TimeoutError)
        )
        
        async def _generate_internal():
            try:
                # Prepare messages for Claude
                messages = []
                if system_prompt:
                    messages.append({
                        "role": "user",
                        "content": system_prompt
                    })
                messages.append({
                    "role": "user",
                    "content": prompt
                })
                
                # Prepare request body
                request_body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens or settings.llm_max_tokens,
                    "temperature": temperature if temperature is not None else settings.llm_temperature,
                    "messages": messages
                }
                
                # Call Bedrock (run in thread pool since boto3 is synchronous)
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.bedrock_runtime.invoke_model(
                        modelId=self.model,
                        contentType="application/json",
                        accept="application/json",
                        body=json.dumps(request_body)
                    )
                )
                
                # Parse response
                response_body = json.loads(response['body'].read())
                
                # Extract text from Claude response
                if 'content' in response_body and len(response_body['content']) > 0:
                    return response_body['content'][0]['text']
                else:
                    raise ValueError("Unexpected response format from Bedrock")
                    
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                error_message = e.response.get('Error', {}).get('Message', str(e))
                
                # Don't retry on certain error codes
                if error_code in ['ValidationException', 'AccessDeniedException', 'ResourceNotFoundException']:
                    raise LLMProviderError(
                        f"Bedrock API error ({error_code}): {error_message}",
                        provider="bedrock",
                        details={"error_code": error_code, "model": self.model}
                    )
                
                # Retry on other errors
                raise
            except json.JSONDecodeError as e:
                raise LLMProviderError(
                    f"Failed to parse Bedrock response: {str(e)}",
                    provider="bedrock"
                )
            except Exception as e:
                raise LLMProviderError(
                    f"Unexpected error in Bedrock generate: {str(e)}",
                    provider="bedrock"
                )
        
        # Execute with retry logic
        return await retry_async(_generate_internal, config=retry_config)

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """
        Stream a text response using AWS Bedrock.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters

        Yields:
            Text chunks as they are generated
        """
        try:
            # Prepare messages for Claude
            messages = []
            if system_prompt:
                messages.append({
                    "role": "user",
                    "content": system_prompt
                })
            messages.append({
                "role": "user",
                "content": prompt
            })
            
            # Prepare request body
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens or settings.llm_max_tokens,
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "messages": messages
            }
            
            # Call Bedrock with streaming
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.bedrock_runtime.invoke_model_with_response_stream(
                    modelId=self.model,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body)
                )
            )
            
            # Process streaming response
            stream = response.get('body')
            if stream:
                for event in stream:
                    if 'chunk' in event:
                        chunk = json.loads(event['chunk']['bytes'])
                        if 'delta' in chunk and 'text' in chunk['delta']:
                            yield chunk['delta']['text']
                        elif 'content_block_delta' in chunk:
                            if 'delta' in chunk['content_block_delta'] and 'text' in chunk['content_block_delta']['delta']:
                                yield chunk['content_block_delta']['delta']['text']
                            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            raise RuntimeError(f"Bedrock API error ({error_code}): {error_message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error in Bedrock stream: {str(e)}")

    async def generate_with_metadata(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Generate a response with metadata using AWS Bedrock.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters

        Returns:
            Dictionary containing response and metadata
        """
        start_time = time.time()
        
        try:
            # Prepare messages for Claude
            messages = []
            if system_prompt:
                messages.append({
                    "role": "user",
                    "content": system_prompt
                })
            messages.append({
                "role": "user",
                "content": prompt
            })
            
            # Prepare request body
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens or settings.llm_max_tokens,
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "messages": messages
            }
            
            # Call Bedrock
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.bedrock_runtime.invoke_model(
                    modelId=self.model,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body)
                )
            )
            
            # Parse response
            response_body = json.loads(response['body'].read())
            
            # Extract text
            text = ""
            if 'content' in response_body and len(response_body['content']) > 0:
                text = response_body['content'][0]['text']
            
            # Extract usage metadata
            usage = response_body.get('usage', {})
            latency = time.time() - start_time
            
            return {
                'text': text,
                'metadata': {
                    'input_tokens': usage.get('input_tokens', 0),
                    'output_tokens': usage.get('output_tokens', 0),
                    'total_tokens': usage.get('input_tokens', 0) + usage.get('output_tokens', 0),
                    'latency_seconds': latency,
                    'model': self.model,
                    'region': self.region
                }
            }
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            raise RuntimeError(f"Bedrock API error ({error_code}): {error_message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error in Bedrock generate_with_metadata: {str(e)}")

