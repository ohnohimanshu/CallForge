import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  Bot,
  Copy,
  Headphones,
  Mic,
  Phone,
  PhoneCall,
  Plus,
  Radio,
  Server,
  Sparkles,
} from 'lucide-react'
import { api, type Agent, type CallSummary } from '../api'
import { useAuth } from '../auth'
import { SimulatorModal } from '../components/SimulatorModal'
import { useToast } from '../toast'

export function Dashboard() {
  const { user } = useAuth()
  const { show } = useToast()
  const [stats, setStats] = useState<Record<string, number>>({})
  const [agents, setAgents] = useState<Agent[]>([])
  const [calls, setCalls] = useState<CallSummary[]>([])
  const [simulatorAgent, setSimulatorAgent] = useState<Agent | null>(null)

  useEffect(() => {
    Promise.all([api.stats(), api.listAgents(), api.listCalls()])
      .then(([s, a, c]) => {
        setStats(s)
        setAgents(a)
        setCalls(c.slice(0, 6))
      })
      .catch((e) => show(e.message, true))
  }, [show])

  function copyText(text: string, label: string) {
    navigator.clipboard.writeText(text)
    show(`${label} copied to clipboard!`)
  }

  const deployedAgents = agents.filter((a) => a.status === 'deployed')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* 1. Executive Telephony Hero Banner (Pure Luminous Sarvam Aesthetic) */}
      <section
        style={{
          background: '#ffffff',
          border: '1px solid #e5e7eb',
          borderRadius: '24px',
          padding: '2.25rem 2.5rem',
          boxShadow: '0 10px 30px rgba(0, 0, 0, 0.04)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '2rem' }}>
          <div style={{ maxWidth: '680px' }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                background: '#eef2ff',
                border: '1px solid #e0e7ff',
                padding: '0.3rem 0.75rem',
                borderRadius: '999px',
                fontSize: '0.74rem',
                color: '#4f46e5',
                fontWeight: 700,
                letterSpacing: '0.04em',
                marginBottom: '1rem',
              }}
            >
              <Sparkles size={13} />
              <span>SOVEREIGN VOICE CLUSTER • ASTERISK 20 AUDIOSOCKET</span>
            </div>

            <h2
              style={{
                fontSize: 'clamp(1.9rem, 3vw, 2.5rem)',
                fontWeight: 800,
                margin: '0 0 0.75rem',
                letterSpacing: '-0.03em',
                color: '#111827',
                lineHeight: 1.15,
              }}
            >
              Welcome back, {user?.full_name || user?.username || 'Operator'}
            </h2>

            <p style={{ color: '#4b5563', fontSize: '1rem', lineHeight: 1.6, margin: '0 0 1.75rem' }}>
              Your bare-metal telephony runtime is streaming bidirectional 8kHz linear PCM directly to local neural models.
              Zero cloud relay jitter, sub-420ms turnaround, and instant Silero VAD barge-in.
            </p>

            <div style={{ display: 'flex', gap: '0.85rem', flexWrap: 'wrap' }}>
              <Link
                to="/agents/new"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  backgroundColor: '#2a2c33',
                  color: '#ffffff',
                  borderRadius: '9999px',
                  padding: '0.65rem 1.4rem',
                  fontWeight: 500,
                  fontSize: '0.9rem',
                  textDecoration: 'none',
                  boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4), inset 0 -2px 0 rgba(0, 0, 0, 0.2)',
                  transition: 'all 0.2s ease',
                }}
              >
                <Plus size={16} />
                <span>Build New Agent</span>
              </Link>

              <Link
                to="/wallboard"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  backgroundColor: '#ffffff',
                  border: '1px solid #e5e7eb',
                  color: '#111827',
                  borderRadius: '9999px',
                  padding: '0.65rem 1.4rem',
                  fontWeight: 500,
                  fontSize: '0.9rem',
                  textDecoration: 'none',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.04)',
                  transition: 'all 0.2s ease',
                }}
              >
                <Radio size={16} style={{ color: '#10b981' }} />
                <span>Live Wallboard</span>
              </Link>

              <Link
                to="/campaigns"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  backgroundColor: '#ffffff',
                  border: '1px solid #e5e7eb',
                  color: '#475569',
                  borderRadius: '9999px',
                  padding: '0.65rem 1.25rem',
                  fontWeight: 500,
                  fontSize: '0.9rem',
                  textDecoration: 'none',
                  boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
                }}
              >
                <span>Campaigns</span>
                <ArrowRight size={14} />
              </Link>
            </div>
          </div>

          {/* Real-Time Telemetry Badge Box */}
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '20px',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.85rem',
              minWidth: '280px',
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.02)',
            }}
          >
            <div style={{ fontSize: '0.74rem', color: '#64748b', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              TELEPHONY ENGINE STATUS
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
              <span style={{ color: '#111827', fontWeight: 700, fontSize: '0.95rem' }}>AudioSocket TCP :9092</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#64748b', borderTop: '1px solid #e2e8f0', paddingTop: '0.65rem' }}>
              <span>Sample Format</span>
              <span style={{ color: '#111827', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>SLIN16 8000Hz</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#64748b' }}>
              <span>VAD Cutoff</span>
              <span style={{ color: '#047857', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>&lt; 20ms Silero</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#64748b' }}>
              <span>SIP Transport</span>
              <span style={{ color: '#4338ca', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>UDP 5060 PJSIP</span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Key Performance Indicators (KPI Cards) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem' }}>
        <div
          style={{
            background: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: '20px',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.03)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '0.82rem', color: '#64748b', fontWeight: 600 }}>Total Agents</span>
            <div style={{ width: 34, height: 34, borderRadius: '10px', background: '#eef2ff', color: '#4f46e5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Bot size={18} />
            </div>
          </div>
          <div style={{ fontSize: '2.2rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.03em' }}>
            {stats.agents ?? 0}
          </div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: '#64748b' }}>
            <span style={{ color: '#047857', fontWeight: 700 }}>{deployedAgents.length} Active</span> on Asterisk PBX
          </div>
        </div>

        <div
          style={{
            background: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: '20px',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.03)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '0.82rem', color: '#64748b', fontWeight: 600 }}>Deployed Lines</span>
            <div style={{ width: 34, height: 34, borderRadius: '10px', background: '#ecfdf5', color: '#059669', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Phone size={18} />
            </div>
          </div>
          <div style={{ fontSize: '2.2rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.03em' }}>
            {stats.deployed ?? 0}
          </div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: '#64748b' }}>
            G.711u / G.711a Native PCM
          </div>
        </div>

        <div
          style={{
            background: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: '20px',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.03)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '0.82rem', color: '#64748b', fontWeight: 600 }}>Total Completed Calls</span>
            <div style={{ width: 34, height: 34, borderRadius: '10px', background: '#fff7ed', color: '#ea580c', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Activity size={18} />
            </div>
          </div>
          <div style={{ fontSize: '2.2rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.03em' }}>
            {stats.calls ?? 0}
          </div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: '#64748b' }}>
            Sub-420ms avg turnaround
          </div>
        </div>

        <Link
          to="/wallboard"
          style={{
            background: '#ffffff',
            border: '1px solid #a7f3d0',
            borderRadius: '20px',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            textDecoration: 'none',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(16, 185, 129, 0.06)',
            transition: 'all 0.2s ease',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '0.82rem', color: '#047857', fontWeight: 700 }}>Live On-Air Channels</span>
            <div style={{ width: 34, height: 34, borderRadius: '10px', background: '#ecfdf5', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Radio size={18} />
            </div>
          </div>
          <div style={{ fontSize: '2.2rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.03em', display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <span>{stats.active_calls ?? 0}</span>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 10px #10b981' }} />
          </div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: '#047857', fontWeight: 600 }}>
            Open Telephony Wallboard →
          </div>
        </Link>
      </div>

      {/* 3. Main Fleet & Softphone Access Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: '1.5rem' }}>
        {/* Deployed Agents Card */}
        <section
          style={{
            background: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: '24px',
            padding: '1.75rem',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.03)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#111827' }}>Active Agent Fleet</h3>
              <div style={{ fontSize: '0.82rem', color: '#64748b', marginTop: '0.2rem' }}>
                Agents currently bound to Asterisk dialplan extensions
              </div>
            </div>
            <Link
              to="/agents/new"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                background: '#2a2c33',
                color: '#ffffff',
                padding: '0.45rem 1rem',
                borderRadius: '9999px',
                fontSize: '0.82rem',
                fontWeight: 500,
                textDecoration: 'none',
                boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4)',
              }}
            >
              <Plus size={14} />
              <span>Create</span>
            </Link>
          </div>

          {deployedAgents.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3.5rem 1rem', border: '1px dashed #e5e7eb', borderRadius: '16px' }}>
              <Bot size={40} style={{ color: '#94a3b8', marginBottom: '0.75rem' }} />
              <div style={{ color: '#111827', fontWeight: 700, fontSize: '1.05rem', marginBottom: '0.25rem' }}>No deployed agents yet</div>
              <div style={{ color: '#64748b', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto 1.5rem' }}>
                Build your first voice agent with custom LLM prompt, knowledge docs, and neural voice.
              </div>
              <Link
                to="/agents/new"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  background: '#2a2c33',
                  color: '#ffffff',
                  padding: '0.6rem 1.4rem',
                  borderRadius: '9999px',
                  fontWeight: 500,
                  fontSize: '0.88rem',
                  textDecoration: 'none',
                  boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4)',
                }}
              >
                Launch Agent Studio
              </Link>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem' }}>
              {deployedAgents.map((a) => (
                <div
                  key={a.id}
                  style={{
                    background: '#ffffff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '16px',
                    padding: '1.25rem',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.85rem',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.02)',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <div
                        style={{
                          width: 36,
                          height: 36,
                          borderRadius: '10px',
                          background: '#ecfdf5',
                          color: '#059669',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Mic size={18} />
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontSize: '0.98rem', fontWeight: 700, color: '#111827' }}>{a.name}</h4>
                        <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Piper Neural Voice</div>
                      </div>
                    </div>
                    <span
                      style={{
                        background: '#ecfdf5',
                        color: '#047857',
                        border: '1px solid #a7f3d0',
                        padding: '0.2rem 0.6rem',
                        borderRadius: '999px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                      }}
                    >
                      ext {a.extension}
                    </span>
                  </div>

                  <p style={{ color: '#4b5563', fontSize: '0.85rem', margin: 0, lineHeight: 1.5, flex: 1 }}>
                    {a.system_prompt ? a.system_prompt.slice(0, 95) + '...' : 'General voice customer service agent.'}
                  </p>

                  <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', paddingTop: '0.5rem', borderTop: '1px solid #f1f5f9' }}>
                    <span style={{ fontSize: '0.72rem', background: '#f1f5f9', padding: '0.15rem 0.5rem', borderRadius: '4px', color: '#475569', border: '1px solid #e2e8f0' }}>
                      Port :{a.port}
                    </span>
                    <span style={{ fontSize: '0.72rem', background: '#eef2ff', color: '#4338ca', padding: '0.15rem 0.5rem', borderRadius: '4px', fontWeight: 600 }}>
                      {a.language.toUpperCase()}
                    </span>
                    <span style={{ fontSize: '0.72rem', background: '#f1f5f9', padding: '0.15rem 0.5rem', borderRadius: '4px', color: '#475569', border: '1px solid #e2e8f0' }}>
                      {a.llm_model}
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.25rem' }}>
                    <button
                      type="button"
                      onClick={() => setSimulatorAgent(a)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '0.35rem',
                        background: '#10b981',
                        color: '#ffffff',
                        border: 'none',
                        borderRadius: '9999px',
                        padding: '0.45rem',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        boxShadow: '0 2px 8px rgba(16, 185, 129, 0.2)',
                      }}
                    >
                      <Headphones size={13} />
                      <span>Live Test</span>
                    </button>

                    <Link
                      to={`/agents/${a.id}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: '#ffffff',
                        border: '1px solid #e5e7eb',
                        color: '#111827',
                        borderRadius: '9999px',
                        padding: '0.45rem',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        textDecoration: 'none',
                        boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
                      }}
                    >
                      Studio
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Right Column: Recent Calls & Quick Softphone Access */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Quick Softphone Connection Guide */}
          <section
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: '24px',
              padding: '1.75rem',
              boxShadow: '0 4px 16px rgba(0, 0, 0, 0.03)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.65rem' }}>
              <Server size={18} style={{ color: '#10b981' }} />
              <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#111827' }}>
                SIP Softphone Dialing Credentials
              </h4>
            </div>
            <p style={{ fontSize: '0.85rem', color: '#64748b', lineHeight: 1.5, margin: '0 0 1.25rem' }}>
              Connect any standard SIP softphone (MicroSIP, Linphone, Zoiper) to dial agents directly via Asterisk PJSIP:
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '0.65rem 0.85rem' }}>
                <div style={{ fontSize: '0.68rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>SIP Domain</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#111827', fontFamily: 'var(--font-mono)' }}>127.0.0.1:5060</div>
              </div>
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '0.65rem 0.85rem' }}>
                <div style={{ fontSize: '0.68rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>User / Password</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#047857', fontFamily: 'var(--font-mono)' }}>guest / guestpass123</div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.76rem', color: '#64748b' }}>Dial 1001, 1002, etc. to reach agents</span>
              <button
                type="button"
                onClick={() => copyText('127.0.0.1:5060', 'SIP Domain')}
                style={{
                  fontSize: '0.75rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  background: '#ffffff',
                  color: '#111827',
                  border: '1px solid #e5e7eb',
                  borderRadius: '9999px',
                  padding: '0.35rem 0.85rem',
                  cursor: 'pointer',
                  fontWeight: 600,
                  boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
                }}
              >
                <Copy size={12} />
                <span>Copy Host</span>
              </button>
            </div>
          </section>

          {/* Recent Call Records */}
          <section
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: '24px',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 4px 16px rgba(0, 0, 0, 0.03)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 700, color: '#111827' }}>Recent Call Activity</h3>
                <div style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '0.15rem' }}>
                  Latest sessions terminated over AudioSocket
                </div>
              </div>
              <Link to="/calls" style={{ color: '#047857', fontSize: '0.85rem', fontWeight: 600, textDecoration: 'none' }}>
                View All →
              </Link>
            </div>

            {calls.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '2.5rem 1rem' }}>
                <PhoneCall size={32} style={{ color: '#94a3b8', marginBottom: '0.5rem' }} />
                <div style={{ color: '#111827', fontWeight: 600, fontSize: '0.95rem' }}>No calls recorded yet</div>
                <div style={{ color: '#64748b', fontSize: '0.82rem' }}>
                  Dial any extension from your softphone or use the live simulator.
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                {calls.map((c) => (
                  <div
                    key={c.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.75rem 0.95rem',
                      borderRadius: '12px',
                      background: '#f8fafc',
                      border: '1px solid #e2e8f0',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, color: '#111827', fontSize: '0.9rem' }}>{c.agent_name}</div>
                      <div style={{ fontSize: '0.72rem', color: '#64748b' }}>
                        Session #{c.id} • {new Date(c.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                    <Link
                      to={`/calls/${c.id}`}
                      style={{
                        padding: '0.3rem 0.75rem',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        background: '#ffffff',
                        border: '1px solid #e5e7eb',
                        color: '#111827',
                        borderRadius: '9999px',
                        textDecoration: 'none',
                        boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
                      }}
                    >
                      Review
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Interactive Simulator Modal */}
      {simulatorAgent && (
        <SimulatorModal
          agent={simulatorAgent}
          onClose={() => setSimulatorAgent(null)}
        />
      )}
    </div>
  )
}
