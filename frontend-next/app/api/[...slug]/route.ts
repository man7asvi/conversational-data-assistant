import { NextResponse } from 'next/server'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'

export async function POST(request: Request, { params }: { params: Promise<{ slug: string[] }> }) {
  try {
    const { slug } = await params
    const path = '/' + slug.join('/')
    const backendUrl = `${BACKEND_URL}${path}`
    const body = await request.json()
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}

export async function GET(request: Request, { params }: { params: Promise<{ slug: string[] }> }) {
  try {
    const { slug } = await params
    const path = '/' + slug.join('/')
    const backendUrl = `${BACKEND_URL}${path}`
    const response = await fetch(backendUrl)
    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}

export async function DELETE(request: Request, { params }: { params: Promise<{ slug: string[] }> }) {
  try {
    const { slug } = await params
    const path = '/' + slug.join('/')
    const backendUrl = `${BACKEND_URL}${path}`
    const response = await fetch(backendUrl, { method: 'DELETE' })
    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
