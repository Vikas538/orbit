import time
import json
from typing import List, Dict
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright
import os

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
# --- BROWSER ENGINE ---
browser_context = {"browser": None, "page": None, "playwright": None}

def get_browser(target_url):
    if not browser_context["page"]:
        pw = sync_playwright().start()
        print("===================>")
        # headless=False is a must so you can watch it fill!
        browser = pw.chromium.connect_over_cdp(endpoint_url="http://localhost:9222") 
        print("========.")
        context = browser.contexts[0]
        print("==========================>")
        existing_page = None
        for p in context.pages:
            if target_url in p.url:
                existing_page = p
                break
        if existing_page:
            print(f"Found existing tab for {target_url}. Switching to it...")
            existing_page.bring_to_front()
            page = existing_page
        
        page = context.new_page() if not existing_page else existing_page
        browser_context["playwright"] = pw
        browser_context["browser"] = browser
        browser_context["page"] = page
    return browser_context["page"]

# --- THE TOOLS ---

def fetch_cleaned_dom(url: str) -> str:
    """Navigates to a URL and returns a simplified version of the DOM for the AI to read."""
    page = get_browser(url)
    print(f"--- Navigating to: {url} ---")
    page.goto(url, wait_until="networkidle")
    
    # Extract only interactive elements
    elements = page.query_selector_all("input, button, textarea, select, label,a,class")
    dom_summary = []
    
    for el in elements:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        e_id = el.get_attribute("id")
        e_name = el.get_attribute("name")
        e_type = el.get_attribute("type")
        e_text = el.inner_text().strip()
        
        # We give the AI clear selectors
        selector = f"#{e_id}" if e_id else (f"[name='{e_name}']" if e_name else tag)
        e_class = el.get_attribute("class") or ""

        dom_summary.append({
            "element": tag,
            "selector": selector,
            "type": e_type,
            "placeholder": el.get_attribute("placeholder") or "",
            "text":e_text,
            "href":el.get_attribute("href") or "",
            "classes":e_class
        })

    print(dom_summary)
    return json.dumps(dom_summary)

def run_browser_actions(actions: List[Dict[str, str]]) -> str:
    """Executes a sequence of fill, click, or submit actions on the page."""
    page = browser_context["page"]
    execution_log = []

    print("===========================>",actions)
    
    for action in actions:
        a_type = action.get("action")
        selector = action.get("selector") or action.get('element_selector')
        value = action.get("value", "")

        try:
            # Wait for the element to ensure it's actually there before acting
            page.wait_for_selector(selector, state="visible", timeout=100000)
            
            if a_type == "fill":
                page.hover(selector)        # mouse moves to element
                page.click(selector)        # then clicks it
                page.fill(selector, value)  # then fills it
                execution_log.append(f"Successfully filled {selector}")

            elif a_type == "click":
                page.hover(selector)        # mouse moves first
                time.sleep(0.3)             # small delay so you can see it
                page.click(selector)
                execution_log.append(f"Successfully clicked {selector}")

            elif a_type == "submit":
                # Most robust way to submit
                page.locator(selector).dispatch_event("submit")
                execution_log.append(f"Successfully submitted form {selector}")

            elif a_type == "hover":
                page.hover(selector)
                page.wait_for_timeout(500)  # wait for dropdown to appear
                execution_log.append(f"Successfully hovered {selector}")


            
            time.sleep(0.5) # VISUAL DELAY so you can see it happen
        except Exception as e:
            msg = f"FAILED on {selector}: {str(e)}"
            print(msg)
            execution_log.append(msg)
            
    return json.dumps(execution_log)

# --- AI SETUP ---
client = genai.Client(api_key=GEMINI_API_KEY)

chat = client.chats.create(
    model="gemini-2.0-flash",
    config=types.GenerateContentConfig(
        tools=[fetch_cleaned_dom, run_browser_actions],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
    )
)

# --- EXECUTION ---
# Be very specific in the prompt to avoid hallucinations
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


try:
    response = chat.send_message(prompt)
    print("\n--- AI Result ---")
    print(response.text)
    time.sleep(10) # Time to see the final state
finally:
    if browser_context["browser"]:
        browser_context["browser"].close()
        browser_context["playwright"].stop()

