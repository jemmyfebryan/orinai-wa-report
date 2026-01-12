import asyncio

from src.orin_wa_report.core.utils import log_data

async def main():
    entry = {"id": 1, "user": "Alice", "tags": ["python", "async"]}
    await log_data('database.jsonl', entry)
    
    # Adding a completely different set of keys works instantly!
    entry_2 = {"id": 2, "user": "Bob", "active": True, "score": 95}
    await log_data('database.jsonl', entry_2)

if __name__ == "__main__":
    asyncio.run(main())