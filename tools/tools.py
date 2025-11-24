import json
import json
import base64
import markdown
import requests
import re 
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from atlassian import Confluence
from tools.config import CONFLUENCE_API_KEY, CONFLUENCE_DOMAIN, CONFLUENCE_EMAIL, GITHUB_API_KEY

# --------------------------
# Setup: GitHub MCP Server
# --------------------------
github_tools = McpToolset(
            connection_params=StreamableHTTPServerParams(
                url="https://api.githubcopilot.com/mcp/",
                headers={
                    "Authorization": f"Bearer "+ GITHUB_API_KEY,
                    "X-MCP-Toolsets": "all",
                    "X-MCP-Readonly": "true"
                },
            )
)
# --------------------------
# Setup: Confluence Connection
# --------------------------
confluence = Confluence(
    url=CONFLUENCE_DOMAIN,
    username= CONFLUENCE_EMAIL,
    password=CONFLUENCE_API_KEY
)


# --------------------------
# Mermaid Rendering Tool
# --------------------------
def render_mermaid_to_png(mermaid_code: str) -> bytes:
    """
    Sends the Mermaid code to Kroki.io via POST request.
    This avoids the '414 Request-URI Too Large' error by sending data in the body 
    instead of the URL.
    """
    # Kroki is a popular open-source API for rendering diagrams
    url = "https://kroki.io/mermaid/png"
    
    try:
        # sending data in the body (POST) handles very large diagrams
        response = requests.post(url, data=mermaid_code)
        
        if response.status_code == 200:
            return response.content
        else:
            raise Exception(f"Rendering failed (Status {response.status_code}): {response.text}")
            
    except Exception as e:
        # Fallback logging
        print(f"Error connecting to renderer: {e}")
        raise e
    
# --------------------------
# Publishing Tool
# --------------------------
# def publish_to_confluence(space_key: str, title: str, content: str) -> str:
#     try:
#             existing_page = confluence.get_page_by_title(space_key, title)
            
#             if existing_page:
#                 page_id = existing_page['id']
#                 confluence.update_page(
#                     page_id=page_id,
#                     title=title,
#                     body=content,
#                     representation='storage'
#                 )
#                 return f"✅ Success! Page '{title}' updated. URL: {CONFLUENCE_DOMAIN}/wiki/spaces/{space_key}/pages/{page_id}"
#             else:
#                 status = confluence.create_page(
#                     space=space_key,
#                     title=title,
#                     body=content,
#                     representation='storage'
#                 )
#                 page_id = status['id']
#                 return f"✅ Success! Page '{title}' created. URL: {CONFLUENCE_DOMAIN}/wiki/spaces/{space_key}/pages/{page_id}"

#     except Exception as e:
#         return f"❌ Error publishing to Confluence: {str(e)}"

def publish_to_confluence(space_key: str, title: str, content: str) -> str:
    try:
        # 1. Get Page ID (Same as before)
        existing_page = confluence.get_page_by_title(space_key, title)
        if existing_page:
            page_id = existing_page['id']
        else:
            status = confluence.create_page(
                space=space_key,
                title=title,
                body="<p>Drafting content...</p>",
                representation='storage'
            )
            page_id = status['id']

        # 2. Setup Variables
        mermaid_pattern = r"```\s*mermaid\s*(.*?)```"
        match = re.search(mermaid_pattern, content, re.DOTALL)
        final_html = ""

        # 3. Handle Mermaid Diagram
        if match:
            print("Found Mermaid diagram, rendering...")
            mermaid_code = match.group(1).strip()
            
            try:
                # A. Render Image (using the POST fix from previous step)
                image_data = render_mermaid_to_png(mermaid_code)
                filename = "architecture_diagram.png"
                
                # B. Upload Attachment
                confluence.attach_content(
                    content=image_data,
                    name=filename,
                    content_type="image/png",
                    page_id=page_id
                )
                
                # C. Prepare the Confluence XML (The Image Tag)
                # We wrap it in a clean paragraph to ensure structure
                image_xml = f'''<p class="auto-cursor-target"><ac:image ac:align="center" ac:layout="center"><ri:attachment ri:filename="{filename}" /></ac:image></p>'''
                
                # D. REPLACE Markdown with a SAFE PLACEHOLDER
                # We use a unique string that won't confuse the HTML converter
                content_with_placeholder = re.sub(mermaid_pattern, "[[__MERMAID_IMAGE_MARKER__]]", content, flags=re.DOTALL)
                
                # E. Convert Markdown to HTML
                # This handles headers, bolding, lists, etc.
                final_html = markdown.markdown(content_with_placeholder)
                
                # F. SWAP Placeholder with Real XML
                # The markdown converter might wrap our placeholder in <p> tags, so we handle both cases
                final_html = final_html.replace("<p>[[__MERMAID_IMAGE_MARKER__]]</p>", image_xml)
                final_html = final_html.replace("[[__MERMAID_IMAGE_MARKER__]]", image_xml)
                
            except Exception as img_err:
                print(f"Warning: Could not render image. Error: {img_err}")
                # If failure, just convert the raw markdown to HTML
                final_html = markdown.markdown(content)
        else:
            # No mermaid found, just simple conversion
            final_html = markdown.markdown(content)

        # 4. Update Page
        confluence.update_page(
            page_id=page_id,
            title=title,
            body=final_html, 
            representation='storage' # MUST BE STORAGE
        )
        
        return f"✅ Success! Page '{title}' updated. URL: {CONFLUENCE_DOMAIN}/wiki/spaces/{space_key}/pages/{page_id}"

    except Exception as e:
        return f"❌ Error publishing to Confluence: {str(e)}"
    

# --------------------------
# Human Loop Tool (CORRECTED)
# --------------------------
def ask_human_approval(tool_context: ToolContext, draft: str) -> str:
    """
    Presents the current draft to the human user.
    IMPORTANT: Returns a JSON STRING using json.dumps, never a raw dictionary.
    """
    tool_confirmation = tool_context.tool_confirmation
    
    # 1. Request Confirmation if not yet received
    if not tool_confirmation:
        tool_context.request_confirmation(
            hint="Please review the draft and select APPROVE or REJECT.",
            payload={
                "approve": "",  # Expected values: "APPROVE" or "REJECT"
                "title": "",
                "space_key": "",
                "feedback": ""
            }
        )
        return json.dumps({
            "status": "pending",
            "message": "Waiting for user confirmation"
        })
    
    # 2. Process the User's Response
    # We use str() to be safe, and .get() to pull from the root of the JSON
    is_approved = tool_confirmation.payload["approve"].strip().upper() == "APPROVE"  
    if is_approved:
        try:
            space_key = tool_confirmation.payload["space_key"].strip()
            title = tool_confirmation.payload["title"].strip()
            
            if not space_key or not title:
                return json.dumps({
                    "status": "error",
                    "message": "Missing space_key or title for publishing."
                })
            
            # Publish
            publish_result = publish_to_confluence(space_key, title, draft)
            
            return json.dumps({
                "status": "success",
                "message": publish_result
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Error publishing to Confluence: {str(e)}"
            })
    else:
        # User Rejected
        feedback = tool_confirmation.payload["feedback"]
        return json.dumps({
            "status": "rejected",
            "message": f"Draft rejected by user. Feedback: {feedback}"
        })