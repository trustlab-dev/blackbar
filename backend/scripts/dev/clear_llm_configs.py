#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/app/src')
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI

async def clear():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client['blackbar']
    await db.llm_configs.delete_many({})
    await db.system_config.delete_one({'id': 'global_llm_config'})
    print('✅ Cleared all LLM configurations')
    client.close()

asyncio.run(clear())
