import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  const body = await req.json()

  const response = await fetch('http://127.0.0.1:8000/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    console.error('Backend error:', text)
    return NextResponse.json({ error: 'Backend error', detail: text }, { status: response.status })
  }

  const data = await response.json()
  return NextResponse.json(data)
}