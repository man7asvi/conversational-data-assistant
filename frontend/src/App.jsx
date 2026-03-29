import { useState, useEffect, useRef } from "react"

function Table({ data }) {
  if (!data || data.length === 0) return <p>No results found</p>
  const columns = Object.keys(data[0])
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "13px" }}>
      <thead>
        <tr>
          {columns.map(col => (
            <th key={col} style={{ border: "1px solid #ccc", padding: "6px 10px", background: "#f0f0f0", color: "#333" }}>
              {col}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row, i) => (
          <tr key={i}>
            {columns.map(col => (
              <td key={col} style={{ border: "1px solid #ccc", padding: "6px 10px" }}>
                {row[col]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const messagesEndRef = useRef(null)

  useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim()) return

    const userMessage = { sender: "you", text: input, type: "text" }
    setMessages(prev => [...prev, userMessage])
    setInput("")

    const response = await fetch("http://localhost:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input }),
    })

    const data = await response.json()
    const botMessage = { sender: "bot", text: data.reply, type: data.type }
    setMessages(prev => [...prev, botMessage])
  }

  return (
    <div style={{ maxWidth: "700px", margin: "40px auto", fontFamily: "sans-serif" }}>
      <h2>Conversational Data Assistant</h2>

      <div style={{ border: "1px solid #ccc", borderRadius: "8px", padding: "16px", height: "500px", overflowY: "auto", marginBottom: "12px" }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ textAlign: msg.sender === "you" ? "right" : "left", margin: "12px 0" }}>
            {msg.type === "table" ? (
              <div style={{ textAlign: "left" }}>
                <Table data={msg.text} />
              </div>
            ) : (
              <span style={{
                background: msg.sender === "you" ? "#007bff" : "#e9e9e9",
                color: msg.sender === "you" ? "white" : "black",
                padding: "8px 12px",
                borderRadius: "16px",
                display: "inline-block"
              }}>
                {msg.text}
              </span>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div style={{ display: "flex", gap: "8px" }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Try: show all sales, show NY sales, show totals"
          style={{ flex: 1, padding: "10px", borderRadius: "8px", border: "1px solid #ccc" }}
        />
        <button onClick={sendMessage} style={{ padding: "10px 20px", borderRadius: "8px", background: "#007bff", color: "white", border: "none", cursor: "pointer" }}>
          Send
        </button>
      </div>
    </div>
  )
}

export default App