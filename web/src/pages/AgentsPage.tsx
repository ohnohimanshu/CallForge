import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Agent } from '../api'
import { SimulatorModal } from '../components/SimulatorModal'
import { useToast } from '../toast'

export function AgentsPage() {
  const { show } = useToast()
  const [agents, setAgents] = useState<Agent[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [testingAgent, setTestingAgent] = useState<Agent | null>(null)

  const load = () =>
    api
      .listAgents()
      .then(setAgents)
      .catch((e) => show(e.message, true))

  useEffect(() => {
    load()
  }, [])

  async function deploy(id: string) {
    setBusy(id)
    try {
      const res = await api.deployAgent(id)
      show(res.dial_hint || `Deployed on extension ${res.extension}`)
      await load()
    } catch (e) {
      show((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }

  async function undeploy(id: string) {
    setBusy(id)
    try {
      await api.undeployAgent(id)
      show('Agent stopped')
      await load()
    } catch (e) {
      show((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }

  async function remove(id: string) {
    if (!confirm('Delete this agent permanently?')) return
    setBusy(id)
    try {
      await api.deleteAgent(id)
      show('Agent deleted')
      await load()
    } catch (e) {
      show((e as Error).message, true)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agents</h1>
          <p>Your voice fleet. Deploy to open an AudioSocket line and dialplan extension.</p>
        </div>
        <Link className="btn btn-primary" to="/agents/new">
          New agent
        </Link>
      </div>

      {agents.length === 0 ? (
        <div className="panel panel-pad empty">No agents yet. Create your first one.</div>
      ) : (
        <div className="grid-agents">
          {agents.map((a) => (
            <article key={a.id} className="agent-card">
              <div className="meta-row">
                <span className={`chip ${a.status === 'deployed' ? 'ok' : 'warn'}`}>{a.status}</span>
                <span className="chip">ext {a.extension}</span>
                {a.phone_number && (
                  <span className="chip ok" style={{ fontWeight: 600 }} title="Direct Customer Line">
                    📞 {a.phone_number}
                  </span>
                )}
                {a.port != null && <span className="chip muted">port {a.port}</span>}
              </div>
              <h3>{a.name}</h3>
              <p className="desc">{a.description || 'No description'}</p>
              <div className="meta-row">
                <span className="chip muted">{a.language}</span>
                <span className="chip muted">{a.llm_model.split(':')[0]}</span>
              </div>
              <div className="card-actions">
                <button
                  type="button"
                  className="btn btn-ghost-dark btn-sm"
                  onClick={() => setTestingAgent(a)}
                  title="Test agent in browser"
                >
                  🎙️ Test
                </button>
                <Link className="btn btn-ghost-dark btn-sm" to={`/agents/${a.id}`}>
                  Edit
                </Link>
                {a.status === 'deployed' ? (
                  <button
                    className="btn btn-ghost-dark btn-sm"
                    disabled={busy === a.id}
                    onClick={() => undeploy(a.id)}
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={busy === a.id}
                    onClick={() => deploy(a.id)}
                  >
                    Deploy
                  </button>
                )}
                <button className="btn btn-danger btn-sm" disabled={busy === a.id} onClick={() => remove(a.id)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {testingAgent && (
        <SimulatorModal agent={testingAgent} onClose={() => setTestingAgent(null)} />
      )}
    </>
  )
}
