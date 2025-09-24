# QWen Chatbot with Robust Web Search Scraping

This Python script automates interaction with the QWen chat interface ([https://chat.qwen.ai/](https://chat.qwen.ai/)) and provides a robust method for capturing conversation data, including information from web searches. Web search is optional, and now you can use conversational mode to continue conversations within the same session.

## Key Features

- **Conversational Mode**: Supports multi-turn conversations within the same session, allowing follow-up questions to maintain context, and starts new conversations for new sessions.
- **Web Search Integration**: Automatically enables or disables QWen's web search functionality as needed.
- **Robust Scraping**: Captures conversation data by intercepting Fetch/XHR network requests (`Network.requestWillBeSent` events) made by QWen's backend, making it resilient to UI changes compared to DOM scraping.
- **Performance Optimized**: Directly accessing API responses is faster and more efficient than parsing the entire DOM.
- **Comprehensive Data Logging**: Saves user queries, assistant responses, timestamps, model details, web search sources, and suggested follow-up questions to CSV files, with duplicate prevention.
- **Session Management**: Uses session IDs to organize conversations, appending new messages to the same CSV for continued sessions and creating new CSVs for new sessions.
- **JSONCrack Insights**: Development leveraged JSONCrack to visualize and understand the structure of QWen's API responses.
- **Captcha Mitigation**: Uses standard QWen account credentials (email and password) to minimize CAPTCHA risks, avoiding Google or other automatic authentication.
- **Data Export**: Saves conversation data to session-specific CSV files (`session_<session_id>.csv`) in the `outputs` folder.
- **Headless Option**: Supports running in headless mode for background automation.

## Prerequisites

* **Python 3.6+**
* **Selenium** (`pip install selenium`)
* **webdriver-manager** (`pip install webdriver-manager`)
* **dotenv** (`pip install python-dotenv`)
* **Google Chrome** installed on your system.

## Setup

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/rodolflying/qwen_bot](https://github.com/rodolflying/qwen_bot)
    cd qwen_bot
    ```

2.  **Install Dependencies:**
    ```bash
    pip install selenium webdriver-manager python-dotenv
    ```

3.  **Configure Environment Variables:**
    Create a `.env` file in the root directory of the project and add your QWen account credentials:
    ```
    USER=your_email@example.com
    PASS=your_password
    ```
    **Important:** Ensure this account was created using a standard email and password registration on the QWen website, without using Google or other automatic authentication methods.

## Usage

1.  **Run the script:**
    ```bash
    python main.py
    ```

    The example usage in the `if __name__ == "__main__":` block of `main.py` will initialize the bot, send a predefined query, log the conversation (including web search results if applicable), and save it to a CSV file in the `outputs` folder.

2.  **Modify the Query:**
    You can change the `query` variable in the `if __name__ == "__main__":` block of `main.py` to ask different questions.

3.  **Run Headlessly:**
    To run the bot without opening a visible browser window, set `headless=True` when initializing the `QWenChatBot` in `main.py`:
    ```python
    bot = QWenChatBot(headless=True)
    ```

## Understanding the Scraping Method

This script employs a more robust scraping technique by monitoring the network activity of the browser using Selenium's performance logging capabilities. Specifically, it intercepts `Network.requestWillBeSent` events and extracts the `postData` from requests made to QWen's backend. This `postData` contains the history of the conversation, including the assistant's responses and any information gathered during web searches.

This approach is advantageous because:

* It directly accesses the data exchanged between the front-end and back-end, making it less susceptible to changes in the website's HTML structure (DOM). Traditional scraping methods that rely on CSS selectors or XPath expressions break easily when the DOM changes.
* It can capture more comprehensive data, including details about the web search process that might not be directly rendered in the HTML.

To understand the structure of these API calls and responses, the developer used [JSONCrack](https://jsoncrack.com/) to visualize the JSON data, making it easier to identify the relevant information to extract.

While the primary data extraction relies on network monitoring, the script still uses some DOM element interaction (e.g., finding the web search button and the stop icon) to control the chat flow.

Diagram Flow

![Diagram from getdiagram](images/qwen%20bot%20diagram.png)
[Get Diagram Direct Link](https://gitdiagram.com/rodolflying/qwen_bot)

## Disclaimer

This script is intended for personal use and educational purposes. Automating interactions with websites may violate their terms of service. Use this script responsibly and be aware of the potential risks involved. The developer is not responsible for any misuse or consequences resulting from the use of this script. If you want further development for your use cases contact me in linkedin, i'm currently working as a freelancer : [LinkedIn](https://www.linkedin.com/in/rodolfo-sepulveda-847532135/)
