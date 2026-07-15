
# ================================= Langching ============================================ #

# =========================== ConversationBufferMemory =================================== #

       Execute cd /home/kwatk/projects/bella_memory
           && source .venv/bin/activate
           && python -c "from bella_memory import ConversationBufferMemory, ConversationSummaryMemory, ConversationEntityMemory, Conversat...



       Execute cd /home/kwatk/projects/bella_memory
           && source .venv/bin/activate
           && pytest tests/ -v


       bash
           cd /home/kwatk/projects/bella_memory
           source .venv/bin/activate
           bella-memory-cli --session charles --config examples/config_example.json chat
  
  
  
       What is included:
   •  LangChain-style core abstractions: BaseMemory, BaseChatMessageHistory, and message types (HumanMessage, AIMessage, SystemMessage, etc.)
   •  All major memory classes: ConversationBufferMemory, ConversationBufferWindowMemory, ConversationSummaryMemory,   ConversationEntityMemory,   ConversationKGMemory, VectorStoreRetrieverMemory, CombinedMemory
   •  History backends: in-memory, JSON file, SQLite, and Redis adapter
   •  Pure local InMemoryVectorStore with fixed-dimension fallback embeddings (no paid DB required)
   •  OllamaLLM wrapper that defaults to your remote endpoint 100.58.95.110:11434 but works with any Ollama/OpenAI-compatible endpoint
   •  MemoryManager for session lifecycle, auto-checkpoints, manual facts, and config-driven setup
   •  CLI (bella-memory-cli), FastAPI service (bella_memory.api), examples, and pytest suite



{  "shellProps": {
"sessionId": "4714f4bae94746c4a16a38538a6b808f", 
"extName": "HubsExtension",    "contentName": "ResourceMenuBlade",
"resourceId": "/subscriptions/2fbaa9f6-0a68-46d1-8186-999984a3f724/resourceGroups/revupwithus/providers/Microsoft.DocumentDB/mongoClusters/docdb-cluster-20260704-2316" 
},  "error": {    "message": "Resource not found",    "code": 404,    "details": { 
"htmlTemplate": 
"The resource was not found, it may have been deleted. If this was launched from a pinned tile on the dashboard, it should be removed.
MONGODB
<br /><br />Resource ID: /subscriptions/2fbaa9f6-0a68-46d1-8186-999984a3f724/resourceGroups/revupwithus/providers/Microsoft.DocumentDB/mongoClusters/docdb-cluster-20260704-2316<br /><br />Status Code: 404<br /><br />Status Message: 
The Resource &#39;Microsoft.DocumentDB/mongoClusters/docdb-cluster-20260704-2316&#39; under resource group &#39;revupwithus&#39; was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix"    }  }}



