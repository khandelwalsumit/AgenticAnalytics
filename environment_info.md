# Environment Info

## Python
- Version: 3.13
- Environment: virtualenv at `.venv/Scripts/activate` with `uv` manager

## Core Packages & Versions
- google-cloude-aiplatform>=1.71.0
- vertexai >1.71.0
- langgraph > 1.0.0
- langchain > 1.2.0
- langchain-core > 1.2.0
- chainlit > 1.0.500

## LLM / API Config
- Provider: VertexIA cutomer wrapper with google auth in seperate file... you just use core/llm.py with vertex ai api.. i wil change he tcode when i use in environment

## Constraints
- vertexai version is very specific, dosent let me use "field name for additnal properties"
- `always use create_agent  from langchain.agents` not create_react_agent
- I dont have fan out from langchain, implement any parallelism you need using multithreading
- **critical** vertexai requires al schemas to be fully expanded , with no $ref fields

