import { useEffect, useRef, useState } from 'react'
import { api, type Agent, type CallerProfile } from '../api'

interface SimulatorModalProps {
  agent: Agent
  onClose: () => void
}

interface TranscriptTurn {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  language?: string
  timestamp: string
}

interface LatencyRecord {
  stt_ms: number
  llm_ttft_ms: number
  tts_ms: number
  total_ms: number
  speculative_hit?: boolean
}

export function SimulatorModal({ agent, onClose }: SimulatorModalProps) {
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error' | 'ended'>('connecting')
  const [pipelineState, setPipelineState] = useState<'listening' | 'thinking' | 'speaking'>('listening')
  const [isMuted, setIsMuted] = useState(false)
  const [turns, setTurns] = useState<TranscriptTurn[]>([])
  const [partialText, setPartialText] = useState('')
  const [latency, setLatency] = useState<LatencyRecord | null>(null)
  const [handoffNotice, setHandoffNotice] = useState<string | null>(null)
  const [bargeInNotice, setBargeInNotice] = useState(false)
  const [callDuration, setCallDuration] = useState(0)
  const [textInput, setTextInput] = useState('')
  const [micVolume, setMicVolume] = useState(0)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [micWarning, setMicWarning] = useState<string | null>(null)
  const [sessionKey, setSessionKey] = useState(0)

  // Cross-Call Memory & Caller Recognition
  const [callerId, setCallerId] = useState('+15551234567')
  const [callerProfile, setCallerProfile] = useState<CallerProfile | null>(null)
  const [existingCallers, setExistingCallers] = useState<CallerProfile[]>([])

  // Refs for Web Audio API and WebSocket
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null)
  const nextPlayTimeRef = useRef<number>(0)
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([])
  const transcriptEndRef = useRef<HTMLDivElement | null>(null)
  const textInputRef = useRef<HTMLInputElement | null>(null)

  // Fetch known callers list
  useEffect(() => {
    api.listCallers(50).then((callers) => {
      setExistingCallers(callers)
    }).catch(() => {})
  }, [sessionKey])

  // Fetch profile for currently selected callerId
  useEffect(() => {
    if (!callerId.trim()) {
      setCallerProfile(null)
      return
    }
    api.getCaller(callerId.trim())
      .then((p) => setCallerProfile(p))
      .catch(() => setCallerProfile(null))
  }, [callerId, sessionKey])

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, partialText])

  // Call duration timer
  useEffect(() => {
    if (status !== 'connected') return
    const timer = setInterval(() => {
      setCallDuration((d) => d + 1)
    }, 1000)
    return () => clearInterval(timer)
  }, [status])

  // Initialize Web Audio and WebSocket
  useEffect(() => {
    let unmounted = false
    setStatus('connecting')
    setErrorMessage(null)
    setMicWarning(null)
    setCallDuration(0)

    async function initSession() {
      // 1. Establish WebSocket first so chat is ready immediately
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${proto}//${window.location.host}/api/agents/${agent.id}/simulator/ws?caller_id=${encodeURIComponent(callerId.trim() || 'unknown')}`
      let ws: WebSocket
      try {
        ws = new WebSocket(wsUrl)
        ws.binaryType = 'arraybuffer'
        wsRef.current = ws
      } catch (wsErr) {
        console.error('Failed to create WebSocket:', wsErr)
        if (!unmounted) {
          setStatus('error')
          setErrorMessage('Failed to connect to simulator server.')
        }
        return
      }

      ws.onopen = () => {
        if (!unmounted) {
          setStatus('connected')
          // Auto-focus text input for quick testing
          setTimeout(() => textInputRef.current?.focus(), 100)
        }
      }

      ws.onclose = () => {
        if (!unmounted) {
          setStatus((prev) => (prev === 'connected' ? 'ended' : prev))
        }
      }

      ws.onerror = () => {
        if (!unmounted) {
          setStatus('error')
          setErrorMessage('WebSocket connection failed. Ensure the server is running.')
        }
      }

      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          // Audio PCM16 chunk from agent TTS
          if (audioCtxRef.current) {
            handleIncomingAudio(event.data, audioCtxRef.current)
          }
        } else if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data)
            handleJsonEvent(msg)
          } catch (err) {
            console.error('Error parsing simulator message:', err)
          }
        }
      }

      // 2. Initialize AudioContext for agent speech playback
      let audioCtx: AudioContext | null = null
      try {
        const AudioCtxClass =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
        if (AudioCtxClass) {
          audioCtx = new AudioCtxClass()
          audioCtxRef.current = audioCtx
          nextPlayTimeRef.current = audioCtx.currentTime
        }
      } catch (audioErr) {
        console.warn('AudioContext initialization warning:', audioErr)
      }

      // 3. Request microphone stream (graceful fallback if mic is blocked/missing)
      if (audioCtx && navigator?.mediaDevices?.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          })
          if (unmounted) {
            stream.getTracks().forEach((t) => t.stop())
            return
          }
          mediaStreamRef.current = stream

          const source = audioCtx.createMediaStreamSource(stream)
          const processor = audioCtx.createScriptProcessor(2048, 1, 1)
          scriptProcessorRef.current = processor

          // Connect through a silent gain node to prevent speaker feedback while keeping processor active
          const silentGain = audioCtx.createGain()
          silentGain.gain.value = 0

          processor.onaudioprocess = (e) => {
            if (isMuted || ws.readyState !== WebSocket.OPEN) return

            const inputData = e.inputBuffer.getChannelData(0)
            const outputData = e.outputBuffer.getChannelData(0)
            outputData.fill(0) // Mute output to prevent acoustic feedback

            // Compute volume for visualizer
            let sum = 0
            for (let i = 0; i < inputData.length; i++) {
              sum += inputData[i] * inputData[i]
            }
            const rms = Math.sqrt(sum / inputData.length)
            setMicVolume(Math.min(100, Math.round(rms * 400)))

            // Downsample to 8000Hz PCM16 with linear interpolation
            const pcm16 = downsampleTo8k(inputData, audioCtx!.sampleRate)
            ws.send(pcm16.buffer as unknown as ArrayBuffer)
          }

          source.connect(processor)
          processor.connect(silentGain)
          silentGain.connect(audioCtx.destination)
        } catch (micErr: unknown) {
          const errName = (micErr as Error)?.name || ''
          if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
            setMicWarning('Microphone access denied. You can still test the agent using text chat below.')
          } else if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
            setMicWarning('No microphone found. You can still test the agent using text chat below.')
          } else {
            setMicWarning('Microphone unavailable. You can still test the agent using text chat below.')
          }
        }
      } else {
        setMicWarning('Microphone not supported in this browser context (requires HTTPS or localhost). You can test via text chat below.')
      }
    }

    initSession()

    return () => {
      unmounted = true
      cleanup()
    }
  }, [agent.id, sessionKey])

  function cleanup() {
    if (wsRef.current) {
      try {
        wsRef.current.send(JSON.stringify({ type: 'hangup' }))
        wsRef.current.close()
      } catch {
        /* ignore */
      }
      wsRef.current = null
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop())
      mediaStreamRef.current = null
    }
    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect()
      scriptProcessorRef.current = null
    }
    activeSourcesRef.current.forEach((s) => {
      try {
        s.stop()
      } catch {
        /* ignore */
      }
    })
    activeSourcesRef.current = []
    if (audioCtxRef.current) {
      try {
        audioCtxRef.current.close()
      } catch {
        /* ignore */
      }
      audioCtxRef.current = null
    }
  }

  function handleIncomingAudio(arrayBuffer: ArrayBuffer, audioCtx: AudioContext) {
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().then(() => {
        nextPlayTimeRef.current = audioCtx.currentTime
      }).catch(() => {})
    }

    // 8000Hz 16-bit signed PCM
    const int16 = new Int16Array(arrayBuffer)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0
    }

    const audioBuffer = audioCtx.createBuffer(1, float32.length, 8000)
    audioBuffer.copyToChannel(float32, 0)

    const source = audioCtx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(audioCtx.destination)

    const now = audioCtx.currentTime
    const startTime = Math.max(now, nextPlayTimeRef.current)
    source.start(startTime)
    nextPlayTimeRef.current = startTime + audioBuffer.duration

    activeSourcesRef.current.push(source)
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source)
    }
  }

  function handleJsonEvent(msg: Record<string, unknown>) {
    const type = msg.type as string
    if (type === 'state') {
      setPipelineState(msg.state as 'listening' | 'thinking' | 'speaking')
    } else if (type === 'partial_transcript') {
      setPartialText((msg.text as string) || '')
    } else if (type === 'transcript') {
      const role = msg.role as 'user' | 'assistant'
      const content = msg.content as string
      const language = msg.language as string | undefined
      if (role === 'user') {
        setPartialText('')
      }
      setTurns((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).slice(2),
          role,
          content,
          language,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        },
      ])
    } else if (type === 'latency') {
      setLatency({
        stt_ms: Number(msg.stt_ms) || 0,
        llm_ttft_ms: Number(msg.llm_ttft_ms) || 0,
        tts_ms: Number(msg.tts_ms) || 0,
        total_ms: Number(msg.total_ms) || 0,
        speculative_hit: Boolean(msg.speculative_hit),
      })
    } else if (type === 'barge_in') {
      // User interrupted speech: stop all queued audio buffers
      activeSourcesRef.current.forEach((s) => {
        try {
          s.stop()
        } catch {
          /* ignore */
        }
      })
      activeSourcesRef.current = []
      if (audioCtxRef.current) {
        nextPlayTimeRef.current = audioCtxRef.current.currentTime
      }
      setBargeInNotice(true)
      window.setTimeout(() => setBargeInNotice(false), 2000)
    } else if (type === 'handoff') {
      setHandoffNotice(msg.message ? String(msg.message) : `Escalated to human extension ${msg.target}`)
    } else if (type === 'tool_call') {
      const tool = (msg.tool as string) || 'tool'
      const details = (msg.details as string) || (msg.summary as string) || ''
      const isCheck = tool === 'check_sheet_availability' || tool === 'check_availability'
      const icon = isCheck ? '🔍' : '📅'
      const title = isCheck ? 'Checked Sheet Availability' : 'Booked Appointment in Sheet'
      setTurns((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).slice(2),
          role: 'tool',
          content: `${icon} [${title}]: ${details}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        },
      ])
    } else if (type === 'caller_recognized') {
      if (msg.profile) {
        setCallerProfile(msg.profile as CallerProfile)
      }
    } else if (type === 'call_ended') {
      setStatus('ended')
    } else if (type === 'error') {
      setStatus('error')
      setErrorMessage(String(msg.message || 'Server reported an error.'))
    }
  }

  function downsampleTo8k(inputData: Float32Array, inputSampleRate: number): Int16Array {
    if (inputSampleRate === 8000) {
      const output = new Int16Array(inputData.length)
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]))
        output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      return output
    }
    const ratio = inputSampleRate / 8000
    const newLength = Math.round(inputData.length / ratio)
    const output = new Int16Array(newLength)
    for (let i = 0; i < newLength; i++) {
      const srcIndex = i * ratio
      const indexLow = Math.floor(srcIndex)
      const indexHigh = Math.min(indexLow + 1, inputData.length - 1)
      const weight = srcIndex - indexLow
      const sample = inputData[indexLow] * (1 - weight) + inputData[indexHigh] * weight
      const s = Math.max(-1, Math.min(1, sample))
      output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    return output
  }

  function handleSendText() {
    if (!textInput.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    // Resume audio context if suspended on user gesture
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume().catch(() => {})
    }
    wsRef.current.send(JSON.stringify({ type: 'text_input', text: textInput.trim() }))
    setTextInput('')
  }

  function handleHangup() {
    cleanup()
    setStatus('ended')
    setTimeout(() => {
      if (callerId.trim()) {
        api.getCaller(callerId.trim()).then((p) => setCallerProfile(p)).catch(() => {})
        api.listCallers(50).then((callers) => setExistingCallers(callers)).catch(() => {})
      }
    }, 800)
  }

  function handleRetry() {
    cleanup()
    setSessionKey((k) => k + 1)
  }

  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}:${s < 10 ? '0' : ''}${s}`
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="simulator-dialog" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="simulator-header">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <span style={{ fontSize: '1.2rem' }}>🎙️</span>
              <strong style={{ fontSize: '1.1rem' }}>{agent.name} (Live Simulator)</strong>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: '0.2rem' }}>
              Extension: <span className="mono">{agent.extension}</span> · Model: {agent.llm_model.split(':')[0]}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span className={`state-badge state-${pipelineState}`}>
              <span
                className="sim-pulse-dot"
                style={{
                  background:
                    pipelineState === 'listening'
                      ? '#0284c7'
                      : pipelineState === 'thinking'
                      ? '#d97706'
                      : '#16a34a',
                }}
              />
              {pipelineState}
            </span>
            <button className="btn btn-ghost-dark btn-sm" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="simulator-body">
          {/* Caller Identity & Cross-Call Memory Bar */}
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.4rem',
            padding: '0.65rem 0.85rem',
            background: 'var(--paper-2, #f8fafc)',
            border: '1px solid var(--line, #e2e8f0)',
            borderRadius: 8,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem' }}>
                <span style={{ fontWeight: 600 }}>📞 Caller ID:</span>
                <input
                  type="text"
                  value={callerId}
                  onChange={(e) => setCallerId(e.target.value)}
                  list="known-callers-list"
                  placeholder="+15551234567"
                  style={{
                    padding: '0.2rem 0.5rem',
                    fontSize: '0.82rem',
                    borderRadius: 6,
                    border: '1px solid var(--line)',
                    fontFamily: 'var(--font-mono)',
                    width: 155,
                  }}
                />
                <datalist id="known-callers-list">
                  {existingCallers.map((c) => (
                    <option key={c.phone_number} value={c.phone_number}>
                      {c.name ? `${c.name} (${c.phone_number})` : c.phone_number}
                    </option>
                  ))}
                </datalist>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                {callerProfile ? (
                  <span className="chip ok" style={{ fontSize: '0.75rem' }}>
                    🧠 Recognized ({callerProfile.call_count} call{callerProfile.call_count > 1 ? 's' : ''})
                  </span>
                ) : (
                  <span className="chip muted" style={{ fontSize: '0.75rem' }}>
                    🆕 New Caller
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-ghost-dark btn-sm"
                  onClick={handleRetry}
                  title="Reconnect call with this Caller ID"
                  style={{ padding: '0.15rem 0.45rem', fontSize: '0.72rem' }}
                >
                  🔄 Apply & Call
                </button>
              </div>
            </div>

            {/* Profile Memory Details */}
            {callerProfile && (
              <div style={{
                marginTop: '0.15rem',
                padding: '0.45rem 0.65rem',
                background: '#f0fdf4',
                border: '1px solid #bbf7d0',
                borderRadius: 6,
                fontSize: '0.78rem',
                color: '#166534',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.25rem',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>
                    👤 {callerProfile.name || 'Returning Caller'} · Last call: {callerProfile.relative_time || 'recently'}
                  </span>
                  {callerProfile.last_sentiment && (
                    <span style={{
                      fontSize: '0.72rem',
                      background: callerProfile.last_sentiment === 'frustrated' ? '#fee2e2' : '#dcfce7',
                      color: callerProfile.last_sentiment === 'frustrated' ? '#b91c1c' : '#15803d',
                      padding: '0.1rem 0.4rem',
                      borderRadius: 4,
                      fontWeight: 600,
                    }}>
                      Sentiment: {callerProfile.last_sentiment}
                    </span>
                  )}
                </div>
                {callerProfile.last_summary && (
                  <div style={{ fontStyle: 'italic', color: '#15803d', opacity: 0.95 }}>
                    "{callerProfile.last_summary}"
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Status & Call Duration Bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
              <span className={`chip ${status === 'connected' ? 'ok' : status === 'ended' ? 'muted' : 'warn'}`}>
                {status}
              </span>
              <span className="mono" style={{ fontWeight: 600 }}>{formatTime(callDuration)}</span>
            </div>

            {/* Mic Energy Level Bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--muted)' }}>
              <span>Mic:</span>
              <div style={{ width: 80, height: 8, background: '#e2e8e4', borderRadius: 4, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${micVolume}%`,
                    height: '100%',
                    background: micVolume > 20 ? 'var(--accent)' : '#a1a1aa',
                    transition: 'width 60ms linear',
                  }}
                />
              </div>
            </div>
          </div>

          {/* Error Notice */}
          {errorMessage && (
            <div style={{ padding: '0.6rem 0.85rem', borderRadius: 8, background: '#fee2e2', color: '#b91c1c', fontSize: '0.85rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
              <span>⚠️ <strong>Error:</strong> {errorMessage}</span>
              <button type="button" className="btn btn-ghost-dark btn-sm" onClick={handleRetry} style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}>
                🔄 Retry
              </button>
            </div>
          )}

          {/* Mic Warning Notice */}
          {micWarning && !errorMessage && (
            <div style={{ padding: '0.5rem 0.75rem', borderRadius: 8, background: '#fef3c7', color: '#92400e', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span>🎙️</span> <span>{micWarning}</span>
            </div>
          )}

          {/* Barge-in or Handoff Notices */}
          {bargeInNotice && (
            <div style={{ padding: '0.5rem 0.75rem', borderRadius: 8, background: '#fef3c7', color: '#b45309', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span>⚡</span> <strong>Barge-in:</strong> Playback interrupted by your speech.
            </div>
          )}
          {handoffNotice && (
            <div style={{ padding: '0.5rem 0.75rem', borderRadius: 8, background: '#fee2e2', color: '#b91c1c', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span>📞</span> <strong>Handoff Triggered:</strong> {handoffNotice}
            </div>
          )}

          {/* Latency Waterfall Card */}
          {latency && (
            <div className="waterfall-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.82rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontWeight: 600, color: 'var(--ink)' }}>Turn Latency Waterfall</span>
                  {latency.speculative_hit && (
                    <span className="chip ok" style={{ fontSize: '0.72rem', padding: '0.1rem 0.45rem', fontWeight: 600 }}>
                      ⚡ Speculative Hit (~0ms TTFT)
                    </span>
                  )}
                </div>
                <span className="mono" style={{ fontWeight: 700, color: latency.total_ms < 800 ? 'var(--ok)' : 'var(--warn)' }}>
                  Total: {Math.round(latency.total_ms)}ms
                </span>
              </div>
              <div className="waterfall-bars">
                <div
                  style={{
                    width: `${Math.max(5, (latency.stt_ms / latency.total_ms) * 100)}%`,
                    background: '#0ea5e9',
                  }}
                  title={`STT: ${Math.round(latency.stt_ms)}ms`}
                />
                <div
                  style={{
                    width: `${Math.max(5, (latency.llm_ttft_ms / latency.total_ms) * 100)}%`,
                    background: '#8b5cf6',
                  }}
                  title={`LLM TTFT: ${Math.round(latency.llm_ttft_ms)}ms`}
                />
                <div
                  style={{
                    width: `${Math.max(5, (latency.tts_ms / latency.total_ms) * 100)}%`,
                    background: '#f97316',
                  }}
                  title={`TTS: ${Math.round(latency.tts_ms)}ms`}
                />
              </div>
              <div className="waterfall-legend">
                <span><div className="waterfall-dot" style={{ background: '#0ea5e9' }} /> STT: {Math.round(latency.stt_ms)}ms</span>
                <span><div className="waterfall-dot" style={{ background: '#8b5cf6' }} /> LLM TTFT: {Math.round(latency.llm_ttft_ms)}ms</span>
                <span><div className="waterfall-dot" style={{ background: '#f97316' }} /> TTS: {Math.round(latency.tts_ms)}ms</span>
              </div>
            </div>
          )}

          {/* Transcript Area */}
          <div className="sim-transcript">
            {turns.length === 0 && (
              <div className="empty" style={{ padding: '1.5rem 0', fontSize: '0.88rem' }}>
                Start speaking into your microphone or type a message below to test the agent.
              </div>
            )}
            {turns.map((t) => (
              <div key={t.id} className={`sim-bubble ${t.role}`}>
                <div style={{ fontSize: '0.72rem', opacity: 0.7, marginBottom: '0.2rem' }}>
                  {t.role === 'assistant' ? agent.name : t.role === 'tool' ? '⚡ System Tool' : 'You'} · {t.timestamp}
                  {t.language ? ` (${t.language})` : ''}
                </div>
                <div>{t.content}</div>
              </div>
            ))}
            {partialText && (
              <div className="sim-bubble partial">
                <div style={{ fontSize: '0.72rem', opacity: 0.7, marginBottom: '0.2rem' }}>Listening…</div>
                <div>{partialText}</div>
              </div>
            )}
            <div ref={transcriptEndRef} />
          </div>
        </div>

        {/* Footer & Controls */}
        <div className="simulator-footer">
          {/* Text input fallback */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSendText()
            }}
            style={{ display: 'flex', gap: '0.5rem' }}
          >
            <input
              ref={textInputRef}
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder={status === 'connected' ? (micWarning ? "Type a message to talk with agent..." : "Type message or talk into mic...") : status === 'connecting' ? "Connecting to agent..." : "Call ended or disconnected"}
              disabled={status !== 'connected'}
              style={{ flex: 1, padding: '0.55rem 0.75rem', borderRadius: 8, border: '1px solid var(--line)' }}
            />
            <button className="btn btn-ink btn-sm" type="submit" disabled={!textInput.trim() || status !== 'connected'}>
              Send
            </button>
          </form>

          {/* Audio Action Buttons */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                className={`btn btn-sm ${isMuted ? 'btn-danger' : 'btn-ghost-dark'}`}
                onClick={() => setIsMuted((m) => !m)}
                title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
              >
                {isMuted ? '🔇 Unmute' : '🎙️ Mute'}
              </button>
              <button
                type="button"
                className="btn btn-ghost-dark btn-sm"
                onClick={() => setTurns([])}
                title="Clear transcript history"
              >
                🧹 Clear
              </button>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {status === 'connected' ? (
                <button className="btn btn-danger btn-sm" type="button" onClick={handleHangup}>
                  🔴 End Call
                </button>
              ) : (
                <>
                  <button className="btn btn-ghost-dark btn-sm" type="button" onClick={handleRetry}>
                    🔄 Reconnect
                  </button>
                  <button className="btn btn-primary btn-sm" type="button" onClick={onClose}>
                    Close Simulator
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
