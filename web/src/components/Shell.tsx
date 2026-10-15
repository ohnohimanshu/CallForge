import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  ArrowLeft,
  Bot,
  ChevronRight,
  History,
  LogOut,
  Megaphone,
  Menu,
  PhoneCall,
  Plus,
  PlusCircle,
  Radio,
  Server,
  X,
} from 'lucide-react'
import { useAuth } from '../auth'
import { AuthModal } from './AuthModal'

export function Shell() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  const getPageInfo = (pathname: string) => {
    if (pathname.startsWith('/overview')) return { title: 'Fleet Overview', subtitle: 'Real-time telemetry and deployed agent operations' }
    if (pathname.startsWith('/wallboard')) return { title: 'Live Wallboard', subtitle: 'Active audio streams, sentiment radar, and call metrics' }
    if (pathname.startsWith('/telephony')) return { title: 'FreePBX Integration', subtitle: 'Method 1 Direct AudioSocket — ultra-low latency AI voice bridge' }
    if (pathname.startsWith('/campaigns')) return { title: 'Outbound Campaigns', subtitle: 'Automated dialing schedules and lead pipeline' }
    if (pathname.startsWith('/agents/new')) return { title: 'Agent Studio', subtitle: 'Configure LLM reasoning, voice models, and PBX extensions' }
    if (pathname.startsWith('/agents')) return { title: 'Voice Agents', subtitle: 'Fleet directory, dialplans, and knowledge base routing' }
    if (pathname.startsWith('/calls')) return { title: 'Call History', subtitle: 'Recordings, transcript analysis, and latency waterfall' }
    return { title: 'Console', subtitle: 'Enterprise Telephony Runtime' }
  }

  const pageInfo = getPageInfo(location.pathname)

  return (
    <div className="app-shell">
      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(17, 24, 39, 0.4)',
            backdropFilter: 'blur(8px)',
            zIndex: 45,
          }}
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Modern Developer Sidebar (Clean Sarvam AI Aesthetic) */}
      <aside
        className="sidebar"
        style={{
          transform: mobileOpen ? 'translateX(0)' : undefined,
          background: '#ffffff',
          borderRight: '1px solid #e5e7eb',
        }}
      >
        {/* Brand Header */}
        <div className="brand" style={{ padding: '0.25rem 0' }}>
          <Link
            to="/"
            style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', textDecoration: 'none' }}
            onClick={() => setMobileOpen(false)}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '8px',
                background: '#111827',
                color: '#ffffff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 900,
                fontSize: '0.88rem',
                letterSpacing: '-0.04em',
                boxShadow: '0 2px 6px rgba(0, 0, 0, 0.12)',
              }}
            >
              CF
            </div>
            <div className="brand-info">
              <div className="brand-mark" style={{ fontSize: '1.15rem', color: '#111827', fontWeight: 700 }}>
                Call<span>Forge</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <span style={{ fontSize: '0.7rem', color: '#64748b' }}>Voice OS</span>
                <span
                  style={{
                    fontSize: '0.62rem',
                    background: '#eef2ff',
                    color: '#4f46e5',
                    padding: '0.05rem 0.35rem',
                    borderRadius: '4px',
                    fontWeight: 700,
                    border: '1px solid #e0e7ff',
                  }}
                >
                  SOVEREIGN
                </span>
              </div>
            </div>
          </Link>
        </div>

        {/* User Account / Operator Pill */}
        <div
          style={{
            background: '#f8fafc',
            border: '1px solid #e5e7eb',
            borderRadius: '14px',
            padding: '0.75rem 0.85rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.5rem',
          }}
        >
          {user ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', overflow: 'hidden' }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: '50%',
                    background: '#111827',
                    color: '#ffffff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: '0.85rem',
                    flexShrink: 0,
                  }}
                >
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <div style={{ overflow: 'hidden' }}>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: '0.82rem',
                      color: '#111827',
                      whiteSpace: 'nowrap',
                      textOverflow: 'ellipsis',
                      overflow: 'hidden',
                    }}
                  >
                    {user.full_name || user.username}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: '#64748b' }}>@{user.username}</div>
                </div>
              </div>
              <button
                type="button"
                onClick={logout}
                title="Sign out"
                style={{
                  background: '#fee2e2',
                  border: '1px solid #fecaca',
                  color: '#dc2626',
                  borderRadius: '6px',
                  padding: '0.3rem 0.55rem',
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  transition: 'all 0.15s ease',
                }}
              >
                <LogOut size={12} />
                Exit
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              style={{ width: '100%', borderRadius: '9999px', padding: '0.55rem' }}
              onClick={() => setAuthModalOpen(true)}
            >
              Sign In / Register
            </button>
          )}
        </div>

        {/* Quick Action Button: Create Agent */}
        <Link
          to="/agents/new"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.5rem',
            background: '#2a2c33',
            color: '#ffffff',
            borderRadius: '9999px',
            padding: '0.65rem 1rem',
            fontSize: '0.85rem',
            fontWeight: 500,
            textDecoration: 'none',
            boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4), inset 0 -2px 0 rgba(0, 0, 0, 0.2)',
            transition: 'all 0.15s ease',
          }}
        >
          <Plus size={15} />
          <span>Build Voice Agent</span>
        </Link>

        {/* Navigation Sections */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', overflowY: 'auto' }}>
          <div>
            <div
              style={{
                fontSize: '0.68rem',
                fontWeight: 700,
                letterSpacing: '0.08em',
                color: '#94a3b8',
                textTransform: 'uppercase',
                padding: '0 0.75rem',
                marginBottom: '0.4rem',
              }}
            >
              Fleet Operations
            </div>
            <nav className="nav">
              <NavLink to="/overview" end onClick={() => setMobileOpen(false)}>
                <Activity size={17} />
                <span>Overview</span>
              </NavLink>

              <NavLink
                to="/wallboard"
                onClick={() => setMobileOpen(false)}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <Radio size={17} />
                  <span>Live Wallboard</span>
                </div>
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: '#10b981',
                    boxShadow: '0 0 8px #10b981',
                    display: 'inline-block',
                  }}
                />
              </NavLink>

              <NavLink to="/campaigns" onClick={() => setMobileOpen(false)}>
                <Megaphone size={17} />
                <span>Campaigns</span>
              </NavLink>
            </nav>
          </div>

          <div>
            <div
              style={{
                fontSize: '0.68rem',
                fontWeight: 700,
                letterSpacing: '0.08em',
                color: '#94a3b8',
                textTransform: 'uppercase',
                padding: '0 0.75rem',
                marginBottom: '0.4rem',
              }}
            >
              Telephony Studio
            </div>
            <nav className="nav">
              <NavLink to="/telephony" onClick={() => setMobileOpen(false)}>
                <PhoneCall size={17} />
                <span>FreePBX / AudioSocket</span>
              </NavLink>

              <NavLink to="/agents" onClick={() => setMobileOpen(false)}>
                <Bot size={17} />
                <span>Voice Agents</span>
              </NavLink>

              <NavLink to="/agents/new" onClick={() => setMobileOpen(false)}>
                <PlusCircle size={17} />
                <span>Agent Studio</span>
              </NavLink>

              <NavLink to="/calls" onClick={() => setMobileOpen(false)}>
                <History size={17} />
                <span>Call Logs & Audio</span>
              </NavLink>
            </nav>
          </div>
        </div>

        {/* Sidebar Footer */}
        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <Link
            to="/"
            onClick={() => setMobileOpen(false)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              padding: '0.65rem 0.85rem',
              borderRadius: '10px',
              color: '#475569',
              fontSize: '0.82rem',
              fontWeight: 500,
              textDecoration: 'none',
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
              transition: 'all 0.15s ease',
            }}
          >
            <ArrowLeft size={15} />
            <span>Public Homepage</span>
          </Link>

          <div
            style={{
              background: '#ecfdf5',
              border: '1px solid #a7f3d0',
              borderRadius: '12px',
              padding: '0.75rem 0.85rem',
              fontSize: '0.75rem',
              color: '#047857',
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: '0.2rem', fontSize: '0.72rem', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Server size={12} />
              <span>PJSIP ENGINE STATUS</span>
            </div>
            AudioSocket :9092 • SLIN16 8kHz
          </div>
        </div>
      </aside>

      {/* Main Viewport */}
      <div className="main-viewport">
        {/* Top Header Bar */}
        <header
          className="app-topbar"
          style={{
            background: 'rgba(255, 255, 255, 0.88)',
            borderBottom: '1px solid #e5e7eb',
          }}
        >
          <div className="topbar-left">
            <button
              type="button"
              onClick={() => setMobileOpen(!mobileOpen)}
              style={{
                display: 'none',
                background: '#ffffff',
                border: '1px solid #e5e7eb',
                color: '#111827',
                padding: '0.4rem 0.6rem',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
              className="mobile-menu-btn"
            >
              {mobileOpen ? <X size={18} /> : <Menu size={18} />}
            </button>

            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.76rem', color: '#64748b', marginBottom: '0.15rem' }}>
                <span>Console</span>
                <ChevronRight size={12} />
                <span style={{ color: '#111827', fontWeight: 600 }}>{pageInfo.title}</span>
              </div>
              <h1 className="topbar-title" style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700 }}>
                {pageInfo.title}
              </h1>
            </div>
          </div>

          <div className="topbar-right">
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                background: '#ecfdf5',
                border: '1px solid #a7f3d0',
                color: '#047857',
                padding: '0.3rem 0.75rem',
                borderRadius: '999px',
                fontSize: '0.75rem',
                fontWeight: 600,
              }}
            >
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
              <span>AudioSocket :9092 ONLINE</span>
            </div>

            <Link
              to="/agents/new"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                background: '#2a2c33',
                color: '#ffffff',
                borderRadius: '9999px',
                padding: '0.45rem 1rem',
                fontSize: '0.84rem',
                fontWeight: 500,
                textDecoration: 'none',
                boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4), inset 0 -2px 0 rgba(0, 0, 0, 0.2)',
              }}
            >
              <Plus size={15} />
              <span>New Agent</span>
            </Link>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="main" style={{ padding: '2rem 2.5rem' }}>
          <Outlet />
        </main>
      </div>

      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
      />
    </div>
  )
}
