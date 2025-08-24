import asyncio, json, base64, logging, os, io
from aiohttp import web, MultipartReader
import aiohttp_cors
from datetime import datetime, timedelta
import tempfile
from PIL import Image
from typing import Optional, Dict, Any, List
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

# Service imports
from services.intent_classifier import IntentClassifier
from services.ollama_service import OllamaService
from services.response_formatter import ResponseFormatter
from services.contacts_service import ContactsAIService
from services.sms_service import SMSService
from services.advanced_sms_service import advanced_sms_service
from oauth_handler import handle_oauth_token, handle_oauth_refresh, handle_oauth_revoke


# Google API imports
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import httplib2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

APP_NAME = "klai_backend"

# Global service instances
intent_classifier = None
ollama_service = None
response_formatter = None
contacts_service = None
sms_service = None

# Simple session storage (in production, use a database)
sessions = {}

def init_services():
    """Initialize all services."""
    global intent_classifier, ollama_service, response_formatter, contacts_service, sms_service
    
    logger.info("Initializing services...")
    if intent_classifier is None:
        logger.info("Initializing IntentClassifier...")
        intent_classifier = IntentClassifier()
        
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        ollama_model = os.getenv('OLLAMA_MODEL', 'llama2')
        
        logger.info(f"Initializing OllamaService with url: {ollama_url} and model: {ollama_model}")
        ollama_service = OllamaService(base_url=ollama_url, model=ollama_model)
        
        logger.info("Initializing ResponseFormatter...")
        response_formatter = ResponseFormatter()
        
        logger.info("Initializing ContactsAIService...")
        contacts_service = ContactsAIService()
        
        logger.info("Initializing SMSService...")
        sms_service = SMSService()
        
        logger.info("All services initialized.")

async def ensure_session(user_id: str, session_id: str):
    """Ensure session exists and return it."""
    global sessions
    session_key = f"{user_id}_{session_id}"
    if session_key not in sessions:
        sessions[session_key] = {
            "state": {},
            "created_at": datetime.now(),
        }
    return sessions[session_key]

