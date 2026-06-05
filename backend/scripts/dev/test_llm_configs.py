#!/usr/bin/env python3
"""
Test script for LLM configurations
Tests all configured LLMs to verify API keys work
"""
import asyncio
import sys
sys.path.insert(0, '/app/src')

from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI
from llm import LLMService, LLMRepository

async def test_llm_configs():
    """Test all LLM configurations"""
    print("=" * 60)
    print("LLM Configuration Test Script")
    print("=" * 60)
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client["blackbar"]
    
    service = LLMService(db)
    repo = LLMRepository(db)
    
    # Get all configs
    configs = await repo.list_all()
    
    if not configs:
        print("\n❌ No LLM configurations found. Run seed script first.")
        return
    
    print(f"\nFound {len(configs)} LLM configuration(s)\n")
    
    # Test each config
    for config in configs:
        print(f"\n{'=' * 60}")
        print(f"Testing: {config.name}")
        print(f"{'=' * 60}")
        print(f"Provider: {config.request_format.value}")
        print(f"Model: {config.model_name}")
        print(f"Endpoint: {config.api_endpoint}")
        print(f"Enabled: {config.enabled}")
        
        if not config.enabled:
            print("⏭️  Skipped (disabled)")
            continue
        
        try:
            # Test with simple message
            messages = [
                {"role": "user", "content": "Say 'test successful' if you can read this."}
            ]
            
            print("\nSending test message...")
            response = await service.make_llm_call(
                config,
                messages,
                temperature=0,
                max_tokens=20
            )
            
            # Extract text based on format
            if config.request_format.value == "openai":
                text = response['choices'][0]['message']['content']
            elif config.request_format.value == "anthropic":
                text = response['content'][0]['text']
            elif config.request_format.value == "google":
                text = response['candidates'][0]['content']['parts'][0]['text']
            elif config.request_format.value == "cohere":
                text = response['text']
            else:
                text = str(response)
            
            print(f"✅ SUCCESS!")
            print(f"Response: {text[:100]}...")
            
        except Exception as e:
            print(f"❌ FAILED: {str(e)}")
    
    print(f"\n{'=' * 60}")
    print("Test Complete!")
    print(f"{'=' * 60}\n")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(test_llm_configs())
