import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import {
  Check,
  Copy,
  ExternalLink,
  Globe,
  Loader2,
  Lock,
  Radio,
  RefreshCw,
  Server,
  Shield,
  Zap,
} from 'lucide-react'
import { api } from '../api'
import type { FreePbxGuide, FreePbxGuiStatus, FreePbxStatus } from '../api'
import { useToast } from '../toast'

export function TelephonyServerPage() {
  const { show } = useToast()
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [status, setStatus] = useState<FreePbxStatus | null>(null)
  const [guiStatus, setGuiStatus] = useState<FreePbxGuiStatus | null>(null)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    try {
      const [data, gui] = await Promise.all([
        api.getFreePbxStatus(),
        api.getFreePbxGuiStatus().catch(() => null),
      ])
      setStatus(data)
      if (gui) setGuiStatus(gui)
    } catch (err: any) {
      if (!silent) show(err.message || 'Failed to load FreePBX integration status', true)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [show])

  useEffect(() => {
    load()
    const t = setInterval(() => load(true), 15000)
    return () => clearInterval(t)
  }, [load])

  const handleCopy = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      show('Copied to clipboard', false)
      setTimeout(() => setCopiedKey(null), 1800)
    } catch {
      show('Copy failed', true)
    }
  }

  const handleRefreshDialplan = async () => {
    try {
      setRefreshing(true)
      await api.reloadTelephonyServer()
      await load(true)
      show('FreePBX dialplan refreshed', false)
    } catch (err: any) {
      show(err.message || 'Refresh failed', true)
    } finally {
      setRefreshing(false)
    }
  }

  const handleOpenTelephonyServer = () => {
    const targetUrl = guiStatus?.gui_url || 'http://127.0.0.1:8088/admin'
    window.open(targetUrl, '_blank', 'noopener,noreferrer')
  }

  if (loading && !status) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3rem', color: '#64748b' }}>
        <Loader2 size={18} className="animate-spin" />
        Loading FreePBX AudioSocket integration…
      </div>
    )
  }

  const agents: FreePbxGuide[] = status?.agents || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', maxWidth: 1100 }}>
      {/* Hero */}
      <section
        style={{
          borderRadius: 16,
          padding: '1.5rem 1.75rem',
          background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 55%, #312e81 100%)',
          color: '#f8fafc',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', opacity: 0.85 }}>
          <Server size={12} /> FREEPBX · METHOD 1 · DIRECT AUDIOSOCKET
        </div>
        <h1 style={{ margin: '0.55rem 0 0.4rem', fontSize: '1.55rem', fontWeight: 800, letterSpacing: '-0.02em' }}>
          Telephony Server Management
        </h1>
        <p style={{ margin: 0, maxWidth: 720, color: '#cbd5e1', lineHeight: 1.55, fontSize: '0.95rem' }}>
          All SIP extensions, trunks, queues, and calling server controls are managed inside the <strong>FreePBX GUI</strong>.
          CallForge connects directly over high-speed AudioSocket TCP as the neural voice engine.
        </p>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '1.15rem' }}>
          <StatChip label="Status" value={(status?.status || 'unknown').replace(/_/g, ' ')} />
          <StatChip label="AudioSocket host" value={status?.audiosocket_host || '—'} mono />
          <StatChip label="Live lines" value={String(status?.live_lines?.length ?? 0)} />
          <StatChip label="API Base" value={status?.api_base || '—'} mono />
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: '1.1rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={handleRefreshDialplan}
            disabled={refreshing}
            style={btnPrimary}
          >
            {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Refresh dialplan
          </button>
          <button
            type="button"
            onClick={() => status?.dialplan && handleCopy(status.dialplan, 'full')}
            style={btnGhost}
          >
            {copiedKey === 'full' ? <Check size={14} /> : <Copy size={14} />}
            Copy full dialplan
          </button>
        </div>
      </section>

      {/* Primary Telephony Server Button & Security Box */}
      <section
        style={{
          ...card,
          border: '1px solid #c7d2fe',
          background: 'linear-gradient(180deg, #f8faff 0%, #ffffff 100%)',
          boxShadow: '0 4px 12px rgba(99, 102, 241, 0.06)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1.25rem' }}>
          <div style={{ flex: '1 1 500px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Globe size={18} color="#4f46e5" />
              <h2 style={{ ...h2, fontSize: '1.15rem' }}>FreePBX Calling Server & Extension Console</h2>
            </div>
            <p style={{ margin: '0 0 10px', color: '#475569', fontSize: '0.9rem', lineHeight: 1.55 }}>
              Use the FreePBX GUI below to add, delete, and configure extensions, SIP trunks, inbound DIDs, and ring groups.
              Extension management and server controls are centralized here so only authenticated administrators can make changes.
            </p>

            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                background: '#f1f5f9',
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                padding: '0.4rem 0.75rem',
                fontSize: '0.8rem',
                color: '#334155',
              }}
            >
              <Lock size={13} color="#059669" />
              <span>
                <strong>Access Protection:</strong> Direct access by raw IP is restricted. Access and manage only via this authenticated CallForge console.
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
            <button
              type="button"
              onClick={handleOpenTelephonyServer}
              style={{
                ...btnPrimary,
                padding: '0.75rem 1.4rem',
                fontSize: '0.95rem',
                boxShadow: '0 4px 10px rgba(79, 70, 229, 0.25)',
              }}
            >
              <ExternalLink size={16} />
              Open Telephony Server (FreePBX GUI)
            </button>
            <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
              Target: <code>{guiStatus?.gui_url || 'http://127.0.0.1:8088/admin'}</code>
              {' · '}
              <span style={{ color: guiStatus?.online ? '#059669' : '#d97706', fontWeight: 600 }}>
                {guiStatus?.status_detail || 'Offline / Host not detected'}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Why Method 1 */}
      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Zap size={16} color="#4f46e5" />
          <h2 style={h2}>Why Direct AudioSocket (not SIP trunk)</h2>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>
                <th style={th}>Feature</th>
                <th style={th}>Method 1 · AudioSocket</th>
                <th style={th}>Method 2 · SIP trunk</th>
              </tr>
            </thead>
            <tbody>
              <CmpRow feature="Audio latency" a="Ultra-low (<5ms) raw PCM/TCP" b="+50–120ms SDP + RTP jitter" />
              <CmpRow feature="Barge-in" a="Instant — wipes 20ms buffer" b="Sluggish — 0.5–1.5s buffered RTP" />
              <CmpRow feature="Architecture" a="FreePBX → CallForge (1 hop)" b="FreePBX → SIP → Asterisk → AI" />
              <CmpRow feature="Firewall" a="1 TCP port per agent" b="5060 UDP + RTP 10000–20000" />
              <CmpRow feature="Setup" a="~6 lines in extensions_custom.conf" b="Trunks + routes on both PBXs" />
            </tbody>
          </table>
        </div>
      </section>

      {/* Steps */}
      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Shield size={16} color="#059669" />
          <h2 style={h2}>Setup on FreePBX</h2>
        </div>
        <ol style={{ margin: 0, paddingLeft: '1.2rem', color: '#334155', lineHeight: 1.7 }}>
          {(status?.steps || []).map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        {(status?.firewall || []).length > 0 && (
          <div style={{ marginTop: 14, padding: '0.85rem 1rem', background: '#f8fafc', borderRadius: 10, border: '1px solid #e2e8f0' }}>
            <div style={{ fontWeight: 700, fontSize: '0.8rem', color: '#475569', marginBottom: 6 }}>Firewall</div>
            <ul style={{ margin: 0, paddingLeft: '1.1rem', color: '#64748b', fontSize: '0.88rem' }}>
              {status!.firewall.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Per-agent cards */}
      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <Radio size={16} color="#4f46e5" />
          <h2 style={h2}>Deployed agents → FreePBX Custom Destinations</h2>
        </div>

        {agents.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: '0.92rem' }}>
            No deployed agents yet. Open <strong>Voice Agents</strong>, deploy an agent, then return here for the dialplan snippet.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {agents.map((guide) => (
              <div
                key={guide.agent_id}
                style={{
                  border: '1px solid #e2e8f0',
                  borderRadius: 12,
                  padding: '1rem 1.1rem',
                  background: '#fff',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: '1.05rem', color: '#0f172a' }}>{guide.agent_name}</div>
                    <div style={{ fontSize: '0.82rem', color: '#64748b', marginTop: 4 }}>
                      Ext <code>{guide.extension}</code>
                      {' · '}
                      AudioSocket <code>{guide.audiosocket_endpoint}</code>
                      {' · '}
                      Destination <code>{guide.custom_destination}</code>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleCopy(guide.dialplan_snippet, guide.agent_id)}
                    style={btnLight}
                  >
                    {copiedKey === guide.agent_id ? <Check size={14} /> : <Copy size={14} />}
                    Copy dialplan
                  </button>
                </div>
                <pre
                  style={{
                    marginTop: 12,
                    marginBottom: 0,
                    padding: '0.85rem 1rem',
                    background: '#0f172a',
                    color: '#e2e8f0',
                    borderRadius: 10,
                    fontSize: '0.72rem',
                    lineHeight: 1.45,
                    overflowX: 'auto',
                    maxHeight: 220,
                  }}
                >
                  {guide.dialplan_snippet}
                </pre>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Full dialplan file path */}
      {status?.dialplan_file && (
        <section style={{ ...card, display: 'flex', alignItems: 'center', gap: 10, color: '#475569', fontSize: '0.88rem' }}>
          <ExternalLink size={15} />
          Also written to disk: <code>{status.dialplan_file}</code>
        </section>
      )}
    </div>
  )
}

function StatChip({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.08)',
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: 10,
        padding: '0.55rem 0.8rem',
        minWidth: 120,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', opacity: 0.7 }}>{label.toUpperCase()}</div>
      <div style={{ marginTop: 2, fontWeight: 700, fontFamily: mono ? 'ui-monospace, monospace' : undefined, fontSize: mono ? '0.82rem' : '0.95rem' }}>
        {value}
      </div>
    </div>
  )
}

