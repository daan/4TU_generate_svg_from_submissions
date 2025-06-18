import os
import io
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
import markdown

# --- CONFIGURATION ---
# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive']
# The name of the Shared Drive to upload to.
SHARED_DRIVE_NAME = "4TU.DU DDW25"
# The local folder containing your markdown files.
LOCAL_MARKDOWN_FOLDER = "md"
# The base path on Google Drive where folders will be created.
DRIVE_FOLDER_PATH = "submissions/submissions"
# --- END CONFIGURATION ---

def authenticate():
    """Shows basic usage of the Drive v3 API.
    Prints the names and ids of the first 10 files the user has access to.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return build('drive', 'v3', credentials=creds)

def get_shared_drive_id(service, drive_name):
    """Finds the ID of a Shared Drive by its name."""
    try:
        response = service.drives().list(q=f"name='{drive_name}'", pageSize=1).execute()
        drives = response.get('drives', [])
        if not drives:
            print(f"Error: Shared Drive '{drive_name}' not found.")
            return None
        print(f"Found Shared Drive '{drive_name}' with ID: {drives[0]['id']}")
        return drives[0]['id']
    except HttpError as error:
        print(f"An error occurred while searching for the drive: {error}")
        return None

def get_or_create_folder(service, folder_name, parent_id, drive_id):
    """Finds a folder by name within a parent, or creates it if not found."""
    query = f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    try:
        response = service.files().list(q=query,
                                        spaces='drive',
                                        corpora='drive',
                                        driveId=drive_id,
                                        includeItemsFromAllDrives=True,
                                        supportsAllDrives=True,
                                        fields='files(id, name)').execute()
        files = response.get('files', [])
        if files:
            print(f"Found existing folder '{folder_name}' with ID: {files[0].get('id')}")
            return files[0].get('id')
        else:
            # Folder not found, create it
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_id]
            }
            folder = service.files().create(body=file_metadata,
                                            supportsAllDrives=True,
                                            fields='id').execute()
            print(f"Created folder '{folder_name}' with ID: {folder.get('id')}")
            return folder.get('id')
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def main():
    """Main function to find and upload markdown files."""
    service = authenticate()
    
    drive_id = get_shared_drive_id(service, SHARED_DRIVE_NAME)
    if not drive_id:
        return

    # Create the base folder structure if it doesn't exist
    path_parts = DRIVE_FOLDER_PATH.split('/')
    current_parent_id = drive_id # Start at the root of the Shared Drive
    for part in path_parts:
        current_parent_id = get_or_create_folder(service, part, current_parent_id, drive_id)
        if not current_parent_id:
            print("Failed to create base folder structure. Aborting.")
            return

    base_submission_folder_id = current_parent_id

    # Process local markdown files
    for filename in os.listdir(LOCAL_MARKDOWN_FOLDER):
        if filename.endswith(".md"):
            doc_number = os.path.splitext(filename)[0]
            local_filepath = os.path.join(LOCAL_MARKDOWN_FOLDER, filename)
            
            print(f"\n--- Processing {filename} ---")
            
            # Create the specific number folder (e.g., '100')
            target_folder_id = get_or_create_folder(service, doc_number, base_submission_folder_id, drive_id)
            if not target_folder_id:
                print(f"Could not create folder for {doc_number}. Skipping.")
                continue

            # Read and convert Markdown to HTML
            with open(local_filepath, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            html_content = markdown.markdown(markdown_content)

            # Upload and convert HTML to Google Doc
            try:
                file_metadata = {
                    'name': doc_number, # The name of the final Google Doc
                    'mimeType': 'application/vnd.google-apps.document',
                    'parents': [target_folder_id]
                }
                
                # Use io.BytesIO to upload the HTML content from memory
                html_bytes = io.BytesIO(html_content.encode('utf-8'))
                media = MediaIoBaseUpload(html_bytes, mimetype='text/html', resumable=True)

                print(f"Uploading and converting '{filename}' to Google Doc '{doc_number}.gdoc'...")
                
                created_file = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    supportsAllDrives=True, # ESSENTIAL for Shared Drives
                    fields='id, name, webViewLink'
                ).execute()
                
                print(f"Successfully created document: {created_file.get('name')}")
                print(f"Link: {created_file.get('webViewLink')}")

            except HttpError as error:
                print(f"An error occurred during upload: {error}")

if __name__ == '__main__':
    main()