Plan to implement                                                                                                                                                                                                                        

Agentic Analytics System - Implementation Plan                                                                                                                                                                                           

Context                                                                                                                                                                                                                                  

The Customer Experience team has 300K+ call records processed through batch LLM, producing structured analysis fields (problem statements, friction categories, solution pathways, L1-L5 call reason hierarchies). They need an          
intelligent, multi-agent system that helps analysts interactively explore this data, identify friction points, extract actionable insights, and generate crisp reports — all through a conversational UI.                                

Tech stack: LangGraph (orchestration) + Gemini via custom VertexAI endpoint (LLM) + Chainlit (UI)                                                                                                                                        

---                                                                                                                                                                                                                                      
Key Design Decisions                                                                                                                                                                                                                     

1. Markdown-Driven Agent & Skill Definitions                                                                                                                                                                                             

Agents and skills are defined as Markdown files — no Python code for prompt engineering. This makes it trivial to add/update agents or skills without touching application code.                                                         

Agent Markdown Format (agents/definitions/<name>.md):                                                                                                                                                                                    
---                                                                                                                                                                                                                                      
name: data_analyst                                                                                                                                                                                                                       
model: gemini-pro                                                                                                                                                                                                                        
temperature: 0.1                                                                                                                                                                                                                         
top_p: 0.95                                                                                                                                                                                                                              
max_tokens: 8192                                                                                                                                                                                                                         
description: "Prepares data through schema discovery, filtering, and bucketing"                                                                                                                                                          
tools:                                                                                                                                                                                                                                   
  - load_dataset                                                                                                                                                                                                                         
  - filter_data                                                                                                                                                                                                                          
  - bucket_data                                                                                                                                                                                                                          
  - sample_data                                                                                                                                                                                                                          
  - get_distribution                                                                                                                                                                                                                     
---                                                                                                                                                                                                                                      

You are a Data Analyst agent specializing in customer experience data...                                                                                                                                                                 

## Your Responsibilities                                                                                                                                                                                                                 
...system prompt continues...                                                                                                                                                                                                            

Skill Markdown Format (skills/domain/<name>.md or skills/operational/<name>.md):                                                                                                                                                         
# Payment & Transfer Analysis Skill                                                                                                                                                                                                      

## Focus Areas                                                                                                                                                                                                                           
- Payment failures, transfer issues, refunds, limits                                                                                                                                                                                     
...                                                                                                                                                                                                                                      

## Key Fields to Analyze                                                                                                                                                                                                                 
- exact_problem_statement, digital_friction, solution_by_ui, solution_by_technology                                                                                                                                                      
...                                                                                                                                                                                                                                      

## Analysis Framework                                                                                                                                                                                                                    
When analyzing payment & transfer issues, follow this structure:                                                                                                                                                                         
1. Categorize by failure type...                                                                                                                                                                                                         
...                                                                                                                                                                                                                                      

2. Merged Supervisor (no separate Planner)                                                                                                                                                                                               

The original design had User → Supervisor → Planner → Supervisor → Agent — two LLM calls per step. Merged: Supervisor now generates PlanStep, executes it, and updates progress in a single pass. This halves latency and cost. Can be   
re-split later if planning logic becomes heavy.                                                                                                                                                                                          

3. AgentFactory Class                                                                                                                                                                                                                    

A Python class that reads agent markdown files and uses create_react_agent from LangGraph + ChatVertexAI to instantiate agents dynamically.                                                                                              

4. Deterministic Metrics Engine                                                                                                                                                                                                          

All quantitative computations (% distribution, top themes, comparison ratios, volume counts) are Python-computed, not LLM-inferred. The LLM interprets and narrates metrics — never computes them. This is implemented as a              
MetricsEngine class in tools/metrics.py that the Data Analyst tools call internally.                                                                                                                                                     

5. Data Payloads Out of Conversational Context                                                                                                                                                                                           

