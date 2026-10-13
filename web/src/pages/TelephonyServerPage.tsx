import { useEffect, useState } from 'react'
import {
  Check,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  Headphones,
  Laptop,
  Phone,
  PhoneCall,
  PhoneForwarded,
  Plus,
  QrCode,
  Radio,
  RefreshCw,
  Server,
  Smartphone,
  Trash2,
  Users,
  Volume2,
  Wifi,
  X,
  Zap,
} from 'lucide-react'
import { api } from '../api'
import type { Phone as PhoneType, PhoneConfigGuide, TelephonyServerInfo } from '../api'
import { useToast } from '../toast'

export function TelephonyServerPage() {
  const { show } = useToast()
  const toast = (msg: string, type: 'success' | 'error' | 'info' = 'info') => show(msg, type === 'error')
  const [serverInfo, setServerInfo] = useState<TelephonyServerInfo | null>(null)
  const [phones, setPhones] = useState<PhoneType[]>([])
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [activeTab, setActiveTab] = useState<'directory' | 'dialplan' | 'guides' | 'tester'>('directory')

  // Modals
  const [showAddModal, setShowAddModal] = useState(false)
  const [showBulkModal, setShowBulkModal] = useState(false)
  const [showConfigModal, setShowConfigModal] = useState(false)
  const [selectedConfig, setSelectedConfig] = useState<PhoneConfigGuide | null>(null)
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, boolean>>({})

  // Form states
  const [newExt, setNewExt] = useState('')
  const [newName, setNewName] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newDeviceType, setNewDeviceType] = useState<'mobile' | 'ip_phone' | 'softphone'>('mobile')
  const [newNotes, setNewNotes] = useState('')
  const [savingPhone, setSavingPhone] = useState(false)

  // Bulk form
  const [bulkCount, setBulkCount] = useState(10)
  const [bulkStartExt, setBulkStartExt] = useState(1001)
  const [bulkPrefix, setBulkPrefix] = useState('phonepass')
  const [bulkType, setBulkType] = useState<'ip_phone' | 'mobile'>('ip_phone')
  const [savingBulk, setSavingBulk] = useState(false)

  // Test dialer state
  const [dialFrom, setDialFrom] = useState('')
  const [dialTo, setDialTo] = useState('2000')
  const [dialing, setDialing] = useState(false)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const loadData = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [sInfo, pList] = await Promise.all([
        api.getTelephonyServer().catch(() => null),
        api.listPhones().catch(() => []),
      ])
      if (sInfo) setServerInfo(sInfo)
      setPhones(pList)
      if (pList.length > 0 && !dialFrom) {
        setDialFrom(pList[0].extension)
      }
    } catch (err: any) {
      if (!silent) toast(err.message || 'Failed to load telephony data', 'error')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    // Poll presence every 6 seconds
    const interval = setInterval(() => {
      loadData(true)
    }, 6000)
    return () => clearInterval(interval)
  }, [])

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopiedKey(key)
    toast('Copied to clipboard!', 'success')
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const togglePasswordReveal = (id: string) => {
    setRevealedPasswords((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const handleCreatePhone = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newExt.trim() || !newName.trim()) {
      toast('Please provide extension and display name', 'error')
      return
    }
    setSavingPhone(true)
    try {
      const res = await api.createPhone({
        extension: newExt.trim(),
        name: newName.trim(),
        password: newPassword.trim() || undefined,
        device_type: newDeviceType,
        notes: newNotes.trim(),
      })
      toast(res.message || 'Extension created and loaded into PBX', 'success')
      setShowAddModal(false)
      setNewExt('')
      setNewName('')
      setNewPassword('')
      setNewNotes('')
      await loadData()
    } catch (err: any) {
      toast(err.message || 'Failed to create extension', 'error')
    } finally {
      setSavingPhone(false)
    }
  }

  const handleBulkCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingBulk(true)
    try {
      const res = await api.bulkCreatePhones(bulkCount, bulkStartExt, bulkPrefix, bulkType)
      toast(`Successfully created and configured ${res.count} IP phone extensions!`, 'success')
      setShowBulkModal(false)
      await loadData()
    } catch (err: any) {
      toast(err.message || 'Bulk creation failed', 'error')
    } finally {
      setSavingBulk(false)
    }
  }

  const handleDeletePhone = async (phone: PhoneType) => {
    if (!window.confirm(`Delete phone extension ${phone.extension} (${phone.name})?`)) return
    try {
      await api.deletePhone(phone.id)
      toast(`Extension ${phone.extension} deleted from PBX server`, 'success')
      await loadData()
    } catch (err: any) {
      toast(err.message || 'Failed to delete extension', 'error')
    }
  }

  const handleOpenConfig = async (phone: PhoneType) => {
    try {
      const cfg = await api.getPhoneConfig(phone.id)
      setSelectedConfig(cfg)
      setShowConfigModal(true)
    } catch (err: any) {
      toast(err.message || 'Failed to load configuration guide', 'error')
    }
  }

  const handleReloadServer = async () => {
    setReloading(true)
    try {
      const res = await api.reloadTelephonyServer()
      if (res.ok) {
        toast('Asterisk PBX server reloaded successfully! All phones are synchronized.', 'success')
      } else {
        toast('PBX configuration synchronized to disk', 'info')
      }
      await loadData()
    } catch (err: any) {
      toast(err.message || 'Reload error', 'error')
    } finally {
      setReloading(false)
    }
  }

  const handleTestCall = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!dialFrom || !dialTo) {
      toast('Please enter both source and destination extensions', 'error')
      return
    }
    setDialing(true)
    try {
      const res = await api.originateTelephonyCall(dialFrom, dialTo)
      if (res.ok) {
        toast(`Test call placed! Extension ${dialFrom} will ring and connect to ${dialTo}.`, 'success')
      } else {
        toast(res.error || 'Test call failed to initiate', 'error')
      }
    } catch (err: any) {
      toast(err.message || 'Error triggering test call', 'error')
    } finally {
      setDialing(false)
    }
  }

  const getDeviceIcon = (type: string) => {
    switch (type) {
      case 'mobile':
        return <Smartphone size={16} className="text-blue-500" />
      case 'ip_phone':
        return <PhoneCall size={16} className="text-emerald-500" />
      case 'softphone':
        return <Laptop size={16} className="text-purple-500" />
      default:
        return <Phone size={16} className="text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'online':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              padding: '0.2rem 0.6rem',
              borderRadius: '9999px',
              fontSize: '0.72rem',
              fontWeight: 700,
              background: '#ecfdf5',
              color: '#059669',
              border: '1px solid #a7f3d0',
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} />
            ONLINE / REGISTERED
          </span>
        )
      case 'in_call':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              padding: '0.2rem 0.6rem',
              borderRadius: '9999px',
              fontSize: '0.72rem',
              fontWeight: 700,
              background: '#fef2f2',
              color: '#dc2626',
              border: '1px solid #fecaca',
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444' }} />
            ON CALL (TALKING)
          </span>
        )
      case 'ringing':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              padding: '0.2rem 0.6rem',
              borderRadius: '9999px',
              fontSize: '0.72rem',
              fontWeight: 700,
              background: '#fffbeb',
              color: '#d97706',
              border: '1px solid #fde68a',
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f59e0b' }} />
            RINGING
          </span>
        )
      default:
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              padding: '0.2rem 0.6rem',
              borderRadius: '9999px',
              fontSize: '0.72rem',
              fontWeight: 600,
              background: '#f3f4f6',
              color: '#6b7280',
              border: '1px solid #e5e7eb',
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#9ca3af' }} />
            OFFLINE
          </span>
        )
    }
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: 1400, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Page Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, #111827 0%, #1f2937 100%)',
          borderRadius: '18px',
          padding: '1.75rem 2rem',
          color: '#ffffff',
          boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.2)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1.5rem',
        }}
      >
        <div style={{ maxWidth: 680 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem' }}>
            <span
              style={{
                background: 'rgba(255, 255, 255, 0.15)',
                color: '#38bdf8',
                padding: '0.2rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 700,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <Server size={12} /> ENTERPRISE PBX SERVER
            </span>
            <span
              style={{
                background: serverInfo?.sip_listening ? '#065f46' : '#7f1d1d',
                color: serverInfo?.sip_listening ? '#34d399' : '#f87171',
                padding: '0.2rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 700,
                letterSpacing: '0.05em',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: serverInfo?.sip_listening ? '#10b981' : '#ef4444',
                }}
              />
              {serverInfo?.sip_listening ? 'SIP LISTENING (UDP 5060)' : 'PBX INITIALIZING'}
            </span>
          </div>
          <h1 style={{ fontSize: '1.85rem', fontWeight: 800, margin: '0 0 0.4rem 0', letterSpacing: '-0.02em' }}>
            Telephone Server & IP Phone Intercom
          </h1>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.5 }}>
            Transform your machine into a full-scale Telephony PBX server. Connect mobile softphones (Linphone / Zoiper)
            and physical IP phones (Yealink / Grandstream) so every phone can dial any other phone, hold group conferences,
            or speak to AI Voice Agents.
          </p>
        </div>

        {/* Server Connection Pill & Action Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', alignItems: 'flex-end' }}>
          <div
            style={{
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              borderRadius: '12px',
              padding: '0.6rem 1rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.85rem',
            }}
          >
            <div>
              <div style={{ fontSize: '0.68rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>
                Server SIP Domain (Local LAN)
              </div>
              <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.95rem', color: '#ffffff' }}>
                {serverInfo?.local_ip ? `${serverInfo.local_ip}:5060` : '127.0.0.1:5060'}
              </div>
            </div>
            <button
              type="button"
              onClick={() => handleCopy(serverInfo?.local_ip || '127.0.0.1', 'sip_ip')}
              title="Copy Server IP for Phone Configuration"
              style={{
                background: 'rgba(255, 255, 255, 0.12)',
                border: 'none',
                color: '#ffffff',
                borderRadius: '8px',
                padding: '0.45rem',
                cursor: 'pointer',
              }}
            >
              {copiedKey === 'sip_ip' ? <Check size={15} className="text-emerald-400" /> : <Copy size={15} />}
            </button>
          </div>

          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => setShowBulkModal(true)}
              style={{
                background: '#4f46e5',
                color: '#ffffff',
                border: 'none',
                borderRadius: '10px',
                padding: '0.6rem 1.1rem',
                fontSize: '0.82rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
                boxShadow: '0 2px 4px rgba(79, 70, 229, 0.3)',
              }}
            >
              <Zap size={14} />
              <span>Provision 10 IP Phones</span>
            </button>

            <button
              type="button"
              onClick={() => setShowAddModal(true)}
              style={{
                background: '#ffffff',
                color: '#111827',
                border: 'none',
                borderRadius: '10px',
                padding: '0.6rem 1.1rem',
                fontSize: '0.82rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
              }}
            >
              <Plus size={15} />
              <span>Add Phone / Mobile</span>
            </button>

            <button
              type="button"
              onClick={handleReloadServer}
              disabled={reloading}
              title="Reload Asterisk PBX"
              style={{
                background: 'rgba(255, 255, 255, 0.12)',
                color: '#ffffff',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                borderRadius: '10px',
                padding: '0.6rem 0.85rem',
                fontSize: '0.82rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              <RefreshCw size={14} className={reloading ? 'animate-spin' : ''} />
              <span>Reload PBX</span>
            </button>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        <div
          style={{
            background: '#ffffff',
            borderRadius: '14px',
            padding: '1.25rem',
            border: '1px solid #e5e7eb',
            boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', color: '#64748b', fontWeight: 600 }}>CONFIGURED EXTENSIONS</span>
            <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#2563eb' }}>
              <Phone size={16} />
            </div>
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#111827' }}>{phones.length}</div>
          <div style={{ fontSize: '0.74rem', color: '#64748b', marginTop: '0.25rem' }}>
            Internal PBX extensions ready to dial
          </div>
        </div>

        <div
          style={{
            background: '#ffffff',
            borderRadius: '14px',
            padding: '1.25rem',
            border: '1px solid #e5e7eb',
            boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', color: '#64748b', fontWeight: 600 }}>ONLINE / REGISTERED</span>
            <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#ecfdf5', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#059669' }}>
              <Wifi size={16} />
            </div>
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#059669' }}>
            {serverInfo?.online_phones ?? 0}
          </div>
          <div style={{ fontSize: '0.74rem', color: '#64748b', marginTop: '0.25rem' }}>
            Active SIP clients reachable now
          </div>
        </div>

        <div
          style={{
            background: '#ffffff',
            borderRadius: '14px',
            padding: '1.25rem',
            border: '1px solid #e5e7eb',
            boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', color: '#64748b', fontWeight: 600 }}>CONFERENCE BRIDGE</span>
            <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#f5f3ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#7c3aed' }}>
              <Users size={16} />
            </div>
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#7c3aed' }}>8888</div>
          <div style={{ fontSize: '0.74rem', color: '#64748b', marginTop: '0.25rem' }}>
            Dial 8888 to talk with all phones together
          </div>
        </div>

        <div
          style={{
            background: '#ffffff',
            borderRadius: '14px',
            padding: '1.25rem',
            border: '1px solid #e5e7eb',
            boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', color: '#64748b', fontWeight: 600 }}>MICROPHONE ECHO TEST</span>
            <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#fef3c7', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#d97706' }}>
              <Headphones size={16} />
            </div>
          </div>
          <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#d97706' }}>*43</div>
          <div style={{ fontSize: '0.74rem', color: '#64748b', marginTop: '0.25rem' }}>
            Dial *43 to test audio latency & duplex
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid #e5e7eb', gap: '1.5rem', marginTop: '0.5rem' }}>
        <button
          type="button"
          onClick={() => setActiveTab('directory')}
          style={{
            background: 'none',
            border: 'none',
            padding: '0.75rem 0.25rem',
            fontSize: '0.9rem',
            fontWeight: activeTab === 'directory' ? 700 : 500,
            color: activeTab === 'directory' ? '#4f46e5' : '#64748b',
            borderBottom: activeTab === 'directory' ? '2px solid #4f46e5' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
          }}
        >
          <Phone size={16} />
          <span>Phone Extensions Directory ({phones.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('dialplan')}
          style={{
            background: 'none',
            border: 'none',
            padding: '0.75rem 0.25rem',
            fontSize: '0.9rem',
            fontWeight: activeTab === 'dialplan' ? 700 : 500,
            color: activeTab === 'dialplan' ? '#4f46e5' : '#64748b',
            borderBottom: activeTab === 'dialplan' ? '2px solid #4f46e5' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
          }}
        >
          <Radio size={16} />
          <span>Internal PBX Dialing Rules</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('guides')}
          style={{
            background: 'none',
            border: 'none',
            padding: '0.75rem 0.25rem',
            fontSize: '0.9rem',
            fontWeight: activeTab === 'guides' ? 700 : 500,
            color: activeTab === 'guides' ? '#4f46e5' : '#64748b',
            borderBottom: activeTab === 'guides' ? '2px solid #4f46e5' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
          }}
        >
          <ExternalLink size={16} />
          <span>Device Setup Guides (Linphone / Zoiper / Yealink)</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('tester')}
          style={{
            background: 'none',
            border: 'none',
            padding: '0.75rem 0.25rem',
            fontSize: '0.9rem',
            fontWeight: activeTab === 'tester' ? 700 : 500,
            color: activeTab === 'tester' ? '#4f46e5' : '#64748b',
            borderBottom: activeTab === 'tester' ? '2px solid #4f46e5' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
          }}
        >
          <PhoneForwarded size={16} />
          <span>Test Call Simulator</span>
        </button>
      </div>

      {/* Tab 1: Phone Extensions Directory */}
      {activeTab === 'directory' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {loading && phones.length === 0 ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: '#64748b' }}>
              <RefreshCw className="animate-spin" size={24} style={{ margin: '0 auto 0.5rem auto' }} />
              <div>Loading telephony extensions...</div>
            </div>
          ) : phones.length === 0 ? (
            <div
              style={{
                background: '#ffffff',
                borderRadius: '16px',
                padding: '3rem 2rem',
                textAlign: 'center',
                border: '1px dashed #cbd5e1',
              }}
            >
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: '50%',
                  background: '#e0e7ff',
                  color: '#4f46e5',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 1rem auto',
                }}
              >
                <PhoneCall size={26} />
              </div>
              <h3 style={{ fontSize: '1.2rem', fontWeight: 700, margin: '0 0 0.5rem 0', color: '#111827' }}>
                No Phone Extensions Added Yet
              </h3>
              <p style={{ color: '#64748b', maxWidth: 450, margin: '0 auto 1.5rem auto', fontSize: '0.88rem' }}>
                Create your first phone extension or click "Quick Provision 10 IP Phones" to automatically set up 10 extensions
                that can immediately call and talk to each other.
              </p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowBulkModal(true)}
                  className="btn btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                >
                  <Zap size={15} />
                  <span>Provision 10 IP Phones</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowAddModal(true)}
                  className="btn btn-outline"
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                >
                  <Plus size={15} />
                  <span>Add Single Phone</span>
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '1rem' }}>
              {phones.map((phone) => {
                const isPasswordRevealed = revealedPasswords[phone.id] || false
                return (
                  <div
                    key={phone.id}
                    style={{
                      background: '#ffffff',
                      borderRadius: '14px',
                      border: '1px solid #e5e7eb',
                      padding: '1.25rem',
                      boxShadow: '0 1px 3px rgba(0, 0, 0, 0.04)',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      gap: '1rem',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <div>
                      {/* Top Bar: Ext + Type + Status */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                          <span
                            style={{
                              background: '#111827',
                              color: '#ffffff',
                              padding: '0.25rem 0.65rem',
                              borderRadius: '8px',
                              fontFamily: 'monospace',
                              fontWeight: 800,
                              fontSize: '1.05rem',
                            }}
                          >
                            {phone.extension}
                          </span>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.3rem',
                              fontSize: '0.72rem',
                              fontWeight: 600,
                              color: '#475569',
                              background: '#f1f5f9',
                              padding: '0.2rem 0.5rem',
                              borderRadius: '6px',
                            }}
                          >
                            {getDeviceIcon(phone.device_type)}
                            {phone.device_type === 'mobile'
                              ? 'Mobile App'
                              : phone.device_type === 'ip_phone'
                              ? 'Desk IP Phone'
                              : 'Softphone'}
                          </span>
                        </div>
                        {getStatusBadge(phone.status)}
                      </div>

                      {/* Name and Caller ID */}
                      <div style={{ fontWeight: 700, fontSize: '1rem', color: '#111827', marginBottom: '0.25rem' }}>
                        {phone.name}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: '0.85rem' }}>
                        Caller ID: <span style={{ fontFamily: 'monospace', color: '#334155' }}>{phone.caller_id || `"${phone.name}" <${phone.extension}>`}</span>
                      </div>

                      {/* Credentials Box */}
                      <div
                        style={{
                          background: '#f8fafc',
                          borderRadius: '10px',
                          border: '1px solid #e2e8f0',
                          padding: '0.75rem',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.5rem',
                          fontSize: '0.78rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: '#64748b' }}>SIP Server:</span>
                          <span style={{ fontFamily: 'monospace', fontWeight: 600, color: '#1e293b' }}>
                            {serverInfo?.local_ip || '127.0.0.1'}:5060 (UDP)
                          </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: '#64748b' }}>SIP Username:</span>
                          <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#1e293b' }}>
                            {phone.extension}
                          </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: '#64748b' }}>SIP Password:</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <span style={{ fontFamily: 'monospace', fontWeight: 600, color: '#1e293b' }}>
                              {isPasswordRevealed ? phone.password : '••••••••••••'}
                            </span>
                            <button
                              type="button"
                              onClick={() => togglePasswordReveal(phone.id)}
                              style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '0 0.2rem' }}
                              title={isPasswordRevealed ? 'Hide password' : 'Show password'}
                            >
                              {isPasswordRevealed ? <EyeOff size={13} /> : <Eye size={13} />}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleCopy(phone.password, `pw_${phone.id}`)}
                              style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '0 0.2rem' }}
                              title="Copy password"
                            >
                              {copiedKey === `pw_${phone.id}` ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
                            </button>
                          </div>
                        </div>
                        {phone.contacts && (
                          <div style={{ fontSize: '0.7rem', color: '#047857', borderTop: '1px dashed #cbd5e1', paddingTop: '0.4rem' }}>
                            Contact: <span style={{ fontFamily: 'monospace' }}>{phone.contacts}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div style={{ display: 'flex', gap: '0.5rem', borderTop: '1px solid #f1f5f9', paddingTop: '0.85rem' }}>
                      <button
                        type="button"
                        onClick={() => handleOpenConfig(phone)}
                        style={{
                          flex: 1,
                          background: '#4f46e5',
                          color: '#ffffff',
                          border: 'none',
                          borderRadius: '8px',
                          padding: '0.5rem 0.75rem',
                          fontSize: '0.78rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '0.35rem',
                        }}
                      >
                        <QrCode size={14} />
                        <span>Connect Device</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          setDialFrom(phone.extension)
                          setActiveTab('tester')
                        }}
                        title="Simulate call from this phone"
                        style={{
                          background: '#f8fafc',
                          color: '#334155',
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          padding: '0.5rem 0.65rem',
                          fontSize: '0.78rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                        }}
                      >
                        <PhoneForwarded size={14} />
                        <span>Dial</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleDeletePhone(phone)}
                        title="Delete phone extension"
                        style={{
                          background: '#fee2e2',
                          color: '#dc2626',
                          border: '1px solid #fecaca',
                          borderRadius: '8px',
                          padding: '0.5rem 0.65rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Internal PBX Dialing Rules */}
      {activeTab === 'dialplan' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.25rem' }}>
          <div style={{ background: '#ffffff', borderRadius: '14px', border: '1px solid #e5e7eb', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <PhoneCall size={18} className="text-indigo-600" />
              <span>Internal Phone-to-Phone Calling</span>
            </h3>
            <p style={{ fontSize: '0.85rem', color: '#64748b', lineHeight: 1.5, margin: '0 0 1rem 0' }}>
              Every phone registered to this server can call any other registered extension directly. Asterisk bridges
              the RTP audio streams with symmetric NAT handling so calls never drop even across cellular/WiFi boundaries.
            </p>
            <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.85rem', border: '1px solid #e2e8f0' }}>
              <div style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: '0.35rem', color: '#1e293b' }}>
                Example Call Flow:
              </div>
              <ol style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                <li>Phone 1001 (Himanshu Mobile) opens dialpad and dials <b>1002</b>.</li>
                <li>Asterisk rings Extension 1002 (Office Desk Phone).</li>
                <li>Extension 1002 answers. Audio is bridged in full duplex (crystal clear ulaw/alaw/opus).</li>
                <li>Both parties can speak, hold, or transfer.</li>
              </ol>
            </div>
          </div>

          <div style={{ background: '#ffffff', borderRadius: '14px', border: '1px solid #e5e7eb', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Users size={18} className="text-purple-600" />
              <span>Group Conference Bridge (8888)</span>
            </h3>
            <p style={{ fontSize: '0.85rem', color: '#64748b', lineHeight: 1.5, margin: '0 0 1rem 0' }}>
              Want 3, 5, or all 10 phones to talk at the same time? Dial <b>8888</b> from any IP phone or mobile softphone.
              Everyone who dials in joins the same audio room with multi-party mixing.
            </p>
            <div style={{ background: '#faf5ff', borderRadius: '10px', padding: '0.85rem', border: '1px solid #e9d5ff' }}>
              <div style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: '0.25rem', color: '#6b21a8' }}>
                How to join:
              </div>
              <div style={{ fontSize: '0.8rem', color: '#581c87', lineHeight: 1.5 }}>
                Dial <b>8888</b> on your mobile phone or desk phone. You will instantly hear other participants and can talk together.
              </div>
            </div>
          </div>

          <div style={{ background: '#ffffff', borderRadius: '14px', border: '1px solid #e5e7eb', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Volume2 size={18} className="text-amber-600" />
              <span>Broadcast Ring All / Paging (8000)</span>
            </h3>
            <p style={{ fontSize: '0.85rem', color: '#64748b', lineHeight: 1.5, margin: '0 0 1rem 0' }}>
              Dial <b>8000</b> to ring all configured IP phones and mobile devices simultaneously. The first person to answer
              connects to your call.
            </p>
            <div style={{ background: '#fffbeb', borderRadius: '10px', padding: '0.85rem', border: '1px solid #fef3c7' }}>
              <div style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: '0.25rem', color: '#92400e' }}>
                Simultaneous Ring Target:
              </div>
              <div style={{ fontSize: '0.78rem', color: '#78350f', fontFamily: 'monospace' }}>
                {phones.length > 0 ? phones.map((p) => p.extension).join(' & ') : 'No phones configured'}
              </div>
            </div>
          </div>

          <div style={{ background: '#ffffff', borderRadius: '14px', border: '1px solid #e5e7eb', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0 0 0.75rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Headphones size={18} className="text-emerald-600" />
              <span>Audio Echo Test (*43 / 9999) & AI Agent (2000)</span>
            </h3>
            <p style={{ fontSize: '0.85rem', color: '#64748b', lineHeight: 1.5, margin: '0 0 1rem 0' }}>
              Verify sound quality before calling colleagues or customers.
            </p>
            <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.82rem', color: '#334155', lineHeight: 1.6 }}>
              <li><b>*43</b> or <b>9999</b>: Echo Test — speak into the phone and hear your own voice echoed back instantly.</li>
              <li><b>2000</b>: AI Voice Agent — dials directly into your CallForge AI agent on this server!</li>
            </ul>
          </div>
        </div>
      )}

      {/* Tab 3: Device Setup Guides */}
      {activeTab === 'guides' && (
        <div style={{ background: '#ffffff', borderRadius: '16px', border: '1px solid #e5e7eb', padding: '2rem' }}>
          <h2 style={{ fontSize: '1.35rem', fontWeight: 800, margin: '0 0 0.5rem 0', color: '#111827' }}>
            How to Connect Your Mobile Phones & IP Phones
          </h2>
          <p style={{ color: '#64748b', fontSize: '0.9rem', margin: '0 0 1.5rem 0' }}>
            Follow these simple steps to install free SIP apps on your smartphones or configure office desk phones.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
            {/* Linphone */}
            <div style={{ border: '1px solid #e2e8f0', borderRadius: '12px', padding: '1.25rem', background: '#f8fafc' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.75rem' }}>
                <Smartphone size={20} className="text-blue-600" />
                <h4 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: '#1e293b' }}>
                  Linphone (Android / iPhone / PC)
                </h4>
              </div>
              <div style={{ fontSize: '0.82rem', color: '#475569', lineHeight: 1.6 }}>
                <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
                  <li>Install <b>Linphone</b> from Google Play Store or Apple App Store.</li>
                  <li>Open the app and choose <b>USE SIP ACCOUNT</b>.</li>
                  <li><b>Username:</b> Your extension number (e.g. <code>1001</code>).</li>
                  <li><b>SIP Domain:</b> <code>{serverInfo?.local_ip || '127.0.0.1'}:5060</code></li>
                  <li><b>Password:</b> Your extension's SIP password.</li>
                  <li><b>Transport:</b> Select <b>UDP</b>.</li>
                  <li>Tap <b>LOGIN</b>. You will see a green status dot!</li>
                </ol>
              </div>
            </div>

            {/* Zoiper */}
            <div style={{ border: '1px solid #e2e8f0', borderRadius: '12px', padding: '1.25rem', background: '#f8fafc' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.75rem' }}>
                <Smartphone size={20} className="text-amber-600" />
                <h4 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: '#1e293b' }}>
                  Zoiper (Android / iOS / Windows)
                </h4>
              </div>
              <div style={{ fontSize: '0.82rem', color: '#475569', lineHeight: 1.6 }}>
                <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
                  <li>Install <b>Zoiper</b> from your device's app store.</li>
                  <li>Open Settings → <b>Accounts</b> → <b>Add Account</b>.</li>
                  <li>Choose <b>SIP</b>.</li>
                  <li><b>User / Host:</b> <code>1001@{serverInfo?.local_ip || '127.0.0.1'}:5060</code></li>
                  <li><b>Password:</b> Your SIP password.</li>
                  <li>Select <b>UDP</b> transport during network check.</li>
                  <li>Ready to make and receive calls!</li>
                </ol>
              </div>
            </div>

            {/* Hardware IP Phone */}
            <div style={{ border: '1px solid #e2e8f0', borderRadius: '12px', padding: '1.25rem', background: '#f8fafc' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.75rem' }}>
                <PhoneCall size={20} className="text-emerald-600" />
                <h4 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: '#1e293b' }}>
                  Hardware IP Phone (Yealink / Grandstream / Cisco)
                </h4>
              </div>
              <div style={{ fontSize: '0.82rem', color: '#475569', lineHeight: 1.6 }}>
                <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
                  <li>Find your IP phone's IP address and open it in your web browser.</li>
                  <li>Log into the phone's web UI (default admin/admin).</li>
                  <li>Go to <b>Account</b> → <b>Register / SIP Settings</b>.</li>
                  <li><b>SIP Server:</b> <code>{serverInfo?.local_ip || '127.0.0.1'}</code> (Port <code>5060</code>)</li>
                  <li><b>Register Name / User ID:</b> Your extension (e.g. <code>1002</code>).</li>
                  <li><b>Password:</b> Your extension password.</li>
                  <li>Click <b>Save & Apply</b>. The phone screen will show <b>Registered</b>!</li>
                </ol>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Test Call Simulator */}
      {activeTab === 'tester' && (
        <div style={{ maxWidth: 650, margin: '0 auto', background: '#ffffff', borderRadius: '16px', border: '1px solid #e5e7eb', padding: '2rem' }}>
          <h3 style={{ fontSize: '1.2rem', fontWeight: 800, margin: '0 0 0.5rem 0', color: '#111827', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <PhoneForwarded size={20} className="text-indigo-600" />
            <span>Test Call Simulator</span>
          </h3>
          <p style={{ color: '#64748b', fontSize: '0.85rem', margin: '0 0 1.5rem 0' }}>
            Trigger an intercom call between any two extensions directly from the web console. Asterisk will call
            the source phone and connect it to the target extension.
          </p>

          <form onSubmit={handleTestCall} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#374151', marginBottom: '0.4rem' }}>
                From Extension (Source Phone):
              </label>
              <select
                value={dialFrom}
                onChange={(e) => setDialFrom(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  border: '1px solid #d1d5db',
                  fontSize: '0.9rem',
                }}
              >
                {phones.map((p) => (
                  <option key={p.id} value={p.extension}>
                    Ext {p.extension} — {p.name} ({p.status})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#374151', marginBottom: '0.4rem' }}>
                To Extension / Feature Code:
              </label>
              <input
                type="text"
                value={dialTo}
                onChange={(e) => setDialTo(e.target.value)}
                placeholder="e.g. 1002, 2000 (AI Agent), 8888 (Conference), *43 (Echo)"
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  border: '1px solid #d1d5db',
                  fontSize: '0.9rem',
                }}
              />
              <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={() => setDialTo('2000')}
                  style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px', padding: '0.25rem 0.55rem', fontSize: '0.72rem', color: '#1d4ed8', cursor: 'pointer' }}
                >
                  AI Agent (2000)
                </button>
                <button
                  type="button"
                  onClick={() => setDialTo('8888')}
                  style={{ background: '#f5f3ff', border: '1px solid #ddd6fe', borderRadius: '6px', padding: '0.25rem 0.55rem', fontSize: '0.72rem', color: '#6d28d9', cursor: 'pointer' }}
                >
                  Conference Bridge (8888)
                </button>
                <button
                  type="button"
                  onClick={() => setDialTo('*43')}
                  style={{ background: '#fef3c7', border: '1px solid #fde68a', borderRadius: '6px', padding: '0.25rem 0.55rem', fontSize: '0.72rem', color: '#b45309', cursor: 'pointer' }}
                >
                  Echo Test (*43)
                </button>
                <button
                  type="button"
                  onClick={() => setDialTo('8000')}
                  style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '6px', padding: '0.25rem 0.55rem', fontSize: '0.72rem', color: '#15803d', cursor: 'pointer' }}
                >
                  Ring All (8000)
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={dialing || phones.length === 0}
              className="btn btn-primary"
              style={{
                padding: '0.75rem',
                fontSize: '0.92rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                marginTop: '0.5rem',
              }}
            >
              <PhoneCall size={16} className={dialing ? 'animate-pulse' : ''} />
              <span>{dialing ? 'Originating Call via Asterisk...' : 'Place Intercom Call'}</span>
            </button>
          </form>
        </div>
      )}

      {/* Modal: Add Single Phone */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(17, 24, 39, 0.6)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            padding: '1rem',
          }}
        >
          <div
            style={{
              background: '#ffffff',
              borderRadius: '16px',
              maxWidth: 500,
              width: '100%',
              padding: '1.75rem',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <h3 style={{ fontSize: '1.2rem', fontWeight: 800, margin: 0, color: '#111827' }}>
                Add New Phone Extension
              </h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleCreatePhone} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Extension Number *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. 1005"
                  value={newExt}
                  onChange={(e) => setNewExt(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Display Name / User Name *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Reception Desk, Himanshu Mobile"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  SIP Password (optional, auto-generated if blank)
                </label>
                <input
                  type="text"
                  placeholder="Leave empty for auto-generated secure password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Device Type
                </label>
                <select
                  value={newDeviceType}
                  onChange={(e) => setNewDeviceType(e.target.value as any)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                >
                  <option value="mobile">Mobile Softphone (Linphone / Zoiper)</option>
                  <option value="ip_phone">Desk IP Hardware Phone (Yealink / Grandstream)</option>
                  <option value="softphone">Desktop Computer Softphone</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Notes / Location
                </label>
                <input
                  type="text"
                  placeholder="e.g. 2nd Floor Meeting Room"
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  style={{ background: '#f3f4f6', color: '#4b5563', border: 'none', borderRadius: '8px', padding: '0.6rem 1rem', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingPhone}
                  className="btn btn-primary"
                  style={{ padding: '0.6rem 1.25rem' }}
                >
                  {savingPhone ? 'Creating...' : 'Save & Reload PBX'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Bulk Provision 10 Phones */}
      {showBulkModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(17, 24, 39, 0.6)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            padding: '1rem',
          }}
        >
          <div
            style={{
              background: '#ffffff',
              borderRadius: '16px',
              maxWidth: 520,
              width: '100%',
              padding: '1.75rem',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Zap size={20} className="text-indigo-600" />
                <h3 style={{ fontSize: '1.2rem', fontWeight: 800, margin: 0, color: '#111827' }}>
                  Quick Provision Phones
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowBulkModal(false)}
                style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.85rem', color: '#64748b', margin: '0 0 1.25rem 0', lineHeight: 1.5 }}>
              Automatically create 10 (or custom number) IP phone extensions in one click. Passwords and internal
              dialplan routes are instantly loaded into Asterisk.
            </p>

            <form onSubmit={handleBulkCreate} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                    Number of Phones
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={bulkCount}
                    onChange={(e) => setBulkCount(parseInt(e.target.value) || 10)}
                    style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                    Start Extension #
                  </label>
                  <input
                    type="number"
                    min={100}
                    max={90000}
                    value={bulkStartExt}
                    onChange={(e) => setBulkStartExt(parseInt(e.target.value) || 1001)}
                    style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Device Type Preset
                </label>
                <select
                  value={bulkType}
                  onChange={(e) => setBulkType(e.target.value as any)}
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                >
                  <option value="ip_phone">Desk IP Hardware Phones</option>
                  <option value="mobile">Mobile Softphones (Linphone / Zoiper)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#374151', marginBottom: '0.35rem' }}>
                  Password Prefix
                </label>
                <input
                  type="text"
                  value={bulkPrefix}
                  onChange={(e) => setBulkPrefix(e.target.value)}
                  placeholder="e.g. phonepass (passwords will be phonepass1001, phonepass1002...)"
                  style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '8px', border: '1px solid #d1d5db' }}
                />
              </div>

              <div style={{ background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '0.78rem', color: '#475569' }}>
                Preview: Will generate extensions <b>{bulkStartExt}</b> through <b>{bulkStartExt + bulkCount - 1}</b> with password format <code>{bulkPrefix}[extension]</code>.
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
                <button
                  type="button"
                  onClick={() => setShowBulkModal(false)}
                  style={{ background: '#f3f4f6', color: '#4b5563', border: 'none', borderRadius: '8px', padding: '0.6rem 1rem', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingBulk}
                  className="btn btn-primary"
                  style={{ padding: '0.6rem 1.25rem' }}
                >
                  {savingBulk ? 'Provisioning...' : `Provision ${bulkCount} Extensions`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Device Configuration Guide & QR Code */}
      {showConfigModal && selectedConfig && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(17, 24, 39, 0.6)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            padding: '1rem',
          }}
        >
          <div
            style={{
              background: '#ffffff',
              borderRadius: '16px',
              maxWidth: 620,
              width: '100%',
              padding: '1.75rem',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
              maxHeight: '90vh',
              overflowY: 'auto',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <div style={{ width: 34, height: 34, borderRadius: '8px', background: '#e0e7ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4f46e5' }}>
                  <Smartphone size={18} />
                </div>
                <div>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 800, margin: 0, color: '#111827' }}>
                    Connect {selectedConfig.phone.name} (Ext {selectedConfig.phone.extension})
                  </h3>
                  <div style={{ fontSize: '0.74rem', color: '#64748b' }}>
                    SIP credentials for mobile apps and physical IP phones
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowConfigModal(false)}
                style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Quick Credentials Block */}
            <div
              style={{
                background: '#f8fafc',
                borderRadius: '12px',
                border: '1px solid #e2e8f0',
                padding: '1rem',
                marginBottom: '1.25rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
                fontSize: '0.82rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#64748b' }}>SIP Server IP / Domain:</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#0f172a' }}>
                  {selectedConfig.credentials.sip_server}:5060
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#64748b' }}>Extension (Username):</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#0f172a' }}>
                  {selectedConfig.credentials.username}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#64748b' }}>SIP Password:</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#0f172a' }}>
                  {selectedConfig.credentials.password}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#64748b' }}>Transport:</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#0f172a' }}>
                  UDP (Port 5060)
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#64748b' }}>SIP URI:</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 600, color: '#2563eb' }}>
                  {selectedConfig.credentials.sip_uri}
                </span>
              </div>
            </div>

            {/* Step-by-Step Instructions */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '1rem' }}>
                <div style={{ fontWeight: 700, fontSize: '0.88rem', color: '#1e293b', marginBottom: '0.5rem' }}>
                  📱 How to connect on Linphone (Mobile):
                </div>
                <ol style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                  {selectedConfig.setup_guides.linphone.steps.map((st, i) => (
                    <li key={i}>{st}</li>
                  ))}
                </ol>
              </div>

              <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '1rem' }}>
                <div style={{ fontWeight: 700, fontSize: '0.88rem', color: '#1e293b', marginBottom: '0.5rem' }}>
                  ☎️ How to connect on Physical IP Phone:
                </div>
                <ol style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                  {selectedConfig.setup_guides.ip_hardware.steps.map((st, i) => (
                    <li key={i}>{st}</li>
                  ))}
                </ol>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.25rem' }}>
              <button
                type="button"
                onClick={() => setShowConfigModal(false)}
                className="btn btn-primary"
                style={{ padding: '0.6rem 1.25rem' }}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
