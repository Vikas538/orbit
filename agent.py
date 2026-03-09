import google.genai as genai
import os
from google.genai import types
import time
from tool import fetch_cleaned_dom, run_browser_actions

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
print("===========>",os.getenv("GEMINI_API_KEY"))
prompt  = """
You are a browser automation agent. You have access to fetch_cleaned_dom and run_browser_actions.

The app is at https://p99soft.keka.com/#/home/dashboard

User request: "Update my timesheet for today with 8 hours and comment Development work"

Follow this loop:
1. THINK: What do I need to do?
2. ACT: Call a tool
3. OBSERVE: Look at the result
4. THINK: Did it work? What's next?
5. Repeat until done

Never assume the DOM — always fetch before acting.
Never click something you haven't seen in the DOM.
"""

class Agent:
    def __init__(self) -> None:
        self.conversations =[]
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.agent = self.client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
        tools=[fetch_cleaned_dom, run_browser_actions],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    ))

    def start(self,task):
        response = self.agent.send_message(prompt)
        print("\n----AI-----")
        print(response.text)
        time.sleep(10)


# agent= Agent()
# agent.start("fill the time sheet in keka")
