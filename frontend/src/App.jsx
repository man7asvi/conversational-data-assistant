import { useState, useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card } from "@/components/ui/card"

function Table({ data }) {
  if (!data || data.length === 0) return <p className="text-sm text-muted-foreground">No results found</p>
  const columns = Object.keys(data[0])
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            {columns.map(col => (
              <th key={col} className="px-4 py-2 text-left font-medium text-muted-foreground">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
              {columns.map(col => (
                <td key={col} className="px-4 py-2">
                  {row[col]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim()) return

    const userMessage = { sender: "you", text: input, type: "text" }
    setMessages(prev => [...prev, userMessage])
    setInput("")
    setLoading(true)

    const response = await fetch("http://localhost:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input }),
    })

    const data = await response.json()
    const botMessage = { sender: "bot", text: data.reply, type: data.type }
    setMessages(prev => [...prev, botMessage])
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-2xl flex flex-col gap-4">

        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500" />
          <h1 className="text-xl font-semibold tracking-tight">Conversational Data Assistant</h1>
        </div>

        <Card className="flex flex-col h-[550px]">
          <ScrollArea className="h-[470px] p-4">
            <div className="flex flex-col gap-3">
              {messages.length === 0 && (
                <div className="text-center text-muted-foreground text-sm mt-8">
                  Try asking: "show all sales", "show NY sales", "show totals"
                </div>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.sender === "you" ? "justify-end" : "justify-start"}`}>
                  {msg.type === "table" ? (
                    <div className="w-full">
                      <Table data={msg.text} />
                    </div>
                  ) : (
                    <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${
                      msg.sender === "you"
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-foreground"
                    }`}>
                      {msg.text}
                    </div>
                  )}
                </div>
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-muted rounded-2xl px-4 py-2 text-sm text-muted-foreground">
                    Thinking...
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          <div className="p-4 border-t flex gap-2">
            <Input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && sendMessage()}
              placeholder="Ask about your data..."
              className="flex-1"
            />
            <Button onClick={sendMessage} disabled={loading}>
              Send
            </Button>
          </div>
        </Card>

      </div>
    </div>
  )
}

export default App