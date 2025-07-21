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
        """Extracts user and assistant messages from msg_data"""
        conversations = []
        try:
            if not msg_data:
                return conversations
                
            for msg_id, msg in msg_data.items():
                try:
                    timestamp = datetime.fromtimestamp(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    content = msg['content']
                    if msg['role'] == 'assistant' and 'content_list' in msg:
                        for content_item in msg['content_list']:
                            if content_item['phase'] == 'answer' and content_item['status'] == 'finished':
                                content = content_item['content']
                                break
                    
                    sources = msg.get('webSearchInfo', [])
                    sources_dict = {f"source_{i}": src for i, src in enumerate(sources)} if sources else {}
                    suggestions = msg.get('suggest', [])
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
                        'sources': json.dumps(sources_dict, ensure_ascii=False) if msg['role'] == 'assistant' else '',
                        'suggestions': json.dumps(suggestions_dict, ensure_ascii=False) if msg['role'] == 'assistant' else '',
                        'extra_data': json.dumps({
                            'models': msg.get('models', []),
                            'feature_config': msg.get('feature_config', {}),
                            'user_action': msg.get('user_action', ''),
                            'done': msg.get('done', False)
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
                fieldnames = new_conversations[0].keys()
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
            
            # Enable performance logging
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            
            if headless:
                options.add_argument('--headless=new')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            
            # Add these additional arguments for better logging support
            options.add_argument('--enable-logging')
            options.add_argument('--v=1')
            
            # Get the correct ChromeDriver version
            driver_manager = ChromeDriverManager().install()
            
            # Initialize WebDriver with the configured options
            self.driver = webdriver.Chrome(
                service=ChromeService(driver_manager),
                options=options
            )
            
            # Set implicit wait (fallback)
            self.driver.implicitly_wait(10)
            
            # Verify Chrome and ChromeDriver versions
            print(f"Browser version: {self.driver.capabilities['browserVersion']}")
            print(f"ChromeDriver version: {self.driver.capabilities['chrome']['chromedriverVersion'].split(' ')[0]}")
            
        except Exception as e:
            self.logger._log_error(f"Error initializing driver: {e}")
            raise
    def login(self):
        """Log in to QWen chat interface (kept as original)"""
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
            
            sleep(5)
            self.is_logged_in = True  # Mark as logged in
            logger.info("Login completed")
            
        except Exception as e:
            self.logger._log_error(f"Error during login: {e}")
            raise

    def _find_element_by_attribute(self, tag_name, attr_name, attr_value):
        """Helper method to find elements by attribute (kept as original)"""
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
            logger.info("New conversation started")
        except TimeoutException:
            self.logger._log_error("New conversation button not found")
            raise
    def clean_query(self, query):
        # Reemplazar múltiples saltos de línea por un solo espacio
        cleaned = re.sub(r'\n+', ' ', query)  # Elimina saltos de línea
        cleaned = re.sub(r'\s+', ' ', cleaned)  # Elimina espacios múltiples
        return cleaned.strip()
    def query(self, query_text, web_search=True, session_id=None):
        """Public API-like method to send a query and get a response"""
        try:
            logger.info(f"Processing query: {query_text[:50]}...")
            logger.debug(f"Current URL: {self.driver.current_url}")
            
            # Only login if not already logged in
            if not self.is_logged_in:
                self.login()
            
            # Generate new session_id if not provided
            if session_id is None:
                session_id = str(uuid.uuid4())
                self.sessions[session_id] = []
                logger.info(f"Created new session: {session_id}")
                self.start_new_conversation()  # Start a new QWen conversation
            else:
                if session_id not in self.sessions:
                    self.sessions[session_id] = []
                    logger.info(f"Created new session: {session_id}")
                    self.start_new_conversation()  # Start a new QWen conversation
                else:
                    logger.info(f"Continuing session: {session_id}")
            
            # Ensure we're on a valid chat page (base URL or conversation URL)
            current_url = self.driver.current_url
            if not (current_url.startswith("https://chat.qwen.ai/") or 
                    current_url.startswith("https://chat.qwen.ai/c/")):
                logger.info("Navigating to base chat page")
                self.driver.get("https://chat.qwen.ai/")
                sleep(2)  # Wait for page to load
            
            # Enable/disable web search
            if web_search:
                self.enable_web_search()
            else:
                self.disable_web_search()
            
            # Send query and get response
            msg_data = self.send_query(query_text)
            conversations = self.logger.extract_conversation_data(msg_data)
            
            # Update session and save to CSV
            self.sessions[session_id].extend(conversations)
            self.logger.save_to_csv(conversations, session_id)
            
            # Return the latest assistant response
            assistant_response = next(
                (conv['content'] for conv in conversations if conv['role'] == 'assistant'),
                "No assistant response found"
            )
            logger.info(f"Query processed successfully for session {session_id}")
            return {
                'session_id': session_id,
                'response': assistant_response,
                'conversations': conversations
            }
            
        except Exception as e:
            self.logger._log_error(f"Error in query: {e}")
            raise

    def send_query(self, query):
        """Send a query to the chat interface and wait for response"""
        try:
            logger.info("Sending query")
            query_element = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'chat-input'))
            )
            query_element.click()
            query_element.clear()
            # Send text in chunks

            clean_text = self.clean_query(query)
            # for chunk in [query[i:i+500] for i in range(0, len(query), 500)]:
            #     query_element.send_keys(chunk)
            #     print(chunk)
            #     sleep(10)  # Small delay between chunks
            #     query_element = WebDriverWait(self.driver, 10).until(
            #     EC.presence_of_element_located((By.ID, 'chat-input'))
            # )
            query_element.send_keys(clean_text)
            
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'send-message-button'))
            )
            submit_button.click()
            logger.info("Query submitted")
            
            self._wait_for_response()
            return self._get_response_data()
            
        except TimeoutException:
            self.logger._log_error("Timeout while sending query")
            raise
        except Exception as e:
            self.logger._log_error(f"Error sending query: {e}")
            raise

    def _wait_for_response(self):
        """Wait for the response to complete, checking loading button as in original"""
        try:
            logger.info("Waiting for response")
            while True:
                try:
                    loading_button = self.driver.find_element(
                        By.CSS_SELECTOR, 'i.iconfont.leading-none.icon-StopIcon.\\!text-30'
                    )
                    logger.debug("Loading button still present, waiting...")
                    sleep(1)
                except:
                    logger.info("Loading button no longer present")
                    break
            logger.info("Response loaded")
            sleep(5)  # Original buffer to ensure response is fully processed
        except Exception as e:
            self.logger._log_error(f"Error waiting for response: {e}")
            raise

    def _get_response_data(self) -> dict:
        """Extract response data from performance logs"""
        try:
            sleep(2)# Ensure logs are fully populated
            # First ensure performance logs are available
            if 'performance' not in self.driver.log_types:
                self.logger._log_error("Performance logs not available")
                return {}
                
            logs = self.driver.get_log('performance')
            msg_data = {}
            
            for entry in logs:
                try:
                    log = json.loads(entry['message'])
                    message = log.get('message', {})

                    print(message)
                    
                    if message.get('method') == 'Network.requestWillBeSent':
                        request = message.get('params', {}).get('request', {})
                        if request.get('method') == 'POST' and 'chat' in request.get('url', ''):
                            post_data = request.get('postData')
                            if post_data:
                                try:
                                    post_data_json = json.loads(post_data)
                                    chat_data = post_data_json.get('chat', {})
                                    history = chat_data.get('history', {})
                                    if 'messages' in history:
                                        msg_data.update(history['messages'])
                                except json.JSONDecodeError:
                                    continue
                                    
                except (KeyError, json.JSONDecodeError, TypeError) as e:
                    self.logger._log_error(f"Error processing log entry: {e}")
                    continue
                    
            return msg_data
            
        except Exception as e:
            self.logger._log_error(f"Error getting response data: {e}")
            return {}
    def close(self):
        """Clean up resources (kept as original)"""
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
            
            result = bot.query("""
Please act as an expert stock market analyst. Your task consists of two parts:
. Consider that the current price is 118.000 and the asset is bitcoin usdt.
Up-to-date News Summary:
Find and summarize the 10-15 most relevant news articles about this Bitcoin from the last week. This is very important, the news MUST BE RECENT.
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
- SL: [...] (reason)""", web_search=True)
            print(f"Session: {result['session_id']}")
            print(f"Response: {result['response'][:50]}...")
            
            # Continue the same session
            result = bot.query("Tell me the same but now with ETH", web_search=True, session_id=result['session_id'])
            print(f"Session: {result['session_id']}")
            print(f"Response: {result['response'][:50]}...")
            
            # # Start a new session without web search
            # result = bot.query("tell me about jobs on europe and how to get an easy visa being from latin america and knowing english and programming", web_search=False)
            # print(f"New Session: {result['session_id']}")
            # print(f"Response: {result['response'][:50]}...")
                
    except Exception as e:
        logger.error(f"Fatal error occurred: {e}")
        logger.error(traceback.format_exc())