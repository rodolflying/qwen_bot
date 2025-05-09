import csv
import json
import os
import traceback
from datetime import datetime
from time import sleep
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
import dotenv
import locale

class QWenChatLogger:
    """Handles conversation logging to CSV files"""
    
    def __init__(self):
        self.ensure_output_folder()
        
    def ensure_output_folder(self):
        """Create outputs folder if it doesn't exist"""
        try:
            os.makedirs('outputs', exist_ok=True)
        except Exception as e:
            self._log_error(f"Error creating outputs folder: {e}")
            raise

    def get_output_filename(self):
        """Generate filename with current date"""
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            return f'outputs/qwen_conversation_{date_str}.csv'
        except Exception as e:
            self._log_error(f"Error generating output filename: {e}")
            raise

    def extract_conversation_data(self, msg_data):
        """
        Extracts both user and assistant messages from the msg_data structure
        Returns a list of message dictionaries ready for CSV storage
        """
        conversations = []
        
        try:
            if not msg_data:
                return conversations
                
            for msg_id, msg in msg_data.items():
                try:
                    # Convert timestamp to readable format
                    timestamp = datetime.fromtimestamp(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Prepare sources data (only for assistant messages)
                    sources = msg.get('webSearchInfo', [])
                    sources_dict = {f"source_{i}": src for i, src in enumerate(sources)} if sources else {}
                    
                    # Prepare suggestions data (only for assistant messages)
                    suggestions = msg.get('suggest', [])
                    suggestions_dict = {"suggestions": suggestions} if suggestions else {}
                    
                    # Create conversation entry
                    conversation = {
                        'id': msg_id,
                        'parent_id': msg.get('parentId'),
                        'role': msg['role'],
                        'content': msg['content'],
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

    def save_to_csv(self, conversations):
        """
        Saves conversation data to CSV file with date in the outputs folder
        """
        try:
            if not conversations:
                print("No conversation data to save")
                return
            
            filename = self.get_output_filename()
            file_exists = os.path.isfile(filename)
            
            with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = conversations[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerows(conversations)
            
            print(f"Conversation data saved to {filename}")
            
        except Exception as e:
            self._log_error(f"Error saving to CSV: {e}")
            raise

    def _log_error(self, message):
        """Logs errors with traceback information"""
        error_msg = f"ERROR: {message}\n{traceback.format_exc()}"
        print(error_msg)
        # You could also log to a file here if desired


class QWenChatBot:
    """Handles interaction with QWen chat interface"""
    
    def __init__(self, headless=False):
        self.driver = None
        self.logger = QWenChatLogger()
        self.initialize_driver(headless)
        
    def initialize_driver(self, headless):
        """Initialize the Selenium WebDriver"""
        try:
            # Set Chilean locale
            locale.setlocale(locale.LC_TIME, 'es_CL.UTF-8')
            
            # Load environment variables
            dotenv.load_dotenv()
            
            # Configure Chrome options
            options = Options()
            if headless:
                options.add_argument('--headless=new')
                
            capabilities = DesiredCapabilities.CHROME
            capabilities['goog:loggingPrefs'] = {'performance': 'ALL'}
            
            # Initialize WebDriver
            self.driver = webdriver.Chrome(
                options=options,
                service=ChromeService(ChromeDriverManager().install()),
                desired_capabilities=capabilities
            )
            
        except Exception as e:
            self.logger._log_error(f"Error initializing driver: {e}")
            raise

    def login(self):
        """Log in to QWen chat interface"""
        try:
            self.driver.get("https://chat.qwen.ai/auth?action=signin")
            sleep(2)
            
            user = os.getenv("USER")
            password = os.getenv("PASS")
            
            if not user or not password:
                raise ValueError("USER or PASS environment variables not set")
            
            # Find and fill username
            username = self._find_element_by_attribute('input', 'type', 'email')
            username.send_keys(user)
            
            # Find and fill password
            password_input = self._find_element_by_attribute('input', 'type', 'password')
            password_input.send_keys(password)
            
            # Find and click submit button
            submit_button = self._find_element_by_attribute('button', 'type', 'submit')
            submit_button.click()
            
            sleep(5)
            
        except Exception as e:
            self.logger._log_error(f"Error during login: {e}")
            raise

    def _find_element_by_attribute(self, tag_name, attr_name, attr_value):
        """Helper method to find elements by attribute"""
        elements = self.driver.find_elements(By.TAG_NAME, tag_name)
        for element in elements:
            if element.get_attribute(attr_name) == attr_value:
                return element
        raise Exception(f"Element not found: {tag_name} with {attr_name}={attr_value}")

    def enable_web_search(self):
        """Enable web search functionality"""
        try:
            web_search_button = self.driver.find_element(
                By.XPATH,
                '//button[.//span[text()="Поиск"]]//i[@class="iconfont leading-none icon-line-globe-01 chat-input-feature-btn-icon"]'
            )
            web_search_button.click()
        except Exception as e:
            self.logger._log_error(f"Error enabling web search: {e}")
            raise

    def send_query(self, query):
        """Send a query to the chat interface and wait for response"""
        try:
            # Find and fill query input
            query_element = self._find_element_by_attribute('textarea', 'id', 'chat-input')
            query_element.send_keys(query)
            
            # Submit query
            submit_button = self.driver.find_element(By.XPATH, '//*[@id="send-message-button"]')
            submit_button.click()
            sleep(1)
            
            # Wait for response to complete
            self._wait_for_response()
            
            # Get and process response
            return self._get_response_data()
            
        except Exception as e:
            self.logger._log_error(f"Error sending query: {e}")
            raise

    def _wait_for_response(self):
        """Wait for the response to complete"""
        try:
            while True:
                loading_button = None
                elements = self.driver.find_elements(By.TAG_NAME, 'i')
                
                for element in elements:
                    try:
                        if element.get_attribute('class') == 'iconfont leading-none icon-StopIcon !text-30':
                            loading_button = element
                            break
                    except StaleElementReferenceException:
                        print("Stale element reference exception")
                        loading_button = None
                        break
                
                if loading_button:
                    sleep(1)
                    print("...")
                else:
                    break
            
            print("Answer loaded")
            sleep(5)
            
        except Exception as e:
            self.logger._log_error(f"Error waiting for response: {e}")
            raise

    def _get_response_data(self):
        """Extract response data from performance logs"""
        try:
            logs = self.driver.get_log('performance')
            msg_data = {}
            
            for entry in logs:
                try:
                    log_message = json.loads(entry['message'])
                    message = log_message.get('message', {})
                    
                    if message.get('method') == 'Network.requestWillBeSent':
                        post_data = message["params"]["request"].get("postData", "")
                        if post_data:
                            post_data_json = json.loads(post_data)
                            history_messages = post_data_json["chat"]["history"]
                            msg_data.update(history_messages)
                            
                except (KeyError, json.JSONDecodeError, TypeError) as e:
                    self.logger._log_error(f"Error processing log entry: {e}")
                    continue
                    
            return msg_data
            
        except Exception as e:
            self.logger._log_error(f"Error getting response data: {e}")
            raise

    def close(self):
        """Clean up resources"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception as e:
            self.logger._log_error(f"Error closing driver: {e}")

    def run_conversation(self, query):
        """Complete conversation workflow"""
        try:
            self.login()
            self.enable_web_search()
            msg_data = self.send_query(query)
            
            if msg_data:
                conversations = self.logger.extract_conversation_data(msg_data)
                self.logger.save_to_csv(conversations)
                print("Conversation completed successfully")
                return conversations
            else:
                print("No conversation data found in logs")
                return None
                
        except Exception as e:
            self.logger._log_error(f"Error in conversation workflow: {e}")
            raise
        finally:
            self.close()


if __name__ == "__main__":
    try:
        # Example usage
        bot = QWenChatBot(headless=False)
        query = "What are the files that i need to deploy a web site on github pages? give me a minimal example"
        conversations = bot.run_conversation(query)
        
        if conversations:
            print("Saved conversations:")
            for conv in conversations:
                print(f"{conv['role']}: {conv['content'][:50]}...")
                
    except Exception as e:
        print(f"Fatal error occurred: {e}")
        print(traceback.format_exc())
