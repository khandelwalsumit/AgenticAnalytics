---
name: excalidraw-diagram
description: Generate a complete Excalidraw architecture diagram in JSON format for the project."
---
# Instruction: Generate Excalidraw Architecture Diagram

Whenever I ask for an excalidraw diagram, you must generate a complete, importable Excalidraw JSON file that visually explains the full project architecture.

Follow these strict rules:

1. Output Format
- Return ONLY valid Excalidraw JSON.
- No explanations.
- No markdown.
- No code fences.
- The output must be directly importable into https://excalidraw.com.

2. Diagram Requirements
- Use rectangles for system components.
- Use arrows to represent data flow.
- Group related components visually.
- Use clear labels for every block.
- Keep spacing clean and structured.
- Layout must be left-to-right unless otherwise specified.

3. Architectural Coverage
The diagram must include:

- Client Layer (e.g., Web App / Chainlit UI / Frontend)
- API Layer (Flask / FastAPI / Node server etc.)
- Agent Orchestration Layer (LangGraph)
- LLM Layer (Vertex AI / Gemini or configurable LLM module)
- Vector Store (FAISS with folder-based indexing)
- Embeddings Pipeline
- File Storage / Prompt Repository
- Workspace & Folder Segmentation
- Tooling Layer (if applicable)
- External APIs (if applicable)
- Logging / Monitoring (if applicable)

4. Flow Representation
Show clearly:
- User query flow
- Embedding generation flow
- Retrieval (RAG) flow
- Agent decision-making loop
- Tool invocation (if exists)
- Response returned to user

5. Styling Guidelines
- Use consistent colors:
  - Frontend: Light Blue
  - Backend/API: Purple
  - Agent Layer: Orange
  - LLM: Green
  - Vector DB: Yellow
  - Storage: Gray
- Use labeled arrows like:
  - "User Query"
  - "Embed"
  - "Retrieve"
  - "Generate"
  - "Return Response"

6. Complexity Level
- The diagram should be detailed enough for a technical architecture review.
- It should clearly explain the system to engineers.
- Avoid oversimplified diagrams.

7. If the project involves:
- Multi-agent setup → show agent nodes and shared state.
- RAG → show embedding + vector store interaction.
- Modular LLM wrapper → show LLM abstraction layer.
- Workspaces/folders → show separate FAISS indices per folder.

Always assume the project is production-grade and architect accordingly.