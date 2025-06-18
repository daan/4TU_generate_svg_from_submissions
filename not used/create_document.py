import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import pandas as pd
from pathlib import Path
import openpyxl
import sys

folder = Path("/Users/d.p.saakes/Downloads/export-ddw-2025-submission-2025-06-16T14/")
xls_file = folder / "export-ddw-2025-submission-2025-06-16T14.12.55.xlsx"
df = pd.read_excel(xls_file)
df['submission id'] = df.index + 100


for index, row in df.iterrows():
    submission_id = row['submission id']
    title = row['Project Title']

    authors = row['Authors and Affiliations']
    affiliation = row['Submitter Affiliation']
    abstract_text = row['Abstract']
    audience_experience_paragraph = row['what does the audience experience?']
    additional_info_paragraph = row['additional info']

    link_to_online_documentation = row['Link to Online Documentation']
    link_to_video = row['Link to Video']

    break

sys.exit(0)

# --- CONFIGURATION ---
# If modifying these scopes, delete the file token.json.
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive" # Drive API scope is crucial
]

# --- !! SET YOUR DETAILS HERE !! ---
NEW_DOC_TITLE = "My Report from Python"
TARGET_FOLDER_NAME = "submissions" # The name of the folder in your Drive
# To save to a Shared Drive, find the Shared Drive's ID and set it here.
# If you set a SHARED_DRIVE_ID, the script will search for TARGET_FOLDER_NAME
# inside that specific Shared Drive. If it's None, it searches "My Drive".
SHARED_DRIVE_ID = "0AE_Y_Y8T8EXoUk9PVA" # Example: "0Axxxxxxxxxxxxxxxxx9" or None

def main():
    """
    Creates a new Google Doc in a specified Google Drive folder.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        # Build the service objects for the Docs and Drive APIs
        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        # === STEP 1: Create the Google Doc ===
        print(f"Creating a new Google Doc titled '{NEW_DOC_TITLE}'...")
        doc = {"title": NEW_DOC_TITLE}
        document = docs_service.documents().create(body=doc).execute()
        document_id = document.get("documentId")
        print(f"SUCCESS: Created document with ID: {document_id}")


        # === STEP 2: Find the destination folder ID ===
        folder_id = find_folder_id(drive_service, TARGET_FOLDER_NAME, SHARED_DRIVE_ID)
        if not folder_id:
            print(f"ERROR: Could not find folder '{TARGET_FOLDER_NAME}'. Please check the name and permissions.")
            # Optional: You could ask the user if they want to create the folder here.
            return

        print(f"Found folder '{TARGET_FOLDER_NAME}' with ID: {folder_id}")


        # === STEP 3: Move the document to the folder ===
        print(f"Moving document to folder '{TARGET_FOLDER_NAME}'...")

        # Retrieve the existing parents to remove the file from the root "My Drive"
        file = drive_service.files().get(fileId=document_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents"))

        # The key API call to move the file
        moved_file = drive_service.files().update(
            fileId=document_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents, name, webViewLink",
            # This is CRUCIAL for shared drive support
            supportsAllDrives=True
        ).execute()

        print("SUCCESS: File moved successfully!")
        print(f"Document Name: {moved_file.get('name')}")
        print(f"Document Link: {moved_file.get('webViewLink')}")


    except HttpError as err:
        print(f"An error occurred: {err}")
        print("Please ensure you have enabled the Google Docs and Google Drive APIs in your Cloud project.")

def find_folder_id(drive_service, folder_name: str, shared_drive_id: str = None) -> str:
    """Helper function to find the ID of a folder by its name."""
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    
    search_params = {
        'q': query,
        'pageSize': 1,
        'fields': "files(id, name)"
    }
    
    # Add shared drive-specific parameters if a shared_drive_id is provided
    if shared_drive_id:
        search_params['corpora'] = 'drive'
        search_params['driveId'] = shared_drive_id
        search_params['includeItemsFromAllDrives'] = True
        search_params['supportsAllDrives'] = True

    response = drive_service.files().list(**search_params).execute()
    files = response.get('files', [])

    if files:
        return files[0].get('id')
    else:
        return None

if __name__ == "__main__":
    main()