# DataChat — Talk to Your Database in Plain English

DataChat is an open-source conversational AI that lets you query any PostgreSQL database using natural language. Ask questions like *"show me the top 5 customers by revenue"* or *"which products have never been ordered"* and get instant results — no SQL knowledge required.

Clone it, point it at your database, and start asking questions.

---

## How It Works

```
You type: "show me the top 5 customers by revenue"
                        ↓
          Natural Language Understanding (LLM)
                        ↓
         Generates: SELECT c.company_name, SUM(...) ...
                        ↓
              SQL Validation & Security Check
                        ↓
             Executes against your database
                        ↓
          Results displayed as a clean table
```

The system connects to your PostgreSQL database, automatically discovers all tables and columns, and uses that schema to generate accurate SQL from your questions. No manual schema configuration needed.

---

## Features

**Query any PostgreSQL database** — Point it at your database via `.env`. The schema inspector discovers tables, columns, types, primary keys, and foreign keys automatically.

**Conversational context** — Ask follow-up questions naturally. *"Show top customers"* → *"Show me their orders"* → *"Which products did they buy?"* — the system maintains context across turns.

**Self-correcting SQL** — If a generated query fails, the system automatically sends the error back to the LLM for a second attempt. Most errors are silently fixed without you ever seeing them.

**Security layers** — Only SELECT queries are allowed. A SQL validator blocks INSERT, DELETE, DROP, and injection attempts. Your database is treated as read-only — the app never writes to it.

**Conversation history** — Chat sessions are saved and titled automatically. Pick up where you left off or start fresh.

