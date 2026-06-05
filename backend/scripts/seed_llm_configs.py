#!/usr/bin/env python3
"""
Seed script for initial LLM configurations

Creates 4 default LLM configurations:
1. OpenAI GPT-4
2. Anthropic Claude Sonnet 4.5
3. Google Gemini 2.5
4. Cohere Command

Sets OpenAI GPT-4 as the global default.
"""
import asyncio
import sys
import os
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/app/src')

from config import MONGODB_URI
from llm import LLMConfigCreate, LLMRepository, LLMService, RequestFormat, LLMSettings


async def seed_llm_configs():
    """Seed initial LLM configurations"""
    print("=" * 60)
    print("LLM Configuration Seed Script")
    print("=" * 60)
    
    # Connect to MongoDB
    print("\nConnecting to MongoDB...")
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client["blackbar"]  # Shared database
    
    repo = LLMRepository(db)
    service = LLMService(db)
    
    # Check if configs already exist
    existing = await repo.list_all()
    if existing:
        print(f"\n⚠️  Found {len(existing)} existing LLM configuration(s):")
        for config in existing:
            print(f"  - {config.name} (ID: {config.id})")
        
        response = input("\nDo you want to proceed anyway? This will add more configs. (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            client.close()
            return
    
    # Get API keys from environment or prompt
    print("\n" + "=" * 60)
    print("API Key Configuration")
    print("=" * 60)
    print("\nPlease provide API keys for each LLM provider.")
    print("You can skip any provider by pressing Enter without a value.\n")
    
    openai_key = os.getenv("OPENAI_API_KEY") or input("OpenAI API Key: ").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or input("Anthropic API Key: ").strip()
    google_key = os.getenv("GOOGLE_API_KEY") or input("Google API Key: ").strip()
    cohere_key = os.getenv("COHERE_API_KEY") or input("Cohere API Key: ").strip()
    
    # Admin user ID (use 'system' for seed script)
    admin_user_id = "system"
    
    configs_created = []
    
    # 1. OpenAI GPT-4
    if openai_key:
        print("\nCreating OpenAI GPT-4 configuration...")
        openai_config = LLMConfigCreate(
            name="OpenAI GPT-4",
            enabled=True,
            api_endpoint="https://api.openai.com/v1/chat/completions",
            api_key=openai_key,
            model_name="gpt-4-turbo-preview",
            request_format=RequestFormat.OPENAI,
            default_settings=LLMSettings(
                temperature=0.7,
                max_tokens=4000,
                top_p=1.0
            ),
            notes="Primary LLM for production use"
        )
        
        config = await repo.create(openai_config, admin_user_id)
        configs_created.append(config)
        print(f"  ✅ Created: {config.name} (ID: {config.id})")
    else:
        print("\n  ⏭️  Skipping OpenAI GPT-4 (no API key provided)")
    
    # 2. Anthropic Claude Sonnet 4.5
    if anthropic_key:
        print("\nCreating Anthropic Claude Sonnet 4.5 configuration...")
        anthropic_config = LLMConfigCreate(
            name="Anthropic Claude Sonnet 4.5",
            enabled=True,
            api_endpoint="https://api.anthropic.com/v1/messages",
            api_key=anthropic_key,
            model_name="claude-sonnet-4.5-20241022",
            request_format=RequestFormat.ANTHROPIC,
            default_settings=LLMSettings(
                temperature=0.7,
                max_tokens=4000,
                top_p=1.0
            ),
            notes="Alternative LLM for privacy-conscious tenants"
        )
        
        config = await repo.create(anthropic_config, admin_user_id)
        configs_created.append(config)
        print(f"  ✅ Created: {config.name} (ID: {config.id})")
    else:
        print("\n  ⏭️  Skipping Anthropic Claude (no API key provided)")
    
    # 3. Google Gemini 2.5
    if google_key:
        print("\nCreating Google Gemini 2.5 configuration...")
        gemini_config = LLMConfigCreate(
            name="Google Gemini 2.5",
            enabled=True,
            api_endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
            api_key=google_key,
            model_name="gemini-2.5-pro",
            request_format=RequestFormat.GOOGLE,
            default_settings=LLMSettings(
                temperature=0.7,
                max_tokens=4000,
                top_p=1.0
            ),
            notes="Google's latest multimodal model"
        )
        
        config = await repo.create(gemini_config, admin_user_id)
        configs_created.append(config)
        print(f"  ✅ Created: {config.name} (ID: {config.id})")
    else:
        print("\n  ⏭️  Skipping Google Gemini (no API key provided)")
    
    # 4. Cohere Command
    if cohere_key:
        print("\nCreating Cohere Command configuration...")
        cohere_config = LLMConfigCreate(
            name="Cohere Command",
            enabled=True,
            api_endpoint="https://api.cohere.ai/v1/chat",
            api_key=cohere_key,
            model_name="command",
            request_format=RequestFormat.COHERE,
            default_settings=LLMSettings(
                temperature=0.7,
                max_tokens=4000,
                top_p=1.0
            ),
            notes="Cohere's command model for chat"
        )
        
        config = await repo.create(cohere_config, admin_user_id)
        configs_created.append(config)
        print(f"  ✅ Created: {config.name} (ID: {config.id})")
    else:
        print("\n  ⏭️  Skipping Cohere (no API key provided)")
    
    # Set global default to OpenAI GPT-4 if it was created
    if configs_created:
        # Find OpenAI config
        openai_config = next((c for c in configs_created if "OpenAI" in c.name), None)
        
        if openai_config:
            print("\n" + "=" * 60)
            print("Setting Global Default LLM")
            print("=" * 60)
            print(f"\nSetting '{openai_config.name}' as global default...")
            
            success = await service.set_default_llm(openai_config.id, admin_user_id)
            if success:
                print("  ✅ Global default LLM set successfully")
            else:
                print("  ❌ Failed to set global default")
        else:
            print("\n⚠️  OpenAI GPT-4 not created. Please set a global default manually.")
    
    # Summary
    print("\n" + "=" * 60)
    print("Seed Complete!")
    print("=" * 60)
    print(f"\nCreated {len(configs_created)} LLM configuration(s):")
    for config in configs_created:
        print(f"  - {config.name}")
    
    if not configs_created:
        print("\n⚠️  No configurations created. Please provide API keys and run again.")
    
    print("\n" + "=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("1. Verify configurations in admin panel")
    print("2. Test each LLM provider")
    print("3. Set tenant overrides as needed")
    print("\n")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_llm_configs())
