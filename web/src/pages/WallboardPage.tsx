import { useEffect, useState } from 'react'
import { api, type Agent, type WallboardStatus } from '../api'
import { SimulatorModal } from '../components/SimulatorModal'
import { useToast } from '../toast'

function formatDuration(secs: number): string {
  if (isNaN(secs) || secs < 0) return '00:00'
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

export function WallboardPage() {
  const { show } = useToast()
  const [wallboard, setWallboard] = useState<WallboardStatus | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentForSim, setSelectedAgentForSim] = useState<Agent | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())
  const [terminatingUuid, setTerminatingUuid] = useState<string | null>(null)

  const fetchWallboard = () => {
    api
      .getWallboard()
      .then((data) => {
        setWallboard(data)
        setLastUpdated(new Date())
      })
      .catch((e) => show(e.message, true))
  }

  // Initial load
  useEffect(() => {
    fetchWallboard()
    api.listAgents().then(setAgents).catch(() => {})
  }, [show])

  // Real-time polling
  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(fetchWallboard, 2000)
    return () => clearInterval(interval)
  }, [autoRefresh])

  // Smooth live duration tick
  useEffect(() => {
    const tick = setInterval(() => {
      setWallboard((prev) => {
        if (!prev || prev.active_calls.length === 0) return prev
        return {
          ...prev,
          active_calls: prev.active_calls.map((c) => ({
            ...c,
            duration_s: c.duration_s + 1,
          })),
        }
      })
    }, 1000)
    return () => clearInterval(tick)
  }, [])

  const handleHangup = async (callUuid: string) => {
    if (!window.confirm('Are you sure you want to disconnect this active call?')) return
    setTerminatingUuid(callUuid)
    try {
      await api.hangupLiveCall(callUuid)
      show('Call terminated by supervisor')
      fetchWallboard()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      show(msg, true)
    } finally {
      setTerminatingUuid(null)
    }
  }

  const system = wallboard?.system ?? {
    telephony_ready: false,
    runtime_ready: false,
    total_active_calls: 0,
    concurrent_capacity: 10,
    channel_occupancy_pct: 0,
  }

  const activeCalls = wallboard?.active_calls ?? []
  const lines = wallboard?.lines ?? []
  const sipTrunk = wallboard?.sip_trunk ?? {
    host: '127.0.0.1',
    port: 5060,
    protocol: 'SIP / UDP',
    reachable: false,
    codecs: ['ulaw', 'alaw', 'slin16'],
    configured_endpoints: ['1001', '1002', 'guest', 'anonymous'],
  }

  // Determine occupancy bar color
  const occPct = system.channel_occupancy_pct
  const occColor = occPct > 85 ? '#b42318' : occPct > 55 ? '#d97706' : '#0f766e'

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Live Call Wallboard</h1>
          <p>Real-time telephony operations, concurrent channel occupancy, active callers, and remote trunk supervisor.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
          <div className="live-pill-badge">
            <span className={`live-pulse-dot ${autoRefresh ? 'active' : ''}`} />
            {autoRefresh ? 'LIVE MONITORING' : 'PAUSED'}
          </div>
          <button
            type="button"
            className="btn btn-ghost-dark"
            onClick={() => setAutoRefresh((v) => !v)}
            title={autoRefresh ? 'Pause auto-refresh' : 'Resume live auto-refresh'}
          >
            {autoRefresh ? '⏸ Pause' : '▶ Live (2s)'}
          </button>
          <button
            type="button"
            className="btn btn-ghost-dark"
            onClick={fetchWallboard}
            title="Refresh now"
          >
            🔄 Refresh
          </button>
        </div>
      </div>

      {/* KPI Cards & Gauges */}
      <div className="stat-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', marginBottom: '1.25rem' }}>
        {/* Channel Occupancy Card */}
        <div className="stat" style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
          <div className="label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Channel Occupancy</span>
            <span className="mono" style={{ fontWeight: 700, color: occColor }}>
              {occPct}%
            </span>
          </div>
          <div className="value" style={{ fontSize: '1.65rem' }}>
            {system.total_active_calls} <span style={{ fontSize: '1rem', color: 'var(--muted)', fontWeight: 400 }}>/ {system.concurrent_capacity} lines</span>
          </div>
          <div className="occupancy-track">
            <div
              className="occupancy-fill"
              style={{ width: `${Math.min(100, Math.max(3, occPct))}%`, background: occColor }}
            />
          </div>
        </div>

        {/* Telephony SIP Gateway */}
        <div className="stat">
          <div className="label">Asterisk SIP Gateway</div>
          <div className="value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.25rem' }}>
            {system.telephony_ready ? (
              <span className="chip ok">● Online (:5060)</span>
            ) : (
              <span className="chip warn">○ Probing (:5060)</span>
            )}
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--muted)', marginTop: '0.25rem' }}>
            Transport: {sipTrunk.protocol} · Codecs: {sipTrunk.codecs.join(', ')}
          </div>
        </div>

        {/* AI Runtime Inference */}
        <div className="stat">
          <div className="label">AI Inference Engine</div>
          <div className="value" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.25rem' }}>
            {system.runtime_ready ? (
              <span className="chip ok">● Whisper + LLM Ready</span>
            ) : (
              <span className="chip warn">○ Initializing Engines</span>
            )}
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--muted)', marginTop: '0.25rem' }}>
            Resident Piper TTS Pools & Ollama shared runtime
          </div>
        </div>

        {/* Live AudioSocket Lines */}
        <div className="stat">
          <div className="label">Active Agent Lines</div>
          <div className="value" style={{ fontSize: '1.65rem' }}>
            {lines.filter((l) => l.listening).length} <span style={{ fontSize: '1rem', color: 'var(--muted)', fontWeight: 400 }}>listening</span>
          </div>
          <div style={{ fontSize: '0.74rem', color: 'var(--muted)', marginTop: '0.25rem' }}>
            Updated {lastUpdated.toLocaleTimeString()}
          </div>
        </div>
      </div>

      {/* Active Calls Table */}
      <section className="panel panel-pad" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.15rem', margin: 0 }}>Active Calls (Real-Time)</h2>
            <p style={{ margin: '0.2rem 0 0 0', color: 'var(--muted)', fontSize: '0.84rem' }}>
              Live callers currently bridged through Asterisk AudioSocket channels.
            </p>
          </div>
          {activeCalls.length > 0 && (
            <span className="on-air-pill">
              <span className="on-air-dot" />
              {activeCalls.length} CALL{activeCalls.length === 1 ? '' : 'S'} IN PROGRESS
            </span>
          )}
        </div>

        {activeCalls.length === 0 ? (
          <div className="idle-telephony-banner">
            <div className="radar-animation">
              <div className="radar-circle circle-1" />
              <div className="radar-circle circle-2" />
              <div className="radar-circle circle-3" />
              <span className="radar-center-icon">📡</span>
            </div>
            <h3>All Telephony Channels Idle</h3>
            <p>
              Agents are deployed and ready. Dial any agent extension from a SIP softphone or start a live in-browser test session.
            </p>
            {agents.length > 0 && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setSelectedAgentForSim(agents[0])}
                style={{ marginTop: '0.5rem' }}
              >
                🎙️ Simulate Test Call
              </button>
            )}
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Agent</th>
                <th>Caller ID</th>
                <th>Extension</th>
                <th>Port</th>
                <th>Duration</th>
                <th>Variant</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {activeCalls.map((c) => (
                <tr key={c.call_uuid} className="active-call-row">
                  <td>
                    <span className="on-air-pill">
                      <span className="on-air-dot" />
                      ON AIR
                    </span>
                  </td>
                  <td style={{ fontWeight: 600 }}>{c.agent_name}</td>
                  <td className="mono">{c.caller_id}</td>
                  <td className="mono">ext {c.extension}</td>
                  <td className="mono">:{c.port}</td>
                  <td className="mono" style={{ fontWeight: 700, color: 'var(--accent)' }}>
                    ⏱ {formatDuration(c.duration_s)}
                  </td>
                  <td>
                    <span className="chip ok mono">Variant {c.ab_variant}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-hangup"
                      disabled={terminatingUuid === c.call_uuid}
                      onClick={() => handleHangup(c.call_uuid)}
                      title="Instantly terminate call session"
                    >
                      {terminatingUuid === c.call_uuid ? 'Ending…' : '🛑 Disconnect'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Deployed Lines & Channel Allocation */}
      <div className="split-2">
        <section className="panel panel-pad">
          <h2 style={{ fontSize: '1.05rem', margin: '0 0 0.85rem 0' }}>Deployed Agent Lines</h2>
          {lines.length === 0 ? (
            <div className="empty">No agents deployed. Deploy an agent to assign an AudioSocket port.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {lines.map((l) => (
                <div key={l.agent_id} className="wallboard-line-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '0.96rem' }}>{l.agent_name}</div>
                      <div className="meta-row" style={{ marginTop: '0.25rem' }}>
                        <span className="chip ok mono">ext {l.extension}</span>
                        <span className="chip mono">port {l.port}</span>
                        <span className="chip muted">{l.language}</span>
                        {l.ab_testing && <span className="chip ok">A/B Split</span>}
                        {l.dialogue_policy && <span className="chip">Slots</span>}
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.35rem' }}>
                      <span className={`chip ${l.active_calls > 0 ? 'ok' : 'muted'}`}>
                        {l.active_calls} active call{l.active_calls === 1 ? '' : 's'}
                      </span>
                      {agents.find((a) => a.id === l.agent_id) && (
                        <button
                          type="button"
                          className="btn btn-ghost-dark btn-sm"
                          style={{ fontSize: '0.74rem', padding: '0.15rem 0.5rem' }}
                          onClick={() => {
                            const found = agents.find((a) => a.id === l.agent_id)
                            if (found) setSelectedAgentForSim(found)
                          }}
                        >
                          🎙️ Test
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* SIP Trunk & Dialplan Supervisor */}
        <section className="panel panel-pad">
          <h2 style={{ fontSize: '1.05rem', margin: '0 0 0.85rem 0' }}>SIP Trunk & Softphone Config</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.85rem' }}>
            <div style={{ background: 'rgba(17, 24, 39, 0.7)', border: '1px solid var(--line)', borderRadius: '10px', padding: '0.75rem 0.85rem' }}>
              <div style={{ fontWeight: 600, color: '#ffffff', marginBottom: '0.35rem' }}>
                🔑 Shared Guest Softphone Credentials
              </div>
              <div style={{ color: 'var(--muted)', lineHeight: 1.45 }}>
                Configure any SIP softphone (Linphone, Zoiper, MicroSIP) to connect directly:
              </div>
              <div style={{ marginTop: '0.4rem', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', background: '#09090b', color: '#facc15', padding: '0.4rem 0.6rem', borderRadius: '6px', border: '1px solid #374151' }}>
                Domain: <strong style={{ color: '#fff' }}>127.0.0.1:5060</strong> · User: <strong style={{ color: '#fff' }}>guest</strong> · Password: <strong style={{ color: '#fff' }}>guestpass123</strong>
              </div>
            </div>

            <div style={{ background: 'rgba(17, 24, 39, 0.7)', border: '1px solid var(--line)', borderRadius: '10px', padding: '0.75rem 0.85rem' }}>
              <div style={{ fontWeight: 600, color: '#ffffff', marginBottom: '0.35rem' }}>
                📞 Configured SIP Endpoints
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                {sipTrunk.configured_endpoints.map((ep) => (
                  <span key={ep} className="chip ok mono">
                    SIP/{ep}
                  </span>
                ))}
              </div>
            </div>

            <div style={{ background: '#f8fafc', border: '1px solid var(--line)', borderRadius: '8px', padding: '0.75rem 0.85rem' }}>
              <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '0.35rem' }}>
                ⚡ AudioSocket Inbound Routing
              </div>
              <div style={{ color: 'var(--muted)', lineHeight: 1.45 }}>
                Inbound calls on dialplan extensions are deframed at 8kHz 16-bit PCM and streamed via high-speed Unix AudioSocket TCP connections.
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* Simulator Modal for in-browser testing directly from Wallboard */}
      {selectedAgentForSim && (
        <SimulatorModal
          agent={selectedAgentForSim}
          onClose={() => setSelectedAgentForSim(null)}
        />
      )}
    </>
  )
}
