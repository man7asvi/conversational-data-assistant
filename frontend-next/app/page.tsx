'use client'

import { useState, useRef, useEffect } from 'react'

type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  type: 'text' | 'table' | 'preview'
  data?: any[]
  sql?: string
  params?: any[]
}

function DataTable({ data }: { data: any[] }) {
  if (!data || data.length === 0) return <p className="text-sm text-muted-foreground">No results found</p>
  const columns = Object.keys(data[0])
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            {columns.map(col => (
              <th key={col} className="px-4 py-2 text-left text-muted-foreground font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} className="border-b hover:bg-muted/30 transition-colors">
              {columns.map(col => (
                <td key={col} className="px-4 py-2">
                  {typeof row[col] === 'boolean' ? String(row[col]) : (row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SqlPreview({ sql, params, onExecute, onCancel }: {
  sql: string
  params: any[]
  onExecute: () => void
  onCancel: () => void
}) {
  return (
    <div className="rounded-lg border p-4 flex flex-col gap-3 bg-card">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Generated SQL</p>
      <pre className="bg-muted rounded-lg p-3 text-sm text-green-400 overflow-x-auto whitespace-pre-wrap font-mono">
        {sql}
      </pre>
      {params && params.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Parameters: <span className="text-foreground">{params.join(', ')}</span>
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={onExecute}
          className="px-4 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm rounded-lg transition-colors"
        >
          Execute
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-1.5 bg-secondary hover:bg-secondary/80 text-secondary-foreground text-sm rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string>('')
  const [conversationLoading, setConversationLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Initialize conversation on mount
  useEffect(() => {
    initializeConversation()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const initializeConversation = async () => {
    try {
      console.log('Initializing conversation (skipping health check)...')
      
      console.log('Creating conversation...')
      const response = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' }),
      })
      
      console.log('Response status:', response.status)
      const data = await response.json()
      console.log('Response data:', data)
      
      if (!response.ok) {
        throw new Error(data.detail || data.error || `HTTP ${response.status}`)
      }
      
      if (!data.conversation_id) {
        throw new Error('No conversation_id in response')
      }
      
      setConversationId(data.conversation_id)
      setError('')
      console.log('✅ Conversation initialized:', data.conversation_id)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      console.error('Failed to initialize:', errorMsg, err)
      setError(`Failed to initialize chat: ${errorMsg}`)
    } finally {
      setConversationLoading(false)
    }
  }

  const handleExecute = async (sql: string, params: any[], msgIndex: number) => {
    const response = await fetch('/api/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, params }),
    })
    const data = await response.json()

    setMessages(prev => prev.map((msg, i) =>
      i === msgIndex
        ? { ...msg, type: 'table', data: data.reply }
        : msg
    ))
  }

  const handleCancel = (msgIndex: number) => {
    setMessages(prev => prev.map((msg, i) =>
      i === msgIndex
        ? { ...msg, type: 'text', content: 'Query cancelled.' }
        : msg
    ))
  }

  const handleSuggestionClick = async (suggestion: string) => {
    if (!conversationId || loading) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: suggestion,
      type: 'text'
    }

    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          text: suggestion,
        }),
      })

      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`)
      }

      const data = await response.json()
      setLoading(false)

      if (data.type === 'preview') {
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: '',
          type: 'preview',
          sql: data.sql,
          params: data.params
        }])
      } else {
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: data.type === 'table' ? '' : data.reply,
          type: data.type,
          data: data.type === 'table' ? data.reply : undefined
        }])
      }
    } catch (err) {
      setLoading(false)
      const errorMsg = err instanceof Error ? err.message : 'Unknown error'
      setError(errorMsg)
      console.error('Error:', err)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || loading || !conversationId) return

    const messageText = input // Save input before clearing
    
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      type: 'text'
    }

    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          text: messageText,
        }),
      })

      if (!response.ok) {
        throw new Error(`API error: ${response.statusText}`)
      }

      const data = await response.json()
      setLoading(false)

      if (data.type === 'preview') {
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: '',
          type: 'preview',
          sql: data.sql,
          params: data.params
        }])
      } else {
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: data.type === 'table' ? '' : data.reply,
          type: data.type,
          data: data.type === 'table' ? data.reply : undefined
        }])
      }
    } catch (err) {
      setLoading(false)
      const errorMsg = err instanceof Error ? err.message : 'Something went wrong'
      setError(errorMsg)
      console.error('Chat error:', err)
    }
  }

  return (
    <main className="min-h-screen bg-background text-foreground flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-3xl flex flex-col gap-4">

        {/* Header */}
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full animate-pulse ${error ? 'bg-red-500' : 'bg-green-500'}`} />
          <h1 className="text-xl font-semibold">Conversational Data Assistant</h1>
          <span className="text-xs text-muted-foreground ml-auto">
            {conversationLoading ? 'Initializing...' : 'Northwind DB'}
          </span>
        </div>

        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}

        {/* Chat window */}
        <div className="flex flex-col bg-card rounded-2xl border overflow-hidden h-[600px]">
          <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
                <p className="text-muted-foreground text-sm">Ask anything about your data</p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {[
                  "show top 5 customers by revenue",
                  "which products are low in stock",
                  "revenue by country",
                  "who are the top employees"
                ].map(suggestion => (
                    <button
                      key={suggestion}
                      onClick={() => handleSuggestionClick(suggestion)}
                      disabled={!conversationId || loading}
                      className="text-xs px-3 py-1.5 rounded-full bg-secondary hover:bg-secondary/80 disabled:opacity-50 text-secondary-foreground transition-colors"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.type === 'table' ? (
                  <div className="w-full">
                    <DataTable data={msg.data ?? []} />
                  </div>
                ) : msg.type === 'preview' ? (
                  <div className="w-full">
                    <SqlPreview
                      sql={msg.sql ?? ''}
                      params={msg.params ?? []}
                      onExecute={() => handleExecute(msg.sql ?? '', msg.params ?? [], i)}
                      onCancel={() => handleCancel(i)}
                    />
                  </div>
                ) : (
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-foreground'
                  }`}>
                    {msg.content}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-muted rounded-2xl px-4 py-2.5 text-sm text-muted-foreground flex items-center gap-2">
                  <span className="animate-pulse">●</span>
                  <span className="animate-pulse" style={{ animationDelay: '0.2s' }}>●</span>
                  <span className="animate-pulse" style={{ animationDelay: '0.4s' }}>●</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-4 border-t flex gap-3">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendMessage()}
              placeholder="Ask about your data..."
              className="flex-1 bg-muted rounded-xl px-4 py-2.5 text-sm text-foreground placeholder-muted-foreground outline-none focus:ring-2 focus:ring-ring transition-all"
            />
            <button
              onClick={sendMessage}
              disabled={loading || conversationLoading}
              className="px-5 py-2.5 bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground text-sm rounded-xl transition-colors font-medium"
            >
              Send
            </button>
          </div>
        </div>

      </div>
    </main>
  )
}