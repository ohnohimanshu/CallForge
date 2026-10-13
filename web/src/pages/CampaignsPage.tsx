import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Agent, type Campaign, type CampaignContact } from '../api'
import { useToast } from '../toast'

function renderCampaignStatusBadge(status: string) {
  switch (status) {
    case 'running':
      return (
        <span className="on-air-pill" style={{ background: '#ecfdf5', color: '#047857', borderColor: '#a7f3d0' }}>
          <span className="on-air-dot" style={{ background: '#10b981' }} />
          RUNNING
        </span>
      )
    case 'paused':
      return <span className="chip warn">⏸ PAUSED</span>
    case 'completed':
      return <span className="chip ok">✓ COMPLETED</span>
    default:
      return <span className="chip muted">⚪ DRAFT</span>
  }
}

function renderContactStatusBadge(status: string) {
  switch (status) {
    case 'dialing':
      return (
        <span className="on-air-pill">
          <span className="on-air-dot" />
          DIALING
        </span>
      )
    case 'completed':
      return <span className="chip ok">✓ Answered</span>
    case 'failed':
      return <span className="chip warn" style={{ background: '#fee2e2', color: '#b91c1c' }}>Failed / Busy</span>
    default:
      return <span className="chip muted">Pending</span>
  }
}

export function CampaignsPage() {
  const { show } = useToast()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [loading, setLoading] = useState(true)

  // Create form state
  const [name, setName] = useState('')
  const [agentId, setAgentId] = useState('')
  const [concurrency, setConcurrency] = useState(1)
  const [callerId, setCallerId] = useState('Outbound AI')
  const [greetingText, setGreetingText] = useState('')
  const [collectFields, setCollectFields] = useState('')
  const [csvText, setCsvText] = useState('')
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [creating, setCreating] = useState(false)

  const fetchCampaigns = () => {
    api
      .listCampaigns()
      .then(setCampaigns)
      .catch((e) => show(e.message, true))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchCampaigns()
    api.listAgents().then((a) => {
      setAgents(a)
      if (a.length > 0) setAgentId(a[0].id)
    }).catch(() => {})
  }, [show])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return show('Campaign name is required', true)
    if (!agentId) return show('Please select an agent', true)

    setCreating(true)
    try {
      // Parse direct CSV text if provided
      const parsedContacts: { phone: string; name?: string }[] = []
      if (csvText.trim()) {
        const lines = csvText.trim().split('\n')
        for (const line of lines) {
          const parts = line.split(',')
          if (parts[0] && parts[0].trim()) {
            parsedContacts.push({
              phone: parts[0].trim(),
              name: parts[1] ? parts[1].trim() : '',
            })
          }
        }
      }

      const camp = await api.createCampaign({
        name: name.trim(),
        agent_id: agentId,
        concurrency_limit: Number(concurrency),
        caller_id: callerId.trim(),
        greeting_text: greetingText.trim(),
        collect_fields: collectFields.trim(),
        contacts: parsedContacts,
      })

      // If CSV file was attached, upload it
      if (csvFile) {
        await api.uploadCampaignCsv(camp.id, csvFile)
      }

      show(`Campaign '${camp.name}' created!`)
      setIsCreateOpen(false)
      setName('')
      setGreetingText('')
      setCollectFields('')
      setCsvText('')
      setCsvFile(null)
      fetchCampaigns()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    } finally {
      setCreating(false)
    }
  }

  const handleToggleStatus = async (camp: Campaign) => {
    try {
      if (camp.status === 'running') {
        await api.pauseCampaign(camp.id)
        show(`Campaign '${camp.name}' paused`)
      } else {
        await api.startCampaign(camp.id)
        show(`Campaign '${camp.name}' started dialing`)
      }
      fetchCampaigns()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    }
  }

  // Aggregate stats
  const totalCampaigns = campaigns.length
  const activeCampaigns = campaigns.filter((c) => c.status === 'running').length
  const totalLeads = campaigns.reduce((acc, c) => acc + c.total_contacts, 0)
  const totalCompleted = campaigns.reduce((acc, c) => acc + c.completed_contacts, 0)
  const totalSuccessful = campaigns.reduce((acc, c) => acc + c.successful_contacts, 0)
  const overallConversion = totalCompleted > 0 ? Math.round((totalSuccessful / totalCompleted) * 100) : 0

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Outbound Campaigns</h1>
          <p>Automated Asterisk outbound batch dialer, contact CSV ingestion, and lead conversion tracker.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setIsCreateOpen(true)}>
          + Create Campaign
        </button>
      </div>

      {/* KPI Cards */}
      <div className="stat-row" style={{ marginBottom: '1.25rem' }}>
        <div className="stat">
          <div className="label">Total Campaigns</div>
          <div className="value">{totalCampaigns}</div>
        </div>
        <div className="stat">
          <div className="label">Active Dialing</div>
          <div className="value" style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            {activeCampaigns}
            {activeCampaigns > 0 && <span className="on-air-dot" />}
          </div>
        </div>
        <div className="stat">
          <div className="label">Leads Dialed</div>
          <div className="value">
            {totalCompleted} <span style={{ fontSize: '1rem', color: 'var(--muted)', fontWeight: 400 }}>/ {totalLeads}</span>
          </div>
        </div>
        <div className="stat">
          <div className="label">Lead Conversion</div>
          <div className="value" style={{ color: 'var(--ok)' }}>
            {overallConversion}%
          </div>
        </div>
      </div>

      {/* Campaigns Table */}
      <section className="panel panel-pad">
        {loading ? (
          <div className="empty">Loading campaigns…</div>
        ) : campaigns.length === 0 ? (
          <div className="empty">
            No outbound campaigns configured yet. Create a campaign to start auto-dialing contacts with an AI voice agent.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Agent</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Conversion</th>
                <th>Concurrency</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const total = c.total_contacts || 0
                const completed = c.completed_contacts || 0
                const pct = total > 0 ? Math.round((completed / total) * 100) : 0
                const conv = completed > 0 ? Math.round((c.successful_contacts / completed) * 100) : 0
                return (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/campaigns/${c.id}`} style={{ fontWeight: 700, color: 'var(--accent)' }}>
                        {c.name}
                      </Link>
                      <div style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
                        Created {new Date(c.created_at).toLocaleDateString()}
                      </div>
                    </td>
                    <td>{c.agent_name}</td>
                    <td>{renderCampaignStatusBadge(c.status)}</td>
                    <td style={{ minWidth: 160 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', marginBottom: '0.2rem' }}>
                        <span>{completed} / {total} dialed</span>
                        <span className="mono" style={{ fontWeight: 600 }}>{pct}%</span>
                      </div>
                      <div className="occupancy-track" style={{ height: 6, margin: 0 }}>
                        <div
                          className="occupancy-fill"
                          style={{ width: `${pct}%`, background: 'var(--accent)' }}
                        />
                      </div>
                    </td>
                    <td>
                      <span className="badge-disp badge-disp-lead" style={{ fontSize: '0.72rem' }}>
                        {conv}% ({c.successful_contacts})
                      </span>
                    </td>
                    <td className="mono">{c.concurrency_limit} lines</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                        <button
                          type="button"
                          className="btn btn-ghost-dark btn-sm"
                          onClick={() => handleToggleStatus(c)}
                          style={{ fontSize: '0.78rem', padding: '0.2rem 0.6rem' }}
                        >
                          {c.status === 'running' ? '⏸ Pause' : '▶ Dial'}
                        </button>
                        <Link
                          to={`/campaigns/${c.id}`}
                          className="btn btn-ghost-dark btn-sm"
                          style={{ fontSize: '0.78rem', padding: '0.2rem 0.6rem' }}
                        >
                          Details →
                        </Link>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* Create Campaign Modal */}
      {isCreateOpen && (
        <div className="simulator-backdrop" onClick={() => setIsCreateOpen(false)}>
          <div
            className="simulator-modal"
            style={{ maxWidth: 560 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sim-head">
              <h2>Create Outbound Campaign</h2>
              <button type="button" className="btn-close" onClick={() => setIsCreateOpen(false)}>
                ✕
              </button>
            </div>
            <form onSubmit={handleCreate} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <label className="field">
                <span>Campaign Name</span>
                <input
                  type="text"
                  placeholder="e.g. Q4 Inactive Customer Re-engagement"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </label>

              <div className="form-grid">
                <label className="field">
                  <span>Assigned Agent Line</span>
                  <select value={agentId} onChange={(e) => setAgentId(e.target.value)} required>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} (ext {a.extension})
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>Concurrent Channels</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Number(e.target.value))}
                  />
                </label>
              </div>

              <label className="field">
                <span>Caller ID Name</span>
                <input
                  type="text"
                  placeholder="e.g. Acme Support"
                  value={callerId}
                  onChange={(e) => setCallerId(e.target.value)}
                />
              </label>

              <label className="field">
                <span>Campaign-Specific Greeting</span>
                <textarea
                  rows={2}
                  placeholder="e.g. Hello {name}, this is Sarah calling from Apex Dental to confirm your appointment for tomorrow. Do you have a quick minute?"
                  value={greetingText}
                  onChange={(e) => setGreetingText(e.target.value)}
                  style={{ minHeight: 65 }}
                />
                <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
                  Spoken the instant the contact answers. Use <code>{'{name}'}</code> to dynamically insert the contact's name. (Leave blank to use agent's default greeting).
                </span>
              </label>

              <label className="field">
                <span>Details to Collect (comma-separated fields)</span>
                <input
                  type="text"
                  placeholder="e.g. appointment_date, preferred_time, notes"
                  value={collectFields}
                  onChange={(e) => setCollectFields(e.target.value)}
                />
                <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
                  Fields the AI should collect (e.g. <code>appointment_date, preferred_time, budget, reason</code>). These are extracted during the call, displayed in the table, and exported to CSV.
                </span>
              </label>

              <label className="field">
                <span>Upload Contacts CSV (Optional)</span>
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setCsvFile(e.target.files ? e.target.files[0] : null)}
                />
                <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
                  CSV columns supported: <code>phone, name</code> (or raw phone list)
                </span>
              </label>

              <label className="field">
                <span>Or Paste Contacts Directly (phone, name per line)</span>
                <textarea
                  placeholder={"+15551234567, Alice Smith\n+15557654321, Bob Jones\n1001, Test Softphone"}
                  rows={4}
                  value={csvText}
                  onChange={(e) => setCsvText(e.target.value)}
                  style={{ minHeight: 90 }}
                />
              </label>

              <div className="form-actions" style={{ marginTop: '0.5rem' }}>
                <button type="submit" className="btn btn-primary" disabled={creating}>
                  {creating ? 'Creating…' : 'Create Campaign'}
                </button>
                <button type="button" className="btn btn-ghost-dark" onClick={() => setIsCreateOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}

export function CampaignDetailPage() {
  const { id } = useParams()
  const { show } = useToast()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [contacts, setContacts] = useState<CampaignContact[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [isUploading, setIsUploading] = useState(false)
  const [moreText, setMoreText] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const fetchDetails = () => {
    if (!id) return
    api
      .getCampaign(id)
      .then(setCampaign)
      .catch((e) => show(e.message, true))

    api
      .listCampaignContacts(id, 200, 0, statusFilter === 'all' ? undefined : statusFilter)
      .then(setContacts)
      .catch((e) => show(e.message, true))
  }

  useEffect(() => {
    fetchDetails()
  }, [id, statusFilter, show])

  // Polling for live campaign progress
  useEffect(() => {
    if (!campaign || campaign.status !== 'running') return
    const interval = setInterval(fetchDetails, 2500)
    return () => clearInterval(interval)
  }, [campaign?.status, statusFilter])

  if (!campaign) return <div className="empty">Loading campaign details…</div>

  const handleToggle = async () => {
    try {
      if (campaign.status === 'running') {
        await api.pauseCampaign(campaign.id)
        show('Campaign paused')
      } else {
        await api.startCampaign(campaign.id)
        show('Campaign started dialing!')
      }
      fetchDetails()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    }
  }

  const handleReset = async () => {
    if (!window.confirm('Reset all contacts back to pending?')) return
    try {
      await api.resetCampaign(campaign.id)
      show('Campaign contacts reset to pending')
      fetchDetails()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    }
  }

  const handleUploadMore = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!moreText.trim()) return
    const lines = moreText.trim().split('\n')
    const list: { phone: string; name?: string }[] = []
    for (const l of lines) {
      const parts = l.split(',')
      if (parts[0] && parts[0].trim()) {
        list.push({ phone: parts[0].trim(), name: parts[1] ? parts[1].trim() : '' })
      }
    }
    try {
      const res = await api.addCampaignContacts(campaign.id, list)
      show(`Added ${res.added} contact(s)`)
      setMoreText('')
      setIsUploading(false)
      fetchDetails()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    }
  }

  const handleCsvFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await api.uploadCampaignCsv(campaign.id, file)
      show(`Imported ${res.added} contact(s) from CSV!`)
      fetchDetails()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      show(msg, true)
    }
  }

  const total = campaign.total_contacts || 0
  const completed = campaign.completed_contacts || 0
  const successful = campaign.successful_contacts || 0
  const failed = campaign.failed_contacts || 0
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  const convRate = completed > 0 ? Math.round((successful / completed) * 100) : 0

  return (
    <>
      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <h1>{campaign.name}</h1>
            {renderCampaignStatusBadge(campaign.status)}
          </div>
          <p>
            Agent: <strong>{campaign.agent_name}</strong> (ext {campaign.agent_extension}) · Caller ID: {campaign.caller_id} · Max Concurrency: {campaign.concurrency_limit}
          </p>
          {campaign.greeting_text && (
            <div style={{ marginTop: '0.45rem', padding: '0.45rem 0.75rem', background: 'rgba(255,176,0,0.06)', borderLeft: '3px solid var(--accent)', borderRadius: '4px', fontSize: '0.82rem' }}>
              <strong style={{ color: 'var(--accent)' }}>Campaign Greeting:</strong> "{campaign.greeting_text}"
            </div>
          )}
          {campaign.collect_fields && (
            <div style={{ marginTop: '0.45rem', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap', fontSize: '0.82rem' }}>
              <span style={{ color: 'var(--muted)', fontWeight: 600 }}>Target Details to Collect:</span>
              {campaign.collect_fields.split(',').map((f) => f.trim()).filter(Boolean).map((f) => (
                <span key={f} className="chip" style={{ fontSize: '0.74rem', fontWeight: 600, background: '#f1f5f9' }}>
                  📌 {f}
                </span>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
          <button
            type="button"
            className={campaign.status === 'running' ? 'btn btn-ghost-dark' : 'btn btn-primary'}
            onClick={handleToggle}
          >
            {campaign.status === 'running' ? '⏸ Pause Dialing' : '▶ Start Dialing'}
          </button>
          <a
            className="btn btn-ghost-dark"
            href={api.exportCampaignCsvUrl(campaign.id)}
            download
          >
            ⬇ Export CSV
          </a>
          <button type="button" className="btn btn-ghost-dark" onClick={handleReset} title="Reset contacts">
            ↺ Reset
          </button>
          <Link className="btn btn-ghost-dark" to="/campaigns">
            ← Campaigns
          </Link>
        </div>
      </div>

      {/* Progress & Stats Dashboard */}
      <div className="panel panel-pad" style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.45rem' }}>
          <span style={{ fontSize: '0.88rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--muted)' }}>
            Campaign Progress
          </span>
          <span className="mono" style={{ fontWeight: 700, fontSize: '0.96rem' }}>
            {completed} of {total} contacts dialed ({pct}%)
          </span>
        </div>
        <div className="occupancy-track" style={{ height: 10, marginBottom: '1.25rem' }}>
          <div className="occupancy-fill" style={{ width: `${pct}%`, background: 'var(--accent)' }} />
        </div>

        <div className="stat-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
          <div className="stat" style={{ padding: '0.75rem 0.9rem' }}>
            <div className="label">Total Leads</div>
            <div className="value" style={{ fontSize: '1.4rem' }}>{total}</div>
          </div>
          <div className="stat" style={{ padding: '0.75rem 0.9rem' }}>
            <div className="label">Answered / Done</div>
            <div className="value" style={{ fontSize: '1.4rem', color: 'var(--accent)' }}>{completed}</div>
          </div>
          <div className="stat" style={{ padding: '0.75rem 0.9rem' }}>
            <div className="label">Leads Captured</div>
            <div className="value" style={{ fontSize: '1.4rem', color: 'var(--ok)' }}>{successful}</div>
          </div>
          <div className="stat" style={{ padding: '0.75rem 0.9rem' }}>
            <div className="label">Failed / Busy</div>
            <div className="value" style={{ fontSize: '1.4rem', color: 'var(--danger)' }}>{failed}</div>
          </div>
          <div className="stat" style={{ padding: '0.75rem 0.9rem' }}>
            <div className="label">Conversion Rate</div>
            <div className="value" style={{ fontSize: '1.4rem', color: 'var(--ok)' }}>{convRate}%</div>
          </div>
        </div>
      </div>

      {/* Contacts List */}
      <section className="panel panel-pad">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.6rem' }}>
          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
            <span style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--muted)', marginRight: '0.4rem' }}>Filter:</span>
            {['all', 'pending', 'dialing', 'completed', 'failed'].map((f) => (
              <button
                key={f}
                type="button"
                className={`rate-chip ${statusFilter === f ? 'active' : ''}`}
                onClick={() => setStatusFilter(f)}
                style={{ textTransform: 'capitalize' }}
              >
                {f}
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              type="file"
              accept=".csv"
              ref={fileInputRef}
              style={{ display: 'none' }}
              onChange={handleCsvFileChange}
            />
            <button
              type="button"
              className="btn btn-ghost-dark btn-sm"
              onClick={() => fileInputRef.current?.click()}
            >
              📎 Import CSV File
            </button>
            <button
              type="button"
              className="btn btn-ghost-dark btn-sm"
              onClick={() => setIsUploading((v) => !v)}
            >
              + Paste Contacts
            </button>
          </div>
        </div>

        {isUploading && (
          <form onSubmit={handleUploadMore} style={{ background: '#f8fafc', border: '1px solid var(--line)', borderRadius: '8px', padding: '0.9rem', marginBottom: '1rem' }}>
            <div style={{ fontWeight: 600, fontSize: '0.84rem', marginBottom: '0.4rem' }}>
              Add Contacts (phone, name per line)
            </div>
            <textarea
              rows={3}
              placeholder="+15559876543, John Doe\n+15553334444, Jane Ray"
              value={moreText}
              onChange={(e) => setMoreText(e.target.value)}
              style={{ width: '100%', marginBottom: '0.5rem', background: '#111318', color: '#ffffff', border: '1px solid #374151', borderRadius: '8px', padding: '0.6rem' }}
            />
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="submit" className="btn btn-primary btn-sm">Add Leads</button>
              <button type="button" className="btn btn-ghost-dark btn-sm" onClick={() => setIsUploading(false)}>Cancel</button>
            </div>
          </form>
        )}

        {contacts.length === 0 ? (
          <div className="empty">No contacts matching the current filter.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Lead / Contact</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Disposition</th>
                <th>Collected Details</th>
                <th>Duration</th>
                <th>Attempts</th>
                <th>Call Link</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 600 }}>{c.name || '—'}</td>
                  <td className="mono">{c.phone}</td>
                  <td>{renderContactStatusBadge(c.status)}</td>
                  <td>
                    {c.disposition ? (
                      <span className={`badge-disp ${c.disposition === 'Lead Captured' ? 'badge-disp-lead' : 'badge-disp-info'}`}>
                        {c.disposition === 'Lead Captured' ? '🎯 Lead Captured' : c.disposition}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td style={{ minWidth: 200 }}>
                    {(() => {
                      let data: Record<string, string> = {}
                      if (c.collected_data_json) {
                        try {
                          data = JSON.parse(c.collected_data_json)
                        } catch {
                          data = {}
                        }
                      }
                      const keys = Object.keys(data)
                      if (keys.length === 0) {
                        return <span style={{ color: 'var(--muted)', fontSize: '0.76rem' }}>—</span>
                      }
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                          {keys.map((k) => (
                            <div key={k} style={{ fontSize: '0.74rem' }}>
                              <span style={{ color: 'var(--muted)', fontWeight: 600 }}>{k}:</span>{' '}
                              <span style={{ color: 'var(--text)', fontWeight: 500 }}>{String(data[k])}</span>
                            </div>
                          ))}
                        </div>
                      )
                    })()}
                  </td>
                  <td className="mono">{c.duration_s > 0 ? `${Math.round(c.duration_s)}s` : '—'}</td>
                  <td className="mono">{c.attempts}</td>
                  <td>
                    {c.call_id ? (
                      <Link className="btn btn-ghost-dark btn-sm" to={`/calls/${c.call_id}`}>
                        Transcript →
                      </Link>
                    ) : (
                      '—'
                    )}
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
