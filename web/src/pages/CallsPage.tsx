import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type CallSummary, type CallTurn } from '../api'
import { useToast } from '../toast'

function formatTime(secs: number): string {
  if (isNaN(secs) || secs < 0) return '00:00'
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function renderDispositionBadge(disp?: string) {
  const d = disp || 'Completed'
  if (d === 'Lead Captured') {
    return <span className="badge-disp badge-disp-lead">🎯 Lead Captured</span>
  } else if (d === 'Escalated to Human') {
    return <span className="badge-disp badge-disp-transferred">👤 Escalated</span>
  } else if (d === 'Dropped / Hangup') {
    return <span className="badge-disp badge-disp-dropped">⏹ Dropped</span>
  } else if (d === 'Follow-up Needed') {
    return <span className="badge-disp badge-disp-followup">📞 Follow-up</span>
  }
  return <span className="badge-disp badge-disp-info">ℹ️ {d}</span>
}

function renderSentimentBadge(sent?: string) {
  const s = (sent || 'neutral').toLowerCase()
  if (s === 'positive') {
    return <span className="badge-sent badge-sent-pos">🟢 Positive</span>
  } else if (s === 'frustrated') {
    return <span className="badge-sent badge-sent-frust">🔴 Frustrated</span>
  }
  return <span className="badge-sent badge-sent-neu">⚪ Neutral</span>
}

export function CallsPage() {
  const { show } = useToast()
  const [calls, setCalls] = useState<CallSummary[]>([])

  useEffect(() => {
    api
      .listCalls()
      .then(setCalls)
      .catch((e) => show(e.message, true))
  }, [show])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Call history</h1>
          <p>Conversation intelligence, lead captures, sentiment analysis, and audio recordings across your agents.</p>
        </div>
      </div>

      <section className="panel panel-pad">
        {calls.length === 0 ? (
          <div className="empty">No calls recorded yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Caller</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Disposition</th>
                <th>Sentiment</th>
                <th>Variant</th>
                <th>Preview</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 600 }}>{c.agent_name}</td>
                  <td className="mono">{c.caller_id}</td>
                  <td className="mono">{new Date(c.started_at).toLocaleString()}</td>
                  <td className="mono">{Math.round(c.duration_s)}s</td>
                  <td>{renderDispositionBadge(c.disposition)}</td>
                  <td>{renderSentimentBadge(c.sentiment)}</td>
                  <td>
                    <span className="chip muted mono">Variant {c.ab_variant || 'A'}</span>
                  </td>
                  <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.transcript_preview || '—'}
                  </td>
                  <td>
                    <Link className="btn btn-ghost-dark" style={{ padding: '0.25rem 0.65rem', fontSize: '0.8rem' }} to={`/calls/${c.id}`}>
                      Details →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

export function CallDetailPage() {
  const { id } = useParams()
  const { show } = useToast()
  const [call, setCall] = useState<(CallSummary & { turns: CallTurn[]; agent_name: string }) | null>(null)

  // Audio Player State
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const transcriptContainerRef = useRef<HTMLDivElement | null>(null)
  const turnRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1.0)
  const [audioAvailable, setAudioAvailable] = useState(true)
  const [engineMode, setEngineMode] = useState<'wav' | 'tts'>('wav')
  const [volume, setVolume] = useState(1.0)
  const [isMuted, setIsMuted] = useState(false)
  const [hoverFrac, setHoverFrac] = useState<number | null>(null)

  // Transcript UI state
  const [searchQuery, setSearchQuery] = useState('')
  const [speakerFilter, setSpeakerFilter] = useState<'all' | 'user' | 'assistant'>('all')
  const [autoScroll, setAutoScroll] = useState(true)
  const [ttsCurrentTurnIdx, setTtsCurrentTurnIdx] = useState<number | null>(null)

  useEffect(() => {
    if (!id) return
    api
      .getCall(id)
      .then((c) => {
        setCall(c)
        if (c.duration_s > 0) setDuration(c.duration_s)
      })
      .catch((e) => show(e.message, true))
  }, [id, show])

  // Stop any active TTS when unmounting or navigating
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel()
      }
    }
  }, [])

  // Calculate active turn index based on playback currentTime
  const totalCallDuration = duration || call?.duration_s || 1
  let activeTurnId: string | null = null
  if (call && call.turns.length > 0) {
    if (engineMode === 'tts' && ttsCurrentTurnIdx !== null && call.turns[ttsCurrentTurnIdx]) {
      activeTurnId = call.turns[ttsCurrentTurnIdx].id
    } else {
      for (let i = 0; i < call.turns.length; i++) {
        const turnStart = call.turns[i].offset_s ?? 0
        const nextTurnStart = i < call.turns.length - 1 ? (call.turns[i + 1].offset_s ?? totalCallDuration) : totalCallDuration
        if (currentTime >= turnStart && currentTime < nextTurnStart) {
          activeTurnId = call.turns[i].id
          break
        }
      }
    }
  }

  // Auto-scroll transcript container to active turn
  useEffect(() => {
    if (!autoScroll || !activeTurnId) return
    const el = turnRefs.current.get(activeTurnId)
    if (el && transcriptContainerRef.current) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeTurnId, autoScroll])

  // Native WAV Player Controls
  const togglePlayWav = () => {
    if (!audioRef.current) return
    if (isPlaying) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      audioRef.current
        .play()
        .then(() => setIsPlaying(true))
        .catch(() => {
          // If native WAV cannot be decoded or loaded, gracefully switch to TTS Speech Engine
          setAudioAvailable(false)
          setEngineMode('tts')
          startTtsPlayback(0)
        })
    }
  }

  // TTS Speech Engine Playback
  const startTtsPlayback = (startIdx: number) => {
    if (!call || call.turns.length === 0 || typeof window === 'undefined' || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()

    let currentIdx = Math.max(0, Math.min(call.turns.length - 1, startIdx))
    setIsPlaying(true)
    setEngineMode('tts')

    const speakNextTurn = () => {
      if (currentIdx >= call.turns.length) {
        setIsPlaying(false)
        setTtsCurrentTurnIdx(null)
        return
      }

      const turn = call.turns[currentIdx]
      setTtsCurrentTurnIdx(currentIdx)
      const offset = turn.offset_s ?? (currentIdx * (totalCallDuration / call.turns.length))
      setCurrentTime(offset)

      const utterance = new SpeechSynthesisUtterance(turn.content)
      utterance.rate = playbackRate

      // Choose distinct voices for caller vs agent
      const voices = window.speechSynthesis.getVoices()
      if (turn.role === 'assistant') {
        const agentVoice =
          voices.find((v) => v.lang.startsWith(turn.language || 'en') && (v.name.includes('Google') || v.name.includes('Natural'))) ||
          voices.find((v) => v.lang.startsWith(turn.language || 'en'))
        if (agentVoice) utterance.voice = agentVoice
        utterance.pitch = 1.05
      } else {
        const callerVoice =
          voices.find((v) => v.lang.startsWith(turn.language || 'en') && !v.name.includes('Google')) ||
          voices.find((v) => v.lang.startsWith(turn.language || 'en'))
        if (callerVoice) utterance.voice = callerVoice
        utterance.pitch = 0.92
      }

      utterance.onend = () => {
        currentIdx++
        speakNextTurn()
      }

      utterance.onerror = () => {
        setIsPlaying(false)
        setTtsCurrentTurnIdx(null)
      }

      window.speechSynthesis.speak(utterance)
    }

    speakNextTurn()
  }

  const stopTtsPlayback = () => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    setIsPlaying(false)
    setTtsCurrentTurnIdx(null)
  }

  const togglePlay = () => {
    if (engineMode === 'wav' && audioAvailable) {
      togglePlayWav()
    } else {
      if (isPlaying) {
        stopTtsPlayback()
      } else {
        // Find index corresponding to currentTime
        const idx = call?.turns.findIndex((t) => (t.offset_s ?? 0) >= currentTime) ?? 0
        startTtsPlayback(idx >= 0 ? idx : 0)
      }
    }
  }

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const frac = Math.max(0, Math.min(1, clickX / rect.width))
    const total = duration || (call?.duration_s ?? 1)
    const newTime = frac * total

    setCurrentTime(newTime)

    if (engineMode === 'wav' && audioRef.current && audioAvailable) {
      audioRef.current.currentTime = newTime
      if (!isPlaying) {
        audioRef.current.play().then(() => setIsPlaying(true)).catch(() => {})
      }
    } else if (call && call.turns.length > 0) {
      // Find turn closest to newTime
      let closestIdx = 0
      for (let i = 0; i < call.turns.length; i++) {
        if ((call.turns[i].offset_s ?? 0) <= newTime) {
          closestIdx = i
        }
      }
      startTtsPlayback(closestIdx)
    }
  }

  const seekToTurn = (offset: number, turnId?: string) => {
    setCurrentTime(offset)
    if (engineMode === 'wav' && audioRef.current && audioAvailable) {
      audioRef.current.currentTime = offset
      if (!isPlaying) {
        audioRef.current.play().then(() => setIsPlaying(true)).catch(() => {})
      }
    } else if (call && call.turns.length > 0) {
      const idx = turnId ? call.turns.findIndex((t) => t.id === turnId) : call.turns.findIndex((t) => (t.offset_s ?? 0) === offset)
      startTtsPlayback(idx >= 0 ? idx : 0)
    }
  }

  const skipTime = (delta: number) => {
    const total = duration || (call?.duration_s ?? 1)
    const newTime = Math.max(0, Math.min(total, currentTime + delta))
    setCurrentTime(newTime)
    if (engineMode === 'wav' && audioRef.current && audioAvailable) {
      audioRef.current.currentTime = newTime
    }
  }

  const changeRate = (rate: number) => {
    setPlaybackRate(rate)
    if (audioRef.current) {
      audioRef.current.playbackRate = rate
    }
  }

  const toggleMute = () => {
    const nextMuted = !isMuted
    setIsMuted(nextMuted)
    if (audioRef.current) {
      audioRef.current.muted = nextMuted
    }
  }

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value)
    setVolume(val)
    setIsMuted(val === 0)
    if (audioRef.current) {
      audioRef.current.volume = val
      audioRef.current.muted = val === 0
    }
  }

  // Speak a single turn on-demand
  const speakSingleTurn = (e: React.MouseEvent, content: string, role: string, lang?: string) => {
    e.stopPropagation()
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(content)
    utter.rate = playbackRate
    const voices = window.speechSynthesis.getVoices()
    const targetVoice = voices.find((v) => v.lang.startsWith(lang || 'en'))
    if (targetVoice) utter.voice = targetVoice
    utter.pitch = role === 'assistant' ? 1.05 : 0.92
    window.speechSynthesis.speak(utter)
  }

  // Copy Full Transcript
  const copyTranscript = () => {
    if (!call || call.turns.length === 0) return
    const text = call.turns
      .map((t) => {
        const timeStr = formatTime(t.offset_s ?? 0)
        const speaker = t.role === 'user' ? 'Caller' : `Agent (${call.agent_name})`
        return `[${timeStr}] ${speaker}: ${t.content}`
      })
      .join('\n\n')

    navigator.clipboard
      .writeText(text)
      .then(() => show('Full transcript copied to clipboard!'))
      .catch(() => show('Failed to copy transcript', true))
  }

  // Download Transcript as TXT
  const downloadTranscript = () => {
    if (!call || call.turns.length === 0) return
    const text = [
      `CallForge Telephony Transcript`,
      `Agent: ${call.agent_name}`,
      `Date: ${new Date(call.started_at).toLocaleString()}`,
      `Duration: ${Math.round(call.duration_s)}s`,
      `Disposition: ${call.disposition || 'Completed'}`,
      `Sentiment: ${call.sentiment || 'neutral'}`,
      `============================================================\n`,
      ...call.turns.map((t) => {
        const timeStr = formatTime(t.offset_s ?? 0)
        const speaker = t.role === 'user' ? 'Caller' : `Agent (${call.agent_name})`
        return `[${timeStr}] ${speaker}:\n${t.content}\n`
      }),
    ].join('\n')

    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `transcript_${call.id.slice(0, 8)}.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  if (!call) return <div className="empty">Loading…</div>

  // Parse captured slots
  let capturedSlots: Record<string, string> = {}
  try {
    if (call.slots_json && call.slots_json !== '{}') {
      capturedSlots = JSON.parse(call.slots_json)
    }
  } catch {
    /* ignore json parse error */
  }
  const hasSlots = Object.keys(capturedSlots).length > 0

  // Pre-generate 54 visual waveform bars with density weighting
  const barCount = 54
  const waveformBars = Array.from({ length: barCount }, (_, idx) => {
    const frac = idx / barCount
    const barSec = frac * totalCallDuration
    const isTurnSpeech = call.turns.some((t) => {
      const start = t.offset_s ?? 0
      return Math.abs(barSec - start) < 3.2
    })
    const heightPercent = isTurnSpeech ? 42 + ((idx * 19 + 29) % 52) : 18 + ((idx * 7 + 13) % 20)
    const isPlayed = barSec <= currentTime
    return { heightPercent, isPlayed, barSec }
  })

  // Filter turns by role and search query
  const filteredTurns = call.turns.filter((t) => {
    if (speakerFilter !== 'all' && t.role !== speakerFilter) return false
    if (searchQuery.trim()) {
      return t.content.toLowerCase().includes(searchQuery.toLowerCase())
    }
    return true
  })

  const userTurnCount = call.turns.filter((t) => t.role === 'user').length
  const agentTurnCount = call.turns.filter((t) => t.role === 'assistant').length

  // Highlight search text helper
  const renderHighlightedContent = (content: string) => {
    if (!searchQuery.trim()) return content
    const parts = content.split(new RegExp(`(${searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return (
      <>
        {parts.map((part, i) =>
          part.toLowerCase() === searchQuery.toLowerCase() ? <mark key={i}>{part}</mark> : part
        )}
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{call.agent_name}</h1>
          <p>
            {new Date(call.started_at).toLocaleString()} · {Math.round(call.duration_s)}s ·{' '}
            <span className="mono">{call.call_uuid.slice(0, 8)}</span>
          </p>
        </div>
        <Link className="btn btn-ghost-dark" to="/calls">
          ← Back to History
        </Link>
      </div>

      {/* Conversation Intelligence Banner */}
      <div className="intelligence-banner">
        <div className="intel-stat">
          <span className="stat-label">Disposition</span>
          <span className="stat-val">{renderDispositionBadge(call.disposition)}</span>
        </div>
        <div className="intel-stat">
          <span className="stat-label">Sentiment</span>
          <span className="stat-val">{renderSentimentBadge(call.sentiment)}</span>
        </div>
        <div className="intel-stat">
          <span className="stat-label">Caller</span>
          <span className="stat-val mono">{call.caller_id}</span>
        </div>
        <div className="intel-stat">
          <span className="stat-label">Duration</span>
          <span className="stat-val mono">{Math.round(call.duration_s)}s</span>
        </div>
        <div className="intel-stat">
          <span className="stat-label">Variant</span>
          <span className="stat-val">
            <span className="chip ok mono">Variant {call.ab_variant || 'A'}</span>
          </span>
        </div>
        {call.handoff_to && (
          <div className="intel-stat">
            <span className="stat-label">Handoff Forwarded</span>
            <span className="stat-val" style={{ color: 'var(--warn)' }}>
              Ext {call.handoff_to}
            </span>
          </div>
        )}
      </div>

      {/* Lead Capture Summary Card */}
      {hasSlots && (
        <div className="lead-capture-card">
          <div className="lead-header">
            <h3>🎯 Lead Capture Information</h3>
            <span className="chip ok">✓ Extracted by Dialogue Policy</span>
          </div>
          <div className="lead-grid">
            {Object.entries(capturedSlots).map(([key, val]) => (
              <div key={key} className="lead-item">
                <div className="slot-name">{key.replace(/_/g, ' ')}</div>
                <div className="slot-value">{val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Audio Waveform Player Section */}
      <div className="waveform-player-card">
        <audio
          ref={audioRef}
          src={api.callAudioUrl(call.id)}
          onTimeUpdate={() => {
            if (audioRef.current && engineMode === 'wav') {
              setCurrentTime(audioRef.current.currentTime)
            }
          }}
          onLoadedMetadata={() => {
            if (audioRef.current && audioRef.current.duration) {
              setDuration(audioRef.current.duration)
              setAudioAvailable(true)
            }
          }}
          onCanPlayThrough={() => setAudioAvailable(true)}
          onEnded={() => setIsPlaying(false)}
          onError={() => {
            // When raw WAV audio is missing from disk or unplayable, auto-switch to Speech Engine fallback
            setAudioAvailable(false)
            setEngineMode('tts')
          }}
        />

        <div className="player-top">
          <div className="player-title">
            <span>🎙️ Call Audio Recording</span>
            {audioAvailable ? (
              <span className="chip ok" style={{ fontSize: '0.72rem' }}>
                🟢 8kHz Telephony WAV
              </span>
            ) : (
              <span className="player-mode-badge" style={{ background: '#ede9fe', color: '#5b21b6' }}>
                🤖 AI Speech Engine
              </span>
            )}
            {/* Audio Engine Mode Selector */}
            <div style={{ display: 'inline-flex', gap: '0.3rem', marginLeft: '0.4rem' }}>
              <button
                type="button"
                className={`rate-chip ${engineMode === 'wav' ? 'active' : ''}`}
                style={{ fontSize: '0.7rem', padding: '0.15rem 0.45rem' }}
                onClick={() => {
                  stopTtsPlayback()
                  setEngineMode('wav')
                }}
                title="Play recorded audio file"
              >
                🎙️ Telephony WAV
              </button>
              <button
                type="button"
                className={`rate-chip ${engineMode === 'tts' ? 'active' : ''}`}
                style={{ fontSize: '0.7rem', padding: '0.15rem 0.45rem' }}
                onClick={() => {
                  if (audioRef.current) audioRef.current.pause()
                  setIsPlaying(false)
                  setEngineMode('tts')
                }}
                title="Synthesize conversation dialogue using Web Speech voices"
              >
                🤖 AI Reader (TTS)
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {audioAvailable && (
              <a
                className="btn btn-ghost-dark"
                style={{ fontSize: '0.78rem', padding: '0.25rem 0.6rem' }}
                href={api.callAudioUrl(call.id)}
                download={`call_${call.id.slice(0, 8)}.wav`}
                title="Download raw audio WAV file"
              >
                ⬇ Download WAV
              </a>
            )}
          </div>
        </div>

        {/* Scrubbable Waveform Track */}
        <div
          className="waveform-interactive-track"
          onClick={handleSeek}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
            setHoverFrac(frac)
          }}
          onMouseLeave={() => setHoverFrac(null)}
          title="Click to scrub audio to any position"
        >
          {waveformBars.map((bar, i) => (
            <div
              key={i}
              className={`waveform-bar-col ${bar.isPlayed ? 'played' : ''}`}
              style={{ height: `${bar.heightPercent}%` }}
            />
          ))}

          {/* Turn Marker Ticks across the timeline */}
          {call.turns.map((t) => {
            const turnOffset = t.offset_s ?? 0
            const markerLeft = (turnOffset / totalCallDuration) * 100
            return (
              <div
                key={`marker-${t.id}`}
                className={`waveform-turn-marker ${t.role === 'assistant' ? 'agent-marker' : ''}`}
                style={{ left: `${Math.min(99.5, Math.max(0.5, markerLeft))}%` }}
                onClick={(e) => {
                  e.stopPropagation()
                  seekToTurn(turnOffset, t.id)
                }}
                title={`Jump to ${t.role === 'user' ? 'Caller' : 'Agent'} at ${formatTime(turnOffset)}: "${t.content.slice(0, 40)}..."`}
              />
            )
          })}

          {/* Scrubber needle with glowing thumb */}
          <div
            className="waveform-scrubber-line"
            style={{
              left: `${Math.min(100, Math.max(0, (currentTime / totalCallDuration) * 100))}%`,
            }}
          >
            <div className="waveform-scrubber-handle" />
          </div>

          {/* Hover Time Tooltip */}
          {hoverFrac !== null && (
            <div
              style={{
                position: 'absolute',
                top: '4px',
                left: `${hoverFrac * 100}%`,
                transform: 'translateX(-50%)',
                background: '#111827',
                color: '#fff',
                fontSize: '0.68rem',
                fontFamily: 'var(--font-mono)',
                padding: '0.1rem 0.35rem',
                borderRadius: '4px',
                pointerEvents: 'none',
                zIndex: 20,
              }}
            >
              {formatTime(hoverFrac * totalCallDuration)}
            </div>
          )}
        </div>

        {/* Controls Row */}
        <div className="player-controls-row">
          <div className="player-left-controls">
            <button
              type="button"
              className="player-skip-btn"
              onClick={() => skipTime(-5)}
              title="Rewind 5 seconds"
            >
              -5s
            </button>
            <button
              type="button"
              className="play-pause-btn"
              onClick={togglePlay}
              title={isPlaying ? 'Pause playback' : 'Play audio'}
            >
              {isPlaying ? '⏸' : '▶'}
            </button>
            <button
              type="button"
              className="player-skip-btn"
              onClick={() => skipTime(5)}
              title="Forward 5 seconds"
            >
              +5s
            </button>

            <div className="player-time-display">
              {formatTime(currentTime)} / {formatTime(totalCallDuration)}
            </div>
          </div>

          <div className="player-right-controls">
            {/* Volume Control */}
            {engineMode === 'wav' && (
              <div className="player-volume-control">
                <button
                  type="button"
                  onClick={toggleMute}
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '0.85rem' }}
                  title={isMuted ? 'Unmute' : 'Mute'}
                >
                  {isMuted || volume === 0 ? '🔇' : volume < 0.5 ? '🔉' : '🔊'}
                </button>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={isMuted ? 0 : volume}
                  onChange={handleVolumeChange}
                  className="player-volume-slider"
                  title={`Volume: ${Math.round((isMuted ? 0 : volume) * 100)}%`}
                />
              </div>
            )}

            {/* Playback Speed */}
            <span style={{ fontSize: '0.78rem', color: 'var(--muted)', fontWeight: 600 }}>Speed:</span>
            {[0.75, 1.0, 1.25, 1.5, 2.0].map((rate) => (
              <button
                key={rate}
                type="button"
                className={`rate-chip ${playbackRate === rate ? 'active' : ''}`}
                onClick={() => changeRate(rate)}
              >
                {rate}x
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Call Transcript Section */}
      <section className="panel panel-pad">
        <div className="transcript-header-bar">
          <div className="transcript-header-title">
            <h2>💬 Call Transcript</h2>
            <span className="chip muted mono" style={{ fontSize: '0.75rem' }}>
              {filteredTurns.length} / {call.turns.length} Turns
            </span>
          </div>

          <div className="transcript-tools">
            {/* Search Input */}
            <div className="transcript-search-box">
              <span className="transcript-search-icon">🔍</span>
              <input
                type="text"
                placeholder="Search dialogue..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  style={{
                    position: 'absolute',
                    right: '6px',
                    border: 'none',
                    background: 'transparent',
                    cursor: 'pointer',
                    color: '#94a3b8',
                    fontSize: '0.8rem',
                  }}
                  title="Clear search"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Speaker Filter Tabs */}
            <div className="transcript-filter-group">
              <button
                type="button"
                className={`transcript-filter-tab ${speakerFilter === 'all' ? 'active' : ''}`}
                onClick={() => setSpeakerFilter('all')}
              >
                All ({call.turns.length})
              </button>
              <button
                type="button"
                className={`transcript-filter-tab ${speakerFilter === 'assistant' ? 'active' : ''}`}
                onClick={() => setSpeakerFilter('assistant')}
              >
                🤖 Agent ({agentTurnCount})
              </button>
              <button
                type="button"
                className={`transcript-filter-tab ${speakerFilter === 'user' ? 'active' : ''}`}
                onClick={() => setSpeakerFilter('user')}
              >
                👤 Caller ({userTurnCount})
              </button>
            </div>

            {/* Auto-scroll toggle */}
            <button
              type="button"
              className={`transcript-btn-sm ${autoScroll ? 'active-toggle' : ''}`}
              onClick={() => setAutoScroll(!autoScroll)}
              title={autoScroll ? 'Disable auto-scroll during playback' : 'Enable auto-scroll to follow speaking turns'}
            >
              {autoScroll ? '✓ Auto-scroll' : 'Auto-scroll: Off'}
            </button>

            {/* Copy Transcript */}
            <button
              type="button"
              className="transcript-btn-sm"
              onClick={copyTranscript}
              title="Copy formatted dialogue to clipboard"
            >
              📋 Copy
            </button>

            {/* Export TXT */}
            <button
              type="button"
              className="transcript-btn-sm"
              onClick={downloadTranscript}
              title="Download transcript as text file"
            >
              ⬇ Export TXT
            </button>
          </div>
        </div>

        {/* Transcript Bubble Stream */}
        <div className="transcript" ref={transcriptContainerRef}>
          {call.turns.length === 0 && (
            <div className="empty" style={{ padding: '2rem 1rem' }}>
              No turns captured for this call.
            </div>
          )}

          {call.turns.length > 0 && filteredTurns.length === 0 && (
            <div className="empty" style={{ padding: '2rem 1rem' }}>
              No dialogue turns match "{searchQuery}".
            </div>
          )}

          {filteredTurns.map((t) => {
            const isActive = t.id === activeTurnId
            const offset = t.offset_s ?? 0
            return (
              <div
                key={t.id}
                ref={(el) => {
                  if (el) turnRefs.current.set(t.id, el)
                  else turnRefs.current.delete(t.id)
                }}
                className={`bubble ${t.role} ${isActive ? 'active-turn' : ''}`}
                onClick={() => seekToTurn(offset, t.id)}
                title="Click turn to jump audio here"
              >
                <div className="turn-header">
                  <div className="who">
                    {t.role === 'user' ? (
                      <span className="turn-role-pill user-pill">👤 Caller</span>
                    ) : (
                      <span className="turn-role-pill agent-pill">🤖 {call.agent_name}</span>
                    )}
                    {t.language && <span className="turn-lang-pill">{t.language.toUpperCase()}</span>}
                  </div>

                  <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                    <button
                      type="button"
                      className="turn-seek-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        seekToTurn(offset, t.id)
                      }}
                      title={`Jump audio to ${formatTime(offset)}`}
                    >
                      {isActive && isPlaying ? '⏸' : '▶'} {formatTime(offset)}
                    </button>
                    <button
                      type="button"
                      className="turn-seek-btn"
                      style={{ padding: '0.2rem 0.45rem', fontSize: '0.72rem' }}
                      onClick={(e) => speakSingleTurn(e, t.content, t.role, t.language)}
                      title="Speak this turn aloud"
                    >
                      🔊
                    </button>
                  </div>
                </div>

                <div className="turn-content">{renderHighlightedContent(t.content)}</div>
              </div>
            )
          })}
        </div>
      </section>
    </>
  )
}

