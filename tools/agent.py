from google.adk.runners import Runner
from google.adk.agents import Agent, SequentialAgent
from google.adk.tools import AgentTool, google_search
from google.adk.models.google_llm import Gemini
from tools.tools import github_tools, ask_human_approval, get_confluence_page_content
from tools.config import retry_config
from google.adk.sessions import DatabaseSessionService
from google.adk.apps import App, ResumabilityConfig
from tools.prompts import (
    ARCHITECT_SYSTEM_PROMPT, ORCHESTRATOR_PROMPT, CONFLUENCE_DRAFT_PROMPT, 
    REFINER_PROMPT, FLOW_CREATOR_PROMPT,
    CHANGELOG_PROMPT, UPDATER_PROMPT
)

# Optimized model usage
model = Gemini(model="gemini-2.5-pro", retry_options=retry_config)
model_flash = Gemini(model="gemini-2.5-flash", retry_options=retry_config)
model_flash_lite = Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config)


# --------------------------
# Agent: Normal Chat Agent
# --------------------------
Chat_agent = Agent(
    name="chat_agent", 
    model=model_flash,
    instruction="You are a helpful assistant which can help users with code related queries.",
    tools=[google_search],
    output_key="chat_response"
)


# --------------------------
# Agent: Repo Architect
# --------------------------
Repo_agent = Agent(
    name="repo_agent",
    model=model_flash,
    instruction=ARCHITECT_SYSTEM_PROMPT,
    tools=[github_tools],
    output_key="Repo_Architecture"
)

# --------------------------
# Agent: Flow Creator
# --------------------------
Flow_Creator_Agent = Agent(
    name="flow_creator_agent",
    model=model_flash_lite,
    instruction=FLOW_CREATOR_PROMPT,
    output_key="Mermaid_Diagram"
)

# --------------------------
# Agent: Confluence Drafter (Creator)
# --------------------------
Confluence_drafter = Agent(
    name="confluence_agent",
    model=model_flash,
    instruction=CONFLUENCE_DRAFT_PROMPT,
    output_key="Confluence_Draft"
)

# --------------------------
# Changelog
# --------------------------
Changelog_Agent = Agent(
    name="changelog_agent",
    model=model_flash,
    instruction=CHANGELOG_PROMPT,
    tools=[github_tools],
    description="Analyzes git history to create release notes.",
    output_key="New_Section_Content"
)

# --------------------------
# NEW AGENT: Content Updater (Merger)
# --------------------------
Updater_Agent = Agent(
    name="updater_agent",
    model=model_flash_lite,
    instruction=UPDATER_PROMPT,
    description="Merges new content into existing Confluence pages.",
    output_key="Confluence_Draft" # Reuses key so Refiner/Approval works
)

# --------------------------
# Agent: Refiner Agent
# --------------------------
Refiner_agent = Agent(
    name="refiner_agent",
    model=model_flash_lite,
    instruction=REFINER_PROMPT,
    tools=[ask_human_approval],
    output_key="Published_document"
)

# --------------------------
# Sequence: Data Gathering (Creation)
# --------------------------
Data_Agent = SequentialAgent(
   name="Data_agent",
   sub_agents=[Repo_agent, Flow_Creator_Agent],
   description="Extracts repo structure and mermaid diagrams.",
)

# --------------------------
# Agent: Orchestrator Agent
# --------------------------
Orchestrator_Agent = Agent(
    name="orchestrator_agent",
    model=model_flash,
    instruction=ORCHESTRATOR_PROMPT,
    tools=[
        AgentTool(Chat_agent),
        AgentTool(Data_Agent),
        AgentTool(Repo_agent),
        AgentTool(Confluence_drafter),
        AgentTool(Changelog_Agent),
        AgentTool(Updater_Agent),
        AgentTool(Refiner_agent),
        get_confluence_page_content, # Direct tool access
        ask_human_approval
    ],
    description="Orchestrates the workflow between data extraction, documentation drafting, and refinement.",
    output_key="Final_Output"
)

root_agent = Orchestrator_Agent

session_service = DatabaseSessionService(db_url="sqlite+aiosqlite:///sessions.db")

app = App(
    root_agent=root_agent,
    name="tools",
    resumability_config=ResumabilityConfig(is_resumable=True)
)

runner = Runner(
    app=app,
    session_service=session_service
)