function CmpRow({ feature, a, b }: { feature: string; a: string; b: string }) {
  return (
    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
      <td style={{ ...td, fontWeight: 600, color: '#334155' }}>{feature}</td>
      <td style={{ ...td, color: '#059669' }}>{a}</td>
      <td style={{ ...td, color: '#94a3b8' }}>{b}</td>
    </tr>
  )
}

const card: CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 14,
  padding: '1.15rem 1.25rem',
}

const h2: CSSProperties = {
  margin: 0,
  fontSize: '0.98rem',
  fontWeight: 800,
  color: '#0f172a',
}

const th: CSSProperties = { padding: '0.45rem 0.5rem', fontWeight: 600 }
const td: CSSProperties = { padding: '0.55rem 0.5rem', verticalAlign: 'top' }

const btnPrimary: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  border: 'none',
  borderRadius: 10,
  padding: '0.55rem 0.9rem',
  background: '#4f46e5',
  color: '#fff',
  fontWeight: 700,
  fontSize: '0.85rem',
  cursor: 'pointer',
}

const btnGhost: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  border: '1px solid rgba(255,255,255,0.25)',
  borderRadius: 10,
  padding: '0.55rem 0.9rem',
  background: 'rgba(255,255,255,0.08)',
  color: '#f8fafc',
  fontWeight: 650,
  fontSize: '0.85rem',
  cursor: 'pointer',
}

const btnLight: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  border: '1px solid #e2e8f0',
  borderRadius: 10,
  padding: '0.5rem 0.85rem',
  background: '#f8fafc',
  color: '#334155',
  fontWeight: 650,
  fontSize: '0.85rem',
  cursor: 'pointer',
}