Raw DataFrames and large text blobs (report markdown, bucket data) are stored in a session-scoped DataStore (file-backed cache keyed by session ID). AnalyticsState only holds metadata references (e.g., "Bucket A: 15,000 rows, Top    
Issue: Authentication"). Agents fetch full data via tools when needed. This prevents memory bloat, slow serialization, and large thread persistence.                                                                                     

6. XML-Wrapped Skill Injection                                                                                                                                                                                                           

SkillLoader wraps each skill's content in XML tags during injection: <skill name="payment_transfer">...content...</skill>. LLMs are highly optimized to read XML boundaries, improving cross-referencing accuracy.                       

7. Insight Ranking System                                                                                                                                                                                                                

Business Analyst outputs structured, scored findings — not free-text. Each finding includes impact_score (volume × friction_severity), ease_score (inverse complexity), and confidence. Report Analyst becomes formatting-only — no      
analytical judgment needed.                                                                                                                                                                                                              

8. Scope Detector as Dedicated Classification Node                                                                                                                                                                                       

Post-analysis Q&A scope detection uses a lightweight, dedicated classification node with structured_output enforcing a strict in_scope: bool response — not a general conversation node. Fast, deterministic, low-cost.                  

9. Chainlit UI Enhancements                                                                                                                                                                                                              

- Chat history persistence — resume previous sessions                                                                                                                                                                                    
- Critique toggle — on/off switch per chat session                                                                                                                                                                                       
- Download buttons — report (PPT) + data file at end of analysis                                                                                                                                                                         
- Planner banner — top banner showing current plan step and completion progress                                                                                                                                                          
- Agent reasoning steps — each node's reasoning displayed as collapsible step-name / step-text                                                                                                                                           
- Waiting indicator — blinking colored indicator when awaiting user confirmation                                                                                                                                                         

---                                                                                                                                                                                                                                      
Architecture                                                                                                                                                                                                                             

User (Chainlit UI)                                                                                                                                                                                                                       
  │  ┌────────────────────────────────────┐                                                                                                                                                                                              
  │  │ Banner: Plan steps & progress      │                                                                                                                                                                                              
  │  │ Toggle: Critique ON/OFF            │                                                                                                                                                                                              
  │  └────────────────────────────────────┘                                                                                                                                                                                              
  ▼                                                                                                                                                                                                                                      
┌──────────────────────────────────────────┐                                                                                                                                                                                             
│              SUPERVISOR                  │                                                                                                                                                                                             
│  (Plan + Route + Manage checkpoints)     │                                                                                                                                                                                             
└────┬─────────┬───────────┬──────────┬────┘                                                                                                                                                                                             
     ▼         ▼           ▼          ▼                                                                                                                                                                                                  
  ┌──────┐ ┌────────┐ ┌────────┐ ┌────────┐                                                                                                                                                                                              
  │ Data │ │Business│ │Report  │ │Critique│                                                                                                                                                                                              
  │Analyst│ │Analyst │ │Analyst │ │(toggle)│                                                                                                                                                                                              
  └──────┘ └────────┘ └────────┘ └────────┘                                                                                                                                                                                              
     │          │         │                                                                                                                                                                                                              
  [Tools]   [Skills]   [DataStore]                                                                                                                                                                                                       
  [Metrics]  (XML)     (file-backed)                                                                                                                                                                                                     
            ┌────┴────┐                                                                                                                                                                                                                  
       Domain      Operational                                                                                                                                                                                                           
       Skills       Skills                                                                                                                                                                                                               

  Post-Analysis:                                                                                                                                                                                                                         
  ┌──────────────────┐                                                                                                                                                                                                                   
  │  SCOPE DETECTOR  │  ← lightweight classification node                                                                                                                                                                                
  │  (structured     │     with_structured_output(bool)                                                                                                                                                                                  
  │   output)        │                                                                                                                                                                                                                   
  └──────────────────┘                                                                                                                                                                                                                   

---                                                                                                                                                                                                                                      
Project Structure                                                                                                                                                                                                                        

AgenticAnalytics/                                                                                                                                                                                                                        
├── app.py                              # Chainlit entry point                                                                                                                                                                           
├── pyproject.toml                      # Dependencies                                                                                                                                                                                   
├── .env.example                        # Environment template                                                                                                                                                                           
├── .chainlit/                          # Chainlit config                                                                                                                                                                                
│   └── config.toml                     # Chainlit settings                                                                                                                                                                              
├── config/                                                                                                                                                                                                                              
│   ├── __init__.py                                                                                                                                                                                                                      
│   └── settings.py                     # App config (model, paths, thresholds)                                                                                                                                                          
├── core/                                                                                                                                                                                                                                
│   ├── __init__.py                                                                                                                                                                                                                      
│   ├── agent_factory.py                # AgentFactory: reads .md → creates LangGraph agents                                                                                                                                             
│   ├── skill_loader.py                 # SkillLoader: reads skill .md files, wraps in XML, injects into prompts                                                                                                                         
│   ├── data_store.py                   # DataStore: session-scoped file-backed cache for large payloads                                                                                                                                 
│   └── llm.py                          # VertexAI/Gemini LLM factory                                                                                                                                                                    
├── agents/                                                                                                                                                                                                                              
│   ├── __init__.py                                                                                                                                                                                                                      
│   ├── state.py                        # AnalyticsState TypedDict + ExecutionTrace + ScopeSnapshot + RankedFinding                                                                                                                      
│   ├── graph.py                        # Main LangGraph StateGraph assembly                                                                                                                                                             
│   ├── nodes.py                        # Agent node functions (thin wrappers using AgentFactory)                                                                                                                                        
│   └── definitions/                    # Agent definitions as Markdown                                                                                                                                                                  
│       ├── supervisor.md               # Supervisor (includes planning logic — no separate planner)                                                                                                                                     
│       ├── data_analyst.md                                                                                                                                                                                                              
│       ├── business_analyst.md                                                                                                                                                                                                          
│       ├── report_analyst.md                                                                                                                                                                                                            
│       └── critique.md                                                                                                                                                                                                                  
├── skills/                             # Skills as Markdown                                                                                                                                                                             
│   ├── domain/                                                                                                                                                                                                                          
│   │   ├── payment_transfer.md                                                                                                                                                                                                          
│   │   ├── transaction_statement.md                                                                                                                                                                                                     
│   │   ├── authentication.md                                                                                                                                                                                                            
│   │   ├── profile_settings.md                                                                                                                                                                                                          
│   │   ├── fraud_dispute.md                                                                                                                                                                                                             
│   │   └── rewards.md                                                                                                                                                                                                                   
│   └── operational/                                                                                                                                                                                                                     
│       ├── digital.md                                                                                                                                                                                                                   
│       ├── operations.md                                                                                                                                                                                                                
│       └── policy.md                                                                                                                                                                                                                    
├── tools/                                                                                                                                                                                                                               
│   ├── __init__.py                                                                                                                                                                                                                      
│   ├── data_tools.py                   # load_dataset, filter_data, bucket_data, sample_data, get_distribution                                                                                                                          
│   ├── metrics.py                      # MetricsEngine: deterministic Python computations (distributions, rankings, comparisons)                                                                                                        
│   └── report_tools.py                 # generate_markdown_report, export_to_pptx                                                                                                                                                       
├── utils/                                                                                                                                                                                                                               
│   ├── __init__.py                                                                                                                                                                                                                      
│   └── pptx_export.py                  # Markdown → PowerPoint converter                                                                                                                                                                
├── ui/                                                                                                                                                                                                                                  
│   ├── __init__.py                                                                                                                                                                                                                      
│   ├── components.py                   # Chainlit UI components (banner, steps, indicators)                                                                                                                                             
│   └── chat_history.py                 # Chat history persistence                                                                                                                                                                       
└── data/                                                                                                                                                                                                                                
    └── .gitkeep                        # Placeholder for CSV data                                                                                                                                                                       

---                                                                                                                                                                                                                                      
Agent Definitions                                                                                                                                                                                                                        

1. Supervisor (agents/definitions/supervisor.md)                                                                                                                                                                                         

- Config: tools: [delegate_to_agent], low temperature                                                                                                                                                                                    
- Role: Receives user input, generates plan step, routes to agents, manages checkpoints — all in one pass (no separate Planner)                                                                                                          
- Planning behavior: Before each delegation, generates a structured PlanStep (next_agent, task_description, requires_user_input, reasoning), executes it, and updates progress counters                                                  
- Key behavior: Manages the guided flow with user checkpoints; updates execution_trace after each step                                                                                                                                   
- Q&A mode behavior: When phase == "qa", delegates to the Scope Detector node first:                                                                                                                                                     
  - Scope Detector returns in_scope: bool via structured_output                                                                                                                                                                          
  - In-scope: Supervisor answers directly using findings, data buckets, report artifacts                                                                                                                                                 
  - Out-of-scope: explains divergence, suggests new chat with "New Chat" action button                                                                                                                                                   

2. Data Analyst (agents/definitions/data_analyst.md)                                                                                                                                                                                     

- Config: tools: [load_dataset, filter_data, bucket_data, sample_data, get_distribution]                                                                                                                                                 
- Role: Data preparation — schema discovery, filtering, bucketing                                                                                                                                                                        
- Tool details:                                                                                                                                                                                                                          
  - load_dataset(path) → loads CSV, returns schema + basic stats                                                                                                                                                                         
  - filter_data(filters: dict) → applies column-value filters, returns filtered count                                                                                                                                                    
  - bucket_data(group_by: str, focus: str) → groups data into named buckets                                                                                                                                                              
  - sample_data(bucket: str, n: int) → random sample from a bucket                                                                                                                                                                       
  - get_distribution(column: str) → value counts / distribution for a column                                                                                                                                                             

3. Business Analyst (agents/definitions/business_analyst.md)                                                                                                                                                                             

- Config: tools: [analyze_bucket, apply_skill, get_findings_summary]                                                                                                                                                                     
- Role: Core analysis — friction points, root causes, actionable findings                                                                                                                                                                
- Skill integration: System prompt is dynamically augmented with XML-wrapped skill markdown content                                                                                                                                      
- Insight Ranking: Outputs structured, scored findings — not free-text:                                                                                                                                                                  
{                                                                                                                                                                                                                                        
  "finding": "...",                                                                                                                                                                                                                      
  "category": "...",                                                                                                                                                                                                                     
  "volume": 12.3,                    # % of records affected                                                                                                                                                                             
  "impact_score": 0.82,              # volume × friction_severity (deterministic)                                                                                                                                                        
  "ease_score": 0.41,                # inverse_complexity                                                                                                                                                                                
  "confidence": 0.91,                                                                                                                                                                                                                    
  "recommended_action": "..."                                                                                                                                                                                                            
}                                                                                                                                                                                                                                        
- Tool details:                                                                                                                                                                                                                          
  - analyze_bucket(bucket: str, questions: list) → analyzes a data bucket against specific questions                                                                                                                                     
  - apply_skill(skill_name: str, data: str) → loads skill .md (XML-wrapped), applies its framework to data                                                                                                                               
  - get_findings_summary() → aggregates all findings so far                                                                                                                                                                              

4. Report Analyst (agents/definitions/report_analyst.md)                                                                                                                                                                                 

- Config: tools: [generate_markdown_report, export_to_pptx]                                                                                                                                                                              
- Role: Formatting-only — takes ranked findings from Business Analyst and structures them into report sections. No analytical judgment.                                                                                                  
- Data access: Fetches full report/bucket data from DataStore via tools only when it's time to write or export                                                                                                                           
- Sections: Executive Summary, Detailed Findings, Impact vs Ease Matrix, Recommendations, Data Appendix                                                                                                                                  

5. Critique (agents/definitions/critique.md)                                                                                                                                                                                             

- Config: tools: [validate_findings, score_quality]                                                                                                                                                                                      
- Role: QA on all analyst outputs — toggleable by user                                                                                                                                                                                   
- Checks: Data accuracy, completeness, actionability, consistency, bias                                                                                                                                                                  

6. Scope Detector (dedicated classification node — no .md file)                                                                                                                                                                          

- Implementation: Lightweight node using llm.with_structured_output(ScopeDecision) — not a full agent                                                                                                                                    
- Input: User question + analysis_scope snapshot                                                                                                                                                                                         
- Output: ScopeDecision(in_scope: bool, reason: str)                                                                                                                                                                                     
- Usage: Called by graph routing in Q&A phase before Supervisor processes the question                                                                                                                                                   

---                                                                                                                                                                                                                                      
Skills                                                                                                                                                                                                                                   

Domain Skills                                                                                                                                                                                                                            

┌─────────────────────────┬────────────────────────────────────────┬───────────────────────────────────────────────────────┐                                                                                                             
│          Skill          │                  File                  │                         Focus                         │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Payment & Transfer      │ skills/domain/payment_transfer.md      │ Payment failures, transfer issues, refunds, limits    │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Transaction & Statement │ skills/domain/transaction_statement.md │ Transaction history, statement access, discrepancies  │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Authentication          │ skills/domain/authentication.md        │ Login issues, OTP, biometric, session management      │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Profile & Settings      │ skills/domain/profile_settings.md      │ Profile updates, preferences, notification settings   │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Fraud & Dispute         │ skills/domain/fraud_dispute.md         │ Unauthorized transactions, dispute resolution, alerts │                                                                                                             
├─────────────────────────┼────────────────────────────────────────┼───────────────────────────────────────────────────────┤                                                                                                             
│ Rewards                 │ skills/domain/rewards.md               │ Points, cashback, redemption, tier benefits           │                                                                                                             
└─────────────────────────┴────────────────────────────────────────┴───────────────────────────────────────────────────────┘                                                                                                             

Operational Skills                                                                                                                                                                                                                       

┌────────────┬──────────────────────────────────┬──────────────────────────────────────────────────────┐                                                                                                                                 
│   Skill    │               File               │                        Focus                         │                                                                                                                                 
├────────────┼──────────────────────────────────┼──────────────────────────────────────────────────────┤                                                                                                                                 
│ Digital    │ skills/operational/digital.md    │ UI/UX issues, mobile vs web, findability, navigation │                                                                                                                                 
├────────────┼──────────────────────────────────┼──────────────────────────────────────────────────────┤                                                                                                                                 
│ Operations │ skills/operational/operations.md │ Process gaps, agent training, SLA issues             │                                                                                                                                 
├────────────┼──────────────────────────────────┼──────────────────────────────────────────────────────┤                                                                                                                                 
│ Policy     │ skills/operational/policy.md     │ Policy clarity, compliance, customer communication   │                                                                                                                                 
└────────────┴──────────────────────────────────┴──────────────────────────────────────────────────────┘                                                                                                                                 

---                                                                                                                                                                                                                                      
Core Components                                                                                                                                                                                                                          

AgentFactory (core/agent_factory.py)                                                                                                                                                                                                     

class AgentFactory:                                                                                                                                                                                                                      
    """Reads agent .md files → creates LangGraph agents with VertexAI."""                                                                                                                                                                

    def __init__(self, definitions_dir: str, llm_factory):                                                                                                                                                                               
        self.definitions_dir = definitions_dir                                                                                                                                                                                           
        self.llm_factory = llm_factory                                                                                                                                                                                                   
        self._cache = {}                                                                                                                                                                                                                 

    def parse_agent_md(self, name: str) -> AgentConfig:                                                                                                                                                                                  
        """Parse YAML frontmatter + system prompt from .md file."""                                                                                                                                                                      
        # Returns: AgentConfig(name, model, temperature, top_p, max_tokens,                                                                                                                                                              
        #          description, tools, system_prompt)                                                                                                                                                                                    

    def make_agent(self, name: str, extra_context: str = "") -> CompiledGraph:                                                                                                                                                           
        """Create a LangGraph agent using create_react_agent.                                                                                                                                                                            
        - Reads agent .md → parses config + prompt                                                                                                                                                                                       
        - Resolves tools from registry                                                                                                                                                                                                   
        - Optionally appends XML-wrapped skill content to system prompt (extra_context)                                                                                                                                                  
        - Creates ChatVertexAI with config params                                                                                                                                                                                        
        - Returns compiled agent via create_react_agent                                                                                                                                                                                  
        """                                                                                                                                                                                                                              

    def make_node(self, name: str) -> Callable:                                                                                                                                                                                          
        """Returns a node function for use in the main StateGraph."""                                                                                                                                                                    

SkillLoader (core/skill_loader.py)                                                                                                                                                                                                       

class SkillLoader:                                                                                                                                                                                                                       
    """Reads skill .md files, wraps in XML tags, and provides them for prompt injection."""                                                                                                                                              

    def __init__(self, skills_dir: str):                                                                                                                                                                                                 
        self.skills_dir = skills_dir                                                                                                                                                                                                     

    def load_skill(self, category: str, name: str) -> str:                                                                                                                                                                               
        """Load a skill markdown file. Wraps content in XML tags:                                                                                                                                                                        
        <skill name="payment_transfer" category="domain">                                                                                                                                                                                
        ...content...                                                                                                                                                                                                                    
        </skill>                                                                                                                                                                                                                         
        """                                                                                                                                                                                                                              

    def load_skills(self, skill_names: list[str]) -> str:                                                                                                                                                                                
        """Load multiple skills, each XML-wrapped, concatenated."""                                                                                                                                                                      

    def list_skills(self) -> dict[str, list[str]]:                                                                                                                                                                                       
        """Returns available skills grouped by category."""                                                                                                                                                                              

DataStore (core/data_store.py)                                                                                                                                                                                                           

class DataStore:                                                                                                                                                                                                                         
    """Session-scoped file-backed cache for large data payloads.                                                                                                                                                                         

    Keeps raw DataFrames, report markdown, and bucket data OUT of                                                                                                                                                                        
    the conversational context / LangGraph state. State only holds                                                                                                                                                                       
    metadata references (e.g., bucket_id, row_count, top_issue).                                                                                                                                                                         
    """                                                                                                                                                                                                                                  

    def __init__(self, session_id: str, cache_dir: str = ".cache"):                                                                                                                                                                      
        self.session_id = session_id                                                                                                                                                                                                     
        self.cache_dir = cache_dir                                                                                                                                                                                                       
        self._registry = {}  # key → {path, metadata}                                                                                                                                                                                    

    def store_dataframe(self, key: str, df: pd.DataFrame, metadata: dict) -> str:                                                                                                                                                        
        """Store DataFrame to parquet, return reference key."""                                                                                                                                                                          

    def get_dataframe(self, key: str) -> pd.DataFrame:                                                                                                                                                                                   
        """Retrieve DataFrame by key."""                                                                                                                                                                                                 

    def store_text(self, key: str, content: str, metadata: dict) -> str:                                                                                                                                                                 
        """Store large text (report markdown, etc.) to file."""                                                                                                                                                                          

    def get_text(self, key: str) -> str:                                                                                                                                                                                                 
        """Retrieve text content by key."""                                                                                                                                                                                              

    def get_metadata(self, key: str) -> dict:                                                                                                                                                                                            
        """Return metadata only (for state storage)."""                                                                                                                                                                                  

    def list_keys(self) -> list[str]:                                                                                                                                                                                                    
        """List all stored keys for this session."""                                                                                                                                                                                     

    def cleanup(self):                                                                                                                                                                                                                   
        """Remove all cached files for this session."""                                                                                                                                                                                  

MetricsEngine (tools/metrics.py)                                                                                                                                                                                                         

class MetricsEngine:                                                                                                                                                                                                                     
    """Deterministic Python computations — keeps math out of LLM.                                                                                                                                                                        

    All quantitative operations (distributions, rankings, comparisons,                                                                                                                                                                   
    impact scores) are computed here. LLM interprets results, never computes.                                                                                                                                                            
    """                                                                                                                                                                                                                                  

    @staticmethod                                                                                                                                                                                                                        
    def get_distribution(df: pd.DataFrame, column: str) -> dict:                                                                                                                                                                         
        """Value counts with percentages."""                                                                                                                                                                                             

    @staticmethod                                                                                                                                                                                                                        
    def compute_impact_score(volume_pct: float, friction_severity: float) -> float:                                                                                                                                                      
        """impact = volume × friction_severity"""                                                                                                                                                                                        

    @staticmethod                                                                                                                                                                                                                        
    def compute_ease_score(complexity: float) -> float:                                                                                                                                                                                  
        """ease = 1 - complexity (normalized 0-1)"""                                                                                                                                                                                     

    @staticmethod                                                                                                                                                                                                                        
    def rank_findings(findings: list[dict], sort_by: str = "impact_score") -> list[dict]:                                                                                                                                                
        """Sort findings by score, add rank field."""                                                                                                                                                                                    

    @staticmethod                                                                                                                                                                                                                        
    def compare_buckets(df_a: pd.DataFrame, df_b: pd.DataFrame, column: str) -> dict:                                                                                                                                                    
        """Cross-bucket comparison ratios."""                                                                                                                                                                                            

    @staticmethod                                                                                                                                                                                                                        
    def top_n(df: pd.DataFrame, column: str, n: int = 10) -> list[dict]:                                                                                                                                                                 
        """Top N values by frequency."""                                                                                                                                                                                                 

LLM Factory (core/llm.py)                                                                                                                                                                                                                

def get_llm(model: str = "gemini-pro", temperature: float = 0.1,                                                                                                                                                                         
            top_p: float = 0.95, max_tokens: int = 8192) -> ChatVertexAI:                                                                                                                                                                
    """Create a ChatVertexAI instance with custom endpoint config."""                                                                                                                                                                    

---                                                                                                                                                                                                                                      
Shared State (agents/state.py)                                                                                                                                                                                                           

# --- Structured Types ---                                                                                                                                                                                                               

class ExecutionTrace(TypedDict):                                                                                                                                                                                                         
    """Structured trace for each agent execution step.                                                                                                                                                                                   
    Enables debugging, governance, performance tracking, cost analytics."""                                                                                                                                                              
    step_id: str                                                                                                                                                                                                                         
    agent: str                                                                                                                                                                                                                           
    input_summary: str                                                                                                                                                                                                                   
    output_summary: str                                                                                                                                                                                                                  
    tools_used: list[str]                                                                                                                                                                                                                
    latency_ms: int                                                                                                                                                                                                                      
    success: bool                                                                                                                                                                                                                        

class ScopeSnapshot(TypedDict):                                                                                                                                                                                                          
    """Strict scope definition for Q&A validation, audit, and report headers."""                                                                                                                                                         
    dataset_path: str                                                                                                                                                                                                                    
    filters: dict                                                                                                                                                                                                                        
    skills_used: list[str]                                                                                                                                                                                                               
    buckets_created: list[str]                                                                                                                                                                                                           
    focus_column: str                                                                                                                                                                                                                    

class RankedFinding(TypedDict):                                                                                                                                                                                                          
    """Structured, scored finding from Business Analyst."""                                                                                                                                                                              
    finding: str                                                                                                                                                                                                                         
    category: str                                                                                                                                                                                                                        
    volume: float                       # % of records affected                                                                                                                                                                          
    impact_score: float                 # volume × friction_severity (Python-computed)                                                                                                                                                   
    ease_score: float                   # inverse_complexity (Python-computed)                                                                                                                                                           
    confidence: float                                                                                                                                                                                                                    
    recommended_action: str                                                                                                                                                                                                              

class ScopeDecision(TypedDict):                                                                                                                                                                                                          
    """Output of the Scope Detector classification node."""                                                                                                                                                                              
    in_scope: bool                                                                                                                                                                                                                       
    reason: str                                                                                                                                                                                                                          

# --- Main State ---                                                                                                                                                                                                                     

class AnalyticsState(TypedDict):                                                                                                                                                                                                         
    messages: Annotated[list[AnyMessage], add_messages]                                                                                                                                                                                  

    # User intent                                                                                                                                                                                                                        
    user_focus: str                                                                                                                                                                                                                      
    analysis_type: str                  # "domain" | "operational" | "combined"                                                                                                                                                          
    selected_skills: list[str]                                                                                                                                                                                                           
    critique_enabled: bool              # Toggle from UI                                                                                                                                                                                 

    # Plan (Supervisor generates + executes — no separate planner)                                                                                                                                                                       
    current_plan: dict                  # Current PlanStep                                                                                                                                                                               
    plan_steps_total: int               # For banner progress                                                                                                                                                                            
    plan_steps_completed: int                                                                                                                                                                                                            

    # Execution trace (structured, not raw dicts)                                                                                                                                                                                        
    execution_trace: list[ExecutionTrace]                                                                                                                                                                                                

    # Data — METADATA ONLY (raw data lives in DataStore)                                                                                                                                                                                 
    dataset_path: str                                                                                                                                                                                                                    
    dataset_schema: dict                                                                                                                                                                                                                 
    active_filters: dict                                                                                                                                                                                                                 
    data_buckets: dict[str, dict]       # key → {row_count, top_issues, columns} — NOT raw DataFrames                                                                                                                                    

    # Analysis — scored findings                                                                                                                                                                                                         
    findings: list[RankedFinding]       # Structured, ranked findings                                                                                                                                                                    
    domain_analysis: dict                                                                                                                                                                                                                
    operational_analysis: dict                                                                                                                                                                                                           

    # Report — metadata only (full text in DataStore)                                                                                                                                                                                    
    report_markdown_key: str            # DataStore key for full report text                                                                                                                                                             
    report_file_path: str                                                                                                                                                                                                                
    data_file_path: str                 # For download button                                                                                                                                                                            

    # Quality                                                                                                                                                                                                                            
    critique_feedback: dict                                                                                                                                                                                                              
    quality_score: float                                                                                                                                                                                                                 

    # Control flow                                                                                                                                                                                                                       
    next_agent: str                                                                                                                                                                                                                      
    requires_user_input: bool                                                                                                                                                                                                            
    checkpoint_message: str                                                                                                                                                                                                              
    phase: str                          # "analysis" | "qa" — tracks current mode                                                                                                                                                        

    # Q&A mode                                                                                                                                                                                                                           
    analysis_complete: bool             # True after report delivered                                                                                                                                                                    
    analysis_scope: ScopeSnapshot       # Strict scope for Q&A validation + audit                                                                                                                                                        

    # UI state                                                                                                                                                                                                                           
    agent_reasoning: list[dict]         # [{step_name, step_text, agent}]                                                                                                                                                                

---                                                                                                                                                                                                                                      
Chainlit UI (app.py + ui/)                                                                                                                                                                                                               

Chat History (ui/chat_history.py)                                                                                                                                                                                                        

- Persist conversation state using Chainlit's built-in thread persistence                                                                                                                                                                
- User can resume previous analysis sessions from sidebar                                                                                                                                                                                

Banner & Progress (ui/components.py)                                                                                                                                                                                                     

- Planner Banner: Top-of-chat element showing:                                                                                                                                                                                           
  - Current step name and description                                                                                                                                                                                                    
  - Progress bar (step X of Y)                                                                                                                                                                                                           
  - Completed steps with checkmarks                                                                                                                                                                                                      
- Agent Reasoning Steps: Each agent execution rendered as:                                                                                                                                                                               
  - Collapsible cl.Step(name="Data Analyst", type="tool") with reasoning text                                                                                                                                                            
- Waiting Indicator: Animated blinking element with color when awaiting user confirmation                                                                                                                                                
  - Uses cl.Message with custom CSS class for pulsing animation                                                                                                                                                                          

Critique Toggle                                                                                                                                                                                                                          

- Settings panel or inline button: "Critique: ON / OFF"                                                                                                                                                                                  
- Stored in AnalyticsState.critique_enabled                                                                                                                                                                                              
- When OFF, supervisor skips critique node entirely                                                                                                                                                                                      

Download Buttons                                                                                                                                                                                                                         

- At end of analysis, render two cl.Action buttons:                                                                                                                                                                                      
  - "Download Report (PPT)" → serves generated .pptx file                                                                                                                                                                                
  - "Download Data File" → serves the filtered/bucketed CSV                                                                                                                                                                              

---                                                                                                                                                                                                                                      
Data Schema (CSV Columns)                                                                                                                                                                                                                

┌──────────────────────────┬────────────────────────────────────────┐                                                                                                                                                                    
│          Column          │              Description               │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ exact_problem_statement  │ Customer's exact problem from the call │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ digital_friction         │ Digital channel friction analysis      │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ policy_friction          │ Policy-related friction analysis       │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ solution_by_ui           │ Solution via UI/UX changes             │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ solution_by_ops          │ Solution via operational changes       │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ solution_by_education    │ Solution via customer education        │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ solution_by_technology   │ Solution via technology fixes          │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ call_reason              │ L1 - Top-level call reason             │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ call_reason_l2           │ L2 - Secondary call reason             │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ broad_theme_l3           │ L3 - Broad theme                       │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ intermediate_theme_l4    │ L4 - Intermediate theme                │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ granular_theme_l5        │ L5 - Granular theme                    │                                                                                                                                                                    
├──────────────────────────┼────────────────────────────────────────┤                                                                                                                                                                    
│ friction_driver_category │ Category of friction driver            │                                                                                                                                                                    
└──────────────────────────┴────────────────────────────────────────┘                                                                                                                                                                    

System auto-discovers additional columns at runtime via load_dataset tool.                                                                                                                                                               

---                                                                                                                                                                                                                                      
Graph Flow                                                                                                                                                                                                                               

Phase A: Analysis Pipeline                                                                                                                                                                                                               

START → supervisor (plans + routes)                                                                                                                                                                                                      
              │                                                                                                                                                                                                                          
   ┌──────────┼────────────────┬──────────────┐                                                                                                                                                                                          
   ▼          ▼                ▼              ▼                                                                                                                                                                                          
data_analyst  business_analyst report_analyst  user_checkpoint                                                                                                                                                                           
   │          │                │                                                                                                                                                                                                         
   └──────────┴────────────────┘                                                                                                                                                                                                         
              │                                                                                                                                                                                                                          
              ▼                                                                                                                                                                                                                          
          supervisor → (if critique ON) → critique → supervisor                                                                                                                                                                          
              │                                                                                                                                                                                                                          
              ▼                                                                                                                                                                                                                          
          REPORT DELIVERED (download buttons)                                                                                                                                                                                            
              │                                                                                                                                                                                                                          
              ▼                                                                                                                                                                                                                          
          → enters Q&A mode ─┐                                                                                                                                                                                                           

Phase B: Post-Analysis Q&A Mode                                                                                                                                                                                                          

                   ┌──────────────────────┐                                                                                                                                                                                              
  user question →  │    SCOPE DETECTOR    │  ← dedicated classification node                                                                                                                                                             
                   │  with_structured_    │     ScopeDecision(in_scope: bool)                                                                                                                                                            │
                   │  output()            │                                                                                                                                                                                              
                   └────────┬─────────────┘                                                                                                                                                                                              
                            │                                                                                                                                                                                                            
              ┌─────────────┴──────────────┐                                                                                                                                                                                             
              ▼                            ▼                                                                                                                                                                                             
         IN-SCOPE                     OUT-OF-SCOPE                                                                                                                                                                                       
    (subset / drill-down)         (divergent request)                                                                                                                                                                                    
              │                            │                                                                                                                                                                                             
              ▼                            ▼                                                                                                                                                                                             
    ┌──────────────────┐          Prompt: "This requires                                                                                                                                                                                 
    │  SUPERVISOR       │          a new analysis scope.                                                                                                                                                                                 
    │  (uses existing   │          Start a new chat?"                                                                                                                                                                                    
    │  artifacts via    │          [New Chat] button                                                                                                                                                                                     
    │  DataStore:       │                                                                                                                                                                                                                
    │  - findings       │                                                                                                                                                                                                                
    │  - data_buckets   │                                                                                                                                                                                                                
    │  - report)        │                                                                                                                                                                                                                
    └──────────────────┘                                                                                                                                                                                                                 

Scope Detection Logic (part of Supervisor prompt):                                                                                                                                                                                       
- IN-SCOPE: Questions that drill into existing findings, ask for clarification, request comparisons within the analyzed data, or want different views of already-bucketed data                                                           
  - "Tell me more about the payment friction on mobile"                                                                                                                                                                                  
  - "Compare authentication issues between L3 themes"                                                                                                                                                                                    
  - "What % of digital friction is about findability?"                                                                                                                                                                                   
- OUT-OF-SCOPE: Requests that require new data, different filters not already applied, or a fundamentally different analysis focus                                                                                                       
  - "Now analyze the credit card data" (new dataset)                                                                                                                                                                                     
  - "What about international transfers?" (not in current filters)                                                                                                                                                                       
  - "Run a completely different analysis on rewards"                                                                                                                                                                                     
- Response to out-of-scope: Politely explain that this diverges from the current analysis, suggest starting a new chat to preserve the integrity of completed work, and offer a "New Chat" action button                                 

Artifacts Available for Q&A:                                                                                                                                                                                                             
- data_buckets — filtered/grouped DataFrames from Data Analyst                                                                                                                                                                           
- findings — structured findings from Business Analyst                                                                                                                                                                                   
- domain_analysis / operational_analysis — per-skill analysis results                                                                                                                                                                    
- report_markdown — the generated report                                                                                                                                                                                                 
- dataset_schema — column metadata for contextual answers                                                                                                                                                                                

Checkpoints (interrupt_before): Graph pauses at user_checkpoint node for user input. Used after:                                                                                                                                         
- Data discovery (confirm schema understanding)                                                                                                                                                                                          
- Filter/bucket results (confirm data slicing)                                                                                                                                                                                           
- Analysis findings (steer or go deeper)                                                                                                                                                                                                 

---                                                                                                                                                                                                                                      
Implementation Order                                                                                                                                                                                                                     

Phase 1: Foundation (8 files)                                                                                                                                                                                                            

1. pyproject.toml — Dependencies                                                                                                                                                                                                         
2. .env.example — Environment variables                                                                                                                                                                                                  
3. config/settings.py — Configuration constants                                                                                                                                                                                          
4. core/llm.py — VertexAI LLM factory                                                                                                                                                                                                    
5. core/agent_factory.py — AgentFactory (parse .md → create_react_agent)                                                                                                                                                                 
6. core/skill_loader.py — SkillLoader (with XML wrapping)                                                                                                                                                                                
7. core/data_store.py — DataStore (session-scoped file-backed cache)                                                                                                                                                                     
8. agents/state.py — Shared state: AnalyticsState + ExecutionTrace + ScopeSnapshot + RankedFinding + ScopeDecision                                                                                                                       

Phase 2: Agent Definitions (5 files — no separate planner)                                                                                                                                                                               

9. agents/definitions/supervisor.md — Supervisor (includes planning logic)                                                                                                                                                               
10. agents/definitions/data_analyst.md — Data Analyst definition                                                                                                                                                                         
11. agents/definitions/business_analyst.md — Business Analyst definition                                                                                                                                                                 
12. agents/definitions/report_analyst.md — Report Analyst definition                                                                                                                                                                     
13. agents/definitions/critique.md — Critique agent definition                                                                                                                                                                           

Phase 3: Skills (9 files)                                                                                                                                                                                                                

14. skills/domain/payment_transfer.md                                                                                                                                                                                                    
15. skills/domain/transaction_statement.md                                                                                                                                                                                               
16. skills/domain/authentication.md                                                                                                                                                                                                      
17. skills/domain/profile_settings.md                                                                                                                                                                                                    
18. skills/domain/fraud_dispute.md                                                                                                                                                                                                       
19. skills/domain/rewards.md                                                                                                                                                                                                             
20. skills/operational/digital.md                                                                                                                                                                                                        
21. skills/operational/operations.md                                                                                                                                                                                                     
22. skills/operational/policy.md                                                                                                                                                                                                         

Phase 4: Tools (4 files)                                                                                                                                                                                                                 

23. tools/data_tools.py — Data loading, filtering, bucketing, sampling, distribution (uses MetricsEngine internally)                                                                                                                     
24. tools/metrics.py — MetricsEngine: deterministic computations (distributions, rankings, impact/ease scores)                                                                                                                           
25. tools/report_tools.py — Report generation, PPT export trigger (fetches from DataStore)                                                                                                                                               
26. utils/pptx_export.py — Markdown → PowerPoint converter                                                                                                                                                                               

Phase 5: Graph & Nodes (2 files)                                                                                                                                                                                                         

27. agents/nodes.py — Node functions for each agent + scope_detector node (using AgentFactory + structured_output)                                                                                                                       
28. agents/graph.py — Main StateGraph: nodes, edges, conditional routing (with scope_detector branch), checkpointer                                                                                                                      

Phase 6: UI & Integration (4 files)                                                                                                                                                                                                      

29. ui/components.py — Banner, reasoning steps, waiting indicator, download buttons                                                                                                                                                      
30. ui/chat_history.py — Chat history persistence                                                                                                                                                                                        
31. .chainlit/config.toml — Chainlit configuration                                                                                                                                                                                       
32. app.py — Chainlit app: on_chat_start, on_message, streaming, file handling                                                                                                                                                           

---                                                                                                                                                                                                                                      
Verification Plan                                                                                                                                                                                                                        

1. Smoke test: AgentFactory.parse_agent_md() correctly parses all 5 agent .md files                                                                                                                                                      
2. Skill test: SkillLoader.load_skills(["payment_transfer", "digital"]) returns XML-wrapped combined content                                                                                                                             
3. DataStore test: Store/retrieve DataFrames and text; verify metadata-only in state                                                                                                                                                     
4. Metrics test: MetricsEngine.get_distribution(), compute_impact_score(), rank_findings() produce correct deterministic results                                                                                                         
5. Tool test: Each data tool works independently on a sample CSV, stores results in DataStore                                                                                                                                            
6. Agent test: Each agent node runs in isolation with mock state                                                                                                                                                                         
7. Scope Detector test: Classification node returns correct ScopeDecision(in_scope=True/False) for sample queries                                                                                                                        
8. ExecutionTrace test: Verify traces capture step_id, agent, tools_used, latency_ms, success for each step                                                                                                                              
9. Graph test: Full graph runs end-to-end with sample data:                                                                                                                                                                              
  - chainlit run app.py                                                                                                                                                                                                                  
  - Upload CSV → define focus → review filters → get analysis → toggle critique → download report                                                                                                                                        
  - Post-analysis: ask in-scope question (drill-down) → verify response uses existing artifacts                                                                                                                                          
  - Post-analysis: ask out-of-scope question → verify "New Chat" suggestion                                                                                                                                                              
10. UI test: Verify banner updates, reasoning steps render, blinking indicator shows, download buttons work                                                                                                                              
11. PPT test: Generated .pptx opens correctly with all report sections                                                                                                                                                                   
12. Memory test: Verify DataFrames are NOT in LangGraph state; only metadata refs present