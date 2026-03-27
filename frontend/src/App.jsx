import { useState } from 'react'


function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [todoinput, setTodoinput] = useState("")
  const [todos, setTodos] = useState([])

  const sendMessage = async () => {
    if (!input.trim()) return 

    const userMessage = { sender: "you", text: input }
    setMessages(prev => [...prev, userMessage])
    setInput("")

    const response = await fetch("http://localhost:8000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({text:input}),
    });


    const data = await response.json()
    const botMessage = {sender:"bot", text:data.reply}
    setMessages((prev) => [...prev, botMessage]);
      
  }

  const todoAdd = async () => {
    if (!todoinput.trim()) return 

    await fetch("http://localhost:8000/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({task:todoinput})
    });

    setTodoinput("")

    const todoResponse = await fetch("http://localhost:8000/todos")
    const todoData = await todoResponse.json()
    setTodos(todoData.todos)
  }

  return (
    <div
      style={{
        maxWidth: "600px",
        margin: "40px auto",
        fontFamily: "sans-serif",
      }}
    >
      <h2>Conversational Data Assistant</h2>

      <div
        style={{
          border: "1px solid #ccc",
          borderRadius: "8px",
          padding: "16px",
          height: "400px",
          overflowY: "auto",
          marginBottom: "12px",
        }}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              textAlign: msg.sender === "you" ? "right" : "left",
              margin: "8px 0",
            }}
          >
            <span
              style={{
                background: msg.sender === "you" ? "#007bff" : "#e9e9e9",
                color: msg.sender === "you" ? "white" : "black",
                padding: "8px 12px",
                borderRadius: "16px",
                display: "inline-block",
              }}
            >
              {msg.text}
            </span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: "8px" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Type a message..."
          style={{
            flex: 1,
            padding: "10px",
            borderRadius: "8px",
            border: "1px solid #ccc",
          }}
        />
        <button
          onClick={sendMessage}
          style={{
            padding: "10px 20px",
            borderRadius: "8px",
            background: "#007bff",
            color: "white",
            border: "none",
            cursor: "pointer",
          }}
        >
          Send
        </button>
      </div>
    </div>
  );

}

export default App
