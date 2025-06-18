import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/documents"]



def edit_document(title, submission_id, authors, affiliation,
                 abstract_text, audience_experience_paragraph,
                 additional_info_paragraph, info_data):

        # --- 3. Build the requests to add content ---
        index = 1
        requests = []

        # Helper function to insert text and apply a paragraph style
        def insert_text(text, style=None):
            nonlocal index
            req = {'insertText': {'location': {'index': index}, 'text': text}}
            requests.append(req)

            if style:
                style_req = {
                    'updateParagraphStyle': {
                        'range': {
                            'startIndex': index,
                            'endIndex': index + len(text)
                        },
                        'paragraphStyle': {
                            'namedStyleType': style,
                        },
                        'fields': 'namedStyleType'
                    }
                }
                requests.append(style_req)
            index += len(text)

        # --- Populate the document from top to bottom ---

        insert_text(f"Submission ID: {submission_id}\n", "SUBTITLE")
        insert_text(f"{authors}\n", "NORMAL_TEXT")
        insert_text(f"{affiliation}\n\n", "NORMAL_TEXT")
        insert_text(f"{title}\n", "HEADING_1")
        insert_text(f"{abstract_text}\n\n", "NORMAL_TEXT")
        insert_text("What does the audience experience?\n", "HEADING_2")
        insert_text(f"{audience_experience_paragraph}\n\n", "NORMAL_TEXT")

        # Subsection: Information
        insert_text("Information\n", "HEADING_2")
        
        for item_name, content in info_data:
            # We need to know the index *before* we insert the text
            # so we can style the correct range later.
            line_start_index = index

            # The full line of text to insert, including the newline
            line_text = f"{item_name}: {content}\n"

            # 1. Request to insert the full line of text
            requests.append({
                'insertText': {
                    'location': {'index': line_start_index},
                    'text': line_text
                }
            })

            # 2. Request to make the "item_name" part bold.
            #    This is an updateTextStyle request, which applies inline styling.
            requests.append({
                'updateTextStyle': {
                    'range': {
                        'startIndex': line_start_index,
                        # The endIndex is exclusive, so it's start + length of the bold part
                        'endIndex': line_start_index + len(item_name)
                    },
                    'textStyle': {
                        'bold': True
                    },
                    # This 'fields' mask is crucial. It tells the API to only change the 'bold' property.
                    'fields': 'bold'
                }
            })

            # 3. Update the global index to point to the end of the newly inserted line.
            index += len(line_text)

        insert_text("\n", "NORMAL_TEXT")
        
        insert_text("Additional Info\n", "HEADING_2")
        insert_text(f"{additional_info_paragraph}\n", "NORMAL_TEXT")

        return requests



def make_document(folder, creds, title, submission_id, authors, affiliation,
                 abstract_text, audience_experience_paragraph,
                 additional_info_paragraph, info_data):

        service = build("docs", "v1", credentials=creds)

        print(f"Creating new document titled: '{title}'")
        document = service.documents().create(body={'title': title}).execute()
        doc_id = document.get("documentId")
        print(f"Document created with ID: {doc_id}")
        print(f"View the document at: https://docs.google.com/document/d/{doc_id}/edit")


        print("Adding content to the document...")
        requests = edit_document(
            title, submission_id, authors, affiliation,
            abstract_text, audience_experience_paragraph,
            additional_info_paragraph, info_data
        )
        
        result = service.documents().batchUpdate(
            documentId=doc_id, body={'requests': requests}
        ).execute()
        print("Content added successfully.")



def main():
    """Creates a Google Doc with a specific structure and content."""
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
        make_document(
            folder=None,  # Not used in this example, but can be passed if needed
            creds=creds,
            title="My Awesome Research Submission",
            submission_id="SUB-2024-00123",
            authors="Jane Doe, John Smith",
            affiliation="Python University, Institute of Code",
            abstract_text=("This is the abstract for the submission. It summarizes the key points of the work, "
                           "highlighting the methodology, results, and conclusions in a concise manner."),
            audience_experience_paragraph=("The audience will experience an interactive presentation that walks them "
                                           "through the core concepts of our project. Through live demonstrations and "
                                           "Q&A sessions, they will gain a deep understanding of the practical applications "
                                           "of our work."),
            additional_info_paragraph=("This work was partially funded by the Foundation for Pythonic Arts. "
                                       "All source code and data will be made available upon publication under "
                                       "the MIT License."),
            info_data=[
                ["Author Email", "jane.doe@example.com"],
                ["Themes", "Artificial Intelligence, API Automation, Python"],
                ["Presentation Format", "Live Demo & Talk (20 minutes)"],
                ["Link to Documentation", "https://docs.example.com/project-x"],
                ["Link to Video", "https://video.example.com/project-x-demo"]
            ]
        )

    except HttpError as err:
        print(f"An error occurred: {err}")

if __name__ == "__main__":
    main()