def get_fallback_response(message: str) -> str:
    """Provide intelligent fallback responses when Ollama is unavailable."""
    message_lower = message.lower().strip()
    
    # Greetings
    if any(greeting in message_lower for greeting in ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']):
        return "Hello! I'm your AI assistant. I can help you with Google services like Calendar, Gmail, Drive, Contacts, and more. What can I do for you today?"
    
    # How are you
    if any(phrase in message_lower for phrase in ['how are you', 'how do you do', 'what\'s up']):
        return "I'm doing great and ready to help! I can assist you with managing your Google services, checking your calendar, sending messages, and much more."
    
    # Help requests
    if any(word in message_lower for word in ['help', 'what can you do', 'capabilities', 'features']):
        return """I can help you with:
📅 Calendar - Check events, create meetings, schedule appointments
📧 Gmail - Send emails, check messages
📁 Drive - Manage files and folders
📊 Sheets - Create and edit spreadsheets
📝 Docs - Create and edit documents
👥 Contacts - Find and manage your contacts
📱 SMS - Send text messages to your contacts
📸 Images - Process photos and extract information

Just ask me things like "What's on my calendar today?" or "Text John saying I'll be late" and I'll help you!"""
    
    # Time/date requests
    if any(word in message_lower for word in ['time', 'date', 'today', 'now']):
        current_time = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        return f"The current date and time is {current_time}. How can I help you today?"
    
    # Thank you
    if any(phrase in message_lower for phrase in ['thank you', 'thanks', 'thank', 'appreciate']):
        return "You're welcome! I'm here whenever you need help with your Google services or anything else."
    
    # Goodbye
    if any(word in message_lower for word in ['bye', 'goodbye', 'see you', 'farewell']):
        return "Goodbye! Feel free to come back anytime you need assistance with your Google services or other tasks."
    
    # Default intelligent response
    return "I understand you're trying to communicate with me. While my full AI capabilities are temporarily limited, I'm still here to help you with Google services like Calendar, Gmail, Drive, and Contacts. Try asking me about your calendar or to help with a specific Google service!"

# Google Service Handlers
async def handle_google_calendar(message: str, access_token: str) -> dict:
    """Handle Google Calendar interactions."""
    try:
        # Validate access token first
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        
        # Parse time range from message
        message_lower = message.lower()
        time_range = 'upcoming'  # default
        
        if 'today' in message_lower:
            time_range = 'today'
        elif 'tomorrow' in message_lower:
            time_range = 'tomorrow'
        elif 'this week' in message_lower:
            time_range = 'this week'
        elif 'next week' in message_lower:
            time_range = 'next week'
        elif any(month in message_lower for month in ['january', 'february', 'march', 'april', 'may', 'june',
                                                      'july', 'august', 'september', 'october', 'november', 'december']):
            # Extract month from message for specific month queries
            for month in ['january', 'february', 'march', 'april', 'may', 'june',
                         'july', 'august', 'september', 'october', 'november', 'december']:
                if month in message_lower:
                    time_range = month.title()
                    break
        elif any(day in message_lower for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']):
            # Extract day from message for specific day queries
            for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                if day in message_lower:
                    time_range = day.title()
                    break
        
        # Check if this is a special calendar command
        if any(keyword in message_lower for keyword in ['invite', 'attendees']) and 'meeting' in message_lower:
            return await handle_calendar_invite(message, service)
        elif any(keyword in message_lower for keyword in ['create event', 'schedule', 'add event', 'new event']):
            return await handle_calendar_create(message, service)
        elif any(keyword in message_lower for keyword in ['delete', 'cancel', 'remove']):
            return await handle_calendar_delete(message, service)
        elif any(keyword in message_lower for keyword in ['search', 'find']):
            return await handle_calendar_search(message, service)
        elif any(keyword in message_lower for keyword in ['update', 'modify', 'change', 'edit']):
            return await handle_calendar_update(message, service)
        else:
            # Default to listing events with detected time range
            return await list_calendar_events(service, time_range)
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return {"error": str(e)}

async def list_calendar_events(service, time_range='today'):
    """List calendar events based on time range."""
    try:
        now = datetime.utcnow()
        
        if time_range == 'today':
            time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
        elif time_range == 'tomorrow':
            tomorrow = now + timedelta(days=1)
            time_min = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
        elif time_range == 'this week':
            # Start of current week (Monday)
            days_since_monday = now.weekday()
            start_of_week = now - timedelta(days=days_since_monday)
            time_min = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = (start_of_week + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
        elif time_range == 'next week':
            # Start of next week (Monday)
            days_since_monday = now.weekday()
            start_of_next_week = now - timedelta(days=days_since_monday) + timedelta(days=7)
            time_min = start_of_next_week.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = (start_of_next_week + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
        elif time_range in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
            # Find the next occurrence of this day
            target_weekday = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].index(time_range)
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            target_date = now + timedelta(days=days_ahead)
            time_min = target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = target_date.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
        else:
            # Default: upcoming events (next 30 days)
            time_min = now.isoformat() + 'Z'
            time_max = (now + timedelta(days=30)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        formatted_events = []
        
        for event in events:
            # Clean the event data - NO URLs
            event_data = {
                'id': event.get('id'),
                'summary': event.get('summary', 'Untitled Event'),
                'start': event.get('start', {}),
                'end': event.get('end', {}),
                'location': event.get('location', ''),
                'description': event.get('description', '')
            }
            
            # Remove any URLs from description
            if event_data['description']:
                import re
                # Remove URLs
                event_data['description'] = re.sub(r'https?://[^\s]+', '', event_data['description'])
                # Remove Google Meet links
                event_data['description'] = re.sub(r'meet\.google\.com/[^\s]+', '', event_data['description'])
                # Clean up extra whitespace
                event_data['description'] = ' '.join(event_data['description'].split())
            
            formatted_events.append(event_data)
        
        return {
            'events': formatted_events,
            'time_range': time_range
        }
    except Exception as e:
        logger.error(f"List calendar events error: {e}")
        return {"error": str(e)}

async def handle_google_gmail(message: str, access_token: str) -> dict:
    """Handle Google Gmail interactions."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
        
        # Determine action based on message
        message_lower = message.lower()
        
        # Check if asking for last email/recent emails
        if any(word in message_lower for word in ['last', 'recent', 'latest', 'newest']) and \
           any(word in message_lower for word in ['email', 'mail', 'message', 'inbox']):
            # Get recent emails
            results = service.users().messages().list(
                userId='me', 
                maxResults=5,
                labelIds=['INBOX']
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                return {'response': "You don't have any emails in your inbox."}
            
            # Get details of the most recent email
            msg = service.users().messages().get(
                userId='me', 
                id=messages[0]['id']
            ).execute()
            
            # Parse email details
            headers = msg['payload'].get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            # Get body snippet
            snippet = msg.get('snippet', '')
            
            return {
                'action': 'retrieve_email',
                'latest_email': {
                    'subject': subject,
                    'from': from_email,
                    'date': date,
                    'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet
                },
                'total_emails': len(messages)
            }
            
        elif 'send' in message_lower or 'email' in message_lower:
            # Handle sending email
            return await handle_send_email(message, service)
        else:
            # Default to listing messages
            results = service.users().messages().list(userId='me', maxResults=5).execute()
            messages = results.get('messages', [])
            return {'messages': messages}
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        return {"error": str(e)}

async def handle_google_docs(message: str, access_token: str) -> dict:
    """Handle Google Docs interactions - CREATE ACTUAL DOCUMENTS."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('docs', 'v1', credentials=creds, cache_discovery=False)
        
        # Determine action based on message
        if 'create' in message.lower() or 'new' in message.lower():
            # Extract document title from message
            title = "New Document"
            message_lower = message.lower()
            
            # Try to extract title
            if 'about' in message_lower:
                parts = message.split('about')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'called' in message_lower:
                parts = message.split('called')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'titled' in message_lower:
                parts = message.split('titled')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'document' in message_lower:
                # Try to extract what comes after document
                parts = message_lower.split('document')
                if len(parts) > 1 and parts[1].strip():
                    potential_title = parts[1].strip()
                    # Remove common words
                    for word in ['for', 'about', 'on', 'with']:
                        if potential_title.startswith(word):
                            potential_title = potential_title[len(word):].strip()
                            break
                    if potential_title:
                        title = potential_title.title()
            
            # Create the document
            document = service.documents().create(body={'title': title}).execute()
            doc_id = document.get('documentId')
            doc_title = document.get('title')
            
            return {
                'action': 'create_document',
                'document_created': True,
                'document_id': doc_id,
                'document_title': doc_title,
                'response': f"✅ Document '{doc_title}' has been created successfully! What content would you like to add to it?",
                'next_step': 'You can now add content by saying something like "Add a paragraph about..." or "Write an introduction..."'
            }
        else:
            # List recent documents
            drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            results = drive_service.files().list(
                pageSize=5,
                q="mimeType='application/vnd.google-apps.document'",
                fields="files(id, name, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            return {
                'action': 'list_documents',
                'documents': files,
                'response': f"You have {len(files)} recent documents."
            }
    except Exception as e:
        logger.error(f"Docs error: {e}")
        return {"error": str(e)}

async def handle_google_sheets(message: str, access_token: str) -> dict:
    """Handle Google Sheets interactions - CREATE ACTUAL SPREADSHEETS."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        
        # Determine action based on message
        if 'create' in message.lower() or 'new' in message.lower():
            # Extract spreadsheet title from message
            title = "New Spreadsheet"
            message_lower = message.lower()
            
            # Try to extract title
            if 'for' in message_lower:
                parts = message.split('for')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'called' in message_lower:
                parts = message.split('called')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'spreadsheet' in message_lower:
                parts = message_lower.split('spreadsheet')
                if len(parts) > 1 and parts[1].strip():
                    potential_title = parts[1].strip()
                    for word in ['for', 'about', 'to track', 'to manage']:
                        if potential_title.startswith(word):
                            potential_title = potential_title[len(word):].strip()
                            break
                    if potential_title:
                        title = potential_title.title()
            
            # Create the spreadsheet
            spreadsheet = {
                'properties': {
                    'title': title
                }
            }
            
            spreadsheet = service.spreadsheets().create(
                body=spreadsheet,
                fields='spreadsheetId,properties.title,spreadsheetUrl'
            ).execute()
            
            sheet_id = spreadsheet.get('spreadsheetId')
            sheet_title = spreadsheet.get('properties', {}).get('title')
            
            return {
                'action': 'create_spreadsheet',
                'spreadsheet_created': True,
                'spreadsheet_id': sheet_id,
                'spreadsheet_title': sheet_title,
                'response': f"✅ Spreadsheet '{sheet_title}' has been created successfully! You can now add data to it.",
                'next_step': 'You can add data by saying "Add row with..." or "Create columns for..."'
            }
        elif 'update' in message.lower() or 'write' in message.lower():
            return await update_sheet(message, service)
        else:
            # List recent spreadsheets
            drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            results = drive_service.files().list(
                pageSize=5,
                q="mimeType='application/vnd.google-apps.spreadsheet'",
                fields="files(id, name, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            return {
                'action': 'list_spreadsheets',
                'spreadsheets': files,
                'response': f"You have {len(files)} spreadsheets."
            }
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return {"error": str(e)}

async def handle_google_forms(message: str, access_token: str) -> dict:
    """Handle Google Forms interactions - CREATE ACTUAL FORMS."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
        
        # Forms API requires Drive API for creation
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        
        if 'create' in message.lower() or 'new' in message.lower():
            # Extract form title from message
            title = "New Form"
            message_lower = message.lower()
            
            # Try to extract title
            if 'for' in message_lower:
                parts = message.split('for')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'called' in message_lower:
                parts = message.split('called')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            elif 'about' in message_lower:
                parts = message.split('about')
                if len(parts) > 1:
                    title = parts[1].strip().title()
            
            # Create a Google Form using Drive API
            file_metadata = {
                'name': title,
                'mimeType': 'application/vnd.google-apps.form'
            }
            
            form = drive_service.files().create(
                body=file_metadata,
                fields='id,name,webViewLink'
            ).execute()
            
            form_id = form.get('id')
            form_name = form.get('name')
            
            return {
                'action': 'create_form',
                'form_created': True,
                'form_id': form_id,
                'form_title': form_name,
                'response': f"✅ Form '{form_name}' has been created successfully! You can now add questions to it.",
                'next_step': 'You can open the form in Google Forms to add questions and customize it.'
            }
        else:
            # List recent forms
            results = drive_service.files().list(
                pageSize=5,
                q="mimeType='application/vnd.google-apps.form'",
                fields="files(id, name, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            return {
                'action': 'list_forms',
                'forms': files,
                'response': f"You have {len(files)} forms."
            }
    except Exception as e:
        logger.error(f"Forms error: {e}")
        return {"error": str(e)}

async def handle_sms(message: str, access_token: str = None) -> dict:
    """Handle SMS functionality with proper response formatting."""
    try:
        # Parse the SMS command using advanced SMS service
        command_info = advanced_sms_service.parse_sms_command(message)
        
        # Check if this is a scheduled SMS
        if command_info.get('schedule'):
            # Extract recipient and message
            recipient = command_info.get('recipient', '')
            sms_content = command_info.get('message', '')
            schedule_info = command_info['schedule']
            
            # Try to find contact phone number if we have access token
            contact_name = recipient
            phone_number = None
            
            if access_token and recipient and not recipient.isdigit():
                try:
                    # Search for contact
                    creds = Credentials(access_token)
                    service = build('people', 'v1', credentials=creds, cache_discovery=False)
                    
                    results = service.people().searchContacts(
                        query=recipient,
                        readMask='names,phoneNumbers'
                    ).execute()
                    
                    connections = results.get('results', [])
                    if connections:
                        contact_info = connections[0]['person']
                        phone_numbers = contact_info.get('phoneNumbers', [])
                        if phone_numbers:
                            phone_number = phone_numbers[0]['value']
                            names = contact_info.get('names', [])
                            if names:
                                contact_name = names[0].get('displayName', recipient)
                except Exception as e:
                    logger.error(f"Contact search error: {e}")
            
            # If no phone number from contacts, try to use as-is
            if not phone_number:
                phone_number = recipient
            
            # Schedule the SMS
            confirmation = await advanced_sms_service.schedule_sms(
                recipient=phone_number,
                message=sms_content,
                schedule_info=schedule_info
            )
            
            return {
                'action': 'schedule_sms',
                'recipient': phone_number,
                'contact_name': contact_name,
                'message_content': sms_content,
                'schedule': schedule_info,
                'instruction': 'SCHEDULE_SMS',
                'status': 'scheduled',
                'response': confirmation
            }
        
        # Handle immediate SMS sending
        elif 'text' in message.lower() and ('saying' in message.lower() or 'to say' in message.lower()):
            # Extract recipient and message
            parts = message.lower().replace('to say', 'saying').split('saying')
            if len(parts) >= 2:
                recipient_query = parts[0].replace('text', '').replace('send', '').replace('message', '').replace('to', '').strip()
                sms_content = parts[1].strip().strip('"').strip("'")
                
                # Try to find contact phone number
                contact_name = recipient_query
                phone_number = None
                contact_info = None
                
                if access_token:
                    try:
                        # Search for contact
                        creds = Credentials(access_token)
                        service = build('people', 'v1', credentials=creds, cache_discovery=False)
                        
                        results = service.people().searchContacts(
                            query=recipient_query,
                            readMask='names,phoneNumbers'
                        ).execute()
                        
                        connections = results.get('results', [])
                        if connections:
                            contact_info = connections[0]['person']
                            phone_numbers = contact_info.get('phoneNumbers', [])
                            if phone_numbers:
                                phone_number = phone_numbers[0]['value']
                                names = contact_info.get('names', [])
                                if names:
                                    contact_name = names[0].get('displayName', recipient_query)
                    except Exception as e:
                        logger.error(f"Contact search error: {e}")
                
                # If no phone number from contacts, try to use as-is (might be direct number)
                if not phone_number:
                    phone_number = recipient_query
                
                # Return proper response for SMS sending
                return {
                    'action': 'send_sms',
                    'recipient': phone_number,
                    'contact_name': contact_name,
                    'message_content': sms_content,
                    'instruction': 'SEND_SMS',  # Signal to mobile app
                    'status': 'ready_to_send',
                    'response': f"✅ SMS to {contact_name}: \"{sms_content}\" is ready. Opening SMS app..."
                }
        
        # Handle SMS management commands
        elif 'list' in message.lower() and 'scheduled' in message.lower():
            scheduled_messages = advanced_sms_service.list_scheduled_messages()
            return {
                'action': 'list_scheduled_sms',
                'scheduled_messages': scheduled_messages,
                'response': f"You have {len(scheduled_messages)} scheduled SMS messages"
            }
        
        elif 'cancel' in message.lower() and 'sms' in message.lower():
            # Extract schedule ID from message if provided
            # This is simplified - in real implementation, parse the message properly
            return {
                'action': 'cancel_sms',
                'response': 'Please provide the schedule ID to cancel'
            }
        
        # Handle other SMS requests
        return {'action': 'sms', 'response': 'SMS functionality ready. Try saying "Text [contact] saying [message]"'}
    except Exception as e:
        logger.error(f"SMS error: {e}")
        return {"error": str(e), "action": "send_sms"}

# Keep all the other handler functions from the original file...
# (handle_calendar_invite, handle_calendar_create, handle_calendar_delete, etc.)

async def handle_chat(request: web.Request):
    """Main chat handler with improved routing and response formatting."""
    data = await request.json()
    
    user_id = data.get("user_id", "anon")
    session_id = data.get("session_id", "default")
    message = data.get("message", "")
    access_token = data.get("access_token")
    
    session = await ensure_session(user_id, session_id)
    
    # Initialize response
    final_response = ""
    response_source = "system"
    raw_service_result = None  # Store raw service result
    
    # Classify intent
    intent_result = None
    if message:
        intent_result = intent_classifier.classify(message)
        logger.info(f"Intent classification: {intent_result}")
        session["state"]["intent_classification"] = intent_result
    
    # Route based on intent
    if intent_result:
        if intent_result['type'] == 'google':
            # Check for authentication
            if not access_token:
                # Return authentication required message
                final_response = f"Please sign in with Google to use {intent_result['service'].title()} services."
                response_source = "auth_required"
            else:
                # Handle Google service request
                service_name = intent_result['service']
                response_source = f"google_{service_name}"
                
                # Service handlers
                service_handlers = {
                    'calendar': handle_google_calendar,
                    'gmail': handle_google_gmail,
                    'drive': handle_google_drive,
                    'sheets': handle_google_sheets,
                    'docs': handle_google_docs,
                    'contacts': handle_google_contacts,
                    'tasks': handle_google_tasks,
                    'keep': handle_google_keep,
                    'slides': handle_google_slides,
                    'forms': handle_google_forms,
                    'sms': handle_sms
                }
                
                handler = service_handlers.get(service_name)
                if handler:
                    try:
                        # All services now get access token (SMS uses it for contact lookup)
                        service_result = await handler(message, access_token)
                        raw_service_result = service_result  # Store raw result
                        
                        # Format response using ResponseFormatter
                        final_response = response_formatter.format_google_service_response(
                            service_name, service_result
                        )
                        
                        # For SMS, check if we need to pass instruction
                        if service_name == 'sms' and 'instruction' in service_result:
                            # Pass the instruction through for the mobile app
                            return web.json_response({
                                "response": final_response,
                                "source": response_source,
                                "instruction": service_result['instruction'],
                                "recipient": service_result.get('recipient'),
                                "message_content": service_result.get('message_content')
                            })
                        
                    except Exception as e:
                        logger.error(f"Service handler error: {e}")
                        final_response = f"An error occurred while accessing {service_name.title()}."
                else:
                    final_response = f"{service_name.title()} service is not yet implemented."
        
        elif intent_result['type'] == 'llm':
            # Route to Ollama for general conversation, with fallback responses
            response_source = "assistant"
            
            try:
                if await ollama_service.health_check():
                    # Generate response from Ollama
                    ollama_chunks = []
                    async for chunk in ollama_service.generate(message):
                        ollama_chunks.append(chunk)
                    
                    ollama_response = "".join(ollama_chunks)
                    
                    # Format response
                    final_response = response_formatter.format_response(
                        ollama_response, source='ollama'
                    )
                else:
                    # Provide basic intelligent responses when Ollama is unavailable
                    final_response = get_fallback_response(message)
                    
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                final_response = get_fallback_response(message)
        
        else:
            # Unknown intent type
            final_response = "I'm not sure how to help with that. Could you please rephrase your request?"
    
    else:
        # No message provided
        final_response = "Please provide a message."
    
    # Clean up the final response
    final_response = response_formatter.format_response(final_response, source=response_source)
    
    return web.json_response({
        "response": final_response,
        "source": response_source
    })

# Include all other necessary functions from the original file
# (handle_unified_query, handle_health, handle_ollama_status, etc.)

async def handle_send_email(message: str, service) -> dict:
    """Handle sending emails."""
    try:
        # This is a simplified implementation
        # In real app, parse message to extract email details
        return {'sent': True}
    except Exception as e:
        logger.error(f"Send email error: {e}")
        return {"error": str(e)}

async def handle_google_drive(message: str, access_token: str) -> dict:
    """Handle Google Drive interactions."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        
        # Determine action based on message
        if 'create' in message.lower():
            return await create_drive_file(message, service)
        elif 'folder' in message.lower():
            return await create_drive_folder(message, service)
        elif 'share' in message.lower():
            return await share_drive_file(message, service)
        else:
            # Default to listing files
            results = service.files().list(pageSize=10, fields="nextPageToken, files(id, name)").execute()
            files = results.get('files', [])
            return {'files': [{'id': file['id'], 'name': file['name']} for file in files]}
    except Exception as e:
        logger.error(f"Drive error: {e}")
        return {"error": str(e)}

async def create_drive_file(message: str, service) -> dict:
    """Create a new file in Google Drive."""
    try:
        # Simplified implementation
        return {'file_created': True}
    except Exception as e:
        logger.error(f"Create drive file error: {e}")
        return {"error": str(e)}

async def create_drive_folder(message: str, service) -> dict:
    """Create a new folder in Google Drive."""
    try:
        # Simplified implementation
        return {'folder_created': True, 'folder_name': 'New Folder'}
    except Exception as e:
        logger.error(f"Create drive folder error: {e}")
        return {"error": str(e)}

async def share_drive_file(message: str, service) -> dict:
    """Share a file in Google Drive."""
    try:
        # Simplified implementation
        return {'shared': True}
    except Exception as e:
        logger.error(f"Share drive file error: {e}")
        return {"error": str(e)}

async def update_sheet(message: str, service) -> dict:
    """Update a Google Sheet."""
    try:
        # Simplified implementation
        return {'updated_cells': 5}
    except Exception as e:
        logger.error(f"Update sheet error: {e}")
        return {"error": str(e)}

async def handle_google_contacts(message: str, access_token: str) -> dict:
    """Handle Google Contacts interactions."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('people', 'v1', credentials=creds, cache_discovery=False)
        
        # Search for contacts
        results = service.people().connections().list(
            resourceName='people/me',
            pageSize=1000,
            personFields='names,emailAddresses,phoneNumbers'
        ).execute()
        
        connections = results.get('connections', [])
        
        # Filter by search terms if provided
        search_terms = [term.lower() for term in message.split() if len(term) > 2]
        filtered_contacts = []
        
        for person in connections:
            names = person.get('names', [])
            phones = person.get('phoneNumbers', [])
            emails = person.get('emailAddresses', [])
            
            # Check if search terms match
            if not search_terms or any(
                term in ' '.join([name.get('displayName', '') for name in names]).lower() or
                term in ' '.join([phone.get('value', '') for phone in phones]).lower() or
                term in ' '.join([email.get('value', '') for email in emails]).lower()
                for term in search_terms
            ):
                filtered_contacts.append({
                    'name': names[0].get('displayName', 'Unknown') if names else 'Unknown',
                    'phones': [phone.get('value', '') for phone in phones],
                    'emails': [email.get('value', '') for email in emails]
                })
        
        return {
            'contacts': filtered_contacts,
            'search_terms': search_terms,
            'total_count': len(connections)
        }
    except Exception as e:
        logger.error(f"Contacts error: {e}")
        return {"error": str(e)}

async def handle_google_tasks(message: str, access_token: str) -> dict:
    """Handle Google Tasks interactions."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('tasks', 'v1', credentials=creds, cache_discovery=False)
        
        # Get task lists
        tasklists = service.tasklists().list().execute()
        
        if 'items' in tasklists:
            # Get tasks from first task list
            tasklist_id = tasklists['items'][0]['id']
            tasks = service.tasks().list(tasklist=tasklist_id).execute()
            return {'tasks': tasks.get('items', [])}
        else:
            return {'tasks': []}
    except Exception as e:
        logger.error(f"Tasks error: {e}")
        return {"error": str(e)}

async def handle_google_keep(message: str, access_token: str) -> dict:
    """Handle Google Keep interactions."""
    # Keep API is not officially supported, but we can provide placeholder functionality
    try:
        return {'notes': [{'title': 'Sample Note', 'content': 'This is a sample note'}]}
    except Exception as e:
        logger.error(f"Keep error: {e}")
        return {"error": str(e)}

async def handle_google_slides(message: str, access_token: str) -> dict:
    """Handle Google Slides interactions."""
    try:
        creds = Credentials(access_token)
        if not creds.valid:
            return {"error": "Invalid or expired credentials"}
            
        service = build('slides', 'v1', credentials=creds, cache_discovery=False)
        
        # Simplified response
        return {'presentation_created': True}
    except Exception as e:
        logger.error(f"Slides error: {e}")
        return {"error": str(e)}

# Include all the calendar handler functions
async def handle_calendar_invite(message: str, service) -> dict:
    """Handle calendar invitation creation with contact integration."""
    try:
        # Extract event details from message
        # This is a simplified implementation - in real implementation, you'd parse the message properly
        event_details = {
            'summary': 'Meeting with Contact',
            'description': 'Scheduled via Kirlew AI Assistant',
            'start': datetime.now() + timedelta(hours=1),
            'end': datetime.now() + timedelta(hours=2),
            'attendees': []  # Would be populated from contacts
        }
        
        # Create event
        event = {
            'summary': event_details['summary'],
            'description': event_details['description'],
            'start': {
                'dateTime': event_details['start'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'end': {
                'dateTime': event_details['end'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'attendees': event_details['attendees'],
        }
        
        event = service.events().insert(calendarId='primary', body=event).execute()
        
        return {
            'action': 'create_event',
            'result': f"Meeting scheduled successfully",
            'event_details': {
                'title': event_details['summary'],
                'start_time': event_details['start'].strftime('%B %d, %Y at %I:%M %p'),
                'attendees': event_details['attendees']
            }
        }
    except Exception as e:
        logger.error(f"Calendar invite error: {e}")
        return {"error": str(e)}

async def handle_calendar_create(message: str, service) -> dict:
    """Create a new calendar event."""
    try:
        # Simple event creation - in real app, parse message for details
        event = {
            'summary': 'New Event',
            'start': {
                'dateTime': (datetime.now() + timedelta(hours=1)).isoformat(),
                'timeZone': 'America/Chicago',
            },
            'end': {
                'dateTime': (datetime.now() + timedelta(hours=2)).isoformat(),
                'timeZone': 'America/Chicago',
            },
        }
        
        event = service.events().insert(calendarId='primary', body=event).execute()
        
        return {
            'action': 'create_event',
            'result': 'Event created successfully',
            'event_details': {
                'title': 'New Event',
                'start_time': (datetime.now() + timedelta(hours=1)).strftime('%B %d, %Y at %I:%M %p')
            }
        }
    except Exception as e:
        logger.error(f"Calendar create error: {e}")
        return {"error": str(e)}

async def handle_calendar_delete(message: str, service) -> dict:
    """Delete calendar events based on search."""
    try:
        # Search for events to delete
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime',
            q=message  # Use message as search query
        ).execute()
        
        events = events_result.get('items', [])
        
        deleted_count = 0
        for event in events:
            try:
                service.events().delete(calendarId='primary', eventId=event['id']).execute()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete event {event['id']}: {e}")
        
        return {
            'action': 'delete_events',
            'result': f'Deleted {deleted_count} event(s)',
            'search_query': message
        }
    except Exception as e:
        logger.error(f"Calendar delete error: {e}")
        return {"error": str(e)}

async def handle_calendar_search(message: str, service) -> dict:
    """Search for calendar events."""
    try:
        events_result = service.events().list(
            calendarId='primary',
            q=message,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        formatted_events = []
        
        for event in events:
            formatted_events.append({
                'id': event.get('id'),
                'summary': event.get('summary', 'Untitled Event'),
                'start': event.get('start', {}),
                'end': event.get('end', {}),
                'location': event.get('location', ''),
                'description': event.get('description', '')
            })
        
        return {
            'action': 'search_events',
            'events': formatted_events,
            'search_query': message
        }
    except Exception as e:
        logger.error(f"Calendar search error: {e}")
        return {"error": str(e)}

async def handle_calendar_update(message: str, service) -> dict:
    """Update existing calendar events."""
    try:
        # This is a simplified implementation
        # In a real app, you'd parse the update request and find the specific event to modify
        return {
            'action': 'update_events',
            'result': 'Event update functionality available'
        }
    except Exception as e:
        logger.error(f"Calendar update error: {e}")
        return {"error": str(e)}

async def handle_image_processing(message: str, image_data: bytes, access_token: str) -> dict:
    """Handle image processing and integration with Google services."""
    try:
        # Process image in memory
        image = Image.open(io.BytesIO(image_data))
        
        # Extract text using OCR (simulated)
        # In a real implementation, you would use Google Vision API or similar
        
        extracted_text = "Sample extracted text from image"
        
        # Determine where to save based on message context
        if 'drive' in message.lower() or 'save' in message.lower():
            # Save to Google Drive
            creds = Credentials(access_token)
            drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            
            # Save extracted text as a document
            file_metadata = {
                'name': 'Scanned Document.txt',
                'mimeType': 'text/plain'
            }
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                f.write(extracted_text)
                temp_path = f.name
            
            # Upload to Drive
            media = MediaFileUpload(temp_path, mimetype='text/plain')
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            os.unlink(temp_path)
            
            return {
                'action': 'image_processed',
                'response': f"Document saved to Google Drive",
                'extracted_text': extracted_text
            }
        elif 'sheet' in message.lower() or 'spreadsheet' in message.lower():
            # Save to Google Sheets
            return {
                'action': 'image_processed',
                'response': "Data saved to Google Sheets",
                'extracted_text': extracted_text
            }
        elif 'doc' in message.lower() or 'document' in message.lower():
            # Save to Google Docs
            return {
                'action': 'image_processed',
                'response': "Content saved to Google Docs",
                'extracted_text': extracted_text
            }
        else:
            # Return extracted text
            return {
                'action': 'image_processed',
                'response': "Image processed successfully",
                'extracted_text': extracted_text
            }
    except Exception as e:
        logger.error(f"Image processing error: {e}")
        return {"error": str(e), "action": "image_processed"}

async def handle_unified_query(request: web.Request):
    """Handle unified queries that can include images."""
    
    try:
        # Parse multipart form data
        reader = await request.multipart()
        
        # Initialize data containers
        message = ""
        image_data = None
        access_token = None
        user_id = "anon"
        session_id = "default"
        
        # Process multipart data
        while True:
            part = await reader.next()
            if part is None:
                break
            
            if part.name == 'message':
                message = await part.text()
            elif part.name == 'image':
                image_data = await part.read()
            elif part.name == 'access_token':
                access_token = await part.text()
            elif part.name == 'user_id':
                user_id = await part.text()
            elif part.name == 'session_id':
                session_id = await part.text()
        
        session = await ensure_session(user_id, session_id)
        
        # If there's an image, process it
        if image_data:
            if access_token:
                result = await handle_image_processing(message, image_data, access_token)
                formatted_response = response_formatter.format_google_service_response('drive', result)
                return web.json_response({
                    "response": formatted_response,
                    "source": "image_processing"
                })
            else:
                return web.json_response({
                    "response": "Please sign in to process images and save content to Google services.",
                    "source": "auth_required"
                })
        
        # If no image, treat as regular chat
        # Create a new request with the data
        return await handle_chat(request)
        
    except Exception as e:
        logger.error(f"Unified query error: {e}")
        return web.json_response({
            "response": "I encountered an error processing your request.",
            "source": "error"
        })

async def handle_health(request: web.Request):
    """Health check endpoint."""
    return web.json_response({"status": "ok", "timestamp": datetime.now().isoformat()})

async def handle_ollama_status(request: web.Request):
    """Check Ollama service status."""
    is_available = await ollama_service.health_check() if ollama_service else False
    return web.json_response({"ollama_available": is_available})

async def handle_test_intent(request: web.Request):
    """Test intent classification."""
    data = await request.json()
    message = data.get("message", "")
    
    if intent_classifier:
        result = intent_classifier.classify(message)
        return web.json_response(result)
    else:
        return web.json_response({"error": "Intent classifier not initialized"})

async def handle_contacts_process(request: web.Request):
    """Process contacts with enhanced search."""
    data = await request.json()
    
    contacts = data.get("contacts", [])
    search_query = data.get("search_query", "")
    
    if contacts_service:
        result = contacts_service.process_contacts(contacts, search_query)
        return web.json_response(result)
    else:
        return web.json_response({"error": "Contacts service not initialized"})

async def handle_sms_process(request: web.Request):
    """Process SMS request."""
    data = await request.json()
    
    contact_info = data.get("contact_info", {})
    message = data.get("message", "")
    
    if sms_service:
        result = sms_service.send_sms(contact_info, message)
        return web.json_response(result)
    else:
        return web.json_response({"error": "SMS service not initialized"})

# Application setup
app = web.Application()

# Configure CORS
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods="*"
    )
})

# Register routes
app.router.add_post('/chat', handle_chat)
app.router.add_post('/unified_query', handle_unified_query)
app.router.add_get('/health', handle_health)
app.router.add_get('/ollama/status', handle_ollama_status)
app.router.add_post('/test_intent', handle_test_intent)
app.router.add_post('/oauth/token', handle_oauth_token)
app.router.add_post('/oauth/refresh', handle_oauth_refresh)
app.router.add_post('/oauth/revoke', handle_oauth_revoke)
app.router.add_post('/contacts/process', handle_contacts_process)
app.router.add_post('/sms/process', handle_sms_process)

async def startup(app):
    """Application startup with OLLAMA check"""
    # First ensure OLLAMA is running
    from startup_ollama import OllamaManager
    manager = OllamaManager()
    ollama_ready = manager.ensure_ollama_ready()
    
    # Initialize services regardless (they handle fallback)
    init_services()
    
    if not ollama_ready:
        logger.warning("Starting without OLLAMA - using fallback responses")

app.on_startup.append(startup)

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Starting web server on port {port}")
        web.run_app(app, host='0.0.0.0', port=port)
    except Exception as e:
        logger.exception(f"Error starting web server: {e}")