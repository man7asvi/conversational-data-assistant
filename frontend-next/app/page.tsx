'use client'

import { useState, useRef, useEffect, useCallback } from 'react'

type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  type: 'text' | 'table' | 'error' | 'empty'
  data?: any[]
  sql?: string
  params?: any[]
}

type Conversation = {
  conversation_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  database_name?: string
}

// ─── Data Table ──────────────────────────────────────────────────────────────

function DataTable({ data, sql }: { data: any[]; sql?: string }) {
  const [showSql, setShowSql] = useState(false)

  if (!data || data.length === 0)
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
        <div className="assistant-bubble" style={{ color: 'var(--text3)', fontStyle: 'italic' }}>
          No results found for that query.
        </div>
      </div>
    )

  const columns = Object.keys(data[0])

  return (
    <div className="table-wrapper">
      <div className="table-meta">
        <span className="row-count">{data.length} row{data.length !== 1 ? 's' : ''}</span>
        {sql && (
          <button className="sql-toggle" onClick={() => setShowSql(v => !v)}>
            {showSql ? 'Hide SQL' : 'View SQL'}
          </button>
        )}
      </div>
      {showSql && sql && (
        <pre className="sql-block">{sql}</pre>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col}>{col.replace(/_/g, ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i}>
                {columns.map(col => (
                  <td key={col}>
                    {typeof row[col] === 'boolean'
                      ? row[col] ? '✓' : '✗'
                      : (row[col] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Empty Result ─────────────────────────────────────────────────────────────

function EmptyResult({ message, sql }: { message: string; sql?: string }) {
  const [showSql, setShowSql] = useState(false)
  return (
    <div className="empty-result-wrapper">
      <div className="empty-result-icon">∅</div>
      <div className="empty-result-body">
        <p className="empty-result-msg">{message}</p>
        {sql && (
          <>
            <button className="sql-toggle" onClick={() => setShowSql(v => !v)}>
              {showSql ? 'Hide SQL' : 'View SQL that ran'}
            </button>
            {showSql && <pre className="sql-block" style={{ marginTop: 8 }}>{sql}</pre>}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Typing indicator ────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="typing-indicator">
        <span /><span /><span />
      </div>
    </div>
  )
}

// ─── Sidebar conversation item ───────────────────────────────────────────────

function ConvItem({
  conv,
  active,
  onClick,
  onDelete,
}: {
  conv: Conversation
  active: boolean
  onClick: () => void
  onDelete: (e: React.MouseEvent) => void
}) {
  return (
    <div className={`conv-item ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="conv-item-body">
        <p className="conv-title">{conv.title}</p>
        <p className="conv-meta">
          {conv.message_count ?? 0} msg{conv.message_count !== 1 ? 's' : ''}
          {conv.database_name ? ` · ${conv.database_name}` : ''}
        </p>
      </div>
      <button
        className="conv-delete"
        onClick={onDelete}
        title="Delete conversation"
      >
        ✕
      </button>
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  'show top 5 customers by revenue',
  'which products are low in stock',
  'revenue by country',
  'top employees by orders handled',
]

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState('')
  const [conversationLoading, setConversationLoading] = useState(true)
  const [error, setError] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [convsLoading, setConvsLoading] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [dbName, setDbName] = useState('Database')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // If user types and hits Send before the conversation ID is ready,
  // we store the message here and fire it once init completes.
  const pendingMessageRef = useRef<string | null>(null)

  useEffect(() => {
    initializeConversation()
    loadConversations()
    // Fetch database name from backend
    fetch('/api/health')
      .then(r => r.json())
      .then(data => {
        if (data.allowed_tables) {
          // Use the database name from the health endpoint
          const name = data.database_name || 'Database'
          setDbName(name.charAt(0).toUpperCase() + name.slice(1))
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // ── API helpers ─────────────────────────────────────────────────────────────

  const initializeConversation = async (title = 'New Chat') => {
    setConversationLoading(true)
    setMessages([])
    setError('')
    try {
      const res = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`)
      const newId = data.conversation_id
      setConversationId(newId)

      // If the user already typed and hit Send before this resolved,
      // fire that message now that we have a valid conversation ID.
      if (pendingMessageRef.current) {
        const pending = pendingMessageRef.current
        pendingMessageRef.current = null
        // Small timeout so React state (conversationId) has settled
        setTimeout(() => sendMessageWithId(pending, newId), 50)
      }
    } catch (err) {
      setError(`Could not start conversation: ${err instanceof Error ? err.message : err}`)
    } finally {
      setConversationLoading(false)
    }
  }

  const loadConversations = async () => {
    setConvsLoading(true)
    try {
      const res = await fetch('/api/conversations')
      const data = await res.json()
      setConversations(Array.isArray(data) ? data : data.conversations || [])
    } catch {
      // silent
    } finally {
      setConvsLoading(false)
    }
  }

  const loadConversationMessages = async (convId: string) => {
    setConversationId(convId)
    setMessages([])
    setError('')
    try {
      const res = await fetch(`/api/conversations/${convId}`)
      const data = await res.json()
      if (!data.messages || !Array.isArray(data.messages)) return

      const loaded: Message[] = data.messages.map((msg: any, idx: number) => {
        const isErrMsg = (s: string) =>
          s.startsWith('Something went wrong') ||
          s.startsWith('Query blocked') ||
          s === 'This operation is not allowed.' ||
          s === 'Could not generate SQL.' ||
          s.toLowerCase().includes('must appear in the group by') ||
          s.toLowerCase().includes('syntax error')

        if (msg.role === 'assistant' && msg.sql_generated) {
          try {
            const parsed = JSON.parse(msg.content)
            return {
              id: idx.toString(),
              role: 'assistant',
              content: '',
              type: 'table',
              data: parsed,
              sql: msg.sql_generated,
              params: msg.params_used,
            }
          } catch {
            // fall through to text
          }
        }
        return {
          id: idx.toString(),
          role: msg.role,
          content: msg.content,
          type: (msg.role === 'assistant' && isErrMsg(msg.content)) ? 'error' : 'text',
        }
      })
      setMessages(loaded)
    } catch (err) {
      setError('Failed to load conversation')
    }
  }

  const deleteConversation = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation()
    try {
      await fetch(`/api/conversations/${convId}`, { method: 'DELETE' })
      setConversations(prev => prev.filter(c => c.conversation_id !== convId))
      if (convId === conversationId) {
        await initializeConversation()
      }
    } catch {
      // silent
    }
  }

  // ── Send message ────────────────────────────────────────────────────────────
  //
  // Split into two functions:
  //   sendMessageWithId  — does the actual work, requires a known convId
  //   sendMessage        — public entry point; queues the message if convId
  //                        isn't ready yet (race condition fix)

  const sendMessageWithId = async (messageText: string, convId: string) => {
    if (!messageText || loading) return

    setInput('')
    setLoading(true)
    setError('')

    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      type: 'text',
    }])

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: convId, text: messageText }),
      })
      if (!res.ok) throw new Error(`API error: ${res.statusText}`)
      const data = await res.json()

      const isError = data.type === 'error' || (typeof data.reply === 'string' && (
        data.reply.startsWith('Something went wrong') ||
        data.reply.startsWith('Query blocked') ||
        data.reply === 'This operation is not allowed.' ||
        data.reply === 'Could not generate SQL.' ||
        data.reply.toLowerCase().includes('error') ||
        data.reply.toLowerCase().includes('column') ||
        data.reply.toLowerCase().includes('syntax')
      ))

      const isEmpty = data.type === 'empty'

      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: (data.type === 'table') ? '' : data.reply,
        type: isError ? 'error' : isEmpty ? 'empty' : data.type,
        data: data.type === 'table' ? data.reply : undefined,
        sql: data.sql,
        params: data.params,
      }])

      // If the backend generated a title for this conversation (first message),
      // update the sidebar immediately without waiting for loadConversations()
      if (data.title) {
        setConversations(prev => prev.map(c =>
          c.conversation_id === conversationId
            ? { ...c, title: data.title, message_count: (c.message_count || 0) + 2 }
            : c
        ))
      }

      loadConversations()
    } catch (err) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: err instanceof Error ? err.message : 'Something went wrong',
        type: 'error',
      }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
      inputRef.current?.focus()
    }
  }

  const sendMessage = useCallback((text?: string) => {
    const messageText = (text ?? input).trim()
    if (!messageText || loading) return

    if (!conversationId) {
      // Conversation is still being created — queue the message.
      // initializeConversation() will pick it up once the ID arrives.
      pendingMessageRef.current = messageText
      setInput('')
      // Show the user message optimistically so it doesn't feel lost
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: 'user',
        content: messageText,
        type: 'text',
      }])
      setLoading(true)
      return
    }

    sendMessageWithId(messageText, conversationId)
  }, [input, loading, conversationId])

  // ── Render ──────────────────────────────────────────────────────────────────

  const activeConv = conversations.find(c => c.conversation_id === conversationId)

  return (
    <>
      <style>{`
        /* ── Reset & base ─────────────────────────────────────────── */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
          --bg:        #0d0f14;
          --bg2:       #13161d;
          --bg3:       #1a1e28;
          --border:    #252b3b;
          --border2:   #2e3548;
          --text:      #e2e8f0;
          --text2:     #8892a4;
          --text3:     #4a5568;
          --accent:    #3b82f6;
          --accent2:   #60a5fa;
          --green:     #10b981;
          --red:       #ef4444;
          --yellow:    #f59e0b;
          --user-bg:   #1e3a5f;
          --user-text: #bfdbfe;
          --radius:    10px;
          --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
          --font-ui:   'DM Sans', 'Outfit', system-ui, sans-serif;
        }

        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');

        body {
          background: var(--bg);
          color: var(--text);
          font-family: var(--font-ui);
          font-size: 14px;
          line-height: 1.6;
          overflow: hidden;
          height: 100vh;
        }

        /* ── Layout ───────────────────────────────────────────────── */
        .app {
          display: flex;
          height: 100vh;
          width: 100vw;
          overflow: hidden;
        }

        /* ── Sidebar ──────────────────────────────────────────────── */
        .sidebar {
          width: 260px;
          min-width: 260px;
          background: var(--bg2);
          border-right: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          transition: width 0.2s ease, min-width 0.2s ease;
          overflow: hidden;
        }
        .sidebar.collapsed {
          width: 0;
          min-width: 0;
          border-right: none;
        }

        .sidebar-header {
          padding: 20px 16px 14px;
          border-bottom: 1px solid var(--border);
          flex-shrink: 0;
        }

        .sidebar-logo {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 14px;
        }
        .sidebar-logo .logo-icon {
          width: 28px;
          height: 28px;
          background: linear-gradient(135deg, var(--accent), #7c3aed);
          border-radius: 7px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
          flex-shrink: 0;
        }
        .sidebar-logo span {
          font-weight: 600;
          font-size: 14px;
          color: var(--text);
          white-space: nowrap;
        }

        .new-chat-btn {
          width: 100%;
          padding: 9px 12px;
          background: var(--accent);
          color: #fff;
          border: none;
          border-radius: var(--radius);
          font-family: var(--font-ui);
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          transition: background 0.15s, opacity 0.15s;
          white-space: nowrap;
        }
        .new-chat-btn:hover { background: #2563eb; }
        .new-chat-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .db-section {
          padding: 10px 16px;
          border-bottom: 1px solid var(--border);
          flex-shrink: 0;
        }
        .db-label {
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--text3);
          margin-bottom: 6px;
        }
        .db-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          background: var(--bg3);
          border: 1px solid var(--border2);
          border-radius: 7px;
          font-size: 12px;
          color: var(--text2);
        }
        .db-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--green);
          flex-shrink: 0;
        }

        .conv-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
          scrollbar-width: thin;
          scrollbar-color: var(--border) transparent;
        }
        .conv-list-label {
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--text3);
          padding: 4px 8px 8px;
        }

        .conv-item {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 10px;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.12s;
          margin-bottom: 2px;
        }
        .conv-item:hover { background: var(--bg3); }
        .conv-item.active { background: rgba(59,130,246,0.15); }

        .conv-item-body { flex: 1; min-width: 0; }
        .conv-title {
          font-size: 13px;
          font-weight: 500;
          color: var(--text);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .conv-item.active .conv-title { color: var(--accent2); }
        .conv-meta {
          font-size: 11px;
          color: var(--text3);
          margin-top: 1px;
        }

        .conv-delete {
          width: 22px;
          height: 22px;
          border: none;
          background: transparent;
          color: var(--text3);
          cursor: pointer;
          border-radius: 4px;
          font-size: 11px;
          display: flex;
          align-items: center;
          justify-content: center;
          opacity: 0;
          transition: opacity 0.1s, background 0.1s, color 0.1s;
          flex-shrink: 0;
        }
        .conv-item:hover .conv-delete { opacity: 1; }
        .conv-delete:hover { background: rgba(239,68,68,0.15); color: var(--red); }

        .empty-convs {
          text-align: center;
          color: var(--text3);
          font-size: 12px;
          padding: 24px 8px;
        }

        /* ── Main area ────────────────────────────────────────────── */
        .main {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: var(--bg);
        }

        /* ── Topbar ───────────────────────────────────────────────── */
        .topbar {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 14px 20px;
          border-bottom: 1px solid var(--border);
          flex-shrink: 0;
        }

        .sidebar-toggle {
          width: 32px;
          height: 32px;
          border: 1px solid var(--border2);
          background: var(--bg2);
          border-radius: 8px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text2);
          font-size: 14px;
          transition: background 0.12s, color 0.12s;
          flex-shrink: 0;
        }
        .sidebar-toggle:hover { background: var(--bg3); color: var(--text); }

        .topbar-title {
          font-size: 15px;
          font-weight: 600;
          color: var(--text);
          flex: 1;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .topbar-sub {
          font-size: 12px;
          color: var(--text3);
        }

        .status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--green);
          animation: pulse 2s infinite;
          flex-shrink: 0;
        }
        .status-dot.error { background: var(--red); animation: none; }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }

        /* ── Messages ─────────────────────────────────────────────── */
        .messages {
          flex: 1;
          overflow-y: auto;
          padding: 24px 20px;
          display: flex;
          flex-direction: column;
          gap: 16px;
          scrollbar-width: thin;
          scrollbar-color: var(--border) transparent;
        }

        /* Empty state */
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          gap: 20px;
          text-align: center;
          color: var(--text2);
        }
        .empty-state .hero-icon {
          width: 56px;
          height: 56px;
          background: linear-gradient(135deg, rgba(59,130,246,0.2), rgba(124,58,237,0.2));
          border: 1px solid rgba(59,130,246,0.3);
          border-radius: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 24px;
        }
        .empty-state h2 {
          font-size: 18px;
          font-weight: 600;
          color: var(--text);
        }
        .empty-state p {
          font-size: 13px;
          color: var(--text2);
          max-width: 300px;
        }
        .suggestions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: center;
          max-width: 500px;
        }
        .suggestion-btn {
          padding: 7px 14px;
          background: var(--bg2);
          border: 1px solid var(--border2);
          color: var(--text2);
          border-radius: 20px;
          font-family: var(--font-ui);
          font-size: 12px;
          cursor: pointer;
          transition: all 0.15s;
        }
        .suggestion-btn:hover {
          background: rgba(59,130,246,0.1);
          border-color: rgba(59,130,246,0.4);
          color: var(--accent2);
        }
        .suggestion-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        /* Message bubbles */
        .user-bubble {
          align-self: flex-end;
          background: var(--user-bg);
          color: var(--user-text);
          padding: 10px 16px;
          border-radius: 18px 18px 4px 18px;
          max-width: 70%;
          font-size: 14px;
          line-height: 1.5;
          word-break: break-word;
        }

        .assistant-bubble {
          align-self: flex-start;
          background: var(--bg2);
          border: 1px solid var(--border);
          color: var(--text);
          padding: 10px 16px;
          border-radius: 4px 18px 18px 18px;
          max-width: 70%;
          font-size: 14px;
          line-height: 1.5;
          word-break: break-word;
        }
        .assistant-bubble.error {
          background: rgba(239,68,68,0.08);
          border-color: rgba(239,68,68,0.25);
          color: #fca5a5;
          word-break: break-word;
          white-space: pre-wrap;
          font-family: var(--font-mono);
          font-size: 12px;
          max-width: 85%;
        }
        .assistant-bubble .icon { margin-right: 6px; }
        .assistant-bubble.empty-result { color: var(--text3); font-style: italic; }

        /* Typing indicator */
        .typing-indicator {
          display: flex;
          gap: 5px;
          align-items: center;
          background: var(--bg2);
          border: 1px solid var(--border);
          padding: 12px 16px;
          border-radius: 4px 18px 18px 18px;
          width: fit-content;
        }
        .typing-indicator span {
          width: 7px;
          height: 7px;
          background: var(--text3);
          border-radius: 50%;
          animation: blink 1.4s infinite;
        }
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes blink {
          0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
          40%            { opacity: 1;   transform: scale(1); }
        }

        /* Table */
        .table-wrapper {
          width: 100%;
          background: var(--bg2);
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
        }
        .table-meta {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          border-bottom: 1px solid var(--border);
          background: var(--bg3);
        }
        .row-count {
          font-size: 11px;
          color: var(--text3);
          font-weight: 500;
        }
        .sql-toggle {
          font-size: 11px;
          color: var(--accent2);
          background: none;
          border: none;
          cursor: pointer;
          font-family: var(--font-ui);
          padding: 2px 6px;
          border-radius: 4px;
          transition: background 0.12s;
        }
        .sql-toggle:hover { background: rgba(59,130,246,0.1); }
        .sql-block {
          padding: 10px 14px;
          background: #0a0c11;
          font-family: var(--font-mono);
          font-size: 12px;
          color: #7dd3fc;
          border-bottom: 1px solid var(--border);
          white-space: pre-wrap;
          word-break: break-all;
        }
        .table-scroll {
          overflow-x: auto;
          max-height: 400px;
          overflow-y: auto;
          scrollbar-width: thin;
          scrollbar-color: var(--border) transparent;
        }
        table { width: 100%; border-collapse: collapse; }
        thead { position: sticky; top: 0; z-index: 1; background: var(--bg3); }
        th {
          padding: 9px 14px;
          text-align: left;
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: var(--text3);
          white-space: nowrap;
          border-bottom: 1px solid var(--border);
        }
        td {
          padding: 9px 14px;
          font-size: 13px;
          color: var(--text);
          border-bottom: 1px solid var(--border);
          white-space: nowrap;
        }
        tbody tr:last-child td { border-bottom: none; }
        tbody tr:hover td { background: rgba(255,255,255,0.02); }

        /* Empty result */
        .empty-result-wrapper {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          background: var(--bg2);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 12px 16px;
          max-width: 500px;
        }
        .empty-result-icon {
          font-size: 18px;
          color: var(--text3);
          flex-shrink: 0;
          margin-top: 1px;
        }
        .empty-result-body { flex: 1; }
        .empty-result-msg {
          font-size: 13px;
          color: var(--text2);
          margin-bottom: 6px;
        }

        /* Error banner */
        .error-banner {
          margin: 0 20px;
          padding: 10px 14px;
          background: rgba(239,68,68,0.08);
          border: 1px solid rgba(239,68,68,0.25);
          border-radius: 8px;
          color: #fca5a5;
          font-size: 13px;
          flex-shrink: 0;
        }

        /* ── Input bar ────────────────────────────────────────────── */
        .input-bar {
          padding: 14px 20px;
          border-top: 1px solid var(--border);
          display: flex;
          gap: 10px;
          align-items: center;
          flex-shrink: 0;
          background: var(--bg);
        }
        .chat-input {
          flex: 1;
          background: var(--bg2);
          border: 1px solid var(--border2);
          color: var(--text);
          font-family: var(--font-ui);
          font-size: 14px;
          padding: 10px 16px;
          border-radius: 10px;
          outline: none;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .chat-input::placeholder { color: var(--text3); }
        .chat-input:focus {
          border-color: rgba(59,130,246,0.5);
          box-shadow: 0 0 0 3px rgba(59,130,246,0.08);
        }
        .send-btn {
          padding: 10px 18px;
          background: var(--accent);
          color: #fff;
          border: none;
          border-radius: 10px;
          font-family: var(--font-ui);
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.15s, opacity 0.15s;
          white-space: nowrap;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .send-btn:hover:not(:disabled) { background: #2563eb; }
        .send-btn:disabled { opacity: 0.45; cursor: not-allowed; }
      `}</style>

      <div className="app">
        {/* ── Sidebar ── */}
        <div className={`sidebar${sidebarOpen ? '' : ' collapsed'}`}>
          <div className="sidebar-header">
            <div className="sidebar-logo">
              <div className="logo-icon">⚡</div>
              <span>DataChat</span>
            </div>
            <button
              className="new-chat-btn"
              onClick={() => initializeConversation()}
              disabled={conversationLoading}
            >
              <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
              New Conversation
            </button>
          </div>

          <div className="db-section">
            <div className="db-label">Database</div>
            <div className="db-badge">
              <span className="db-dot" />
              {dbName.toLowerCase()}
            </div>
          </div>

          <div className="conv-list">
            <div className="conv-list-label">History</div>
            {convsLoading ? (
              <div className="empty-convs">Loading…</div>
            ) : conversations.length === 0 ? (
              <div className="empty-convs">No conversations yet</div>
            ) : (
              conversations
                .filter(conv => conv.message_count > 0 || conv.conversation_id === conversationId)
                .map(conv => (
                <ConvItem
                  key={conv.conversation_id}
                  conv={conv}
                  active={conv.conversation_id === conversationId}
                  onClick={() => loadConversationMessages(conv.conversation_id)}
                  onDelete={(e) => deleteConversation(e, conv.conversation_id)}
                />
              ))
            )}
          </div>
        </div>

        {/* ── Main ── */}
        <div className="main">
          {/* Topbar */}
          <div className="topbar">
            <button
              className="sidebar-toggle"
              onClick={() => setSidebarOpen(v => !v)}
              title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
            >
              {sidebarOpen ? '◀' : '▶'}
            </button>
            <div
              className={`status-dot${error ? ' error' : ''}`}
              title={error ? 'Error' : 'Connected'}
            />
            <div className="topbar-title">
              {activeConv?.title ?? (conversationLoading ? 'Initializing…' : 'Conversational Data Assistant')}
            </div>
            <span className="topbar-sub">{dbName} DB</span>
          </div>

          {/* Error banner */}
          {error && <div className="error-banner">⚠ {error}</div>}

          {/* Messages */}
          <div className="messages">
            {messages.length === 0 && !loading ? (
              <div className="empty-state">
                <div className="hero-icon">🔍</div>
                <h2>Ask about your data</h2>
                <p>Query your database in plain English. Try one of these:</p>
                <div className="suggestions">
                  {SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      className="suggestion-btn"
                      onClick={() => sendMessage(s)}
                      disabled={loading}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map(msg => (
                <div
                  key={msg.id}
                  style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}
                >
                  {msg.type === 'table' ? (
                    <div style={{ width: '100%' }}>
                      <DataTable data={msg.data ?? []} sql={msg.sql} />
                    </div>
                  ) : msg.type === 'empty' ? (
                    <EmptyResult message={msg.content} sql={msg.sql} />
                  ) : msg.role === 'user' ? (
                    <div className="user-bubble">{msg.content}</div>
                  ) : (
                    <div className={`assistant-bubble${msg.type === 'error' ? ' error' : ''}`}>
                      {msg.type === 'error' && <span className="icon">⚠</span>}
                      {msg.content}
                    </div>
                  )}
                </div>
              ))
            )}

            {loading && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="input-bar">
            <input
              ref={inputRef}
              className="chat-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder="Ask about your data…"
              disabled={false}
            />
            <button
              className="send-btn"
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
            >
              Send ↵
            </button>
          </div>
        </div>
      </div>
    </>
  )
}