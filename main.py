import csv
import json
import os
import re
import uuid
import traceback
from datetime import datetime
from time import sleep
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import dotenv
import locale
import logging
import requests

# Set up logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class QWenChatLogger:
    """Handles conversation logging to CSV files"""
    
    def __init__(self, output_dir='outputs'):
        self.output_dir = output_dir
        self.ensure_output_folder()
        
    def ensure_output_folder(self):
        """Create outputs folder if it doesn't exist"""
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception as e:
            self._log_error(f"Error creating outputs folder: {e}")
            raise

    def get_output_filename(self, session_id):
        """Generate filename for a session"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.output_dir, f'session_{session_id}_{date_str}.csv')

    def get_existing_message_ids(self, session_id):
        """Read existing message IDs from the session's CSV file"""
        filename = self.get_output_filename(session_id)
        existing_ids = set()
        if os.path.isfile(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if 'id' in row:
                            existing_ids.add(row['id'])
            except Exception as e:
                self._log_error(f"Error reading existing message IDs from {filename}: {e}")
        return existing_ids


    def extract_conversation_data(self, msg_data):
        """Extracts user and assistant messages from msg_data based on the new API response structure."""
        conversations = []
        try:
            if not msg_data:
                return conversations
                
            for msg_id, msg in msg_data.items():
                try:
                    timestamp = datetime.fromtimestamp(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    content = msg.get('content', '') # Direct content for user/assistant messages
                    
                    sources_dict = {}
                    suggestions_dict = {}

                    if msg['role'] == 'assistant':
                        # Extract final answer content from content_list if available
                        if 'content_list' in msg:
                            for content_item in msg['content_list']:
                                if content_item.get('phase') == 'answer' and content_item.get('status') == 'finished':
                                    content = content_item.get('content', content) # Use this content, fallback to direct 'content'
                                # Extract web search info from content_list if available
                                if content_item.get('phase') == 'web_search':
                                    web_search_info = content_item.get('extra', {}).get('web_search_info', [])
                                    sources_dict = {f"source_{i}": src for i, src in enumerate(web_search_info)} if web_search_info else {}
                        
                        # Extract suggestions from 'info' field
                        suggestions = msg.get('info', {}).get('suggest', [])
                        suggestions_dict = {"suggestions": suggestions} if suggestions else {}
                    
                    conversation = {
                        'id': msg_id,
                        'parent_id': msg.get('parentId'),
                        'role': msg['role'],
                        'content': content,
                        'timestamp': timestamp,
                        'model': msg.get('model', ''),
                        'model_name': msg.get('modelName', ''),
                        'chat_type': msg.get('chat_type', ''),
                        'sources': json.dumps(sources_dict, ensure_ascii=False) if sources_dict else '',
                        'suggestions': json.dumps(suggestions_dict, ensure_ascii=False) if suggestions_dict else '',
                        'extra_data': json.dumps({
                            'models': msg.get('models', []),
                            'feature_config': msg.get('feature_config', {}),
                            'user_action': msg.get('user_action', ''),
                            'done': msg.get('done', False),
                            # Any other relevant 'extra' fields from the root message might go here
                            'meta': msg.get('meta', {})
                        }, ensure_ascii=False)
                    }
                    conversations.append(conversation)
                except Exception as e:
                    self._log_error(f"Error processing message {msg_id}: {e}")
                    continue
        except Exception as e:
            self._log_error(f"Error extracting conversation data: {e}")
            raise
        return conversations

    def save_to_csv(self, conversations, session_id):
        """Saves conversation data to a session-specific CSV file, avoiding duplicates"""
        try:
            if not conversations:
                logger.info("No conversation data to save")
                return
            
            # Get existing message IDs to avoid duplicates
            existing_ids = self.get_existing_message_ids(session_id)
            new_conversations = [conv for conv in conversations if conv['id'] not in existing_ids]
            
            if not new_conversations:
                logger.info(f"No new messages to save for session {session_id}")
                return
            
            filename = self.get_output_filename(session_id)
            file_exists = os.path.isfile(filename)
            
            with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = list(new_conversations[0].keys()) # Ensure fieldnames are ordered
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerows(new_conversations)
            
            logger.info(f"Saved {len(new_conversations)} new messages to {filename}")
            
        except Exception as e:
            self._log_error(f"Error saving to CSV: {e}")
            raise

    def _log_error(self, message):
        """Logs errors with traceback information"""
        error_msg = f"ERROR: {message}\n{traceback.format_exc()}"
        logger.error(error_msg)
        with open(os.path.join(self.output_dir, 'error.log'), 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()}: {error_msg}\n")


class QWenChatBot:
    """Handles interaction with QWen chat interface"""
    
    def __init__(self, headless=False):
        self.driver = None
        self.logger = QWenChatLogger()
        self.sessions = {}  # Store session data {session_id: [messages]}
        self.web_search_enabled = False
        self.is_logged_in = False  # Track login state
        self.initialize_driver(headless)

    def initialize_driver(self, headless: bool):
        """Initialize the Selenium WebDriver with proper settings"""
        try:
            locale.setlocale(locale.LC_TIME, 'es_CL.UTF-8')
            dotenv.load_dotenv()
            
            options = Options()
            
            # Performance logs are no longer strictly needed for data extraction, but can be kept for debugging
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'}) 
            
            if headless:
                options.add_argument('--headless=new')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            
            options.add_argument('--enable-logging')
            options.add_argument('--v=1')
            
            driver_manager = ChromeDriverManager().install()
            
            self.driver = webdriver.Chrome(
                service=ChromeService(driver_manager),
                options=options
            )
            
            self.driver.implicitly_wait(10)
            
            print(f"Browser version: {self.driver.capabilities['browserVersion']}")
            print(f"ChromeDriver version: {self.driver.capabilities['chrome']['chromedriverVersion'].split(' ')[0]}")
            
        except Exception as e:
            self.logger._log_error(f"Error initializing driver: {e}")
            raise
            
    def login(self):
        """Log in to QWen chat interface"""
        try:
            logger.info("Starting login process")
            self.driver.get("https://chat.qwen.ai/auth?action=signin")
            sleep(2)
            
            user = os.getenv("USER")
            password = os.getenv("PASS")
            
            if not user or not password:
                raise ValueError("USER or PASS environment variables not set")
            
            username = self._find_element_by_attribute('input', 'type', 'email')
            username.send_keys(user)
            
            password_input = self._find_element_by_attribute('input', 'type', 'password')
            password_input.send_keys(password)
            
            submit_button = self._find_element_by_attribute('button', 'type', 'submit')
            submit_button.click()
            
            sleep(5) # Give time for login to complete and redirect
            self.is_logged_in = True  # Mark as logged in
            logger.info("Login completed")
            
        except Exception as e:
            self.logger._log_error(f"Error during login: {e}")
            raise

    def _get_conversation_id_from_url(self) -> str | None:
        """Extracts the conversation ID (the hash) from the current URL."""
        current_url = self.driver.current_url
        match = re.search(r'https://chat\.qwen\.ai/c/([a-f0-9-]+)', current_url)
        if match:
            conversation_id = match.group(1)
            logger.info(f"Extracted conversation ID from URL: {conversation_id}")
            return conversation_id
        logger.warning(f"Could not extract conversation ID from URL: {current_url}")
        return None

    def _get_browser_cookies(self) -> str:
        """Extracts cookies from the current Selenium session and formats them for requests."""
        cookies = self.driver.get_cookies()
        formatted_cookies = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
        logger.debug(f"Extracted cookies: {formatted_cookies[:100]}...") # Log first 100 chars
        return formatted_cookies
    
    def _find_element_by_attribute(self, tag_name, attr_name, attr_value):
        """Helper method to find elements by attribute"""
        elements = self.driver.find_elements(By.TAG_NAME, tag_name)
        for element in elements:
            if element.get_attribute(attr_name) == attr_value:
                return element
        raise Exception(f"Element not found: {tag_name} with {attr_name}={attr_value}")

    def enable_web_search(self):
        """Enable web search functionality with robust waiting"""
        if self.web_search_enabled:
            return
        try:
            logger.info("Enabling web search")
            web_search_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'icon-line-globe-01'))
            )
            web_search_button.click()
            self.web_search_enabled = True
            logger.info("Web search enabled")
        except TimeoutException:
            self.logger._log_error("Web search button not found")
            raise

    def disable_web_search(self):
        """Disable web search functionality"""
        if not self.web_search_enabled:
            return
        try:
            logger.info("Disabling web search")
            web_search_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'icon-line-globe-01'))
            )
            web_search_button.click()
            self.web_search_enabled = False
            logger.info("Web search disabled")
        except TimeoutException:
            self.logger._log_error("Web search button not found")
            raise

    def start_new_conversation(self):
        """Start a new QWen conversation by clicking the New Conversation button"""
        try:
            logger.info("Starting new conversation")
            new_conversation_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'i.iconfont.leading-none.icon-line-plus-01.sidebar-new-chat-icon'))
            )
            new_conversation_button.click()
            sleep(2)  # Wait for the new conversation to initialize
            # Important: The URL won't immediately contain the session ID here. 
            # It will update after the first message is sent and a conversation is saved.
            logger.info("New conversation started in browser. ID will be captured after first query.")
        except TimeoutException:
            self.logger._log_error("New conversation button not found")
            raise
            
    def clean_query(self, query):
        # Replace multiple newlines with a single space and clean extra spaces
        cleaned = re.sub(r'\s+', ' ', query) 
        return cleaned.strip()

    def query(self, query_text, web_search=True, session_id=None):
        """Public API-like method to send a query and get a response"""
        try:
            logger.info(f"Processing query: {query_text[:50]}...")
            logger.debug(f"Current URL: {self.driver.current_url}")
            
            if not self.is_logged_in:
                self.login()
            
            current_conversation_id = self._get_conversation_id_from_url()
            
            # Logic to handle session_id:
            # 1. If no session_id is provided AND no ID in URL (first query of a new session)
            # 2. If session_id is provided and different from current URL ID (switching session)
            # 3. If session_id is provided and matches current URL ID (continuing session)
            # 4. If no session_id provided but ID exists in URL (re-running on existing chat tab)

            if session_id is None: # This is the first query for a potentially new or unknown session
                if not current_conversation_id: # Truly a new conversation flow
                    self.start_new_conversation()
                    # After starting new conversation, send query. The ID will appear in URL after response.
                    logger.info("No existing session ID. Starting fresh and will capture ID after response.")
                else: # Already on a conversation page, use its ID
                    session_id = current_conversation_id
                    logger.info(f"Detected existing session in browser: {session_id}. Using it.")
            elif session_id != current_conversation_id: # User wants to switch or start a specific session
                target_url = f"https://chat.qwen.ai/c/{session_id}"
                logger.info(f"Navigating to specified session URL: {target_url}")
                self.driver.get(target_url)
                sleep(3) # Give time to load existing chat
                # After navigating, confirm the ID matches or deal with potential redirects/errors
                if self._get_conversation_id_from_url() != session_id:
                    logger.warning(f"Navigated to {target_url} but current URL ID does not match {session_id}.")
                    # You might want to raise an error or try to create a new one, depending on desired robustness.
                    # For now, we'll proceed and let the API call fail if the ID is truly invalid.
            
            # Ensure web search setting is correct before sending query
            if web_search:
                self.enable_web_search()
            else:
                self.disable_web_search()
            
            # Send query via Selenium
            self.send_query(query_text)
            
            # After sending the query and waiting for response, *now* get the conversation ID
            # This is critical for new conversations where the ID isn't in the URL initially.
            final_session_id = self._get_conversation_id_from_url()
            if not final_session_id:
                raise Exception("Failed to obtain conversation ID from URL after sending query. Cannot fetch data via API.")
            
            # Update the internal session tracking if a new ID was found or confirmed
            if final_session_id not in self.sessions:
                self.sessions[final_session_id] = []
            
            # Fetch response data directly from the API using the confirmed conversation ID
            msg_data = self._get_response_data(final_session_id) 
            
            conversations = self.logger.extract_conversation_data(msg_data)
            
            # Update session and save to CSV
            self.sessions[final_session_id].extend(conversations)
            self.logger.save_to_csv(conversations, final_session_id)
            
            # Return the latest assistant response
            assistant_response = next(
                (conv['content'] for conv in conversations if conv['role'] == 'assistant'),
                "No assistant response found"
            )
            logger.info(f"Query processed successfully for session {final_session_id}")
            return {
                'session_id': final_session_id,
                'response': assistant_response,
                'conversations': conversations
            }
            
        except Exception as e:
            self.logger._log_error(f"Error in query: {e}")
            raise

    def send_query(self, query):
        """Send a query to the chat interface using Selenium."""
        try:
            logger.info("Sending query via Selenium")
            query_element = WebDriverWait(self.driver, 15).until( # Increased wait time
                EC.presence_of_element_located((By.ID, 'chat-input'))
            )
            query_element.click() # Ensure the input field is focused
            query_element.clear()
            
            clean_text = self.clean_query(query)
            query_element.send_keys(clean_text)
            
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'send-message-button'))
            )
            submit_button.click()
            logger.info("Query submitted via Selenium")
            
            self._wait_for_response() # Wait for the visual response in the browser
            
        except TimeoutException:
            self.logger._log_error("Timeout while sending query via Selenium")
            raise
        except Exception as e:
            self.logger._log_error(f"Error sending query via Selenium: {e}")
            raise

    def _wait_for_response(self):
        """Wait for the response to complete, checking loading button."""
        try:
            logger.info("Waiting for response completion in browser")
            # Wait for the "Stop" button (loading indicator) to disappear
            WebDriverWait(self.driver, 120).until_not( # Increased max wait to 120 seconds
                EC.presence_of_element_located((By.CSS_SELECTOR, 'i.iconfont.leading-none.icon-StopIcon.\\!text-30'))
            )
            logger.info("Loading button no longer present, response likely loaded.")
            sleep(5)  # A small buffer to ensure the page state is stable after response
        except TimeoutException:
            self.logger._log_error("Timeout waiting for response to complete (loading button did not disappear).")
            raise
        except Exception as e:
            self.logger._log_error(f"Error waiting for response completion: {e}")
            raise

    def _get_response_data(self, conversation_id: str) -> dict:
        """
        Fetches conversation data using a direct requests call to the API.
        Requires the conversation_id and browser cookies.
        """
        try:
            cookies = self._get_browser_cookies()
            if not cookies:
                raise Exception("No cookies found to make API request.")

            url = f"https://chat.qwen.ai/api/v2/chats/{conversation_id}"
            
            headers = {'Accept-Language': 'es-419,es;q=0.9,es-ES;q=0.8,en;q=0.7,en-GB;q=0.6,en-US;q=0.5,es-CL;q=0.4',
                'Connection': 'keep-alive',
                'Referer': 'https://chat.qwen.ai/c/36a48cf4-4cf8-4fdd-bcab-7ce17706bdb0',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
                'accept': 'application/json',
                'Cookie': cookies}
            
            # GET request usually doesn't need a payload, keeping for consistency if it ever changes
            payload = {} 

            logger.info(f"Fetching data from API for conversation ID: {conversation_id}")
            response = requests.get(url, headers=headers, data=payload)
            response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)

            api_response_json = response.json()
            logger.debug(f"API response: {json.dumps(api_response_json, indent=2)[:500]}...")

            if not api_response_json.get('success'):
                raise Exception(f"API call was not successful: {api_response_json.get('message', 'Unknown error')}")

            # Navigate the new JSON structure: data -> chat -> history -> messages
            msg_data = api_response_json.get('data', {}).get('chat', {}).get('history', {}).get('messages', {})
            
            if not msg_data:
                logger.warning(f"No messages found in API response for conversation ID: {conversation_id}")

            return msg_data
            
        except requests.exceptions.RequestException as e:
            self.logger._log_error(f"Error making requests call to get conversation data: {e}")
            traceback.print_exc()
            #get the exact line where of my code where it failed

            return {}
        except json.JSONDecodeError:
            self.logger._log_error(f"Failed to decode JSON from API response. Response text: {response.text[:200]}...")
            return {}
        except Exception as e:
            self.logger._log_error(f"Unexpected error in _get_response_data: {e}")
            return {}

    def close(self):
        """Clean up resources"""
        try:
            if self.driver:
                logger.info("Closing WebDriver")
                self.driver.quit()
                self.driver = None
        except Exception as e:
            self.logger._log_error(f"Error closing driver: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    try:
        with QWenChatBot(headless=False) as bot:
            # Start a new session
            print("Sending initial query...")
            initial_query_text = """
Please act as an expert stock market analyst. Your task consists of two parts:
. Consider that the current price is 443 and the asset is tesla.
Up-to-date News Summary:
Find and summarize the 10-15 most relevant news articles about this tesla share from the last week. This is very important, the news MUST BE RECENT.
Include the potential impact of each news item (positive/negative/neutral). Provide dates and sources when possible.
Technical Analysis and Prediction: Based on current news and market data:

Probable trend: (bullish/bearish/sideways)
Estimated probability: (e.g., 70% chance of increase)
Expected price range: (support/resistance)
Trading recommendation:
Ideal entry price
Take Profit (1-3 levels)
Stop Loss (with justification)
Time horizon: (intraday/short-term/medium-term)
Required format:
**News Summary**
1. [Summarized Title] - [Date/Source]
- [Impact]: [Brief explanation]
**Market Analysis**
- Trend: [...]
- Probabilidad: [...]
- Key Range: [...]
**Recommendation**
Can be short or long, depending on the trend and probability
- Entry: [...]
- TP: [...] (reason)
- SL: [...] (reason)"""
            
            result_initial = bot.query(initial_query_text, web_search=True)
            print(f"Initial Session ID: {result_initial['session_id']}")
            print(f"Initial Response: {result_initial['response'][:100]}...")
            
            # Continue the same session using the obtained session_id
            print("\nContinuing session with ETH query...")
            result_eth = bot.query("Tell me the same but now with XRP usdt", web_search=True, session_id=result_initial['session_id'])
            print(f"Continued Session ID: {result_eth['session_id']}")
            print(f"Response for ETH: {result_eth['response'][:100]}...")
            
    except Exception as e:
        logger.error(f"Fatal error occurred: {e}")
        logger.error(traceback.format_exc())