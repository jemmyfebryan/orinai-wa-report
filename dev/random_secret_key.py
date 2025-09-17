from dev.create_user import generate_api_token
import asyncio

if __name__ == '__main__':
    dummy_user_result = asyncio.run(generate_api_token(length=16))
    print(dummy_user_result)