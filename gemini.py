import asyncio
import os
from langchain_google_genai import ChatGoogleGenerativeAI

async def check_gemini():
    print("Checking Gemini (gemini-1.5-pro)...")
    
    # Initialize the model
    # Note: Ensure GOOGLE_API_KEY is set in your environment variables
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key="AIzaSyCNfipGnordYd5vPntI4G5nOrIpiBs7dpE",
            temperature=0
        )
        
        # Simple test invocation
        response = await llm.ainvoke("Ping")
        
        print("\n" + "="*30)
        print(" SUCCESS: Gemini is online!")
        print(f" Response: {response.content}")
        print("="*30)
        
    except Exception as e:
        print("\n" + "="*30)
        print(" ❌ CONNECTION FAILED")
        
        error_msg = str(e)
        if "404" in error_msg:
            print(" Reason: Model name not found (404).")
            print(" Action: Check your API version or model string.")
        elif "API_KEY_INVALID" in error_msg:
            print(" Reason: Your API key is incorrect.")
        else:
            print(f" Error: {error_msg}")
        print("="*30)

if __name__ == "__main__":
    # If you haven't set the env var in your shell, uncomment the line below:
    # os.environ["GOOGLE_API_KEY"] = "YOUR_ACTUAL_KEY_HERE"
    
    asyncio.run(check_gemini())