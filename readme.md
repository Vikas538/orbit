## How it works

1. Jira ticket created in structured format
2. Webhook triggers FastAPI host
3. Docker container spawned with AI coding agent
4. Agent executes ticket within defined scope
5. Permission gate blocks dangerous operations for human approval
6. Git branch pushed on completion
7. Session evaluated automatically — diff scored against acceptance criteria
8. Context compressed and stored in ChromaDB for future sessions