**Out-of-scope detection** — Ask *"what's the weather?"* and the system tells you it can only answer questions about your data instead of generating a meaningless query.

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL** (running locally or remotely)
- **Groq API key** — free at [console.groq.com](https://console.groq.com)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/datachat.git
cd datachat
```

### 2. Set up the backend

```bash
cd backend
pip install fastapi uvicorn psycopg2-binary groq python-dotenv
```

### 3. Configure your databases

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your database details:

```env
# The database you want to ask questions about (READ ONLY)
TARGET_DB_HOST=localhost
TARGET_DB_PORT=5432
TARGET_DB_NAME=your_database
TARGET_DB_USER=your_user
TARGET_DB_PASSWORD=your_password
TARGET_DB_SCHEMA=public

# Where chat history is stored (READ + WRITE)
STORAGE_DB_HOST=localhost
STORAGE_DB_PORT=5432
STORAGE_DB_NAME=datachat_storage
STORAGE_DB_USER=your_user
STORAGE_DB_PASSWORD=your_password
STORAGE_DB_SCHEMA=public

# LLM API key
GROQ_API_KEY=gsk_your_key_here
```

> **Note:** The target database is never modified — only SELECT queries are run against it. The storage database is where conversation history is saved. These can be the same database if you prefer, but keeping them separate is recommended.

### 4. Create the storage tables

If using a separate storage database, create it first:

```bash
createdb datachat_storage
```

Then run the migration:

```bash
psql -U your_user -d datachat_storage -f migrations/setup.sql
```

If using the same database for both target and storage, just run the migration against it:

```bash
psql -U your_user -d your_database -f migrations/setup.sql
```

### 5. Start the backend

```bash
cd backend
uvicorn main:app --reload
```

You should see:

```
✅ Storage DB: datachat_storage @ localhost
✅ Target DB: your_database @ localhost
🔍 Inspecting database schema: your_database...
   ⏭️  Skipping internal table: conversations
   ⏭️  Skipping internal table: messages
✅ Schema discovered: 12 tables, 67 columns
✅ System prompt built: 1842 chars, 12 tables
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

### 7. Open the app

Go to [http://localhost:3000](http://localhost:3000) and start asking questions about your data.

---

## Project Structure

```
datachat/
├── backend/
│   ├── main.py                    # FastAPI app, API endpoints, request handling
│   ├── llm_service.py             # LLM integration, prompt building, SQL generation
│   ├── schema_inspector.py        # Auto-discovers database schema from PostgreSQL
│   ├── validator.py               # SQL validation, security checks, table whitelisting
│   ├── db_manager.py              # Database config loading from .env
│   ├── models.py                  # Data models (ConversationState, MessageRecord)
│   ├── session_store.py           # Abstract storage interface
│   ├── postgres_session_store.py  # PostgreSQL implementation of session storage
│   ├── nlu.py                     # Basic NLU parser (legacy, not used in LLM flow)
│   └── .env.example               # Template for database configuration
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Main chat UI
│   │   └── api/[...slug]/
│   │       └── route.ts           # Proxy: forwards frontend requests to backend
│   └── ...
│
└── migrations/
    └── setup.sql                  # Creates conversations & messages tables
```

---

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────┐
│                  │     │            BACKEND (FastAPI)          │
│   FRONTEND       │     │                                      │
│   (Next.js)      │────▶│  main.py ──▶ llm_service.py ──▶ Groq │
│                  │     │     │              │                  │
│   page.tsx       │◀────│     │         schema_inspector.py     │
│   route.ts       │     │     │              │                  │
│                  │     │     ▼              ▼                  │
└──────────────────┘     │  validator.py    (schema)             │
                         │     │                                 │
                         └─────┼─────────────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼                     ▼
          ┌─────────────────┐   ┌─────────────────┐
          │  TARGET DB      │   │  STORAGE DB      │
          │  (read-only)    │   │  (read + write)  │
          │                 │   │                   │
          │  Your tables    │   │  conversations    │
          │  Your data      │   │  messages         │
          └─────────────────┘   └─────────────────┘
```

### Request lifecycle

1. User types a question in the browser
2. Frontend sends `POST /api/chat` with the question and conversation ID
3. `route.ts` proxies the request to `http://localhost:8000/chat`
4. Backend loads conversation history from the storage database
5. `llm_service.py` builds the prompt: system prompt (with schema) + conversation history + user question
6. Groq API generates a SQL query as JSON
7. `validator.py` checks the SQL for security (only SELECT, no forbidden patterns, table whitelist)
8. SQL executes against the target database
9. If it fails, `fix_sql_with_error()` sends the error back to the LLM for self-correction
10. Results are returned to the frontend and rendered as a table

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TARGET_DB_HOST` | Yes | Host of the database to query |
| `TARGET_DB_PORT` | Yes | Port (default: 5432) |
| `TARGET_DB_NAME` | Yes | Database name |
| `TARGET_DB_USER` | Yes | Database username |
| `TARGET_DB_PASSWORD` | Yes | Database password |
| `TARGET_DB_SCHEMA` | No | Schema to inspect (default: `public`) |
| `STORAGE_DB_HOST` | Yes | Host for chat history storage |
| `STORAGE_DB_PORT` | Yes | Port (default: 5432) |
| `STORAGE_DB_NAME` | Yes | Storage database name |
| `STORAGE_DB_USER` | Yes | Storage database username |
| `STORAGE_DB_PASSWORD` | Yes | Storage database password |
| `STORAGE_DB_SCHEMA` | No | Storage schema (default: `public`) |
| `GROQ_API_KEY` | Yes | API key from [console.groq.com](https://console.groq.com) |

### Schema Inspector

The schema inspector automatically excludes these internal tables from discovery:
- `conversations`
- `messages`
- `databases`

If your database has tables with these names that you want to query, you can customize the exclusion list in `schema_inspector.py`:

```python
schema_inspector = SchemaInspector(db_config, exclude_tables={"my_internal_table"})
```

Pass an empty set to include everything:

```python
schema_inspector = SchemaInspector(db_config, exclude_tables=set())
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server status, connected database, discovered tables |
| `GET` | `/schema` | Full discovered schema as JSON |
| `POST` | `/schema/refresh` | Re-inspect database schema without restarting |
| `POST` | `/conversations` | Create a new conversation |
| `GET` | `/conversations` | List all conversations |
| `GET` | `/conversations/:id` | Get a conversation with full message history |
| `DELETE` | `/conversations/:id` | Delete a conversation |
| `POST` | `/chat` | Send a message and get a response |

---

## Security

DataChat is designed to be safe to point at production databases:

- **Read-only queries** — Only `SELECT` statements are generated and executed. The SQL validator blocks `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, and other write operations.
- **Pattern blocking** — SQL injection patterns like `--`, `/*`, and multi-statement queries (`;`) are detected and blocked.
- **Table whitelisting** — Only tables discovered during schema inspection are allowed. The LLM cannot reference tables outside the discovered schema.
- **No writes to target DB** — The target database connection is only used for `SELECT` queries. All writes (conversation history) go to the separate storage database.
- **Dangerous word pre-check** — Messages containing words like "delete", "drop", or "truncate" are rejected before reaching the LLM.

**Recommendation:** For production databases, create a read-only PostgreSQL user:

```sql
CREATE USER datachat_reader WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE your_database TO datachat_reader;
GRANT USAGE ON SCHEMA public TO datachat_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datachat_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO datachat_reader;
```

Then use `datachat_reader` as your `TARGET_DB_USER`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Backend | Python, FastAPI |
| LLM | Groq API (Llama 3.3 70B) |
| Database | PostgreSQL |
| SQL Validation | Custom regex-based validator |
| Schema Discovery | PostgreSQL `information_schema` |

---

## Limitations

- **PostgreSQL only** — Schema inspection uses PostgreSQL-specific `information_schema` queries. MySQL, SQLite, and other databases are not currently supported.
- **SELECT only** — The system cannot create, modify, or delete data. It's a read-only query tool.
- **No visualization** — Results are displayed as tables only. Charts and graphs are not currently supported.
- **LLM latency** — Complex queries may take 5-10 seconds due to LLM processing time on the free Groq tier.
- **Large schemas** — Databases with 50+ tables may exceed the LLM's context window. The system works best with databases under 30 tables.
- **No authentication** — The app has no user login system. Anyone with access to the URL can query the connected database.

---

## License

MIT